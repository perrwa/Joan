# What's needed to build wght 400-700 + Italic

`config-family.yaml` is ready to build the full family, but the source data
isn't there yet. `Joan_Merged_Paths.glyphs`, `Joan_Working_File.glyphs`, and
`backup/2021_Joan.glyphs` each have exactly one master (`Regular`) and no
weight or italic axis. Run `python scripts/check_masters.py sources/*.glyphs`
to confirm this directly.

This is Glyphs.app work — do not hand-edit the `.glyphs` files for any of it.
Master/instance/axis structures need Glyphs to keep master IDs, layer IDs,
and interpolation math consistent.

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

## Italic: `Joan-Italic.glyphs`

Separate file, not a slant transform of the roman. Needs:

- Its own `wght` axis, its own Regular (400) and Bold (700) masters.
- `Italic Angle` set per master in Font Info.
- True italic letterforms where the roman differs structurally — single-storey
  `a`, cursive/open `g`, descending `f`, etc. — not just sheared roman glyphs.

Save as `sources/Joan-Italic.glyphs`.

## After both files exist

1. `python scripts/check_masters.py sources/Joan.glyphs sources/Joan-Italic.glyphs`
   should report 2 masters and a `wght` axis for each, exit 0.
2. `gftools builder sources/config-family.yaml` should build without error.
3. Retire `Joan_Merged_Paths.glyphs` / `Joan_Working_File.glyphs`, repoint
   `config.yaml` at the new source (or drop `config.yaml` in favor of
   `config-family.yaml`), and update `README.md` (drop the "only the roman is
   available" line, add a changelog entry).
