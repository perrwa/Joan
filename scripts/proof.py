#!/usr/bin/env python3
"""Render roman vs. italic proofsheets straight from .glyphs sources.

Read-only rasterizer: flattens contours (including components), fills by
signed area (outer contours black, counters white via winding sign), and
writes PNGs. Not a real font renderer — no hinting, no OpenType features,
no kerning — just enough fidelity to eyeball letterform quality while
iterating on scripts/make_italic.py and scripts/italic_tuning.py.

Usage:
    python scripts/proof.py [output_dir]

Writes proof_roman.png and proof_italic.png (skipped if Joan-Italic.glyphs
doesn't exist yet) to output_dir (default: repo root).
"""

import os
import sys

import glyphsLib
from fontTools.misc.transform import Transform
from fontTools.pens.recordingPen import RecordingPen
from PIL import Image, ImageDraw

WORDS = ["hamburgefonts", "waltz nymph"]


class GlyphSource:
    def __init__(self, path):
        self.font = glyphsLib.GSFont(path)
        self.master_id = self.font.masters[0].id
        self.by_name = {g.name: g for g in self.font.glyphs}

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


def render_word(source, word, path, scale=0.3, pad=40, line_height=1500):
    widths = [source.width(n) if n != " " else source.width("space") or 250 for n in word]
    W = int(sum(widths) * scale) + pad * 2
    H = int(line_height * scale) + pad * 2
    img = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(img)
    x = pad
    for ch, w in zip(word, widths):
        if ch != " ":
            polys = [flatten(c) for c in source.contours(ch)]
            polys.sort(key=lambda p: -abs(signed_area(p)))
            for poly in polys:
                dev = [(x + px * scale, H - pad - py * scale) for px, py in poly]
                draw.polygon(dev, fill=(0 if signed_area(poly) > 0 else 255))
        x += w * scale
    img.save(path)
    print(f"wrote {path}")


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    roman_path = os.path.join(repo_root, "sources", "Joan_Merged_Paths.glyphs")
    roman = GlyphSource(roman_path)
    for word in WORDS:
        safe = word.replace(" ", "_")
        render_word(roman, word, os.path.join(out_dir, f"proof_roman_{safe}.png"))

    italic_path = os.path.join(repo_root, "sources", "Joan-Italic.glyphs")
    if os.path.exists(italic_path):
        italic = GlyphSource(italic_path)
        for word in WORDS:
            safe = word.replace(" ", "_")
            render_word(italic, word, os.path.join(out_dir, f"proof_italic_{safe}.png"))
    else:
        print(f"skipping italic proofs: {italic_path} does not exist yet")


if __name__ == "__main__":
    main()
