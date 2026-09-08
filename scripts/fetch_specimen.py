"""Download Paolo Biagini's published italic specimen images into
reference/pb-italic/ (gitignored -- they're his copyrighted images, not
ours to redistribute from an OFL repo). Run this once per machine/session
before scripts/specimen_score.py or scripts/vectorize.py need them.

Checks each download's sha256 against MANIFEST below and warns (does not
fail) on a mismatch -- if the source page changes, calibration constants
derived from the old images (crop grid, baseline, scale) may no longer be
valid, and that's worth knowing rather than silently tracing stale data
against a new picture.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

BASE_URL = "https://www.paolobiagini.altervista.org/img/joan-italic-font-{}.png"
OUT_DIR = Path(__file__).resolve().parent.parent / "reference" / "pb-italic"

# Recorded 2026-09-08, from the same fetch that established the
# segmentation/calibration constants in specimen_score.py.
MANIFEST = {
    1: "4180b216885d9b6685544a763f4f625ff5fbb76baaffc4df70bb25ced4b67651",
    2: "730c74b452cc14eaa61ae58a30762c984b58a7e2d4d6dbe0b33675ae729acf5f",
    3: "8b1e1daf21a3c42a97a4878fd6356ae7fb02afd9185be3c795881085b0a585cd",
}


def fetch():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for i, expected in MANIFEST.items():
        path = OUT_DIR / f"pb-italic-{i}.png"
        if not path.exists():
            urllib.request.urlretrieve(BASE_URL.format(i), path)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        status = "OK" if actual == expected else "MISMATCH -- source may have changed, recheck calibration"
        print(f"pb-italic-{i}.png: {status}")
    return OUT_DIR


if __name__ == "__main__":
    sys.exit(0 if fetch() else 1)
