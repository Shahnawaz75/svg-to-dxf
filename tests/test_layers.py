"""Layers from colors and groups, entity colors, hidden elements, hatches."""

import pytest
from conftest import entities

from svg_to_dxf.colors import color_layer_name, nearest_aci, sanitize_layer_name

BODY = (
    '<g inkscape:groupmode="layer" inkscape:label="Cut">'
    '<g id="g12"><rect x="10" y="10" width="20" height="20" fill="none" stroke="#ff0000"/></g></g>'
    '<g id="engrave"><circle cx="70" cy="70" r="5" fill="none" stroke="#0000ff"/></g>'
    '<line x1="0" y1="0" x2="10" y2="0" stroke="#000000"/>'
)


def layer_of(doc, dxftype):
    return [e.dxf.layer for e in entities(doc, dxftype)]


def test_layers_by_stroke_color(run):
    doc, _ = run(BODY)
    assert layer_of(doc, "LWPOLYLINE") == ["RED_FF0000"]
    assert layer_of(doc, "CIRCLE") == ["BLUE_0000FF"]
    assert layer_of(doc, "LINE") == ["BLACK_000000"]
    red = doc.layers.get("RED_FF0000")
    assert red.color == 1 and red.rgb == (255, 0, 0)
    assert doc.layers.get("BLUE_0000FF").color == 5
    assert all(e.dxf.color == 256 for e in doc.modelspace())  # BYLAYER


def test_fill_only_shape_uses_fill_color(run):
    doc, _ = run('<rect width="10" height="10" fill="#2e7d32"/>')
    assert layer_of(doc, "LWPOLYLINE") == ["GREEN_2E7D32"]


def test_layers_by_inkscape_layer_and_group(run):
    doc, _ = run(BODY, layers="group")
    assert layer_of(doc, "LWPOLYLINE") == ["Cut"]  # inner <g id="g12"> stays in the Inkscape layer
    assert layer_of(doc, "CIRCLE") == ["engrave"]
    assert layer_of(doc, "LINE") == ["0"]
    (rect,) = entities(doc, "LWPOLYLINE")
    assert rect.dxf.color == 1 and rect.rgb == (255, 0, 0)  # color kept on the entity


def test_layers_none_keeps_entity_colors(run):
    doc, _ = run(BODY, layers="none")
    assert {e.dxf.layer for e in doc.modelspace()} == {"0"}
    assert entities(doc, "CIRCLE")[0].dxf.color == 5


def test_r12_layer_names_follow_r12_rules(run):
    doc, result = run(
        '<g inkscape:groupmode="layer" inkscape:label="Cut lines 3mm"><line x2="5" stroke="red"/></g>',
        layers="group",
        dxf_version="R12",
    )
    assert layer_of(doc, "LINE") == ["CUT_LINES_3MM"]
    assert any("renamed" in c for c in result.changes)


HIDDEN = (
    '<rect width="5" height="5" stroke="red" fill="none" display="none"/>'
    '<rect width="5" height="5" stroke="red" fill="none" style="visibility:hidden"/>'
    '<rect width="5" height="5" stroke="red" fill="none" opacity="0"/>'
    '<rect width="5" height="5" stroke="none" fill="none"/>'
    '<g opacity="0"><rect width="5" height="5" stroke="red" fill="none" opacity="1"/></g>'
    '<g visibility="hidden"><rect x="50" width="5" height="5" stroke="red" fill="none" visibility="visible"/></g>'
)


def test_hidden_elements_are_skipped_and_counted(run):
    doc, result = run(HIDDEN)
    assert len(entities(doc, "LWPOLYLINE")) == 1  # only the explicitly visible child
    assert any(w.startswith("5 hidden") for w in result.warnings)
    doc, _ = run(HIDDEN, include_hidden=True)
    assert len(entities(doc, "LWPOLYLINE")) == 6


def test_fill_as_hatch(run):
    body = '<rect x="10" y="10" width="20" height="10" fill="#ff8000"/><circle cx="60" cy="60" r="5" fill="blue"/>'
    doc, _ = run(body, fill_as_hatch=True)
    hatches = entities(doc, "HATCH")
    assert len(hatches) == 2 and all(h.dxf.solid_fill for h in hatches)
    assert hatches[0].rgb == (255, 128, 0) and len(hatches[0].paths) == 1
    assert len(entities(doc, "LWPOLYLINE")) == 1 and len(entities(doc, "CIRCLE")) == 1  # outlines kept


def test_color_helpers():
    assert color_layer_name((255, 0, 0)) == "RED_FF0000"
    assert color_layer_name((30, 136, 229)) == "BLUE_1E88E5"
    assert [nearest_aci(c) for c in [(255, 0, 0), (0, 0, 255), (0, 0, 0), (255, 255, 255)]] == [1, 5, 7, 7]
    assert sanitize_layer_name("a/b:c", r12=False) == "a_b_c"


@pytest.mark.parametrize("paint", ['stroke="url(#g)" fill="none"', 'fill="url(#g)"'])
def test_gradient_paint_is_exported_with_warning(run, paint):
    doc, result = run(
        '<linearGradient id="g"><stop offset="0" stop-color="red"/></linearGradient>'
        f'<rect width="5" height="5" {paint}/>'
    )
    assert len(entities(doc, "LWPOLYLINE")) == 1
    assert any("gradient" in w for w in result.warnings)
