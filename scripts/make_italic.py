#!/usr/bin/env python3
"""Generate sources/Joan-Italic.glyphs from sources/Joan_Merged_Paths.glyphs.

Tier 2: a mechanically-derived italic. Every composite glyph is decomposed
to plain contours (general affine composition, so rotated/scaled accent
placements like the caron built from a rotated acutecomb stay correct),
sheared about the x-height midline, given back its curve extrema, then
optically corrected per scripts/italic_tuning.py (narrowing + sidebearing).

Tier 3 (github.com/perrwa/Joan/issues/1) replaces individual letterforms
with true italic constructions cut from Joan's own contours. A glyph name
in RECIPES (populated from scripts/italic_recipes.py) is built by its
callable instead of the mechanical path and gets no further correction —
a recipe is expected to return finished geometry (a Part: contours, its
own advance width, its own anchors), built by direct contour surgery
(scripts/italic_geom.py) rather than boolean union of clipped shapes.

Build graph: `part_for(name)` is memoized and, per name, is one of:
  1. name in RECIPES -> the recipe's Part, called with `ctx`.
  2. a pure composite (no paths of its own) whose components transitively
     include a recipe glyph -> `compose_from_parts` places each
     component's already-built Part into the composite, conjugating the
     roman component transform for plain (non-recipe) components and
     re-solving mark placement from anchors when a sibling component is
     recipe-built (see compose_from_parts docstring).
  3. otherwise -> today's mechanical path (decompose, shear, reinsert
     extrema, narrow), unchanged from Tier 2.
Memoization plus recursion gives dependency ordering for free.

Deterministic and re-runnable: rerun after editing italic_tuning.py or
italic_recipes.py, inspect with scripts/proof.py, repeat.

Usage: python scripts/make_italic.py
"""

import importlib.util
import math
import os

import glyphsLib
from fontTools.misc.bezierTools import calcCubicParameters, solveQuadratic, splitCubicAtT
from fontTools.misc.transform import Transform
from glyphsLib import glyphdata
from glyphsLib.classes import GSPath, GSNode

import italic_tuning
from italic_geom import Contour, Part

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROMAN_PATH = os.path.join(REPO_ROOT, "sources", "Joan_Merged_Paths.glyphs")
ITALIC_PATH = os.path.join(REPO_ROOT, "sources", "Joan-Italic.glyphs")

ITALIC_ANGLE = 10.0
SLANT_K = math.tan(math.radians(ITALIC_ANGLE))

# name -> callable(ctx) -> Part. Populated below from italic_recipes, kept
# as a plain module dict so tests/tools can still do `RECIPES["a"] = ...`.
RECIPES = {}


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


def mechanical_matrix(name, pivot_y):
    """The affine map (shear about pivot_y, then this glyph's own
    narrow/left_delta) that scripts/italic_tuning.py applies to `name`.
    Used by compose_from_parts to conjugate roman component transforms."""
    narrow, left_delta, _right_delta = tuning_for(name)
    return Transform(narrow, 0, narrow * SLANT_K, 1, -narrow * SLANT_K * pivot_y + left_delta, 0)


def mechanical_part(name, by_name, master_id, pivot_y):
    """Today's Tier 2 path (decompose, shear, reinsert extrema, narrow),
    packaged as a Part. This is the raw material ctx.italic(name) hands to
    recipes, and the fallback for every glyph not touched by a recipe."""
    glyph = by_name.get(name)
    if glyph is None:
        return Part([], 0, {})
    layer = glyph.layers[master_id]

    contours = decompose(name, by_name, master_id)
    contours = [shear_contour(c, pivot_y) for c in contours]
    contours = [insert_extrema(c) for c in contours]

    narrow, left_delta, right_delta = tuning_for(name)
    contours = [correct_contour(c, narrow, left_delta) for c in contours]

    width = layer.width * narrow + left_delta + right_delta

    anchors = {}
    for anchor in layer.anchors:
        x, y = shear_pt((anchor.position.x, anchor.position.y), pivot_y)
        anchors[anchor.name] = (x * narrow + left_delta, y)

    return Part(contours, width, anchors)


class Ctx:
    """Passed to recipe(ctx) -> Part. ctx.italic(name) is the memoized
    mechanical italic form of any roman glyph — the raw material recipes
    cut from — regardless of whether `name` itself has a recipe."""

    def __init__(self, by_name, master_id, pivot_y, master):
        self.by_name = by_name
        self.master_id = master_id
        self.pivot_y = pivot_y
        self.xheight = master.xHeight
        self.slant_k = SLANT_K
        self.ascender = master.ascender
        self.descender = master.descender
        self.cap_height = master.capHeight
        self._cache = {}

    def italic(self, name):
        if name not in self._cache:
            self._cache[name] = mechanical_part(name, self.by_name, self.master_id, self.pivot_y)
        return self._cache[name]


def is_pure_composite(name, by_name, master_id):
    glyph = by_name.get(name)
    if glyph is None:
        return False
    layer = glyph.layers[master_id]
    return not layer.paths and bool(layer.components)


def depends_on_recipe(name, by_name, master_id, memo):
    if name in memo:
        return memo[name]
    memo[name] = False  # break cycles conservatively; composite nesting is acyclic in practice
    if name in RECIPES:
        result = True
    else:
        glyph = by_name.get(name)
        layer = glyph.layers[master_id] if glyph else None
        components = layer.components if layer else []
        result = any(depends_on_recipe(c.name, by_name, master_id, memo) for c in components)
    memo[name] = result
    return result


def _apply_affine(transform, contour):
    def f(pt):
        return transform.transformPoint(pt)

    segs = []
    for seg in contour.segments:
        if seg[0] == "line":
            _, pt, smooth = seg
            segs.append(("line", f(pt), smooth))
        else:
            _, c1, c2, pt, smooth = seg
            segs.append(("curve", f(c1), f(c2), f(pt), smooth))
    return Contour(f(contour.start), contour.start_smooth, segs)


def _linear_only(transform):
    return Transform(transform.xx, transform.xy, transform.yx, transform.yy, 0, 0)


def compose_from_parts(name, by_name, master_id, pivot_y, memo, part_for_fn):
    """Assemble a pure composite whose components transitively include a
    recipe glyph. Each component is placed by:

    - Recipe-dependent component (the recipe letter itself, e.g. `a` in
      `aacute`): placed directly via its own roman component transform
      (identity in every case in this font) — the recipe already returns
      finished, correctly-scaled geometry, so no further conjugation.

    - Plain (mechanical) component, e.g. an accent mark: its LINEAR part
      is conjugated the usual way (this glyph's own tuning, roman
      transform, the component's own tuning inverted) so rotated/scaled
      accents like a caron stay correctly shaped. Its TRANSLATION is
      re-solved from anchors — base carries anchor X, mark carries _X —
      because the roman offset assumed the OLD (mechanical) base shape;
      a recipe base has a different outline and the accent has to sit on
      its actual anchor, not the old numeric offset. If no anchor match
      exists, falls back to the raw roman component translation.
    """
    layer = by_name[name].layers[master_id]
    out_contours = []
    placed_anchors = {}
    width = None

    for c in layer.components:
        base_part = part_for_fn(c.name)
        L = Transform(*c.transform)

        if depends_on_recipe(c.name, by_name, master_id, memo):
            transform = L
            out_contours.extend(_apply_affine(transform, ct) for ct in base_part.contours)
            for aname, apos in base_part.anchors.items():
                placed_anchors[aname] = transform.transformPoint(apos)
            if width is None:
                width = base_part.width
            continue

        M_name = mechanical_matrix(name, pivot_y)
        M_c = mechanical_matrix(c.name, pivot_y)
        linear = _linear_only(M_name).transform(_linear_only(L)).transform(_linear_only(M_c).inverse())

        target = None
        for aname, apos in placed_anchors.items():
            mark_anchor = base_part.anchors.get("_" + aname)
            if mark_anchor is not None:
                target = (apos, mark_anchor)
                break

        if target is not None:
            base_target, mark_local = target
            mapped = linear.transformPoint(mark_local)
            dx = base_target[0] - mapped[0]
            dy = base_target[1] - mapped[1]
        else:
            dx, dy = L.dx, L.dy

        transform = Transform(linear.xx, linear.xy, linear.yx, linear.yy, dx, dy)
        out_contours.extend(_apply_affine(transform, ct) for ct in base_part.contours)
        for aname, apos in base_part.anchors.items():
            if not aname.startswith("_"):
                placed_anchors[aname] = transform.transformPoint(apos)

    return Part(out_contours, width if width is not None else 0, placed_anchors)


def part_for(name, by_name, master_id, pivot_y, ctx, cache, depend_memo):
    if name in cache:
        return cache[name]

    def resolve(n):
        return part_for(n, by_name, master_id, pivot_y, ctx, cache, depend_memo)

    if name in RECIPES:
        part = RECIPES[name](ctx)
    elif is_pure_composite(name, by_name, master_id) and depends_on_recipe(name, by_name, master_id, depend_memo):
        part = compose_from_parts(name, by_name, master_id, pivot_y, depend_memo, resolve)
    else:
        part = mechanical_part(name, by_name, master_id, pivot_y)

    cache[name] = part
    return part


def main():
    reference = glyphsLib.GSFont(ROMAN_PATH)
    italic = glyphsLib.GSFont(ROMAN_PATH)

    ref_master = reference.masters[0]
    ref_by_name = {g.name: g for g in reference.glyphs}
    master_id = ref_master.id
    pivot_y = ref_master.xHeight / 2

    ctx = Ctx(ref_by_name, master_id, pivot_y, ref_master)
    cache = {}
    depend_memo = {}

    for glyph in italic.glyphs:
        layer = glyph.layers[master_id]
        if not layer.paths and not layer.components:
            continue

        part = part_for(glyph.name, ref_by_name, master_id, pivot_y, ctx, cache, depend_memo)

        layer.components = []
        layer.paths = [contour_to_gspath(c) for c in part.contours]
        layer.width = part.width

        if layer.anchors:
            for anchor in layer.anchors:
                pos = part.anchors.get(anchor.name)
                if pos is not None:
                    anchor.position = pos

    italic.masters[0].italicAngle = ITALIC_ANGLE
    if italic.instances:
        italic.instances[0].name = "Italic"
        italic.instances[0].isItalic = True

    italic.save(ITALIC_PATH)
    print(f"wrote {ITALIC_PATH}")


# Load recipes if the module exists at all — deliberately NOT a bare
# `try/except ImportError`, which would swallow a real bug inside
# italic_recipes.py (e.g. a name error, or `from italic_tuning import
# CONSTRUCTION` failing because that name doesn't exist) identically to
# "the module just isn't there yet", and make_italic.py would silently
# fall back to pure Tier 2 with no signal anything is wrong.
if importlib.util.find_spec("italic_recipes") is not None:
    import italic_recipes
    RECIPES.update(italic_recipes.RECIPES)


if __name__ == "__main__":
    main()
