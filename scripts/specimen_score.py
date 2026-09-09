"""Segment Paolo Biagini's published italic specimen images into per-glyph
crops, and score a candidate Part's silhouette against one by a soft
(fractional-coverage) intersection-over-union.

This is the objective function behind the Tier A/B execution protocol
(github.com/perrwa/Joan/issues/3, /4): render a candidate glyph, crop the
matching specimen cell, and measure overlap so "did this edit move toward
the target" has a number attached, not just a visual impression. Coarse by
nature — the specimen source is roughly a 60px em — so treat scores as a
ranking/regression signal alongside a visual check, not a precision fitness
function.

render_part supersamples then box-downsamples (real antialiasing, not a hard
threshold) and iou() compares fractional ink coverage rather than two
booleans — otherwise two candidates differing by less than one native
specimen pixel can tie exactly even when they'd visibly differ once
upscaled for human inspection. Found via rubber-duck review after a scale
comparison's visual judgment ("4x looks best") didn't match a tied ad-hoc
metric elsewhere in this project; see render_part's and iou's own
docstrings for the specifics.

Usage: python scripts/specimen_score.py <glyph> [--crop out.png]
"""

import argparse
import math
import os
import sys

from PIL import Image, ImageDraw

# Repo-relative, not a session-specific temp path -- populated by
# scripts/fetch_specimen.py, gitignored (Paolo's copyrighted images).
DEFAULT_SPECIMEN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reference", "pb-italic"
)

# Row/column layout of https://www.paolobiagini.altervista.org/joan-italic-font.php's
# three specimen images, transcribed by hand from the published PNGs — cell
# order isn't derivable from the images themselves. Verified: segmenting each
# image with a 5px row gap / 18px column gap yields exactly these counts per
# row (8/8/8/8/8/7 for image 1, 8/8/8/8/8/5 for image 2/3).
IMG1 = [
    ["a", "ae", "b", "c", "d", "eth", "e", "schwa"],
    ["f", "g", "h", "i", "j", "ij", "k", "kgreenlandic"],
    ["l", "m", "n", "nhookleft", "eng", "o", "oe", "p"],
    ["thorn", "q", "r", "s", "germandbls", "longs", "t", "u"],
    ["v", "w", "x", "y", "z", "one", "two", "three"],
    ["four", "five", "six", "seven", "eight", "nine", "zero"],
]
IMG2 = [
    ["A", "AE", "B", "C", "D", "Eth", "E", "Schwa"],
    ["F", "G", "H", "I", "J", "IJ", "K", "L"],
    ["M", "N", "Nhookleft", "Eng", "O", "OE", "P", "Thorn"],
    ["Q", "R", "S", "Germandbls", "T", "U", "V", "W"],
    ["X", "Y", "Z", "one.lf", "two.lf", "three.lf", "four.lf", "five.lf"],
    ["six.lf", "seven.lf", "eight.lf", "nine.lf", "zero.lf"],
]
IMG3 = [
    [n + ".sc" if not n[0].isupper() else n for n in row]
    for row in [
        ["a", "ae", "b", "c", "d", "eth", "e", "schwa"],
        ["f", "g", "h", "i", "j", "ij", "k", "l"],
        ["m", "n", "nhookleft", "eng", "o", "oe", "p", "thorn"],
        ["q", "r", "s", "germandbls", "t", "u", "v", "w"],
        ["x", "y", "z", "one", "two", "three", "four", "five"],
        ["six", "seven", "eight", "nine", "zero"],
    ]
]
# .sc figures are zero.sc-nine.sc, not zero.lf.sc (verified: doesn't exist).
IMG3 = [[n.replace(".sc", "") + ".sc" if n.endswith(".sc") else n for n in row] for row in IMG3]

SPECIMENS = {1: ("pb-italic-1.png", IMG1), 2: ("pb-italic-2.png", IMG2), 3: ("pb-italic-3.png", IMG3)}


def _load_rgba_on_white(path):
    src = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", src.size, (255, 255, 255, 255))
    return Image.alpha_composite(bg, src).convert("L")


def _bands(values, gap):
    out = []
    start = prev = values[0]
    for v in values[1:]:
        if v - prev > gap:
            out.append((start, prev))
            start = v
        prev = v
    out.append((start, prev))
    return out


def _grid(im):
    w, h = im.size
    px = im.load()
    rows = [y for y in range(h) if any(px[x, y] < 128 for x in range(w))]
    grid = []
    for y0, y1 in _bands(rows, 5):
        cols = [x for x in range(w) if any(px[x, y] < 128 for y in range(y0, y1 + 1))]
        grid.append(((y0, y1), _bands(cols, 18)))
    return grid


def _row_baseline_sheet_px(im, grid, row_idx, row_names):
    """Baseline of one specimen row, in the full sheet's own pixel
    coordinates (y-down) -- the mean ink-bottom of the tightest cluster
    of agreeing cells in the row, not any single hardcoded reference
    letter: non-descenders all bottom out at (almost) the exact same
    pixel row since they share one baseline, while descenders cluster at
    a distinctly larger y (further down). Taking the largest 3px-wide
    cluster finds that consensus regardless of which cells happen to be
    descenders.

    NOT a plain median across the row -- tried that first and it broke
    exactly here: image1's row1 (f g h i j ij k kgreenlandic) splits
    exactly 4 descenders (f g j ij, bottom=275) / 4 non-descenders (h i k
    kgreenlandic, bottom=257-258), and `sorted(bottoms)[len//2]` on an
    even-length 50/50 split picks the upper-middle element -- which
    landed on a DESCENDER's bottom (275) instead of true baseline (257),
    caught by the resulting descender depth (23 units) being visibly too
    shallow against what the specimen crop actually shows.

    Needed at all because a glyph's own ink bbox bottom is NOT baseline
    for a descender -- positioning one by "its own bbox bottom = 0" (an
    earlier version of vectorize.py's positioning did this) puts the
    descender's TIP at baseline instead of below it, silently shifting
    the whole glyph up by the descender's own depth. Caught only because
    g's mechanical form genuinely descends (bbox -284 to 464) and g had
    already been presented and approved before this existed."""
    (y0, y1), cb = grid[row_idx]
    px = im.load()
    bottoms = []
    for x0, x1 in cb:
        ys = [y for y in range(y0, y1 + 1) if any(px[x, y] < 128 for x in range(x0, x1 + 1))]
        if ys:
            bottoms.append(ys[-1])
    bottoms.sort()
    best_cluster = [bottoms[0]]
    cur = [bottoms[0]]
    for v in bottoms[1:]:
        if v - cur[0] <= 3:
            cur.append(v)
        else:
            cur = [v]
        if len(cur) > len(best_cluster):
            best_cluster = cur
    return round(sum(best_cluster) / len(best_cluster))


def find_cell(image_dir, image_num, name, pad=0):
    """Return (PIL image, baseline_y_in_crop) for `name` cropped to its
    ink bounds plus `pad` pixels of real surrounding context on each side
    (sourced from the full specimen sheet, not synthetic whitespace), or
    (None, None) if it isn't in that specimen image's table.
    `baseline_y_in_crop` is the row's shared baseline (see
    `_row_baseline_sheet_px`), in the SAME y-down pixel coordinates as
    the returned crop's own indexing (0 = crop's top row) -- use it to
    position a glyph correctly rather than assuming the crop's own
    bottom edge is baseline, which is only true for non-descenders.

    Default pad=0 (the tight ink-only crop) is what scoring (iou/
    render_part) compares against -- that's the ground-truth silhouette,
    padding it would change what's being measured. vectorize.py's tracing
    pipeline wants pad>0 instead: found directly (github.com/perrwa/Joan
    issue #3 flag-review session) that mkbitmap/potrace produce
    meaningfully better traces with breathing room around the glyph --
    the tight crop starves deringing filters and lets edge effects reach
    the actual strokes."""
    fname, table = SPECIMENS[image_num]
    for row_idx, row in enumerate(table):
        if name in row:
            im = _load_rgba_on_white(f"{image_dir}/{fname}")
            grid = _grid(im)
            (y0, y1), cb = grid[row_idx]
            x0, x1 = cb[row.index(name)]
            px = im.load()
            ys = [y for y in range(y0, y1 + 1) if any(px[x, y] < 128 for x in range(x0, x1 + 1))]
            w, h = im.size
            crop_top = max(0, ys[0] - pad)
            crop = im.crop((max(0, x0 - pad), crop_top, min(w, x1 + 1 + pad), min(h, ys[-1] + 1 + pad)))
            baseline_sheet = _row_baseline_sheet_px(im, grid, row_idx, row)
            return crop, baseline_sheet - crop_top
    return None, None


def find_cell_any(image_dir, name, pad=0):
    """Search all three specimen images for `name`; returns
    (image_num, crop, baseline_y_in_crop) or (None, None, None). See
    find_cell for `pad` and `baseline_y_in_crop`."""
    for n in (1, 2, 3):
        c, baseline = find_cell(image_dir, n, name, pad=pad)
        if c is not None:
            return n, c, baseline
    return None, None, None


def _flatten(contour, n=24):
    pts = [contour.start]
    for seg in contour.segments:
        if seg[0] == "line":
            pts.append(seg[1])
        else:
            p0 = pts[-1]
            p1, p2, p3 = seg[1], seg[2], seg[3]
            for i in range(1, n + 1):
                t = i / n
                m = 1 - t
                pts.append(
                    (
                        m**3 * p0[0] + 3 * m * m * t * p1[0] + 3 * m * t * t * p2[0] + t**3 * p3[0],
                        m**3 * p0[1] + 3 * m * m * t * p1[1] + 3 * m * t * t * p2[1] + t**3 * p3[1],
                    )
                )
    return pts


def _signed_area(poly):
    a = 0.0
    for i in range(len(poly)):
        xA, yA = poly[i]
        xB, yB = poly[(i + 1) % len(poly)]
        a += xA * yB - xB * yA
    return a / 2


def render_part(part, target_height_px, supersample=8):
    """Rasterize a Part's contours (nonzero-winding fill by signed area, not
    a true boolean union — fine for scoring, not for the actual font build)
    to a grayscale image scaled so its bbox height matches target_height_px,
    with the top-left of the bbox at pixel (0, 0) — no padding, matching how
    iou() aligns it against the specimen crop's own top-left-anchored bbox.
    Aspect ratio is preserved (not stretched to a target width), so a width
    error shows up as IoU loss instead of being hidden.

    Draws the polygon fill at `supersample`x the target resolution (still a
    hard mode "1" edge — PIL's ImageDraw has no antialiasing), then
    downsamples with Image.BOX (a plain area-average) to get genuine
    fractional pixel coverage at the boundary, returned as mode "L" (0=ink,
    255=background, matching the specimen crop's own convention). This is
    what lets iou() compare real sub-pixel coverage instead of two
    hard-thresholded masks that can tie exactly on differences smaller than
    one native specimen pixel (found via rubber-duck review, requested
    after a scale comparison's visual "4x looks best" judgment didn't match
    a tied metric). Image.LANCZOS was deliberately NOT used for the
    downsample — it has negative side-lobes that ring on hard edges, the
    same failure mode that produced literal ghosting artifacts when tried
    as a deringing filter earlier this session; Image.BOX has no ringing,
    which matters more here than its slightly softer falloff."""
    polys = [_flatten(c) for c in part.contours]
    if not polys:
        return None
    xs = [p[0] for q in polys for p in q]
    ys = [p[1] for q in polys for p in q]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    s = (target_height_px * supersample) / max(1e-6, (y1 - y0))
    w = max(1, round((x1 - x0) * s))
    h = max(1, round((y1 - y0) * s))
    img = Image.new("1", (w, h), 1)
    draw = ImageDraw.Draw(img)
    for poly in sorted(polys, key=lambda q: -abs(_signed_area(q))):
        fill = 0 if _signed_area(poly) > 0 else 1
        draw.polygon([((p[0] - x0) * s, h - 1 - (p[1] - y0) * s) for p in poly], fill=fill)
    out_w = max(1, round(w / supersample))
    out_h = max(1, round(h / supersample))
    return img.convert("L").resize((out_w, out_h), Image.BOX)


def iou(specimen_crop, rendered):
    """Soft (fractional-coverage) intersection-over-union between a
    grayscale specimen crop and a grayscale rendered image — both ink=0,
    background=255, values in between meaning partial coverage — compared
    over the specimen's own bbox.

    Generalizes boolean IoU (intersection = count where both are ink,
    union = count where either is ink) to continuous coverage fractions:
    intersection = sum(min(a, b)), union = sum(max(a, b)), same ratio.
    Reduces to the boolean formula exactly when every pixel is fully ink
    or fully background, and picks up real signal at partially-covered
    edge pixels that a hard threshold on either image would discard —
    real signal, since it exists in the specimen crop's own antialiasing
    and (as of render_part's supersample+box-downsample) in the render
    too, not invented.

    render_part preserves the candidate's own aspect ratio, so its width
    almost never equals the specimen crop's width. Building the
    comparison canvas explicitly at background value (255) and pasting
    the actual render into it (rather than `rendered.crop((0, 0, w, h))`,
    which pads out-of-bounds mode "1" pixels with ink, not background —
    a confirmed, since-fixed bug in an earlier version of this function)
    keeps a too-narrow candidate from getting free credit for area it
    never actually drew."""
    w, h = specimen_crop.size
    r = Image.new("L", (w, h), 255)
    r.paste(rendered, (0, 0))
    spec_ink = [(255 - v) / 255.0 for v in specimen_crop.getdata()]
    r_ink = [(255 - v) / 255.0 for v in r.getdata()]
    inter = sum(min(a, b) for a, b in zip(spec_ink, r_ink))
    union = sum(max(a, b) for a, b in zip(spec_ink, r_ink))
    return inter / union if union else 0.0


def score(image_dir, name, part):
    """Convenience: find name's specimen cell in any of the 3 images, score
    part against it. Returns (image_num, iou_score, specimen_crop, rendered)
    or (None, None, None, None) if name isn't in any specimen."""
    image_num, crop, _baseline = find_cell_any(image_dir, name)
    if crop is None or not part.contours:
        return None, None, crop, None
    rendered = render_part(part, crop.size[1])
    return image_num, iou(crop, rendered), crop, rendered


if __name__ == "__main__":
    import glyphsLib
    import make_italic as MI

    ap = argparse.ArgumentParser()
    ap.add_argument("glyph")
    ap.add_argument("--specimen-dir", default=DEFAULT_SPECIMEN_DIR)
    ap.add_argument("--crop", help="save the specimen crop here")
    ap.add_argument("--render", help="save the mechanical-italic render here")
    args = ap.parse_args()

    roman = glyphsLib.GSFont(MI.ROMAN_PATH)
    by = {g.name: g for g in roman.glyphs}
    mid = roman.masters[0].id
    pivot = roman.masters[0].xHeight / 2.0
    ctx = MI.Ctx(by, mid, pivot, roman.masters[0])
    part = ctx.italic(args.glyph)

    image_num, s, crop, rendered = score(args.specimen_dir, args.glyph, part)
    if crop is None:
        print(f"{args.glyph}: not found in any specimen image")
        sys.exit(1)
    print(f"{args.glyph}: image{image_num} IoU={s:.3f} specimen={crop.size} render={rendered.size if rendered else None}")
    if args.crop:
        crop.resize((crop.width * 8, crop.height * 8), Image.LANCZOS).save(args.crop)
    if args.render and rendered:
        rendered.convert("L").resize((rendered.width * 8, rendered.height * 8), Image.LANCZOS).save(args.render)
