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
    "stroke_to_contour",
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


def _flatten_open(segments, start, samples_per_curve=14):
    """A spine's own on-curve/off-curve segments (same ('line', pt)/
    ('curve', c1, c2, pt) shape as Contour.segments, minus the smooth
    flag — a spine is open, not a closed glyph contour) to a dense
    polyline: [start, ...intermediate samples..., end]."""
    pts = [start]
    for seg in segments:
        if seg[0] == "line":
            pts.append(seg[1])
        else:
            p0 = pts[-1]
            _, c1, c2, p3 = seg
            for i in range(1, samples_per_curve + 1):
                t = i / samples_per_curve
                m = 1 - t
                pts.append(
                    (
                        m**3 * p0[0] + 3 * m * m * t * c1[0] + 3 * m * t * t * c2[0] + t**3 * p3[0],
                        m**3 * p0[1] + 3 * m * m * t * c1[1] + 3 * m * t * t * c2[1] + t**3 * p3[1],
                    )
                )
    return pts


def stroke_to_contour(segments, start, half_width, samples_per_curve=14, start_cap=2, end_cap=2):
    """Turn an open spine (a calligraphic pen path — start point plus
    line/curve segments, same shape as Contour.segments) into a closed
    outline Contour: flatten to a dense polyline, offset each sample
    point by `half_width` (a constant, or a callable half_width(t) for
    t in [0, 1] along the spine's arc length — thick/thin modulation)
    along its local normal, and walk out one edge, around a cap, back
    the other edge, around a cap, to close.

    This is the tool for a uniform (or gently modulated) -weight
    calligraphic stroke — e.g. a cursive letterform's whole skeleton —
    as opposed to connector()'s tangent-matched single seam, which is
    for splicing two already-similar shapes together. Built for issue #3
    once a local seam turned out not to be enough: Paolo's cursive `n`
    differs from Joan's mechanical form in overall stroke weight and
    character across the whole letter, not just at one corner, so the
    fix has to redraw the whole skeleton, not patch a joint.

    Caps are a short flat polyline of `start_cap`/`end_cap` points
    across the spine's own end tangent — good enough for a rounded felt-
    tip look once the flatten density is high; pass 1 for a square-ish
    cut end instead.

    Returns a single closed Contour with smooth=True line segments
    throughout (dense polyline, not fit to few beziers — let the caller
    run it through the ordinary build pipeline, which reinserts extrema
    on drawn Parts same as mechanical ones)."""
    poly = _flatten_open(segments, start, samples_per_curve)
    n = len(poly)
    if callable(half_width):
        widths = [half_width(i / (n - 1)) for i in range(n)]
    else:
        widths = [half_width] * n

    # Per-sample tangent (central difference, one-sided at the ends) and
    # its left-hand normal.
    normals = []
    for i in range(n):
        p_prev = poly[i - 1] if i > 0 else poly[i]
        p_next = poly[i + 1] if i < n - 1 else poly[i]
        tx, ty = unit(p_next[0] - p_prev[0], p_next[1] - p_prev[1])
        normals.append((-ty, tx))

    left = [(poly[i][0] + normals[i][0] * widths[i], poly[i][1] + normals[i][1] * widths[i]) for i in range(n)]
    right = [(poly[i][0] - normals[i][0] * widths[i], poly[i][1] - normals[i][1] * widths[i]) for i in range(n)]

    def cap_points(a, b, count):
        # A short straight-line cap across the spine's end, `count`
        # points including both ends.
        if count <= 1:
            return [b]
        return [(a[0] + (b[0] - a[0]) * i / count, a[1] + (b[1] - a[1]) * i / count) for i in range(1, count + 1)]

    ring = list(left) + cap_points(left[-1], right[-1], end_cap) + list(reversed(right))[1:] + cap_points(right[0], left[0], start_cap)

    segs = [("line", pt, True) for pt in ring[1:]]
    return Contour(ring[0], True, segs)


def fit(contours, lsb, rsb):
    """Shift contours so their left edge sits at lsb; return (contours, width)."""
    x0, _y0, x1, _y1 = bounds(contours)
    shifted = translate(contours, lsb - x0, 0)
    width = (x1 - x0) + lsb + rsb
    return shifted, width
