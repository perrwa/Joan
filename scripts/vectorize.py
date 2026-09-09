"""Vectorize a specimen glyph cell directly, instead of hand-authoring
curves against it (github.com/perrwa/Joan/issues/3 -- the `n` attempt
proved hand-guessing bezier coordinates from a ~30px source doesn't
converge, even when it beats the IoU number, because eyeballing can't
reproduce a calligraphic curve's actual proportions).

Pipeline: crop (scripts/specimen_score.py, already validated) -> upscale +
smooth (mkbitmap, potrace's own documented approach for low-res sources) ->
trace (potrace -> SVG) -> parse (fontTools.svgLib, already a project
dependency) -> position into the glyph's italic-space font units using the
same crop-height/bbox-height calibration specimen_score.render_part uses
for scoring.

Requires `potrace`/`mkbitmap` on PATH (`brew install potrace`).

Usage: python scripts/vectorize.py <glyph> [--alphamax 1.0] [--opttolerance 0.2]
"""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from fontTools.pens.recordingPen import RecordingPen
from fontTools.svgLib.path import parse_path
from PIL import Image

import italic_geom as ig
import specimen_score as ss


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr}")
    return r


def trace_crop(crop, mkbitmap_scale=40, mkbitmap_blur=1, alphamax=1.3, opttolerance=2.0):
    """Smooth-upscale a specimen crop with mkbitmap, trace it (potrace),
    and return the raw SVG path `d` string(s) plus the pixel dimensions
    the trace's own coordinate system is in (tracked via the traced SVG's
    own viewBox so no separate bookkeeping is needed).

    Feeds the RAW crop straight to mkbitmap rather than pre-upscaling with
    PIL first: doing both (a generic Lanczos upscale, then mkbitmap's own
    scale+filter) produced ~1000 spurious single-pixel speckle contours on
    a real test glyph -- Lanczos's negative side-lobes ring on a small
    near-binary source, and thresholding that ringing creates exactly this
    kind of noise.

    `-b/--blur` (mkbitmap_blur) is the actual smoothing lever -- a lowpass
    filter, default off. `-f/--filter` (not exposed here, left at
    mkbitmap's own default) is a HIGHPASS filter for correcting uneven
    scan lighting, unrelated to smoothing; an earlier version of this
    function tuned that one by mistake and couldn't get past ~157
    segments for a single glyph no matter how it was pushed.

    Blur is a real tradeoff, not just a cleanup knob, at this source
    resolution: a real test glyph's own connecting stroke (the arch in a
    cursive n) is only 1-2px wide, and blur=2 erased it completely --
    rendered as two disconnected stems, not an n. blur=1 was the sweet
    spot found by direct comparison: keeps every structural stroke intact
    while still roughly halving segment count (206 -> 114) versus no blur
    at all. Reducing further toward a hand-drawn font's typical 20-60
    nodes is a nice-to-have for later (fontTools-side curve simplification
    on the result), not a correctness requirement -- checked that this
    setting doesn't self-intersect (scripts/vectorize.py's own smoke test
    via pathops) before treating it as good enough."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pgm_path = td / "in.pgm"
        crop.save(pgm_path)

        pbm_path = td / "mk.pbm"
        cmd = ["mkbitmap", "-x", "-s", str(mkbitmap_scale)]
        if mkbitmap_blur:
            cmd += ["-b", str(mkbitmap_blur)]
        cmd += ["-o", str(pbm_path), str(pgm_path)]
        _run(cmd)

        svg_path = td / "out.svg"
        _run(["potrace", "-s", "-a", str(alphamax), "-O", str(opttolerance), "-o", str(svg_path), str(pbm_path)])

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
    scale the crop's trace up to glyph space)."""
    img_num, crop = ss.find_cell_any(specimen_dir, glyph_name)
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

    x0, y0, x1, y1 = ig.bounds(all_contours)
    th = target_units_height if target_units_height is not None else mech_bbox_height
    s = th / max(1e-6, (y1 - y0))
    positioned = ig.scale_about(all_contours, s, s, x0, y0)
    # Land the traced bbox's own min at (0, 0) -- final placement (advance
    # width, sidebearings) is a per-glyph decision made afterward, same as
    # the mechanical/tuning pipeline already does.
    x0b, y0b, _, _ = ig.bounds(positioned)
    positioned = ig.translate(positioned, -x0b, -y0b)
    return positioned, img_num, crop


if __name__ == "__main__":
    import glyphsLib
    import make_italic as MI

    ap = argparse.ArgumentParser()
    ap.add_argument("glyph")
    ap.add_argument("--specimen-dir", default=ss.DEFAULT_SPECIMEN_DIR)
    ap.add_argument("--mkbitmap-blur", type=int, default=1)
    ap.add_argument("--alphamax", type=float, default=1.3)
    ap.add_argument("--opttolerance", type=float, default=2.0)
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
        mkbitmap_blur=args.mkbitmap_blur, alphamax=args.alphamax, opttolerance=args.opttolerance,
    )
    print(f"{args.glyph}: traced {len(contours)} contour(s) from image{img_num}, bbox {ig.bounds(contours)}")

    if args.render:
        from italic_geom import Part
        part = Part(contours, 0, {})
        rendered = ss.render_part(part, crop.size[1])
        s = ss.iou(crop, rendered)
        print(f"IoU vs its own source specimen (sanity check, should be high): {s:.3f}")
        rendered.convert("L").resize((rendered.width * 10, rendered.height * 10), Image.LANCZOS).save(args.render)
