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


def find_cell(image_dir, image_num, name):
    """Return a tightly-cropped (to ink bounds) PIL image for `name`, or
    None if it isn't in that specimen image's table."""
    fname, table = SPECIMENS[image_num]
    for row_idx, row in enumerate(table):
        if name in row:
            im = _load_rgba_on_white(f"{image_dir}/{fname}")
            grid = _grid(im)
            (y0, y1), cb = grid[row_idx]
            x0, x1 = cb[row.index(name)]
            px = im.load()
            ys = [y for y in range(y0, y1 + 1) if any(px[x, y] < 128 for x in range(x0, x1 + 1))]
            return im.crop((x0, ys[0], x1 + 1, ys[-1] + 1))
    return None


def find_cell_any(image_dir, name):
    """Search all three specimen images for `name`; returns (image_num, crop)
    or (None, None)."""
    for n in (1, 2, 3):
        c = find_cell(image_dir, n, name)
        if c is not None:
            return n, c
    return None, None


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
    image_num, crop = find_cell_any(image_dir, name)
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
