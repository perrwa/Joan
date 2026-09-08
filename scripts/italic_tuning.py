"""Optical-correction data for scripts/make_italic.py.

Plain data, edited during visual iteration against scripts/proof.py output.
Nothing here is load-bearing math — it's just per-glyph/per-category knobs.
"""

# Applied to glyphs whose glyphdata category doesn't match a key below
# (punctuation, symbols, marks, production-only helper glyphs, etc).
DEFAULT_NARROW = 1.0

# Horizontal narrowing factor by coarse category (see make_italic.classify).
# A plain shear doesn't change advance widths, but italics read better
# slightly condensed; these are starting points for that iteration.
CATEGORY_NARROW = {
    "lowercase": 0.96,
    "uppercase": 0.97,
    "figures": 0.97,
}

# Explicit per-glyph overrides, checked before CATEGORY_NARROW.
GLYPH_NARROW = {}

# Per-glyph (left, right) sidebearing deltas in font units, applied after
# narrowing. Positive widens that side. Ascender/descender overhang from the
# shear causes collisions around long verticals with a slanted top or tail;
# start here and adjust based on what scripts/proof.py shows.
SIDEBEARING_DELTA = {
    "f": (0, 30),
    "j": (0, 30),
    "l": (0, 20),
    "p": (0, 20),
    "y": (0, 20),
}

# Tier A construction data (scripts/italic_recipes.py) — cut node indices,
# connector tangents, and handle lengths for the true italic constructions
# (github.com/perrwa/Joan/issues/3), against the ALREADY sheared+narrowed
# italic form of the named source glyph (ctx.italic(name) — see
# make_italic.Ctx), not roman space. Coordinates chosen by reading the
# specimen crop (scripts/specimen_score.py) and checked by IoU + visual
# comparison against it, per the execution protocol in issue #3 — one
# glyph at a time, iterated here until approved.
#
# scripts/italic_recipes.py gates its RECIPES registration on
# `CONSTRUCTION.get(name)`, so a glyph with no entry here simply isn't
# built by a recipe yet (falls through to the ordinary mechanical/Tier 2
# path), rather than crashing.
#
# Shape each key needs:
#   "n" (and other whole-letter cursive rebuilds — see STROKES below, not
#        this dict): no CONSTRUCTION entry — spine points live directly in
#        italic_recipes.py next to the recipe that builds them, since
#        there's no cut/splice data to separate from the geometry itself.
#   "a": {"ear_cut": (cut_start_node, cut_end_node), "peak": (x, y),
#         "peak_tangent": (dx, dy), "h0", "h_peak_in", "h_peak_out", "h1"}
#   "f": {"stem_cut": (right_node, left_node), "tail_slice": (start_seg, count),
#         "bridge_h0", "bridge_h1", "lsb", "rsb"}
#   "g": {"bowl_gap": (leave_node, return_node), "tail_slice": (start_seg, count),
#         "bridge_h0", "bridge_h1", "lsb", "rsb"}
#   "v"/"w"/"y": {"left": side, "right": side} where each side is
#         {"tip_idx", "new_tip": (x, y), "leave_tangent": (dx, dy),
#          "depart_tangent": (dx, dy), "h_in", "h_out",
#          "tip_in_tangent": (dx, dy)}  # tip_in_tangent optional, defaults
#                                       # to a smooth pass-through

CONSTRUCTION = {}
