"""Real-world size: units, DPI, viewBox, scale, fit, Y flip and origin."""

import ezdxf.bbox
import pytest
from conftest import entities, xy

from svg_to_dxf import ConvertOptions, parse_length

RED = 'fill="none" stroke="red"'


def extents(doc):
    box = ezdxf.bbox.extents(doc.modelspace())
    return (box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y)


def test_viewbox_rect_is_exactly_100_by_50_mm(run):
    doc, result = run(f'<rect width="1000" height="500" {RED}/>', 'width="100mm" height="50mm" viewBox="0 0 1000 500"')
    assert extents(doc) == pytest.approx((0, 0, 100, 50), abs=1e-9)
    assert result.size == pytest.approx((100, 50), abs=1e-9)
    assert doc.header["$INSUNITS"] == 4  # millimetres


def test_circle_r10_mm(run):
    doc, _ = run(f'<circle cx="50" cy="40" r="10" {RED}/>')
    (circle,) = entities(doc, "CIRCLE")
    assert circle.dxf.radius == pytest.approx(10, abs=1e-12)
    assert xy(circle.dxf.center) == pytest.approx((50, 60), abs=1e-12)  # y flipped


def test_mm_lengths_inside_document_are_exact(run):
    doc, _ = run(f'<circle cx="20mm" cy="20mm" r="10mm" {RED}/>', 'width="40mm" height="40mm"')
    (circle,) = entities(doc, "CIRCLE")
    assert circle.dxf.radius == pytest.approx(10, abs=1e-12)
    assert xy(circle.dxf.center) == pytest.approx((20, 20), abs=1e-12)


@pytest.mark.parametrize("dpi, size", [(96, 25.4), (72, 25.4 * 96 / 72), (90, 25.4 * 96 / 90)])
def test_unitless_px_follow_dpi(run, dpi, size):
    _, result = run(f'<rect width="96" height="48" {RED}/>', 'width="96" height="48"', dpi=dpi)
    assert result.size == pytest.approx((size, size / 2), abs=1e-9)


@pytest.mark.parametrize("dpi", [72, 96])
@pytest.mark.parametrize("width, mm", [("10cm", 100), ("4in", 101.6), ("72pt", 25.4), ("6pc", 25.4)])
def test_physical_root_units_ignore_dpi(run, width, mm, dpi):
    attrs = f'width="{width}" height="{width}" viewBox="0 0 10 10"'
    _, result = run(f'<rect width="10" height="10" {RED}/>', attrs, dpi=dpi)
    assert result.size == pytest.approx((mm, mm), abs=1e-9)


def test_viewbox_without_width_uses_user_units_as_px(run):
    _, result = run(f'<rect width="24" height="24" {RED}/>', 'viewBox="0 0 24 24"')
    assert result.size == pytest.approx((6.35, 6.35), abs=1e-9)  # 24 px at 96 dpi


def test_inch_output(run):
    doc, result = run(
        f'<rect width="100" height="50" {RED}/>', 'width="2in" height="1in" viewBox="0 0 100 50"', units="in"
    )
    assert result.size == pytest.approx((2, 1), abs=1e-12)
    assert doc.header["$INSUNITS"] == 1


def test_scale_and_fit(run):
    attrs = 'width="50mm" height="25mm" viewBox="0 0 50 25"'
    body = f'<rect width="50" height="25" {RED}/>'
    assert run(body, attrs, scale=2)[1].size == pytest.approx((100, 50), abs=1e-9)
    assert run(body, attrs, fit_width="200mm")[1].size == pytest.approx((200, 100), abs=1e-9)
    assert run(body, attrs, fit_height="2in")[1].size == pytest.approx((101.6, 50.8), abs=1e-9)


def test_viewbox_with_other_aspect_is_centered(run):
    # preserveAspectRatio "xMidYMid meet": 100x100 user units in a 200x100 mm viewport
    _, result = run(f'<rect width="100" height="100" {RED}/>', 'width="200mm" height="100mm" viewBox="0 0 100 100"')
    assert result.extents == pytest.approx((0, 0, 100, 100), abs=1e-9)


def test_viewbox_offset_origin_is_bottom_left_of_viewbox(run):
    _, result = run(
        f'<rect x="-50" y="-50" width="20" height="20" {RED}/>',
        'width="100mm" height="100mm" viewBox="-50 -50 100 100"',
    )
    assert result.extents == pytest.approx((0, 80, 20, 100), abs=1e-9)


@pytest.mark.parametrize(
    "origin, box",
    [
        ("bottom-left", (0, 90, 10, 100)),
        ("top-left", (0, -10, 10, 0)),
        ("center", (-50, 40, -40, 50)),
        ("bbox", (0, 0, 10, 10)),
    ],
)
def test_y_flip_and_origin(run, origin, box):
    _, result = run(f'<rect width="10" height="10" {RED}/>', origin=origin)  # SVG top-left corner
    assert result.extents == pytest.approx(box, abs=1e-9)


def test_parse_length_and_validation():
    assert parse_length("200mm") == 200
    assert parse_length("2in", "mm") == pytest.approx(50.8)
    assert parse_length("25.4mm", "in") == pytest.approx(1)
    assert parse_length("96px", "mm", dpi=96) == pytest.approx(25.4)
    with pytest.raises(ValueError):
        parse_length("wide")
    with pytest.raises(ValueError):
        ConvertOptions(scale=2, fit_width=100)
    with pytest.raises(ValueError):
        ConvertOptions(dxf_version="R14")
