#!/usr/bin/env python3
"""Synthetic sanity checks for scripts/italic_geom.py and the splicing
pattern scripts/italic_recipes.py builds on — connector() tangent math,
_tail_piece()-style wraparound slicing, and splice closure.

These don't touch real glyph data on purpose: they're meant to catch the
class of bug a blind sign/index fix can introduce (three of which showed
up in italic_recipes.py this session — see the plan) before any cut
point or tangent has been chosen, using synthetic points instead. They
are not a substitute for proofing real constructions once CONSTRUCTION
has data in it.

Usage: python scripts/check_geom.py
"""

import math
import sys

from italic_geom import Contour, bounds, connector, dist, node_smooth, nodes, unit


def check_connector_tangents():
    """A connector's cubic must actually leave p0 along t0 and arrive at
    p1 along t1 — i.e. the derivative at t=0 is parallel to t0 and at
    t=1 is parallel to t1. This is close to true by construction
    (c1 = p0 + t0*h0), but exercising it as a check means a future
    change to connector() that breaks the tangent math (like the
    reversed-tangent bugs found this session) fails loudly instead of
    only showing up as a visual kink much later."""
    p0, p1 = (0.0, 0.0), (100.0, 40.0)
    t0, t1 = unit(1, 2), unit(-1, 3)  # arbitrary, non-axis-aligned
    seg = connector(p0, t0, p1, t1)
    assert seg[0] == "curve"
    _, c1, c2, end, _smooth = seg
    assert end == p1

    d_start = unit(c1[0] - p0[0], c1[1] - p0[1])
    d_end = unit(p1[0] - c2[0], p1[1] - c2[1])
    assert abs(d_start[0] - t0[0]) < 1e-9 and abs(d_start[1] - t0[1]) < 1e-9, \
        f"connector leaves p0 along {d_start}, expected {t0}"
    assert abs(d_end[0] - t1[0]) < 1e-9 and abs(d_end[1] - t1[1]) < 1e-9, \
        f"connector arrives at p1 along {d_end}, expected {t1}"

    # Explicit handle lengths are honored (every real call site passes
    # them explicitly, so the d/3 default is otherwise unexercised).
    seg2 = connector(p0, t0, p1, t1, h0=7.0, h1=11.0)
    assert abs(dist(p0, seg2[1]) - 7.0) < 1e-9
    assert abs(dist(p1, seg2[2]) - 11.0) < 1e-9

    # smooth flag passes through unchanged (used to preserve a
    # pre-existing point's corner/smooth status at a splice join).
    assert connector(p0, t0, p1, t1, smooth=False)[-1] is False
    assert connector(p0, t0, p1, t1, smooth=True)[-1] is True
    return True


def _synthetic_ring(n=8, r=100.0):
    """A closed n-gon-ish contour with alternating line/curve segments,
    purely synthetic — stands in for "some glyph's contour" without
    using real font data."""
    pts = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    segs = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        if i % 2 == 0:
            segs.append(("line", b, False))
        else:
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            segs.append(("curve", a, mid, b, True))
    return Contour(pts[0], True, segs)


def check_tail_piece_wraparound():
    """The (start_seg_idx, count) wraparound slicing that
    italic_recipes._tail_piece uses (and that CONSTRUCTION["f"]/["g"]
    will key into) must produce a chain of segments where each one picks
    up exactly where the previous one ended — including across the
    wraparound past the contour's own close/start. Reimplemented here
    against a synthetic ring rather than importing the private function,
    so this doesn't depend on italic_recipes.py (which needs real
    CONSTRUCTION data to do anything) or on jdotless's specific shape."""
    ring = _synthetic_ring(n=8)
    segs = ring.segments
    n = len(segs)
    node_list = nodes(ring)

    for start_seg_idx, count in [(0, 3), (5, 3), (6, 4), (7, 2)]:  # last two wrap past close
        piece = [segs[(start_seg_idx + i) % n] for i in range(count)]
        # A segment doesn't carry its own start explicitly (Contour
        # stores it implicitly as "wherever the previous one left off"),
        # so the check is: walking the piece in order visits exactly the
        # same points walking the full ring would.
        cur = node_list[start_seg_idx]
        for seg in piece:
            cur = seg[3] if seg[0] == "curve" else seg[1]
        expected_end = node_list[(start_seg_idx + count) % n]
        assert cur == expected_end, (
            f"start_seg_idx={start_seg_idx} count={count}: piece ends at {cur}, "
            f"expected {expected_end} (walking the ring directly)"
        )
    return True


def check_splice_closure():
    """The core splice pattern every recipe uses — segments[:cut_a] +
    [new bridging segment(s)] + segments[cut_b:] — must still close: the
    last segment's endpoint must equal contour.start. contour_to_gspath
    silently drops the final point if this doesn't hold (it treats the
    last node in the sequence as already-present via closure), so a
    broken splice wouldn't error, it would just quietly produce a wrong
    outline. Checked here against a synthetic ring with a synthetic
    connector bridge, exercising the exact list-slice-and-splice shape
    make_a/make_f/make_g use, without needing real cut points."""
    ring = _synthetic_ring(n=8)
    segs = ring.segments
    node_list = nodes(ring)

    cut_a, cut_b = 2, 5
    p0, p1 = node_list[cut_a], node_list[cut_b]
    t0 = unit(1, 0)
    t1 = unit(0, -1)
    bridge = connector(p0, t0, p1, t1, smooth=node_smooth(ring, cut_b))

    new_segments = list(segs[:cut_a]) + [bridge] + list(segs[cut_b:])
    spliced = Contour(ring.start, ring.start_smooth, new_segments)

    cur = spliced.start
    for seg in spliced.segments:
        cur = seg[3] if seg[0] == "curve" else seg[1]
    assert cur == spliced.start, f"spliced contour doesn't close: ends at {cur}, start is {spliced.start}"

    # And a deliberately broken splice — the LAST segment doesn't reach
    # back to start — must be caught, not silently accepted (a gap
    # anywhere else in the chain doesn't affect this particular
    # invariant: every segment after it still ends at its own coded
    # point regardless of what came before, so the only way to actually
    # violate "does the contour close" is to corrupt the final segment).
    bad_last = list(new_segments)
    last = bad_last[-1]
    off = (spliced.start[0] + 5, spliced.start[1])
    bad_last[-1] = ("line", off, False) if last[0] == "line" else ("curve", last[1], last[2], off, last[4])
    bad = Contour(ring.start, ring.start_smooth, bad_last)
    cur = bad.start
    for seg in bad.segments:
        cur = seg[3] if seg[0] == "curve" else seg[1]
    assert cur != bad.start, "sanity check itself is broken: didn't detect a non-closing splice"

    assert bounds([spliced])  # bounds() shouldn't choke on a spliced contour either
    return True


CHECKS = [
    ("connector tangent math", check_connector_tangents),
    ("tail-piece wraparound slicing", check_tail_piece_wraparound),
    ("splice closure", check_splice_closure),
]


def main():
    ok = True
    for label, fn in CHECKS:
        try:
            fn()
            print(f"  ok   {label}")
        except AssertionError as e:
            ok = False
            print(f"  FAIL {label}: {e}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
