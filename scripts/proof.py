#!/usr/bin/env python3
"""Render roman vs. italic proofsheets straight from .glyphs sources.

Read-only rasterizer: flattens contours (including components), fills by
signed area (outer contours black, counters white via winding sign), and
writes PNGs. Not a real font renderer — no hinting, no OpenType features,
no kerning — just enough fidelity to eyeball letterform quality while
iterating on scripts/make_italic.py, scripts/italic_recipes.py and
scripts/italic_tuning.py.

Usage:
    python scripts/proof.py [output_dir]
        No-argument form: renders the default WORDS list for roman and
        italic (skipped if Joan-Italic.glyphs doesn't exist yet) to
        output_dir (default: repo root).

    python scripts/proof.py --text "waltz nymph" [--text "..."] ...
        Render one PNG per --text per style (roman/italic), instead of
        the default WORDS list.

    python scripts/proof.py --glyphs a,g,f,v,w,y
        Render a single-row sheet of the named glyphs (large, spaced out
        for construction review) instead of word proofs.

    python scripts/proof.py --text "hamburgefonts" --compare
        Stack roman above italic in one PNG per --text/--glyphs entry,
        instead of writing separate roman/italic files.

    --scale FLOAT   glyph-units-to-pixels scale (default 0.3)
    --out DIR       output directory (default: repo root, or the
                     positional arg in the no-argument-compatible form)
"""

import argparse
import os

import glyphsLib
from fontTools.misc.transform import Transform
from fontTools.pens.recordingPen import RecordingPen
from PIL import Image, ImageDraw

WORDS = ["hamburgefonts", "waltz nymph"]


class GlyphSource:
    def __init__(self, path):
        self.font = glyphsLib.GSFont(path)
        master = self.font.masters[0]
        self.master_id = master.id
        self.by_name = {g.name: g for g in self.font.glyphs}
        self.ascender = master.ascender
        self.descender = master.descender

    def contours(self, name, matrix=Transform(), out=None):
        """Recording-pen contours for a glyph, flattening components with
        full affine composition (not just translation — several composites
        in this font use rotated or scaled accents, e.g. dcaron's caron is
        a rotated acutecomb)."""
        out = [] if out is None else out
        glyph = self.by_name.get(name)
        if glyph is None:
            return out
        layer = glyph.layers[self.master_id]
        for path in layer.paths:
            nodes = list(path.nodes)
            if not nodes:
                continue
            # Contours can start at any node; rotate so we start on-curve.
            start = max(i for i, n in enumerate(nodes) if n.type != "offcurve")
            seq = nodes[start + 1:] + nodes[:start + 1]
            pen = RecordingPen()
            pen.moveTo(matrix.transformPoint((nodes[start].position.x, nodes[start].position.y)))
            buf = []
            for n in seq:
                pt = matrix.transformPoint((n.position.x, n.position.y))
                if n.type == "offcurve":
                    buf.append(pt)
                elif n.type == "curve":
                    pen.curveTo(*buf, pt)
                    buf = []
                else:
                    pen.lineTo(pt)
                    buf = []
            pen.closePath()
            out.append(pen.value)
        for c in layer.components:
            sub_matrix = matrix.transform(Transform(*c.transform))
            self.contours(c.name, sub_matrix, out)
        return out

    def width(self, name):
        glyph = self.by_name.get(name)
        return glyph.layers[self.master_id].width if glyph else 0


def flatten(recording, steps=24):
    """Recording-pen value -> flat point list (cubic curves subdivided)."""
    pts, last = [], None
    for op, args in recording:
        if op == "moveTo":
            pts = [args[0]]
            last = args[0]
        elif op == "lineTo":
            pts.append(args[0])
            last = args[0]
        elif op == "curveTo":
            a, b, c, d = last, args[0], args[1], args[2]
            for i in range(1, steps + 1):
                t = i / steps
                m = 1 - t
                pts.append((
                    m**3 * a[0] + 3 * m*m*t * b[0] + 3 * m*t*t * c[0] + t**3 * d[0],
                    m**3 * a[1] + 3 * m*m*t * b[1] + 3 * m*t*t * c[1] + t**3 * d[1],
                ))
            last = d
    return pts


def signed_area(pts):
    return sum(
        pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
        for i in range(len(pts))
    ) / 2


def _glyph_width(source, name):
    return source.width(name) if name != " " else (source.width("space") or 250)


def row_width(source, names, scale, gap=0):
    total = sum(_glyph_width(source, n) * scale for n in names)
    return total + gap * max(len(names) - 1, 0)


def draw_run(draw, source, names, x, y_baseline, scale, gap=0):
    """Draw a sequence of glyph names starting at device (x, y_baseline);
    return the device x position after the last glyph."""
    for name in names:
        if name != " ":
            polys = [flatten(c) for c in source.contours(name)]
            polys.sort(key=lambda p: -abs(signed_area(p)))
            for poly in polys:
                dev = [(x + px * scale, y_baseline - py * scale) for px, py in poly]
                draw.polygon(dev, fill=(0 if signed_area(poly) > 0 else 255))
        x += _glyph_width(source, name) * scale + gap
    return x


def render_row(source, names, path, scale=0.3, pad=40, gap=0):
    """Row height/baseline come from the source's own ascender/descender
    (not a guessed line_height with a fixed pad below baseline) — a
    single-storey g's tail or any other real descender needs actual room
    below the baseline, not just the margin."""
    W = pad * 2 + int(row_width(source, names, scale, gap))
    row_h = int((source.ascender - source.descender) * scale)
    H = row_h + pad * 2
    img = Image.new("L", (max(W, 1), H), 255)
    draw = ImageDraw.Draw(img)
    baseline = pad + int(source.ascender * scale)
    draw_run(draw, source, names, pad, baseline, scale, gap)
    img.save(path)
    print(f"wrote {path}")


def render_compare(roman, italic, names, path, scale=0.3, pad=40, gap=0, row_gap=30):
    """Stack a roman render above an italic render of the same names."""
    W = pad * 2 + max(int(row_width(roman, names, scale, gap)), int(row_width(italic, names, scale, gap)))
    ascender = max(roman.ascender, italic.ascender)
    descender = min(roman.descender, italic.descender)
    row_h = int((ascender - descender) * scale)
    H = row_h * 2 + pad * 2 + row_gap
    img = Image.new("L", (max(W, 1), H), 255)
    draw = ImageDraw.Draw(img)
    baseline = pad + int(ascender * scale)
    draw_run(draw, roman, names, pad, baseline, scale, gap)
    draw_run(draw, italic, names, pad, baseline + row_h + row_gap, scale, gap)
    img.save(path)
    print(f"wrote {path}")


def default_main(out_dir, repo_root):
    """No-argument-compatible behaviour: render WORDS for roman and
    (if present) italic."""
    roman_path = os.path.join(repo_root, "sources", "Joan_Merged_Paths.glyphs")
    roman = GlyphSource(roman_path)
    for word in WORDS:
        safe = word.replace(" ", "_")
        render_row(roman, list(word), os.path.join(out_dir, f"proof_roman_{safe}.png"))

    italic_path = os.path.join(repo_root, "sources", "Joan-Italic.glyphs")
    if os.path.exists(italic_path):
        italic = GlyphSource(italic_path)
        for word in WORDS:
            safe = word.replace(" ", "_")
            render_row(italic, list(word), os.path.join(out_dir, f"proof_italic_{safe}.png"))
    else:
        print(f"skipping italic proofs: {italic_path} does not exist yet")


def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out_dir_positional", nargs="?", default=None,
                         help="output dir (no-argument-compatible positional form)")
    parser.add_argument("--text", action="append", default=[], help="render this string (repeatable)")
    parser.add_argument("--glyphs", default=None, help="comma-separated glyph names for a single-row sheet")
    parser.add_argument("--compare", action="store_true", help="stack roman above italic in one PNG")
    parser.add_argument("--scale", type=float, default=0.3, help="glyph-units-to-pixels scale (default 0.3)")
    parser.add_argument("--out", default=None, help="output directory (default: repo root)")
    args = parser.parse_args()

    out_dir = args.out or args.out_dir_positional or "."
    os.makedirs(out_dir, exist_ok=True)

    if not args.text and not args.glyphs:
        default_main(out_dir, repo_root)
        return

    roman_path = os.path.join(repo_root, "sources", "Joan_Merged_Paths.glyphs")
    italic_path = os.path.join(repo_root, "sources", "Joan-Italic.glyphs")
    roman = GlyphSource(roman_path)
    italic = GlyphSource(italic_path) if os.path.exists(italic_path) else None
    if args.compare and italic is None:
        print(f"--compare needs {italic_path}, which does not exist yet")
        return

    entries = [(word.replace(" ", "_"), list(word), 0) for word in args.text]
    if args.glyphs:
        names = [n.strip() for n in args.glyphs.split(",") if n.strip()]
        entries.append(("glyphs_" + "-".join(names), names, 60))

    for tag, names, gap in entries:
        if args.compare:
            path = os.path.join(out_dir, f"proof_compare_{tag}.png")
            render_compare(roman, italic, names, path, scale=args.scale, gap=gap)
        else:
            render_row(roman, names, os.path.join(out_dir, f"proof_roman_{tag}.png"), scale=args.scale, gap=gap)
            if italic is not None:
                render_row(italic, names, os.path.join(out_dir, f"proof_italic_{tag}.png"), scale=args.scale, gap=gap)


if __name__ == "__main__":
    main()
