#!/usr/bin/env python3
"""Render overlay contact sheets comparing glyph outlines between two .glyphs
sources. Merged_Paths fills blue, Working_File fills red (semi-transparent);
overlap reads as dark purple, and any area unique to one side shows as pure
red or blue. Read-only, reuses the flatten/contours approach from proof.py.

Usage:
    python scripts/diff_overlay.py <glyph1> <glyph2> ... [--out DIR]
    python scripts/diff_overlay.py --names-file FILE [--out DIR]
"""

import os
import sys

import glyphsLib
from fontTools.pens.recordingPen import RecordingPen
from PIL import Image, ImageDraw

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MERGED_PATH = os.path.join(REPO_ROOT, "sources", "Joan_Merged_Paths.glyphs")
WORKING_PATH = os.path.join(REPO_ROOT, "sources", "Joan_Working_File.glyphs")


class GlyphSource:
    def __init__(self, path):
        self.font = glyphsLib.GSFont(path)
        self.master_id = self.font.masters[0].id
        self.by_name = {g.name: g for g in self.font.glyphs}

    def contours(self, name, xform=(1, 0, 0, 1, 0, 0), out=None):
        """Recording-pen contours for a glyph, flattening components with
        their full affine transform (rotation/scale/mirror, not just dx/dy)."""
        out = [] if out is None else out
        glyph = self.by_name.get(name)
        if glyph is None:
            return out
        a, b, c, d, e, f = xform

        def apply(pt):
            x, y = pt
            return (a * x + c * y + e, b * x + d * y + f)

        layer = glyph.layers[self.master_id]
        for path in layer.paths:
            nodes = list(path.nodes)
            if not nodes:
                continue
            start = max(i for i, n in enumerate(nodes) if n.type != "offcurve")
            seq = nodes[start + 1:] + nodes[:start + 1]
            pen = RecordingPen()
            pen.moveTo(apply((nodes[start].position.x, nodes[start].position.y)))
            buf = []
            for n in seq:
                pt = apply((n.position.x, n.position.y))
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
        for comp in layer.components:
            t = comp.transform
            ca, cb, cc, cd, ce, cf = t[0], t[1], t[2], t[3], t[4], t[5]
            composed = (
                a * ca + c * cb,
                b * ca + d * cb,
                a * cc + c * cd,
                b * cc + d * cd,
                a * ce + c * cf + e,
                b * ce + d * cf + f,
            )
            self.contours(comp.name, composed, out)
        return out

    def width(self, name):
        glyph = self.by_name.get(name)
        return glyph.layers[self.master_id].width if glyph else 0


def flatten(recording, steps=24):
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


def render_glyph_layer(source, name, scale, pad, cell_w, cell_h, ascent, color):
    """Return an RGBA tile with the glyph filled in `color`."""
    tile = Image.new("RGBA", (cell_w, cell_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    polys = [flatten(c) for c in source.contours(name)]
    polys.sort(key=lambda p: -abs(signed_area(p)))
    for poly in polys:
        dev = [(pad + px * scale, pad + (ascent - py) * scale) for px, py in poly]
        fill = color if signed_area(poly) > 0 else (0, 0, 0, 0)
        draw.polygon(dev, fill=fill)
    return tile


def contact_sheet(merged, working, names, out_path, cols=10, scale=0.10, pad=14, ascent=1500, descent=400, label_h=18):
    cell_w = int(700 * scale) + pad * 2
    cell_h = int((ascent + descent) * scale) + pad * 2 + label_h
    rows = (len(names) + cols - 1) // cols
    sheet = Image.new("RGB", (cell_w * cols, cell_h * rows), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)

    for i, name in enumerate(names):
        col, row = i % cols, i // cols
        ox, oy = col * cell_w, row * cell_h

        tile_base = Image.new("RGBA", (cell_w, cell_h - label_h), (255, 255, 255, 255))
        merged_tile = render_glyph_layer(merged, name, scale, pad, cell_w, cell_h - label_h, ascent, (30, 60, 220, 140))
        working_tile = render_glyph_layer(working, name, scale, pad, cell_w, cell_h - label_h, ascent, (220, 40, 40, 140))
        tile_base = Image.alpha_composite(tile_base, merged_tile)
        tile_base = Image.alpha_composite(tile_base, working_tile).convert("RGB")

        sheet.paste(tile_base, (ox, oy + label_h))
        draw.text((ox + pad, oy + 2), name, fill=(0, 0, 0))
        draw.rectangle([ox, oy, ox + cell_w - 1, oy + cell_h - 1], outline=(220, 220, 220))

    draw.rectangle([0, 0, cell_w * cols - 1, cell_h * rows - 1], outline=(180, 180, 180))
    sheet.save(out_path)
    print(f"wrote {out_path}  ({len(names)} glyphs, {cols}x{rows})")
    return out_path


def main():
    args = sys.argv[1:]
    out_dir = "."
    names_file = None
    names = []
    out_name = "diff_contact_sheet.png"
    i = 0
    while i < len(args):
        if args[i] == "--out":
            out_dir = args[i + 1]
            i += 2
        elif args[i] == "--names-file":
            names_file = args[i + 1]
            i += 2
        elif args[i] == "--out-name":
            out_name = args[i + 1]
            i += 2
        else:
            names.append(args[i])
            i += 1

    if names_file:
        with open(names_file) as f:
            names.extend(line.strip() for line in f if line.strip())

    if not names:
        print("usage: diff_overlay.py <glyph1> <glyph2> ... [--out DIR] [--names-file FILE]")
        sys.exit(1)

    merged = GlyphSource(MERGED_PATH)
    working = GlyphSource(WORKING_PATH)

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, out_name)
    contact_sheet(merged, working, names, out_path)


if __name__ == "__main__":
    main()
