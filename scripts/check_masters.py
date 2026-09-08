#!/usr/bin/env python3
"""Report masters/axes/instances declared in one or more .glyphs sources.

Read-only. Exits nonzero if any file has fewer than 2 masters or doesn't
declare a real wght axis, since neither can interpolate a weight range.

Usage: python scripts/check_masters.py sources/*.glyphs
"""

import re
import sys

import glyphsLib


def has_declared_axes(path):
    """glyphsLib defaults to a synthetic Weight/Width axis pair when a file
    has no top-level `axes` key, so f.axes alone can't tell us whether the
    source really declares one. Check the raw file instead."""
    with open(path, encoding="utf-8") as fh:
        return re.search(r"^axes = \(", fh.read(), re.MULTILINE) is not None


def check(path):
    print(f"\n{path}")
    font = glyphsLib.GSFont(path)
    declared = has_declared_axes(path)

    if declared:
        tags = [a.axisTag for a in font.axes]
        print(f"  axes: {tags}")
    else:
        print("  axes: none declared (glyphsLib default Weight/Width shown below is synthetic)")

    print(f"  masters ({len(font.masters)}):")
    for m in font.masters:
        print(f"    {m.name!r}  axesValues={m.axes}")

    print(f"  instances ({len(font.instances)}):")
    for i in font.instances:
        print(f"    {i.name!r}  axesValues={i.axes}")

    ok = declared and "wght" in [a.axisTag for a in font.axes] and len(font.masters) >= 2
    if not ok:
        print("  NOT READY: needs a declared wght axis and >=2 masters to interpolate a weight range")
    return ok


def main(paths):
    if not paths:
        print(__doc__)
        return 1
    results = [check(p) for p in paths]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
