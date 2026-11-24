"""Curves: exact splines, flattening tolerance, arcs, bulges and ellipses."""

import io
import math
import random

import pytest
import svgelements as se
from conftest import entities, flat, svg, xy

from svg_to_dxf.geometry import Bezier
from svg_to_dxf.svgread import _exact_lengths

S = 'fill="none" stroke="black"'


def flip(p):
    return (p[0], 100 - p[1])


def ctrl(spline):
    return [xy(p) for p in spline.control_points]


def test_cubic_bezier_spline_control_points_equal_bezier_points(run):
    doc, _ = run(f'<path d="M 10 90 C 20 50 60 50 90 90" {S}/>')
    (spline,) = entities(doc, "SPLINE")
    assert spline.dxf.degree == 3
    assert flat(ctrl(spline)) == pytest.approx(flat([(10, 10), (20, 50), (60, 50), (90, 10)]), abs=1e-12)
    assert list(spline.knots) == [0, 0, 0, 0, 1, 1, 1, 1]


def test_quadratic_bezier_spline_control_points_equal_bezier_points(run):
    doc, _ = run(f'<path d="M 10 90 Q 50 10 90 90" {S}/>')
    (spline,) = entities(doc, "SPLINE")
    assert spline.dxf.degree == 2
    assert flat(ctrl(spline)) == pytest.approx(flat([(10, 10), (50, 90), (90, 10)]), abs=1e-12)
    assert list(spline.knots) == [0, 0, 0, 1, 1, 1]


def test_multi_segment_spline_reproduces_every_bezier(run):
    d = "M 10 50 C 20 10 30 10 40 50 S 60 90 70 50 C 75 30 85 30 90 50"
    doc, _ = run(f'<path d="{d}" {S}/>')
    (spline,) = entities(doc, "SPLINE")
    assert list(spline.knots) == [0, 0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 3]
    segments = [
        Bezier(((10, 50), (20, 10), (30, 10), (40, 50))),
        Bezier(((40, 50), (50, 90), (60, 90), (70, 50))),  # S reflects (30, 10) about (40, 50)
        Bezier(((70, 50), (75, 30), (85, 30), (90, 50))),
    ]
    tool = spline.construction_tool()
    for i, seg in enumerate(segments):
        for k in range(11):
            s = k / 10
            assert xy(tool.point(i + s)) == pytest.approx(flip(seg.point(s)), abs=1e-9)


@pytest.mark.parametrize("seed", range(4))
def test_random_paths_and_transforms_match_svgelements_exactly(run, seed):
    """SPLINE(i + s) equals SVG segment i at s, evaluated independently by svgelements."""
    rng = random.Random(seed)
    n = lambda: round(rng.uniform(10, 90), 2)  # noqa: E731
    for transform in (
        "",
        "scale(-1,1) translate(-100,0)",
        "rotate(33 50 50)",
        "skewX(20)",
        "matrix(0.8,0.3,-0.2,1.1,5,-3)",
    ):
        d = (
            f"M {n()} {n()} "
            + " ".join(
                rng.choice([f"L {n()} {n()}", f"Q {n()} {n()} {n()} {n()}", f"C {n()} {n()} {n()} {n()} {n()} {n()}"])
                for _ in range(5)
            )
            + " C 1 2 3 4 5 6"
            + rng.choice(["", " Z"])
        )
        body = f'<path d="{d}" transform="{transform}" {S}/>'
        doc, _ = run(body)
        (spline,) = entities(doc, "SPLINE")
        tool = spline.construction_tool()
        with _exact_lengths():
            ref = se.SVG.parse(io.BytesIO(svg(body)), reify=False)
        path = next(e for e in ref.elements() if isinstance(e, se.Path))
        segs = [s for s in path.segments(transformed=False) if not isinstance(s, se.Move) and s.start != s.end]
        assert len(segs) == tool.max_t
        for i, seg in enumerate(segs):
            for s in (0.0, 0.3, 0.5, 0.9):
                q = se.Point(seg.point(s)) * path.transform
                expected = (q.x * 25.4 / 96, 100 - q.y * 25.4 / 96)
                assert xy(tool.point(i + s)) == pytest.approx(expected, abs=1e-9)


def _distance_to_polyline(p, pts):
    best = math.inf
    for a, b in zip(pts, pts[1:]):
        ab = (b[0] - a[0], b[1] - a[1])
        t = max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / (ab[0] ** 2 + ab[1] ** 2)))
        best = min(best, math.hypot(p[0] - a[0] - t * ab[0], p[1] - a[1] - t * ab[1]))
    return best


@pytest.mark.parametrize("tolerance", [0.5, 0.05, 0.005])
@pytest.mark.parametrize(
    "d, curve",
    [
        ("M 10 90 C 20 0 80 0 90 90", Bezier(((10, 90), (20, 0), (80, 0), (90, 90)))),
        ("M 10 90 Q 50 -20 90 90", Bezier(((10, 90), (50, -20), (90, 90)))),
    ],
)
def test_flattened_curve_stays_within_tolerance(run, d, curve, tolerance):
    doc, result = run(f'<path d="{d}" {S}/>', curves="polyline", tolerance=tolerance)
    (pl,) = entities(doc, "LWPOLYLINE")
    pts = [xy(p) for p in pl.get_points("xy")]
    samples = [flip(curve.point(k / 2000)) for k in range(2001)]
    worst = max(_distance_to_polyline(p, pts) for p in samples)
    assert worst <= tolerance
    assert worst > tolerance / 20  # not absurdly over-segmented
    assert any("flattened" in c for c in result.changes)


def test_single_arc_becomes_arc_entity_with_correct_sweep(run):
    doc, _ = run(f'<path d="M 60 50 A 10 10 0 0 1 50 60" {S}/>')  # 90 deg, clockwise on screen
    (arc,) = entities(doc, "ARC")
    assert arc.dxf.radius == pytest.approx(10) and xy(arc.dxf.center) == pytest.approx((50, 50))
    assert (arc.dxf.start_angle % 360, arc.dxf.end_angle % 360) == pytest.approx((270, 0), abs=1e-9)


def test_large_arc_flag_picks_270_degree_arc(run):
    doc, _ = run(f'<path d="M 60 50 A 10 10 0 1 1 50 60" {S}/>')
    (arc,) = entities(doc, "ARC")
    assert xy(arc.dxf.center) == pytest.approx(flip((60, 60)))
    sweep = (arc.dxf.end_angle - arc.dxf.start_angle) % 360
    assert sweep == pytest.approx(270)


def test_arc_inside_path_becomes_bulge(run):
    doc, _ = run(f'<path d="M 10 50 L 40 50 A 10 10 0 0 0 60 50 L 90 50" {S}/>')
    (pl,) = entities(doc, "LWPOLYLINE")
    pts = list(pl.get_points("xyb"))
    assert flat(p[:2] for p in pts) == pytest.approx(flat([(10, 50), (40, 50), (60, 50), (90, 50)]))
    # sweep-flag 0 runs through the bottom of the screen: counter-clockwise in DXF, bulge tan(180/4)
    assert [p[2] for p in pts] == pytest.approx([0, 1, 0, 0])


def test_path_of_two_half_arcs_becomes_circle(run):
    doc, _ = run(f'<path d="M 40 50 A 10 10 0 1 0 60 50 A 10 10 0 1 0 40 50 Z" {S}/>')
    (circle,) = entities(doc, "CIRCLE")
    assert circle.dxf.radius == pytest.approx(10) and xy(circle.dxf.center) == pytest.approx((50, 50))


def test_elliptical_arc_becomes_ellipse_arc(run):
    doc, _ = run(f'<path d="M 70 50 A 20 10 0 0 1 50 60" {S}/>')
    (e,) = entities(doc, "ELLIPSE")
    assert e.dxf.ratio == pytest.approx(0.5) and math.hypot(*xy(e.dxf.major_axis)) == pytest.approx(20)
    ends = sorted([xy(e.start_point), xy(e.end_point)])
    assert flat(ends) == pytest.approx(flat(sorted([(70, 50), flip((50, 60))])), abs=1e-9)
    span = (e.dxf.end_param - e.dxf.start_param) % math.tau
    assert span == pytest.approx(math.pi / 2)
    x, y = xy(next(iter(e.construction_tool().vertices([e.dxf.start_param + span / 2]))))
    assert ((x - 50) / 20) ** 2 + ((y - 50) / 10) ** 2 == pytest.approx(1) and y < 50


def test_mixed_closed_path_is_one_closed_spline(run):
    d = "M 10 10 L 50 10 C 60 10 60 30 50 30 A 10 10 0 0 1 40 20 Z"
    doc, result = run(f'<path d="{d}" {S}/>')
    (spline,) = entities(doc, "SPLINE")
    pts = ctrl(spline)
    assert pts[0] == pts[-1] == pytest.approx(flip((10, 10)))
    assert xy(spline.construction_tool().point(0.5)) == pytest.approx(flip((30, 10)), abs=1e-12)  # the line
    layer = next(iter(result.layers.values()))
    assert layer.closed == 1
