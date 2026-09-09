"""Vectorize a specimen glyph cell directly, instead of hand-authoring
curves against it (github.com/perrwa/Joan/issues/3 -- the `n` attempt
proved hand-guessing bezier coordinates from a ~30px source doesn't
converge, even when it beats the IoU number, because eyeballing can't
reproduce a calligraphic curve's actual proportions).

Pipeline, as settled by a full live flag-review session on `n` (issue #3):
crop with real surrounding margin -> external Lanczos upscale -> optional
deringing (median/NLM/none -- the specimen PNGs are JPEG-derived, confirmed
by measuring 8px-periodic block-boundary artifacts) -> mkbitmap (threshold
only; scaling and blur happen elsewhere in this pipeline, not inside
mkbitmap) -> potrace (SVG) -> parse (fontTools.svgLib) -> position into the
glyph's italic-space font units using the same crop-height/bbox-height
calibration specimen_score.render_part uses for scoring.

Every default below is a real finding from that session, not a guess --
see each function's docstring for the specific evidence. They're tuned
against `n` specifically; per the issue #3 execution protocol, each
subsequent Tier A glyph gets its own review before assuming these transfer,
though they're the right starting point to iterate from.

Requires `potrace`/`mkbitmap` on PATH (`brew install potrace`) and
`numpy`/`opencv-python` in the venv (for NLM deringing).

Usage: python scripts/vectorize.py <glyph> [--upscale 3] [--dering nlm] [--alphamax 1.0]
"""

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from fontTools.pens.recordingPen import RecordingPen
from fontTools.svgLib.path import parse_path
from PIL import Image, ImageFilter

import italic_geom as ig
import specimen_score as ss

# Real surrounding context around the tight ink crop, sourced from the
# specimen sheet itself (not synthetic whitespace) -- found directly that
# mkbitmap/potrace produce meaningfully better traces with this margin; the
# tight crop starves deringing filters and lets edge effects reach real
# strokes. specimen_score.find_cell's own default (pad=0) is what scoring
# still compares against -- only the tracing INPUT gets padded.
CROP_PAD = 20


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr}")
    return r


def dering(image, method="nlm"):
    """Apply the deringing method settled on `n`'s flag-review session.
    `method` is "none", "median", or "nlm" -- kept selectable per glyph
    rather than hardcoded, since issue #3's protocol reviews each Tier A
    letter individually and a different glyph's stroke geometry could
    favor a different method (this one only proved out on n's specific
    trace, where nlm-h30 won on both the corrected soft-IoU metric and a
    high-resolution visual check of curve smoothness -- a naive polygon-
    vs-curve trap that a purely numeric comparison would have missed, see
    the alphamax note in `trace`).

    "median" is a size=5 (radius-2) PIL MedianFilter -- radius 1 barely
    moved a measured JPEG-block-artifact ratio (periodic block noise
    isn't impulse noise, which is what median filters are built for);
    radius 2 was the point real deringing started showing up without
    visibly rounding off corners.

    "nlm" is OpenCV's fastNlMeansDenoising, h=30 -- weaker settings
    (h=10) were barely different from doing nothing; h=30 is where it
    started doing real, edge-preserving work.

    Both parameter choices came from a systematic sweep (measured against
    real traced-and-scored output, not just the denoising step in
    isolation) -- see github.com/perrwa/Joan/issues/3 for the comparison
    artifacts."""
    if method == "none":
        return image
    if method == "median":
        return image.filter(ImageFilter.MedianFilter(size=5))
    if method == "nlm":
        import cv2

        out = cv2.fastNlMeansDenoising(np.array(image), h=30, templateWindowSize=7, searchWindowSize=21)
        return Image.fromarray(out)
    raise ValueError(f"unknown deringing method {method!r}")


def trace_crop(crop, upscale=3, dering_method="nlm", mkbitmap_threshold=0.70, alphamax=1.0, opttolerance=0.1, turdsize=0, unit=2):
    """Upscale a (loosely-cropped, see CROP_PAD) specimen crop, optionally
    dering it, trace it (potrace), and return the raw SVG path `d`
    string(s) plus the pixel dimensions the trace's own coordinate system
    is in (tracked via the traced SVG's own viewBox so no separate
    bookkeeping is needed).

    `upscale` (default 3, Lanczos) happens BEFORE mkbitmap ever sees the
    image, not via mkbitmap's own `-s` (which is fixed at 1 here) --
    found that plain upscale-then-trace, with NO deringing at all, beat
    every deringing method tried at every scale from 1x to 10x on a
    proper end-to-end (real trace, corrected soft-IoU) comparison. The
    earlier belief that deringing helped came from an ad-hoc bitmap-noise
    metric that didn't correlate with actual trace fidelity -- a
    corrected `iou()` (specimen_score.py, itself fixed twice this same
    session: a crop-padding bug that rewarded too-narrow candidates, and
    a resolution-collapsing bug that let close candidates tie exactly)
    settled it. On `n` specifically, nlm deringing at 3x edged out no
    deringing once threshold/alphamax were ALSO retuned per-candidate
    (0.8759 none vs 0.8744 nlm -- close enough that it's worth reviewing
    both on the next glyph rather than assuming one wins generally).

    `mkbitmap_threshold` (default 0.70, NOT mkbitmap's own 0.45 default)
    came from a full sweep 0.30-0.70 per candidate -- confirmed
    deterministic by rerunning the entire sweep twice more and getting
    bit-identical results every time, so the (non-monotonic, genuinely
    jumpy -- thresholding is a discontinuous operation on curve topology)
    curve isn't measurement noise.

    `alphamax`/`opttolerance`/`turdsize`/`unit` came from a sequential
    potrace-flag sweep per candidate. The single most important finding
    there: the numeric IoU winner for one candidate was alphamax=0.0 --
    potrace's PURE POLYGON mode, no curves at all. It scored highest
    because a polygon hugs a pixelated bitmap boundary more precisely
    than a smooth curve does, which is exactly the wrong thing to
    optimize for a font glyph. Invisible at the tiny scoring-resolution
    render; obvious once rendered at real size. Any automated future
    sweep needs a smoothness check (or a floor on alphamax, empirically
    around 0.8-1.2 depending on the candidate) alongside the IoU number,
    not IoU alone.

    turdsize/turnpolicy were swept too and found to have zero effect at
    any tested value -- confirmed genuine (not a silent flag-parsing bug)
    by verifying turdsize deletes the glyph entirely once pushed past its
    actual ink-pixel area (~3590px² on n's trace), and turnpolicy visibly
    changes a synthetic ambiguous-corner test case. They just don't
    matter for a clean single-contour trace with no ambiguous corners --
    left at defaults (turdsize=0) rather than omitted, so they're still
    on the table to revisit per glyph.

    `-b/--blur` (mkbitmap's own native blur, layered on top of whichever
    deringing already ran) was swept 0-5 and lost monotonically every
    time -- not exposed here at all; the external `dering()` step is the
    only smoothing lever."""
    up = crop.resize((crop.width * upscale, crop.height * upscale), Image.LANCZOS)
    deringed = dering(up, dering_method)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pgm_path = td / "in.pgm"
        deringed.save(pgm_path)

        pbm_path = td / "mk.pbm"
        # -x/--nodefaults turns off ALL of mkbitmap's defaults, including
        # the threshold -- not just the highpass filter it's meant to
        # suppress here. An earlier version of this pipeline passed -x
        # with no explicit -t and got a silently un-thresholded greyscale
        # PGM instead of a bilevel PBM for the entire session, until
        # caught by `file` reporting "greymap" instead of "bitmap".
        # mkbitmap_threshold is always passed explicitly now, for exactly
        # that reason -- see the note above on where its value comes from.
        _run(["mkbitmap", "-x", "-s", "1", "-t", str(mkbitmap_threshold), "-o", str(pbm_path), str(pgm_path)])

        svg_path = td / "out.svg"
        _run([
            "potrace", "-s",
            "-a", str(alphamax),
            "-O", str(opttolerance),
            "-t", str(turdsize),
            "-u", str(unit),
            "-o", str(svg_path), str(pbm_path),
        ])

        svg_text = svg_path.read_text()

    vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg_text)
    trace_w, trace_h = float(vb.group(1)), float(vb.group(2))
    paths = re.findall(r'<path d="([^"]+)"', svg_text)

    # potrace wraps its path(s) in <g transform="translate(tx,ty)
    # scale(sx,sy)"> -- its own internal units are 10x the declared
    # viewBox, and the y-flip (raw potrace y grows upward like font
    # space, SVG y grows downward) is baked into that transform's
    # negative y-scale. Ignoring this (an earlier version of this
    # function did, and separately guessed at a y-flip of its own) put
    # every coordinate 10x too large and double-flipped -- caught by a
    # sanity IoU-against-its-own-source check coming out at 0.0 with a
    # suspiciously exact square bbox. Extract and apply the real
    # transform instead of assuming one.
    g = re.search(r'<g transform="translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+),([-\d.]+)\)"', svg_text)
    if g is None:
        raise RuntimeError("potrace SVG missing expected <g transform=...> wrapper -- check potrace version/output format")
    tx, ty, sx, sy = (float(v) for v in g.groups())
    return paths, (trace_w, trace_h), (tx, ty, sx, sy)


def _pen_to_contours(pen):
    """RecordingPen.value (moveTo/lineTo/curveTo/qCurveTo/closePath) ->
    list of italic_geom.Contour. potrace's SVG output uses cubic curves
    and straight lines only (no quadratics), one subpath per contour."""
    contours = []
    start = None
    segs = []
    for op, args in pen.value:
        if op == "moveTo":
            start = args[0]
            segs = []
        elif op == "lineTo":
            segs.append(("line", args[0], True))
        elif op == "curveTo":
            c1, c2, p = args
            segs.append(("curve", c1, c2, p, True))
        elif op == "closePath":
            if segs and start is not None:
                contours.append(ig.Contour(start, True, segs))
            start = None
        elif op == "endPath":
            pass
    return contours


def _apply_g_transform(contours, transform):
    """Apply potrace's own <g transform="translate(tx,ty) scale(sx,sy)">
    to raw parsed points: SVG composes as translate(scale(point)), i.e.
    (x*sx + tx, y*sy + ty). This is potrace's real coordinate mapping
    from its internal units to the declared viewBox -- including the
    y-flip (sy is negative) -- not something to separately guess at."""
    tx, ty, sx, sy = transform

    def fn(p):
        return (p[0] * sx + tx, p[1] * sy + ty)

    out = []
    for c in contours:
        start = fn(c.start)
        segs = []
        for seg in c.segments:
            if seg[0] == "line":
                segs.append(("line", fn(seg[1]), seg[2]))
            else:
                segs.append(("curve", fn(seg[1]), fn(seg[2]), fn(seg[3]), seg[4]))
        out.append(ig.Contour(start, c.start_smooth, segs))
    return out


def _flip_y(contours, svg_height):
    """Convert potrace's SVG-space output (y-down, y=0 at the image top --
    what _apply_g_transform's coordinates are in) to font space (y-up,
    y=0 at the baseline): y' = svg_height - y.

    This single operation does two things at once, confirmed empirically
    (not assumed) on a real traced glyph:

    1. The axis-semantics fix it's named for -- without it, a trace's
       data has y=0 at the top of the letter and increasing y toward the
       bottom, backwards from font convention. Found because every
       preview comparison up to this point went through render_part,
       which applies its OWN y-flip to convert (assumed-correct)
       font-space data to image-space for PIL display -- since the data
       was actually still in image-space, that display flip coincidentally
       cancelled this bug out, so the preview looked right while the real
       data (what reaches contour_to_gspath) was upside-down.

    2. The winding-convention fix a separate `_reverse_contour` function
       used to handle (potrace's SVG winding is opposite Joan's outer/hole
       convention). A y-axis reflection is itself orientation-reversing --
       same effect on signed area as reversing a contour's point order.
       Verified directly: g_transform-only area was -578697.9; EITHER
       this flip alone OR the old reverse_contour alone corrects it to
       +578697.9; applying both together (as an earlier, wrong version of
       this pipeline would if this replaced nothing) cancels back to
       -578697.9. So this REPLACES _reverse_contour rather than
       supplementing it -- keeping both was the actual bug, not a missing
       third operation."""
    def fn(p):
        return (p[0], svg_height - p[1])

    out = []
    for c in contours:
        start = fn(c.start)
        segs = []
        for seg in c.segments:
            if seg[0] == "line":
                segs.append(("line", fn(seg[1]), seg[2]))
            else:
                segs.append(("curve", fn(seg[1]), fn(seg[2]), fn(seg[3]), seg[4]))
        out.append(ig.Contour(start, c.start_smooth, segs))
    return out


def vectorize(glyph_name, specimen_dir, mech_bbox_height, target_units_height=None, **trace_kwargs):
    """Trace `glyph_name`'s specimen cell and return italic_geom Contours
    positioned in font units, scaled so the trace's own bbox height maps
    to `target_units_height` (default: mech_bbox_height, i.e. match the
    mechanical form's overall height as the calibration anchor -- same
    role specimen_score.render_part's target_height_px plays for scoring,
    just inverted: there we scale the glyph down to the crop; here we
    scale the crop's trace up to glyph space).

    Positions the result so the SPECIMEN ROW's real shared baseline lands
    at font-space y=0 -- NOT the traced glyph's own bbox minimum, which
    an earlier version of this function used and which is only the same
    thing for non-descenders. Found directly (github.com/perrwa/Joan
    issue #3): g's mechanical form genuinely descends (bbox -284 to 464),
    and f's specimen does too even though f's roman form doesn't --
    "bbox-min -> 0" would put a descender's TIP at baseline instead of
    below it, silently shifting the whole glyph up by the descender's own
    depth. g was presented and approved before this fix existed and needs
    re-tracing. specimen_score.find_cell_any's baseline_in_crop (median
    ink-bottom across the row -- robust since most letters in a row don't
    descend) is threaded through the same upscale/flip transforms the
    contour geometry goes through, so the same point that's "baseline" in
    the specimen ends up at y=0 here, whatever the glyph's own shape does.

    Uses a loosely-padded crop (CROP_PAD) for the tracing input -- not the
    tight crop specimen_score.find_cell_any returns by default, which is
    what scoring compares against instead."""
    img_num, crop, baseline_in_crop = ss.find_cell_any(specimen_dir, glyph_name, pad=CROP_PAD)
    if crop is None:
        raise ValueError(f"{glyph_name} not found in any specimen image")

    paths, (trace_w, trace_h), g_transform = trace_crop(crop, **trace_kwargs)
    all_contours = []
    for d in paths:
        pen = RecordingPen()
        parse_path(d, pen)
        all_contours.extend(_pen_to_contours(pen))
    all_contours = _apply_g_transform(all_contours, g_transform)
    all_contours = _flip_y(all_contours, trace_h)

    if not all_contours:
        raise ValueError(f"{glyph_name}: trace produced no contours")

    # baseline_in_crop is in the ORIGINAL (pre-upscale) crop's y-down
    # pixel coords. trace_crop's mkbitmap/potrace stage always sees the
    # crop already upscaled by `upscale` (default matches trace_crop's
    # own signature) at a fixed internal mkbitmap -s 1, so the traced
    # SVG's pixel space is exactly `upscale`x the crop's -- scale the
    # reference point the same way, then apply the same y-down -> y-up
    # flip _flip_y just applied to the contours, so both are in the same
    # space before the final scale/position step below.
    upscale = trace_kwargs.get("upscale", 3)
    baseline_trace_px = trace_h - (baseline_in_crop * upscale)

    x0, y0, x1, y1 = ig.bounds(all_contours)
    th = target_units_height if target_units_height is not None else mech_bbox_height
    s = th / max(1e-6, (y1 - y0))
    positioned = ig.scale_about(all_contours, s, s, x0, y0)
    # scale_about's own formula (point' = origin + (point-origin)*s, with
    # origin=(x0,y0)) applied to the baseline reference point -- keeps it
    # exactly consistent with what just happened to the contour geometry.
    baseline_scaled = y0 + (baseline_trace_px - y0) * s
    x0b, _, _, _ = ig.bounds(positioned)
    positioned = ig.translate(positioned, -x0b, -baseline_scaled)

    # Score against the TIGHT (unpadded) crop -- that's the true ground
    # truth silhouette; the loose crop was only ever meant as tracing
    # input with breathing room, not the comparison target.
    _, score_crop, _ = ss.find_cell_any(specimen_dir, glyph_name, pad=0)
    return positioned, img_num, score_crop


if __name__ == "__main__":
    import glyphsLib
    import make_italic as MI

    ap = argparse.ArgumentParser()
    ap.add_argument("glyph")
    ap.add_argument("--specimen-dir", default=ss.DEFAULT_SPECIMEN_DIR)
    ap.add_argument("--upscale", type=int, default=3)
    ap.add_argument("--dering", choices=["none", "median", "nlm"], default="nlm")
    ap.add_argument("--mkbitmap-threshold", type=float, default=0.70)
    ap.add_argument("--alphamax", type=float, default=1.0)
    ap.add_argument("--opttolerance", type=float, default=0.1)
    ap.add_argument("--turdsize", type=int, default=0)
    ap.add_argument("--unit", type=int, default=2)
    ap.add_argument("--render", help="save a rendered preview PNG here")
    args = ap.parse_args()

    roman = glyphsLib.GSFont(MI.ROMAN_PATH)
    by = {g.name: g for g in roman.glyphs}
    mid = roman.masters[0].id
    pivot = roman.masters[0].xHeight / 2.0
    ctx = MI.Ctx(by, mid, pivot, roman.masters[0])
    mech = ctx.italic(args.glyph)
    mb = ig.bounds(mech.contours)
    mech_height = mb[3] - mb[1]

    contours, img_num, crop = vectorize(
        args.glyph, args.specimen_dir, mech_height,
        upscale=args.upscale, dering_method=args.dering,
        mkbitmap_threshold=args.mkbitmap_threshold,
        alphamax=args.alphamax, opttolerance=args.opttolerance,
        turdsize=args.turdsize, unit=args.unit,
    )
    print(f"{args.glyph}: traced {len(contours)} contour(s) from image{img_num}, bbox {ig.bounds(contours)}")

    if args.render:
        from italic_geom import Part
        part = Part(contours, 0, {})
        rendered = ss.render_part(part, crop.size[1])
        s = ss.iou(crop, rendered)
        print(f"IoU vs specimen: {s:.4f}")
        rendered.resize((rendered.width * 10, rendered.height * 10), Image.LANCZOS).save(args.render)
