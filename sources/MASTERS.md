# What's needed to build wght 400-700 + Italic

`config-family.yaml` is ready to build the full family, but the weight-axis
source data isn't there yet. `Joan_Merged_Paths.glyphs`, `Joan_Working_File.glyphs`,
and `backup/2021_Joan.glyphs` each have exactly one master (`Regular`) and no
weight axis. Run `python scripts/check_masters.py sources/*.glyphs` to confirm
this directly. `Joan-Italic.glyphs` is intentionally single-master for now
(see below), so check that one on its own with
`--single-master-ok sources/Joan-Italic.glyphs`.

Adding a weight axis is Glyphs.app work; do not hand-edit the `.glyphs` files
for it. Master/instance/axis structures need Glyphs to keep master IDs, layer
IDs, and interpolation math consistent.

## Roman: `Joan.glyphs`

1. Font Info → Axes: add a `Weight` axis, tag `wght`.
2. Existing `Regular` master → set `axesValues` to `400`.
3. Add a `Bold` master at `700`. Same glyph set as Regular, and outlines
   must be interpolation-compatible with it (same contour count, same point
   count and order per contour, same anchor names) or fontmake will fail or
   produce garbage in between.
4. Give the Bold master its own alignment zones / overshoot values — don't
   copy Regular's; a heavier weight needs its own optical correction.
5. Instances: Regular (400), SemiBold (600, interpolated — no master needed
   unless the midpoint needs manual correction), Bold (700).
6. Save as `sources/Joan.glyphs`.

Vertical metrics and naming custom parameters carry over unchanged from the
current Regular master: `typoAscender 1000`, `typoDescender -292`,
`typoLineGap 0`, `winAscent 1117`, `winDescent 615`, `unitsPerEm 1000`.

## Italic: `sources/Joan-Italic.glyphs`

This exists now, but not from Glyphs.app work. `scripts/make_italic.py`
generates it mechanically from `Joan_Merged_Paths.glyphs`. It decomposes every
composite with full affine composition (so rotated/scaled accents like the
caron built from a rotated `acutecomb` land correctly), shears 10° about the
x-height midline, reinserts the curve extrema the shear moves off-node, then
applies per-category narrowing and per-glyph sidebearing correction from
`scripts/italic_tuning.py`. Single master, `italicAngle 10`, no weight axis,
the same gap as the Roman file above.

Check it with `python scripts/check_masters.py --single-master-ok
sources/Joan-Italic.glyphs`. To iterate: edit `italic_tuning.py` (or the
generator itself), rerun `python scripts/make_italic.py`, then look at the
result with `python scripts/proof.py` before rebuilding fonts.

A plain shear changes a letterform's angle, not its structure, so most of the
font stays a good sloped roman. `RECIPES` (populated from
`scripts/italic_recipes.py`) is the hook where individual letters instead get
a real italic construction, and that's landed for the letters whose specimen
skeleton genuinely differs from a sheared roman: `a f g y k p n m h r
germandbls l eng` (single-storey `a`, cursive `g`, descending `f`, entry/exit
strokes on `y`, ...) are traced directly from Paolo Biagini's published
italic specimen (`scripts/vectorize.py`: crop → upscale → mkbitmap → potrace
→ position in italic space) rather than sheared, per
[perrwa/Joan#3](https://github.com/perrwa/Joan/issues/3). Every composite
that transitively depends on one of these (`aacute`, `gcommaaccent`, ...) is
reassembled around the real construction via `compose_from_parts`, not left
pointing at the old mechanical shape.

The rest of the lowercase/figures/extended-latin set that's close-but-not-
identical to the specimen (`b c d e i j o q s t u x z v w` + figures, IoU
0.32–0.81) is still mechanically sheared, pending targeted tuning in
[perrwa/Joan#4](https://github.com/perrwa/Joan/issues/4). Caps and small caps
are untouched, tracked in
[perrwa/Joan#5](https://github.com/perrwa/Joan/issues/5).

## After both files exist

1. `python scripts/check_masters.py sources/Joan.glyphs sources/Joan-Italic.glyphs`
   should report 2 masters and a `wght` axis for each, exit 0. Until
   `Joan-Italic.glyphs` gets the same weight-axis treatment as the Roman file,
   check it on its own with `--single-master-ok` instead.
2. `gftools builder sources/config-family.yaml` should build without error.
3. Retire `Joan_Merged_Paths.glyphs` / `Joan_Working_File.glyphs`, repoint
   `config.yaml` at the new source (or drop `config.yaml` in favor of
   `config-family.yaml`).
