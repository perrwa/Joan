#!/usr/bin/env python3
"""Generate sources/Joan-Italic.glyphs from sources/Joan_Merged_Paths.glyphs.

Tier 2: a mechanically-derived italic. Every composite glyph is decomposed
to plain contours (general affine composition, so rotated/scaled accent
placements like the caron built from a rotated acutecomb stay correct),
sheared about the x-height midline, given back its curve extrema, then
optically corrected per scripts/italic_tuning.py (narrowing + sidebearing).

Tier 3 (github.com/perrwa/Joan/issues/1) will replace individual
letterforms with true italic constructions. The RECIPES registry below is
that seam: a glyph name in RECIPES is built by its callable instead of the
mechanical path, and gets no further correction applied — a recipe is
expected to return finished geometry.

Deterministic and re-runnable: rerun after editing italic_tuning.py or
RECIPES, inspect with scripts/proof.py, repeat.

Usage: python scripts/make_italic.py
"""

import math
import os

import glyphsLib
from fontTools.misc.bezierTools import calcCubicParameters, solveQuadratic, splitCubicAtT
from fontTools.misc.transform import Transform
from glyphsLib import glyphdata
from glyphsLib.classes import GSPath, GSNode

import italic_tuning

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROMAN_PATH = os.path.join(REPO_ROOT, "sources", "Joan_Merged_Paths.glyphs")
ITALIC_PATH = os.path.join(REPO_ROOT, "sources", "Joan-Italic.glyphs")

ITALIC_ANGLE = 10.0
SLANT_K = math.tan(math.radians(ITALIC_ANGLE))

# Tier 3 hook (see module docstring). name -> callable(by_name, master_id) -> list[Contour]
RECIPES = {}


class Contour:
    """A closed contour: a start point plus a list of line/curve segments
    back to it. Segments are ('line', pt, smooth) or
    ('curve', ctrl1, ctrl2, pt, smooth) — smooth describes the on-curve
    point the segment ends at."""

    __slots__ = ("start", "start_smooth", "segments")

    def __init__(self, start, start_smooth, segments):
        self.start = start
        self.start_smooth = start_smooth
        self.segments = segments


def classify(name):
    """Coarse category used to key scripts/italic_tuning.CATEGORY_NARROW."""
    info = glyphdata.get_glyph(name)
    if info is None or info.category is None:
        return "other"
    if info.category == "Number":
        return "figures"
    if info.category == "Letter":
        return "uppercase" if name[:1].isupper() else "lowercase"
    return "other"


def decompose(name, by_name, master_id, matrix=Transform()):
    """Fully resolve a glyph (including nested components) to a flat list
    of Contours in absolute space, using the ORIGINAL (unsheared) source.
    General affine composition, so rotated/scaled components resolve
    correctly, not just translated ones."""
    glyph = by_name.get(name)
    if glyph is None:
        return []
    layer = glyph.layers[master_id]
    contours = []
    for path in layer.paths:
        nodes = list(path.nodes)
        if not nodes:
            continue
        start_i = max(i for i, n in enumerate(nodes) if n.type != "offcurve")
        seq = nodes[start_i + 1:] + nodes[:start_i + 1]
        start_node = nodes[start_i]
        start_pt = matrix.transformPoint((start_node.position.x, start_node.position.y))
        segments = []
        buf = []
        for n in seq:
            pt = matrix.transformPoint((n.position.x, n.position.y))
            if n.type == "offcurve":
                buf.append(pt)
            elif n.type == "curve":
                segments.append(("curve", buf[0], buf[1], pt, n.smooth))
                buf = []
            else:
                segments.append(("line", pt, n.smooth))
                buf = []
        contours.append(Contour(start_pt, start_node.smooth, segments))
    for c in layer.components:
        sub_matrix = matrix.transform(Transform(*c.transform))
        contours.extend(decompose(c.name, by_name, master_id, sub_matrix))
    return contours


def shear_pt(pt, pivot_y):
    x, y = pt
    return (x + SLANT_K * (y - pivot_y), y)


def shear_contour(contour, pivot_y):
    start = shear_pt(contour.start, pivot_y)
    segs = []
    for seg in contour.segments:
        if seg[0] == "line":
            _, pt, smooth = seg
            segs.append(("line", shear_pt(pt, pivot_y), smooth))
        else:
            _, c1, c2, pt, smooth = seg
            segs.append((
                "curve",
                shear_pt(c1, pivot_y),
                shear_pt(c2, pivot_y),
                shear_pt(pt, pivot_y),
                smooth,
            ))
    return Contour(start, contour.start_smooth, segs)


def insert_extrema(contour):
    """Split cubic segments at the horizontal-tangent points a shear
    introduces (the shear leaves y(t) untouched, so vertical-tangent
    extrema are unaffected; only left/right extrema move off-node)."""
    new_segs = []
    cur = contour.start
    for seg in contour.segments:
        if seg[0] == "line":
            new_segs.append(seg)
            cur = seg[1]
            continue
        _, c1, c2, end, smooth = seg
        a, b, c, _d = calcCubicParameters(cur, c1, c2, end)
        roots = sorted(t for t in solveQuadratic(3 * a[0], 2 * b[0], c[0]) if 0.001 < t < 0.999)
        if not roots:
            new_segs.append(seg)
        else:
            pieces = splitCubicAtT(cur, c1, c2, end, *roots)
            last = len(pieces) - 1
            for i, (_p0, p1, p2, p3) in enumerate(pieces):
                new_segs.append(("curve", p1, p2, p3, smooth if i == last else True))
        cur = end
    return Contour(contour.start, contour.start_smooth, new_segs)


def correct_contour(contour, narrow_factor, left_delta):
    def fix(pt):
        x, y = pt
        return (x * narrow_factor + left_delta, y)

    start = fix(contour.start)
    segs = []
    for seg in contour.segments:
        if seg[0] == "line":
            _, pt, smooth = seg
            segs.append(("line", fix(pt), smooth))
        else:
            _, c1, c2, pt, smooth = seg
            segs.append(("curve", fix(c1), fix(c2), fix(pt), smooth))
    return Contour(start, contour.start_smooth, segs)


def contour_to_gspath(contour):
    path = GSPath()
    segments = contour.segments
    last_type = "curve" if segments and segments[-1][0] == "curve" else "line"
    path.nodes.append(GSNode(contour.start, type=last_type, smooth=contour.start_smooth))
    # The last segment's endpoint is contour.start itself (the contour is
    # closed), which is already on the path as the node above — so its
    # control points are emitted below but its terminal point is skipped.
    for i, seg in enumerate(segments):
        is_last = i == len(segments) - 1
        if seg[0] == "line":
            if not is_last:
                _, pt, smooth = seg
                path.nodes.append(GSNode(pt, type="line", smooth=smooth))
        else:
            _, c1, c2, pt, smooth = seg
            path.nodes.append(GSNode(c1, type="offcurve"))
            path.nodes.append(GSNode(c2, type="offcurve"))
            if not is_last:
                path.nodes.append(GSNode(pt, type="curve", smooth=smooth))
    return path


def tuning_for(name):
    narrow = italic_tuning.GLYPH_NARROW.get(name)
    if narrow is None:
        narrow = italic_tuning.CATEGORY_NARROW.get(classify(name), italic_tuning.DEFAULT_NARROW)
    left_delta, right_delta = italic_tuning.SIDEBEARING_DELTA.get(name, (0, 0))
    return narrow, left_delta, right_delta


def build_glyph(name, by_name, master_id, pivot_y):
    if name in RECIPES:
        return RECIPES[name](by_name, master_id), None

    contours = decompose(name, by_name, master_id)
    contours = [shear_contour(c, pivot_y) for c in contours]
    contours = [insert_extrema(c) for c in contours]

    narrow, left_delta, right_delta = tuning_for(name)
    contours = [correct_contour(c, narrow, left_delta) for c in contours]

    original_width = by_name[name].layers[master_id].width
    new_width = original_width * narrow + left_delta + right_delta
    return contours, new_width


def main():
    reference = glyphsLib.GSFont(ROMAN_PATH)
    italic = glyphsLib.GSFont(ROMAN_PATH)

    ref_master = reference.masters[0]
    ref_by_name = {g.name: g for g in reference.glyphs}
    master_id = ref_master.id
    pivot_y = ref_master.xHeight / 2

    for glyph in italic.glyphs:
        layer = glyph.layers[master_id]
        if not layer.paths and not layer.components:
            continue

        contours, new_width = build_glyph(glyph.name, ref_by_name, master_id, pivot_y)

        layer.components = []
        layer.paths = [contour_to_gspath(c) for c in contours]
        if new_width is not None:
            layer.width = new_width

        if layer.anchors:
            narrow, left_delta, _right_delta = tuning_for(glyph.name)
            for anchor in layer.anchors:
                x, y = shear_pt((anchor.position.x, anchor.position.y), pivot_y)
                anchor.position = (x * narrow + left_delta, y)

    italic.masters[0].italicAngle = ITALIC_ANGLE
    if italic.instances:
        italic.instances[0].name = "Italic"
        italic.instances[0].isItalic = True

    italic.save(ITALIC_PATH)
    print(f"wrote {ITALIC_PATH}")


if __name__ == "__main__":
    main()
