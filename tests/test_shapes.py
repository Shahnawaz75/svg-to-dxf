"""Shapes, closure, <use> and nested transforms."""

import math

import pytest
from conftest import entities, flat, xy

S = 'fill="none" stroke="black"'


def flip(x, y):
    """SVG user units (1 mm, y down) to DXF (y up) on the 100 mm test page."""
    return (x, 100 - y)


def test_closed_and_open_paths(run):
    doc, result = run(f'<path d="M 10 10 L 20 10 L 20 20 Z" {S}/><path d="M 30 10 L 40 10 L 40 20" {S}/>')
    closed, open_ = entities(doc, "LWPOLYLINE")
    assert closed.closed and len(closed) == 3
    assert not open_.closed and len(open_) == 3
    layer = next(iter(result.layers.values()))
    assert (layer.closed, layer.open) == (1, 1)


def test_path_ending_at_its_start_is_closed(run):
    doc, _ = run(f'<path d="M 0 0 L 10 0 L 10 10 L 0 0" {S}/>')
    (pl,) = entities(doc, "LWPOLYLINE")
    assert pl.closed and len(pl) == 3


def test_rounded_rect_has_exact_corner_arcs(run):
    doc, _ = run(f'<rect x="10" y="10" width="40" height="20" rx="5" {S}/>')
    (pl,) = entities(doc, "LWPOLYLINE")
    pts = list(pl.get_points("xyb"))
    assert pl.closed and len(pts) == 8
    bulges = [abs(p[2]) for p in pts]
    assert sorted(bulges) == pytest.approx([0] * 4 + [math.tan(math.pi / 8)] * 4, abs=1e-12)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert (min(xs), min(ys), max(xs), max(ys)) == pytest.approx((10, 70, 50, 90), abs=1e-12)


def test_polygon_closes_polyline_stays_open(run):
    doc, _ = run(f'<polygon points="10,10 20,10 15,20" {S}/><polyline points="30,10 40,10 35,20" {S}/>')
    polygon, polyline = entities(doc, "LWPOLYLINE")
    assert polygon.closed and not polyline.closed
    assert flat(polygon.get_points("xy")) == pytest.approx(flat([flip(10, 10), flip(20, 10), flip(15, 20)]))


def test_line_element(run):
    doc, _ = run(f'<line x1="10" y1="10" x2="30" y2="40" {S}/>')
    (line,) = entities(doc, "LINE")
    assert xy(line.dxf.start) == pytest.approx(flip(10, 10)) and xy(line.dxf.end) == pytest.approx(flip(30, 40))


def test_ellipse_element(run):
    doc, _ = run(f'<ellipse cx="50" cy="50" rx="20" ry="10" {S}/>')
    (e,) = entities(doc, "ELLIPSE")
    assert xy(e.dxf.center) == pytest.approx((50, 50))
    assert xy(e.dxf.major_axis) == pytest.approx((20, 0)) and e.dxf.ratio == pytest.approx(0.5)


def test_use_references_are_resolved(run):
    body = (
        '<defs><circle id="dot" r="3"/></defs>'
        f'<use xlink:href="#dot" x="10" y="20" {S}/>'
        f'<use href="#dot" x="10" transform="translate(50,50)" {S}/>'
    )
    doc, _ = run(body)
    centers = sorted(xy(c.dxf.center) for c in entities(doc, "CIRCLE"))
    assert flat(centers) == pytest.approx(flat(sorted([flip(10, 20), flip(60, 50)])))


def test_symbol_is_only_drawn_through_use(run):
    body = f'<symbol id="s"><rect width="5" height="5" {S}/></symbol><use href="#s" x="20" y="20"/>'
    doc, _ = run(body)
    (pl,) = entities(doc, "LWPOLYLINE")
    assert min(p[0] for p in pl.get_points("xy")) == pytest.approx(20)


def test_nested_group_transforms(run):
    body = (
        '<g transform="translate(10,20)"><g transform="rotate(90)"><g transform="scale(2)">'
        f'<g transform="matrix(1,0,0,1,5,0)"><line x1="0" y1="0" x2="10" y2="0" {S}/></g></g></g></g>'
    )
    doc, _ = run(body)
    (line,) = entities(doc, "LINE")
    # (0,0) -> (5,0) -> (10,0) -> (0,10) -> (10,30); (10,0) -> (15,0) -> (30,0) -> (0,30) -> (10,50)
    assert xy(line.dxf.start) == pytest.approx(flip(10, 30), abs=1e-12)
    assert xy(line.dxf.end) == pytest.approx(flip(10, 50), abs=1e-12)


def test_rotated_circle_stays_a_circle(run):
    doc, _ = run(f'<g transform="rotate(90 50 50)"><circle cx="70" cy="50" r="10" {S}/></g>')
    (c,) = entities(doc, "CIRCLE")
    assert c.dxf.radius == pytest.approx(10) and xy(c.dxf.center) == pytest.approx(flip(50, 70))


def test_non_uniform_scale_turns_circle_into_ellipse(run):
    doc, _ = run(f'<circle cx="10" cy="20" r="10" transform="scale(2,1)" {S}/>')
    (e,) = entities(doc, "ELLIPSE")
    assert xy(e.dxf.center) == pytest.approx(flip(20, 20))
    assert abs(e.dxf.major_axis[0]) == pytest.approx(20) and e.dxf.ratio == pytest.approx(0.5)


def test_skewed_circle_is_exact_ellipse(run):
    doc, _ = run(f'<circle cx="0" cy="0" r="10" transform="translate(50,50) skewX(30)" {S}/>')
    (e,) = entities(doc, "ELLIPSE")
    k = math.tan(math.radians(30))
    for p in e.construction_tool().vertices([i * 0.1 for i in range(63)]):
        x, y = p[0] - 50, 50 - p[1]  # back to the skewed local frame
        assert math.hypot(x - k * y, y) == pytest.approx(10, abs=1e-9)
