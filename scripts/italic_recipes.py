"""Tier 3 italic constructions (github.com/perrwa/Joan/issues/1): true
italic letterforms cut from Joan's own contours, instead of the
mechanical shear scripts/make_italic.py applies to everything else.

Every construction here is direct contour surgery, not boolean geometry:
cut a glyph's own node list at chosen indices (plain Python slicing —
the cut points are existing on-curve nodes, never a path sliced through
mid-curve), position a piece taken from another glyph by translation, and
join the pieces with scripts/italic_geom.connector — a single curve built
to leave and arrive in the directions the two sides are already heading.
There is no clip-and-union step, so there's no seam for a boolean op to
get subtly wrong: the join IS the curve two points and two tangents say
it should be.

Each function is `recipe(ctx) -> Part` (see make_italic.Ctx /
italic_geom.Part). `ctx.italic(name)` hands back the mechanical italic
form of any roman glyph — sheared, extrema-reinserted, narrowed,
sidebearing-adjusted — as the raw material recipes cut from. Cut node
indices and connector tangents live in scripts/italic_tuning.CONSTRUCTION,
edited during visual iteration against
`python scripts/proof.py --glyphs ... --compare`.

Registered into make_italic.RECIPES by that module's own import at the
bottom of make_italic.py.
"""

import italic_geom as ig
from italic_geom import Contour, Part
from italic_tuning import CONSTRUCTION


def _center_x(b):
    return (b[0] + b[2]) / 2


def _tail_piece(j_part, start_seg_idx, count):
    """An open path cut from jdotless's own descender (contour0):
    `count` consecutive segments starting at segment index
    `start_seg_idx`, wrapping past its close/start if needed. Returns
    (start_point, [segments], end_point) in jdotless's own coordinates —
    translate the whole thing into position at the call site."""
    contour = j_part.contours[0]
    segs = contour.segments
    n = len(segs)
    nodes = ig.nodes(contour)
    piece = [segs[(start_seg_idx + i) % n] for i in range(count)]
    start_pt = nodes[start_seg_idx]
    end_pt = piece[-1][3] if piece[-1][0] == "curve" else piece[-1][1]
    return start_pt, piece, end_pt


# ------------------------------------------------------------------ a --

def make_a(ctx):
    """Single-storey a: the mechanical italic a's own bowl and stem,
    unchanged, with the two-storey ear (the loop from the top of the
    plain stem, over, and back down to the bowl's shoulder) cut out and
    replaced by one smooth stem-top curve. Every point in the result is
    either Joan's own a or Joan's own l (the entry curl at the very top),
    positioned and joined by direct tangent-matched connectors — nothing
    is welded from an unrelated bowl or stem."""
    c = CONSTRUCTION["a"]
    a_part = ctx.italic("a")
    bowl = a_part.contours[1]  # the small counter inside the ear — untouched
    outer = a_part.contours[0]
    nodes = ig.nodes(outer)

    cut_start, cut_end = c["ear_cut"]  # node indices: keep segments[:cut_start] and segments[cut_end:]
    p0 = nodes[cut_start]
    p1 = nodes[cut_end]

    # Tangent leaving p0: direction of the segment already arriving there
    # (segments[cut_start - 1]) — keep going the way the stem was heading.
    # For a curve, that's from its own c2; for a line, from wherever it
    # started (nodes[cut_start - 1] — the point immediately before p0).
    prev_seg = outer.segments[cut_start - 1]
    ref0 = prev_seg[2] if prev_seg[0] == "curve" else nodes[cut_start - 1]
    t0 = ig.unit(p0[0] - ref0[0], p0[1] - ref0[1])

    # Tangent arriving at p1: direction p1's own next segment continues in.
    next_seg = outer.segments[cut_end]
    ref1 = next_seg[1] if next_seg[0] == "curve" else next_seg[1]
    t1 = ig.unit(ref1[0] - p1[0], ref1[1] - p1[1])

    peak = c["peak"]
    peak_t = ig.unit(*c["peak_tangent"])
    # Same tangent on both sides of the peak (direction of travel doesn't
    # reverse there — it's the top of a smooth rounded cap, arriving and
    # leaving in the same direction, the way an arch's crown does).
    seg_up = ig.connector(p0, t0, peak, peak_t, h0=c["h0"], h1=c["h_peak_in"])
    seg_down = ig.connector(
        peak, peak_t, p1, t1, h0=c["h_peak_out"], h1=c["h1"],
        smooth=ig.node_smooth(outer, cut_end),
    )

    new_segments = list(outer.segments[:cut_start]) + [seg_up, seg_down] + list(outer.segments[cut_end:])
    new_outer = Contour(outer.start, outer.start_smooth, new_segments)

    contours = [new_outer, bowl]
    b = ig.bounds(contours)
    anchors = {
        "TOP": (_center_x(b), ctx.xheight),
        "BOTTOM": (_center_x(ig.bounds([new_outer])), 0),
    }
    return Part(contours, a_part.width, anchors)


# ------------------------------------------------------------------ f --

def make_f(ctx):
    """Descending f: f's own crossbar and hook untouched; the foot serif
    (both corners) cut away and replaced by jdotless's own descending
    hook, positioned so its natural attachment point lands exactly on
    f's stem edge (an exact translation match, not a boolean weld) and
    bridged to the other edge with one connector curve."""
    c = CONSTRUCTION["f"]
    f_part = ctx.italic("f")
    stem = f_part.contours[2]
    nodes = ig.nodes(stem)

    right_idx, left_idx = c["stem_cut"]  # node indices: right edge top, left edge bottom
    p_right = nodes[right_idx]  # top of right edge (was: top of right serif)
    p_left = nodes[left_idx]  # bottom of left edge (was: top of left serif)

    j_part = ctx.italic("jdotless")
    start_seg_idx, count = c["tail_slice"]
    tail_start_pt, tail_segments, tail_end_pt = _tail_piece(j_part, start_seg_idx, count)

    dx, dy = p_left[0] - tail_start_pt[0], p_left[1] - tail_start_pt[1]
    tail = ig.translate([Contour(tail_start_pt, True, tail_segments)], dx, dy)[0]
    tail_end_pt = (tail_end_pt[0] + dx, tail_end_pt[1] + dy)

    # Bridge from the tail's translated end back to the stem's right edge.
    # For a curve last segment, the reference is its own c2; for a line,
    # it's the point the line started from (the node before the tail's
    # end — NOT the end point itself, which would give a zero tangent).
    last_seg = tail.segments[-1]
    tail_nodes = ig.nodes(tail)
    ref = last_seg[2] if last_seg[0] == "curve" else tail_nodes[-2]
    t_leave = ig.unit(tail_end_pt[0] - ref[0], tail_end_pt[1] - ref[1])
    next_seg = stem.segments[right_idx]
    ref2 = next_seg[1]
    t_arrive = ig.unit(ref2[0] - p_right[0], ref2[1] - p_right[1])
    bridge = ig.connector(
        tail_end_pt, t_leave, p_right, t_arrive, h0=c["bridge_h0"], h1=c["bridge_h1"],
        smooth=ig.node_smooth(stem, right_idx),
    )

    kept = list(stem.segments[right_idx:left_idx])  # right edge up, hook, left edge down
    new_segments = kept + list(tail.segments) + [bridge]
    new_stem = Contour(p_right, stem.start_smooth, new_segments)

    contours = [f_part.contours[0], f_part.contours[1], new_stem]
    contours, width = ig.fit(contours, c["lsb"], c["rsb"])
    return Part(contours, width, {})


# ------------------------------------------------------------------ g --

def make_g(ctx):
    """Single-storey g: o's bowl, both contours untouched, with jdotless's
    own descending hook spliced into a short gap in the bowl's outer
    edge (two adjacent nodes near its rightmost point). One end lands by
    exact translation; the other is bridged with a connector."""
    c = CONSTRUCTION["g"]
    o_part = ctx.italic("o")
    outer = o_part.contours[0]
    hole = o_part.contours[1]
    nodes = ig.nodes(outer)

    leave_idx, return_idx = c["bowl_gap"]
    p_leave = nodes[leave_idx]
    p_return = nodes[return_idx]

    j_part = ctx.italic("jdotless")
    start_seg_idx, count = c["tail_slice"]
    tail_start_pt, tail_segments, tail_end_pt = _tail_piece(j_part, start_seg_idx, count)

    dx, dy = p_leave[0] - tail_start_pt[0], p_leave[1] - tail_start_pt[1]
    tail = ig.translate([Contour(tail_start_pt, True, tail_segments)], dx, dy)[0]
    tail_end_pt = (tail_end_pt[0] + dx, tail_end_pt[1] + dy)

    # Same reference-point reasoning as make_f's bridge above.
    last_seg = tail.segments[-1]
    tail_nodes = ig.nodes(tail)
    ref = last_seg[2] if last_seg[0] == "curve" else tail_nodes[-2]
    t_leave = ig.unit(tail_end_pt[0] - ref[0], tail_end_pt[1] - ref[1])
    next_seg = outer.segments[return_idx]
    ref2 = next_seg[1]
    t_arrive = ig.unit(ref2[0] - p_return[0], ref2[1] - p_return[1])
    bridge = ig.connector(
        tail_end_pt, t_leave, p_return, t_arrive, h0=c["bridge_h0"], h1=c["bridge_h1"],
        smooth=ig.node_smooth(outer, return_idx),
    )

    before = list(outer.segments[:leave_idx])
    after = list(outer.segments[return_idx:])
    new_outer = Contour(outer.start, outer.start_smooth, before + list(tail.segments) + [bridge] + after)

    contours = [new_outer, hole]
    contours, width = ig.fit(contours, c["lsb"], c["rsb"])
    b = ig.bounds(contours)
    anchors = {"TOP": (_center_x(b), ctx.xheight)}
    return Part(contours, width, anchors)


# --------------------------------------------------------------- v/w/y --

def _curl_terminal(contour, tip_idx, new_tip, leave_tangent, depart_tangent, h_in, h_out, tip_in_tangent=None):
    """Move the on-curve point at nodes[tip_idx] to new_tip. `leave_tangent`
    is the direction the curve leaves `before_pt` (nodes[tip_idx - 1])
    heading toward new_tip; `depart_tangent` is the direction it leaves
    new_tip heading toward `after_pt` (nodes[tip_idx + 1]). `tip_in_tangent`
    is the direction of travel ARRIVING at new_tip — defaults to
    `depart_tangent` (a smooth pass-through, no reversal at the tip);
    pass a different direction for a deliberate corner there instead.
    (`connector`'s own t1 is direction-of-travel — arriving on the
    *negation* of the departure tangent, as an earlier version of this
    function did, isn't "a sharp corner", it's both control points
    landing on the same side of the tip: a zero-width retrace, not a
    corner at any real angle.)

    `after_pt` keeps its original corner/smooth status (from the segment
    being replaced) rather than being forced smooth — it's an unchanged,
    pre-existing point whose role in the rest of the contour doesn't
    change just because a different segment now reaches it."""
    nodes = ig.nodes(contour)
    before_pt = nodes[tip_idx - 1]
    after_pt = nodes[tip_idx + 1]
    if tip_in_tangent is None:
        tip_in_tangent = depart_tangent

    next_seg = contour.segments[tip_idx + 1] if tip_idx + 1 < len(contour.segments) else None
    if next_seg is not None:
        ref = next_seg[1]
        t_arrive_after = ig.unit(ref[0] - after_pt[0], ref[1] - after_pt[1])
    else:
        t_arrive_after = ig.unit(after_pt[0] - new_tip[0], after_pt[1] - new_tip[1])

    seg_in = ig.connector(before_pt, leave_tangent, new_tip, tip_in_tangent, h0=h_in, h1=h_in)
    seg_out = ig.connector(
        new_tip, depart_tangent, after_pt, t_arrive_after, h0=h_out, h1=h_out,
        smooth=ig.node_smooth(contour, tip_idx + 1),
    )

    segs = list(contour.segments)
    segs[tip_idx - 1] = seg_in
    segs[tip_idx] = seg_out
    return Contour(contour.start, contour.start_smooth, segs)


def _stroked(name):
    def recipe(ctx):
        c = CONSTRUCTION[name]
        part = ctx.italic(name)
        contour = part.contours[0]

        for side in (c["left"], c["right"]):
            tip_in = ig.unit(*side["tip_in_tangent"]) if "tip_in_tangent" in side else None
            contour = _curl_terminal(
                contour, side["tip_idx"], side["new_tip"],
                ig.unit(*side["leave_tangent"]), ig.unit(*side["depart_tangent"]),
                side["h_in"], side["h_out"], tip_in_tangent=tip_in,
            )
        return Part([contour], part.width, dict(part.anchors))

    return recipe


# Gated on CONSTRUCTION data, not registered unconditionally: every
# recipe above reads CONSTRUCTION[name] immediately (e.g. make_a's
# c["ear_cut"]), so a name with no data yet would KeyError the moment
# make_italic.py touched it. This way glyphs light up one at a time as
# real cut points/tangents get filled into CONSTRUCTION — nothing to
# remember to un-comment, and make_italic.py runs end-to-end at every
# intermediate state.
_ALL_RECIPES = {
    "a": make_a,
    "f": make_f,
    "g": make_g,
    "v": _stroked("v"),
    "w": _stroked("w"),
    "y": _stroked("y"),
}

RECIPES = {name: fn for name, fn in _ALL_RECIPES.items() if CONSTRUCTION.get(name)}
