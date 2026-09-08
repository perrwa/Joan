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
