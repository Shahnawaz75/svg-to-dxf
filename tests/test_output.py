"""DXF versions, R12 and --laser, joining, text and the Python API."""

import gzip

import ezdxf
import pytest
from conftest import entities, svg, xy

from svg_to_dxf import convert

S = 'fill="none" stroke="black"'
MIXED = (
    f'<path d="M 10 90 C 20 50 60 50 90 90" {S}/>'
    f'<ellipse cx="50" cy="50" rx="20" ry="10" {S}/>'
    f'<rect x="5" y="5" width="30" height="20" rx="4" {S}/>'
    f'<circle cx="80" cy="20" r="5" {S}/>'
    f'<path d="M 60 50 A 10 10 0 0 1 50 60" {S}/>'
    '<path d="M 5 60 L 15 60 L 15 70 Z" fill="red"/>'
    '<text x="10" y="40" font-size="5">R12</text>'
)
R12_ENTITIES = {"LINE", "ARC", "CIRCLE", "POLYLINE", "TEXT"}


def test_r12_writes_only_r12_entities(run):
    doc, result = run(MIXED, dxf_version="R12", text="dxf", fill_as_hatch=True)
    assert doc.dxfversion == "AC1009"
    assert {e.dxftype() for e in doc.modelspace()} <= R12_ENTITIES
    assert entities(doc, "CIRCLE") and entities(doc, "ARC")  # exact primitives survive
    rounded = [p for p in entities(doc, "POLYLINE") if any(v.dxf.bulge for v in p.vertices)]
    assert rounded  # rounded corners stay exact as bulges
    changes = " | ".join(result.changes)
    assert "R12 has no SPLINE" in changes and "R12 has no ELLIPSE" in changes and "R12 has no HATCH" in changes


@pytest.mark.parametrize(
    "version, code", [("R12", "AC1009"), ("R2000", "AC1015"), ("R2010", "AC1024"), ("R2018", "AC1032")]
)
def test_dxf_versions_pass_audit(run, version, code):
    doc, _ = run(MIXED, dxf_version=version, text="dxf", fill_as_hatch=True)
    assert doc.dxfversion == code


def test_laser_preset_joins_into_closed_r12_polyline(run):
    body = (
        f'<line x1="10" y1="10" x2="50" y2="10" {S}/><line x1="50" y1="10" x2="30" y2="40" {S}/>'
        f'<line x1="10" y1="10" x2="30" y2="40" {S}/>'
    )
    doc, result = run(body, laser=True)
    assert result.options.dxf_version == "R12" and result.options.curves == "polyline"
    (pl,) = entities(doc, "POLYLINE")
    assert pl.is_closed and len(list(pl.vertices)) == 3


def test_join_bridges_small_gaps_and_reversed_pieces(run):
    body = (
        f'<path d="M 10 10 L 40 10" {S}/><path d="M 40 40 L 40.01 10.01" {S}/>'  # reversed, 0.014 gap
        f'<path d="M 40 40 L 10 40 L 10 10" {S}/>'
    )
    doc, _ = run(body)
    assert len(entities(doc, "LINE")) == 2 and len(entities(doc, "LWPOLYLINE")) == 1
    doc, _ = run(body, join=True)
    (pl,) = entities(doc, "LWPOLYLINE")
    assert pl.closed and len(pl) == 4


def test_join_never_merges_different_colors(run):
    doc, _ = run(
        '<path d="M 0 0 L 10 0" fill="none" stroke="red"/><path d="M 10 0 L 20 0" fill="none" stroke="blue"/>',
        join=True,
    )
    assert len(entities(doc, "LINE")) == 2


def test_text_is_skipped_with_a_warning(run):
    doc, result = run('<text x="10" y="20">A</text><text x="10" y="30">B</text>')
    assert not entities(doc, "TEXT")
    assert any(w.startswith("2 text element(s) skipped") and "Object to Path" in w for w in result.warnings)


def test_text_dxf_position_and_height(run):
    doc, _ = run('<text x="10" y="20" font-size="10" text-anchor="middle">Hi</text>', text="dxf")
    (t,) = entities(doc, "TEXT")
    assert t.dxf.text == "Hi" and t.dxf.height == pytest.approx(7.0)  # cap height = 0.7 em
    assert xy(t.dxf.align_point) == pytest.approx((10, 80))


def test_report_and_summary(run):
    _, result = run(MIXED)
    report = result.report()
    assert "DXF R2010 (AC1024), units mm ($INSUNITS=4)" in report
    assert "size      " in report and "BLACK_000000" in report and "SPLINE 1" in report
    assert "entities on" in result.summary()


def test_api_accepts_paths_bytes_and_svgz(tmp_path):
    data = svg(f'<rect width="10" height="5" {S}/>', 'width="10mm" height="5mm" viewBox="0 0 10 5"')
    (tmp_path / "a.svg").write_bytes(data)
    (tmp_path / "b.svgz").write_bytes(gzip.compress(data))
    for source in (tmp_path / "a.svg", str(tmp_path / "b.svgz"), data):
        result = convert(source, units="mm")
        assert result.output is None and result.size == pytest.approx((10, 5))
    result = convert(tmp_path / "a.svg", tmp_path / "sub" / "a.dxf", dxf_version="r2018")
    assert ezdxf.readfile(result.output).dxfversion == "AC1032"


def test_empty_svg_gives_empty_dxf_with_warning(run):
    doc, result = run("")
    assert len(doc.modelspace()) == 0 and result.extents is None
    assert any("no drawable geometry" in w for w in result.warnings)
