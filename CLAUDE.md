# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Font source repository for **Joan**, a serif typeface by Paolo Biagini, distributed under the OFL. This is not a software project — there is no application code, and "building" means compiling font binaries from Glyphs source files. Currently only the Roman/Regular style is available; italic is under development.

## Repository layout

- `sources/Joan_Merged_Paths.glyphs` — the canonical build source, referenced by `sources/config.yaml`. Paths here have been merged/simplified for production.
- `sources/Joan_Working_File.glyphs` — the working/editing file where in-progress glyph and path changes happen before being merged into the build source.
- `sources/backup/` — older archived `.glyphs` snapshots (e.g. `2021_Joan.glyphs`), kept for history, not used in builds.
- `sources/config.yaml` — build config consumed by `gftools builder` (Google Fonts' font build tool). Declares the source file, family name, and build flags (`buildVariable`, `buildSmallCap`, `cleanUp`).
- `fonts/otf/`, `fonts/ttf/`, `fonts/webfonts/` — compiled build outputs (OTF, TTF, WOFF2) committed to the repo.

## Build command

Fonts are built from the Glyphs source using [gftools](https://github.com/googlefonts/gftools):

```
pip install gftools
gftools builder sources/config.yaml
```

This regenerates the contents of `fonts/otf/`, `fonts/ttf/`, and `fonts/webfonts/` from `sources/Joan_Merged_Paths.glyphs`. There is no separate lint or test suite in this repo — validation is via the visual/technical checks gftools runs during the build (e.g. `cleanUp: true` in config.yaml removes overlaps and cleans paths as part of the build).

## Editing workflow

Glyph and spacing edits are made in Glyphsapp against `Joan_Working_File.glyphs`, then merged into `Joan_Merged_Paths.glyphs` before running a build (see commit history, e.g. "set up gf file: color fonts + decompose and merge yellow glyphs + tidy path"). When making source changes without Glyphsapp available, be aware `.glyphs` files are large plist-like text files — treat them as opaque binary-ish data rather than hand-editing unless a change is small and well-understood (e.g. a metadata field).

## Git & fork conventions

This repo (`origin`, `perrwa/Joan`) is a fork of the upstream Joan font repo. Never push, open PRs, or create issues on the upstream repo unless explicitly asked to or given the upstream remote/URL — all git operations target `origin` (the fork) by default.

## Versioning

Changes are tracked in `README.md` under `# Changelog` with version headers (e.g. `#### v1.000`) listing notable glyph additions and fixes — update this when a build introduces user-facing changes (new glyphs, corrected paths, updated metrics).
