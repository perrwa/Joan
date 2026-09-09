# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Font source repository for **Joan**, a serif typeface by Paolo Biagini, distributed under the OFL. This is not a software project — there is no application code, and "building" means compiling font binaries from Glyphs source files. Currently only the Roman/Regular style is available; italic is under development.

## Repository layout

- `sources/Joan-Regular.glyphs` — the editable master, component-based (glyphs reference shared shapes rather than each holding fully drawn outlines). All hand edits happen here in Glyphsapp.
- `sources/Joan-Regular-Build.glyphs` — generated from the master by decomposing every component into a flattened, standalone outline. This is the canonical build source, referenced by `sources/config.yaml`. The two files hold identical glyph and unicode coverage; they should always be kept in sync, and `-Build` is regenerated from the master, never edited directly or treated as a separate revision.
- `sources/config.yaml` — build config consumed by `gftools builder` (Google Fonts' font build tool). Declares the source file, family name, and build flags (`buildVariable`, `buildSmallCap`, `cleanUp`).
- `fonts/otf/`, `fonts/ttf/`, `fonts/webfonts/` — compiled build outputs (OTF, TTF, WOFF2) committed to the repo.

No archived snapshots are kept in the tree — the last one (a 2022 state of the source, prior to the current split into master + build file) was removed as redundant with git history; it's recoverable at commit `6cb7b83`.

## Build command

Fonts are built from the Glyphs source using [gftools](https://github.com/googlefonts/gftools):

```
pip install gftools
gftools builder sources/config.yaml
```

This regenerates the contents of `fonts/otf/`, `fonts/ttf/`, and `fonts/webfonts/` from `sources/Joan-Regular-Build.glyphs`. There is no separate lint or test suite in this repo — validation is via the visual/technical checks gftools runs during the build (e.g. `cleanUp: true` in config.yaml removes overlaps and cleans paths as part of the build).

## Editing workflow

Glyph and spacing edits are made in Glyphsapp against `Joan-Regular.glyphs` (the master), then decomposed into `Joan-Regular-Build.glyphs` before running a build (see commit history, e.g. "set up gf file: color fonts + decompose and merge yellow glyphs + tidy path"). Never delete or hand-edit the master in place of the build file — decomposition is one-way, so a component-based edit made only in `-Build` won't propagate back and every dependent glyph becomes separate hand-work. When making source changes without Glyphsapp available, be aware `.glyphs` files are large plist-like text files — treat them as opaque binary-ish data rather than hand-editing unless a change is small and well-understood (e.g. a metadata field).

## Git & fork conventions

This repo (`origin`, `perrwa/Joan`) is a fork of the upstream Joan font repo. Never push, open PRs, or create issues on the upstream repo unless explicitly asked to or given the upstream remote/URL — all git operations target `origin` (the fork) by default.

## Versioning

Changes are tracked in `README.md` under `# Changelog` with version headers (e.g. `#### v1.000`) listing notable glyph additions and fixes — update this when a build introduces user-facing changes (new glyphs, corrected paths, updated metrics).
