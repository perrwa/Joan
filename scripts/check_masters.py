#!/usr/bin/env python3
"""Report masters/axes/instances declared in one or more .glyphs sources.

Read-only. Exits nonzero if any file has fewer than 2 masters or doesn't
declare a real wght axis, since neither can interpolate a weight range.
Pass --single-master-ok to report a single-master file (e.g. a generated
italic that isn't meant to interpolate a weight range) without failing.

Usage: python scripts/check_masters.py [--single-master-ok] sources/*.glyphs
"""

import sys

import glyphsLib

# glyphsLib fills in this exact Weight/Width pair whenever a file declares no
# axes of its own — both when reading an axis-less source (f.axes is always
# populated, even from nothing) and, confusingly, when *writing* one back out
# (GSFont.save() emits a literal "axes = (" block either way). So neither
# f.axes nor the raw file text reliably says whether axes were genuinely
# declared. Treat this specific default pair as "not really declared";
# anything else (e.g. a lone wght axis, per sources/MASTERS.md) counts.
SYNTHETIC_DEFAULT_AXES = [("Weight", "wght"), ("Width", "wdth")]


def has_declared_axes(font):
    return [(a.name, a.axisTag) for a in font.axes] != SYNTHETIC_DEFAULT_AXES


def check(path, single_master_ok):
    print(f"\n{path}")
    font = glyphsLib.GSFont(path)
    declared = has_declared_axes(font)

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

    if single_master_ok and len(font.masters) == 1:
        print("  single master (ok: --single-master-ok)")
        return True

    ok = declared and "wght" in [a.axisTag for a in font.axes] and len(font.masters) >= 2
    if not ok:
        print("  NOT READY: needs a declared wght axis and >=2 masters to interpolate a weight range")
    return ok


def main(argv):
    single_master_ok = "--single-master-ok" in argv
    paths = [a for a in argv if a != "--single-master-ok"]
    if not paths:
        print(__doc__)
        return 1
    results = [check(p, single_master_ok) for p in paths]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
