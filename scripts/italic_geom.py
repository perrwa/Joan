"""Shared geometry for scripts/make_italic.py and scripts/italic_recipes.py.

Tier 3 constructions (github.com/perrwa/Joan/issues/1) work by direct
contour surgery — slicing a glyph's own node list at chosen points,
positioning a piece cut from another glyph, and splicing them together
with tangent-matched connector curves — rather than boolean union of
independently clipped shapes. A boolean union of two overlapping outlines
is only as clean as the overlap: any mismatch in how the pieces cross
shows up as a self-intersecting sliver or a width step at the seam. Direct
splicing sidesteps that class of bug entirely: two pieces joined by one
new curve, with that curve's own handles chosen to match the direction on
both sides, can only look like a deliberate stroke, never a stitched-on
patch.
"""

import math

__all__ = [
    "Contour", "Part",
    "dist", "unit", "translate", "scale_about",
    "connector", "bounds", "fit",
    "nodes", "seg_smooth", "node_smooth",
]


class Contour:
    """A closed contour: a start point plus a list of line/curve segments
    back to it. Segments are ('line', pt, smooth) or
    ('curve', ctrl1, ctrl2, pt, smooth) — smooth describes the on-curve
    point the segment ends at."""

    __slots__ = ("start", "start_smooth", "segments")

    def __init__(self, start, start_smooth, segments):
        self.start = start
        self.start_smooth = start_smooth
        self.segments = segments


class Part:
    """The unit every build path in make_italic.py returns: finished
    italic-space contours, an advance width, and any anchors (name ->
    (x, y) in that same italic space) the glyph carries."""

    __slots__ = ("contours", "width", "anchors")

    def __init__(self, contours, width, anchors=None):
        self.contours = contours
        self.width = width
        self.anchors = anchors if anchors is not None else {}


def dist(p0, p1):
    return math.hypot(p1[0] - p0[0], p1[1] - p0[1])


def unit(vx, vy):
    n = math.hypot(vx, vy)
    return (vx / n, vy / n) if n > 1e-9 else (0.0, 0.0)


def _map_points(contours, fn):
    out = []
    for c in contours:
        start = fn(c.start)
        segs = []
        for seg in c.segments:
            if seg[0] == "line":
                segs.append(("line", fn(seg[1]), seg[2]))
            else:
                segs.append(("curve", fn(seg[1]), fn(seg[2]), fn(seg[3]), seg[4]))
        out.append(Contour(start, c.start_smooth, segs))
    return out


def translate(contours, dx, dy):
    return _map_points(contours, lambda p: (p[0] + dx, p[1] + dy))


def scale_about(contours, sx, sy, ox, oy):
    return _map_points(contours, lambda p: (ox + (p[0] - ox) * sx, oy + (p[1] - oy) * sy))


def connector(p0, t0, p1, t1, h0=None, h1=None, smooth=True):
    """A single cubic segment from p0 to p1, leaving p0 along unit tangent
    t0 and arriving at p1 along unit tangent t1 (i.e. t1 points in the
    direction of travel, not "back toward p0"). Handle lengths default to
    a third of the chord — the standard circle-approximation ratio, a
    reasonable default for a gently curving join.

    This is the seam-smoothing primitive: instead of computing where two
    independently-built shapes happen to cross (a boolean union) and
    living with whatever corner results, the join IS this one curve,
    built to leave and arrive in exactly the directions the two sides are
    already heading."""
    d = dist(p0, p1)
    if h0 is None:
        h0 = d / 3
    if h1 is None:
        h1 = d / 3
    c1 = (p0[0] + t0[0] * h0, p0[1] + t0[1] * h0)
    c2 = (p1[0] - t1[0] * h1, p1[1] - t1[1] * h1)
    return ("curve", c1, c2, p1, smooth)


def nodes(contour):
    """[start] + each segment's on-curve endpoint, so nodes(c)[i] is the
    on-curve point that ends segments[i-1] / begins segments[i]. Note
    len(nodes(c)) == len(c.segments) + 1, with nodes(c)[-1] == c.start
    (the contour is closed)."""
    return [contour.start] + [(s[3] if s[0] == "curve" else s[1]) for s in contour.segments]


def seg_smooth(seg):
    """The smooth flag a segment tuple carries for the on-curve point it
    ends at."""
    return seg[2] if seg[0] == "line" else seg[4]


def node_smooth(contour, idx):
    """The stored smooth flag for nodes(contour)[idx] — from
    contour.start_smooth if idx is 0, otherwise from the segment that
    ends there. Use this to preserve a pre-existing point's corner/smooth
    status when replacing the segment that reaches it with a connector,
    rather than defaulting to connector()'s smooth=True."""
    if idx == 0:
        return contour.start_smooth
    return seg_smooth(contour.segments[idx - 1])


def bounds(contours):
    xs, ys = [], []
    for c in contours:
        xs.append(c.start[0])
        ys.append(c.start[1])
        for seg in c.segments:
            if seg[0] == "line":
                xs.append(seg[1][0])
                ys.append(seg[1][1])
            else:
                xs.extend([seg[1][0], seg[2][0], seg[3][0]])
                ys.extend([seg[1][1], seg[2][1], seg[3][1]])
    return (min(xs), min(ys), max(xs), max(ys))


def fit(contours, lsb, rsb):
    """Shift contours so their left edge sits at lsb; return (contours, width)."""
    x0, _y0, x1, _y1 = bounds(contours)
    shifted = translate(contours, lsb - x0, 0)
    width = (x1 - x0) + lsb + rsb
    return shifted, width
