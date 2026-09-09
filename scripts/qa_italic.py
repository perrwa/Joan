#!/usr/bin/env python3
"""Sanity-check sources/Joan-Italic.glyphs after a scripts/make_italic.py run.

Source-level checks only (fast, no build needed): every check here is
something make_italic.py/italic_recipes.py could plausibly get wrong
(a self-intersecting recipe/composite join, a dropped glyph, a NaN from a
bad transform, a composite whose width never got set) that gftools'
cleanUp/fontbakery wouldn't catch until much later in the pipeline, if at
all -- cleanUp: true in config.yaml removes overlaps silently rather than
flagging that one was found.

Self-intersection is checked ONLY for glyphs actually touched by a Tier A
recipe (RECIPES) or a composite that transitively depends on one -- NOT
the whole font. Confirmed directly: Joan's own roman source has plenty of
glyphs authored with intentionally overlapping contours (Z, dagger,
currency, radical.sc, ...), relying on cleanUp: true to union them at
build time -- checking those against the same simplify()-changes-contour-
count test as a "bug" is pure noise, not signal, and a first version of
this script that checked every glyph produced 244 flagged "problems" that
were entirely pre-existing roman authoring style, not anything Tier A
could have introduced. Scoping to just the recipe-touched glyphs is where
a genuine construction bug (a bad connector join, a bad composite
transform) would actually show up.

If fonts/otf/Joan-Italic.otf exists (i.e. a real build has been run), also
runs fontbakery against it and reports its result -- no baseline diffing
against Joan-Regular yet (see issue #4's verification section for that
standard), just a pass-through of fontbakery's own verdict.

Usage: python scripts/qa_italic.py
Exit code: 1 if any source-level check fails, 0 otherwise (fontbakery's
own exit code is reported but doesn't affect this script's).
"""

import math
import os
import subprocess
import sys

import glyphsLib
import pathops

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_italic as MI  # noqa: E402 -- needs sys.path set first

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROMAN_PATH = os.path.join(REPO_ROOT, "sources", "Joan_Merged_Paths.glyphs")
ITALIC_PATH = os.path.join(REPO_ROOT, "sources", "Joan-Italic.glyphs")
ITALIC_OTF = os.path.join(REPO_ROOT, "fonts", "otf", "Joan-Italic.otf")


def check_coverage(roman, italic):
    rnames = {g.name for g in roman.glyphs}
    inames = {g.name for g in italic.glyphs}
    missing = rnames - inames
    extra = inames - rnames
    problems = []
    if missing:
        problems.append(f"{len(missing)} glyph(s) dropped from italic: {sorted(missing)[:10]}")
    if extra:
        problems.append(f"{len(extra)} unexpected extra glyph(s) in italic: {sorted(extra)[:10]}")
    return problems


def _tier_a_scope(roman):
    """Glyph names actually touched by a Tier A recipe: the recipes
    themselves plus every composite that transitively depends on one
    (make_italic.depends_on_recipe -- same logic the build itself uses to
    decide when compose_from_parts runs, so this is exactly the set of
    glyphs whose geometry Tier A could have gotten wrong)."""
    rmid = roman.masters[0].id
    rby = {g.name: g for g in roman.glyphs}
    memo = {}
    return {g.name for g in roman.glyphs if MI.depends_on_recipe(g.name, rby, rmid, memo)}


def _delta(contours):
    p = pathops.Path()
    pen = p.getPen()
    for c in contours:
        pen.moveTo(c.start)
        for seg in c.segments:
            if seg[0] == "line":
                pen.lineTo(seg[1])
            else:
                pen.curveTo(seg[1], seg[2], seg[3])
        pen.closePath()
    raw = len(list(p.contours))
    simplified = len(list(pathops.simplify(p).contours))
    return raw, simplified


def check_geometry(roman, italic):
    """Per glyph: no NaN/inf coordinates, and no zero-width glyph that has
    ink and isn't zero-width in roman too (a composite whose width never
    got set in compose_from_parts) -- checked across the whole font, both
    real invariants regardless of the font's own overlap-authoring style.

    Self-intersection is checked only within the Tier A scope (see
    _tier_a_scope):

    - The 13 recipe glyphs themselves (RECIPES) get a direct check --
      brand-new geometry, so any self-intersection is worth flagging, no
      baseline needed.
    - Composites that transitively depend on a recipe (e.g. aogonek)
      instead compare against ROMAN's own decomposed raw/simplified delta
      for the same name (make_italic.decompose, unsheared): an accent
      that overlaps its base by design (found directly on aogonek --
      roman's own decomposed a+ogonekcomb is ALSO raw=3/simplified=2,
      the ogonek's normal baseline attachment, nothing to do with Tier A)
      shows the same delta in both, and only a WORSE delta in italic
      signals a real construction problem."""
    rmid = roman.masters[0].id
    imid = italic.masters[0].id
    rby = {g.name: g for g in roman.glyphs}
    scope = _tier_a_scope(roman)
    recipe_names = set(MI.RECIPES)

    problems = []
    for g in italic.glyphs:
        layer = g.layers[imid]
        if not layer.paths and not layer.components:
            continue

        for path in layer.paths:
            for n in path.nodes:
                if not (math.isfinite(n.position.x) and math.isfinite(n.position.y)):
                    problems.append(f"{g.name}: non-finite coordinate")
                    break

        if layer.paths and g.name in scope:
            i_raw, i_simp = _delta(_pen_contours(layer))
            if g.name in recipe_names:
                if i_raw != i_simp:
                    problems.append(f"{g.name}: self-intersection in recipe geometry (raw {i_raw}, simplified {i_simp})")
            else:
                r_raw, r_simp = _delta(MI.decompose(g.name, rby, rmid))
                i_delta, r_delta = i_raw - i_simp, r_raw - r_simp
                if i_delta > r_delta:
                    problems.append(
                        f"{g.name}: self-intersection beyond roman baseline "
                        f"(italic raw {i_raw}/simplified {i_simp}, roman baseline raw {r_raw}/simplified {r_simp})"
                    )

        if layer.width == 0 and layer.paths:
            rglyph = rby.get(g.name)
            rwidth = rglyph.layers[rmid].width if rglyph else None
            if rwidth != 0:
                problems.append(f"{g.name}: zero width with ink (roman width was {rwidth})")

    return problems


def _pen_contours(layer):
    """glyphsLib layer.paths -> italic_geom-style point stream for
    _delta, without importing italic_geom (this module only needs the
    pathops conversion, not the full Contour/Part toolkit)."""
    class _C:
        def __init__(self, start, segments):
            self.start = start
            self.segments = segments

    out = []
    for path in layer.paths:
        nodes = list(path.nodes)
        if not nodes:
            continue
        start_i = max(i for i, n in enumerate(nodes) if n.type != "offcurve")
        seq = nodes[start_i + 1:] + nodes[:start_i + 1]
        start_pt = (nodes[start_i].position.x, nodes[start_i].position.y)
        segments = []
        buf = []
        for n in seq:
            pt = (n.position.x, n.position.y)
            if n.type == "offcurve":
                buf.append(pt)
            elif n.type == "curve":
                segments.append(("curve", buf[0], buf[1], pt))
                buf = []
            else:
                segments.append(("line", pt))
                buf = []
        out.append(_C(start_pt, segments))
    return out


def run_fontbakery():
    if not os.path.exists(ITALIC_OTF):
        print(f"skipping fontbakery: {ITALIC_OTF} does not exist (run gftools builder first)")
        return
    # sys.executable's own directory, not bare "fontbakery" via PATH --
    # this script is normally invoked as `.venv/bin/python scripts/...`,
    # which doesn't put .venv/bin on PATH by itself (that's what `activate`
    # is for, which we don't require here).
    fontbakery_bin = os.path.join(os.path.dirname(sys.executable), "fontbakery")
    print(f"\nrunning fontbakery against {ITALIC_OTF} ...")
    subprocess.run([fontbakery_bin, "check-universal", ITALIC_OTF])


def main():
    if not os.path.exists(ITALIC_PATH):
        print(f"{ITALIC_PATH} does not exist -- run scripts/make_italic.py first")
        return 1

    roman = glyphsLib.GSFont(ROMAN_PATH)
    italic = glyphsLib.GSFont(ITALIC_PATH)

    problems = check_coverage(roman, italic) + check_geometry(roman, italic)

    if problems:
        print(f"FAIL: {len(problems)} problem(s)")
        for p in problems:
            print(f"  - {p}")
    else:
        print(f"PASS: {len(italic.glyphs)} glyphs, no coverage/geometry problems found")

    run_fontbakery()

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
