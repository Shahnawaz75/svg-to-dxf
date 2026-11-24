"""Read an SVG document into geometry items in document space (CSS px, y down).

``svgelements`` does the heavy lifting (CSS, units, viewBox, ``<use>``); it is
called with ``reify=False`` so every shape keeps its local geometry plus one
accumulated matrix, which :mod:`svg_to_dxf.geometry` then applies exactly.
"""

from __future__ import annotations

import gzip
import io
import math
import re
import threading
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import svgelements as se

from .colors import BLACK, RGB
from .geometry import (
    Affine,
    Bezier,
    Bounds,
    EllipticArc,
    FullEllipse,
    Line,
    Point,
    Segment,
    Subpath,
    cross,
    dist,
    union_bounds,
)

INKSCAPE = "{http://www.inkscape.org/namespaces/inkscape}"
ATTRS = se.SVG_STRUCT_ATTRIB  # svgelements keeps each element's own attributes here
NON_RENDERED = {"symbol", "mask", "marker"}  # never drawn where they are defined
_NON_RENDERED_RE = re.compile(rb"<(?:[\w.-]+:)?(?:symbol|mask|marker)[\s/>]")
EPS = 1e-9  # px; shorter segments are dropped
CLOSE_EPS = 1e-6  # px; an open subpath ending this close to its start is closed


@dataclass(frozen=True)
class TextItem:
    """A text run: baseline anchor, em height and baseline direction."""

    text: str
    position: Point
    height: float
    direction: Point
    anchor: str = "start"

    def transformed(self, m: Affine) -> TextItem:
        return TextItem(
            self.text, m.apply(self.position), self.height * m.scale, m.apply_vector(self.direction), self.anchor
        )


Geometry = list[Subpath] | FullEllipse | TextItem


@dataclass
class SvgItem:
    """One visible SVG element with its paint and group (layer) name."""

    geometry: Geometry
    stroke: RGB | None
    fill: RGB | None
    group: str | None
    tag: str

    @property
    def color(self) -> RGB:
        """Color that identifies the element: stroke, else fill, else black."""
        return self.stroke or self.fill or BLACK

    def bounds(self) -> Bounds | None:
        g = self.geometry
        if isinstance(g, TextItem):
            x, y = g.position
            return (x, y, x, y)
        if isinstance(g, FullEllipse):
            return g.bounds()
        return union_bounds(sp.bounds() for sp in g)


@dataclass
class SvgDrawing:
    """Everything read from one SVG file."""

    items: list[SvgItem] = field(default_factory=list)
    page: Bounds | None = None  # the viewBox (or width x height) in px, y down
    hidden: int = 0
    texts: int = 0
    images: int = 0
    gradients: int = 0
    clipped: int = 0


@dataclass(frozen=True)
class _Context:
    hidden: bool = False
    group: str | None = None


_INCHES_PER_UNIT = {"in": 1.0, "cm": 1 / 2.54, "mm": 1 / 25.4, "pt": 1 / 72.0, "pc": 1 / 6.0}
_PARSE_LOCK = threading.Lock()


@contextmanager
def _exact_lengths() -> Iterator[None]:
    """Make svgelements convert physical units exactly while parsing.

    svgelements 1.9 converts mm and cm with a rounded 1/25.4 (0.0393701, a
    5e-7 relative error) and pt/pc as if the resolution were always 96 ppi.
    ``Length.value`` is swapped for an exact version during the parse only.
    """
    original = se.Length.value

    def value(self: se.Length, ppi: float | None = None, *args: object, **kwargs: object) -> object:
        factor = _INCHES_PER_UNIT.get(self.units)
        if factor is None or self.amount is None:
            return original(self, ppi, *args, **kwargs)
        return self if ppi is None else self.amount * ppi * factor  # stay lazy without ppi

    with _PARSE_LOCK:
        se.Length.value = value
        try:
            yield
        finally:
            se.Length.value = original


def read_svg(data: bytes, dpi: float = 96.0, include_hidden: bool = False) -> SvgDrawing:
    """Parse SVG (or gzip-compressed SVGZ) bytes into an :class:`SvgDrawing`."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    data = _move_non_rendered_to_defs(data)
    with _exact_lengths():
        doc = se.SVG.parse(io.BytesIO(data), reify=False, ppi=dpi, parse_display_none=True)
    if not isinstance(doc, se.SVG):
        raise ValueError("not an SVG document (no <svg> root element)")
    page, fix = _page_and_correction(doc)
    drawing = SvgDrawing(page=page)
    _walk(doc, _Context(), drawing, include_hidden, fix)
    return drawing


def _move_non_rendered_to_defs(data: bytes) -> bytes:
    """Move <symbol>, <mask> and <marker> into <defs> so they are never drawn.

    svgelements would otherwise render their children in place; inside <defs>
    they stay available to <use> by id.
    """
    if not _NON_RENDERED_RE.search(data):
        return data
    root = ET.fromstring(data)
    parents = {child: parent for parent in root.iter() for child in parent}

    def local(el: ET.Element) -> str:
        return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""

    def in_defs(el: ET.Element) -> bool:
        p = parents.get(el)
        while p is not None:
            if local(p) in NON_RENDERED or local(p) == "defs":
                return True
            p = parents.get(p)
        return False

    movers = [el for el in root.iter() if local(el) in NON_RENDERED and not in_defs(el)]
    if not movers:
        return data
    defs = ET.SubElement(root, "{http://www.w3.org/2000/svg}defs")
    for el in movers:
        parents[el].remove(el)
        defs.append(el)
    return ET.tostring(root)


def _viewbox_affine(doc: se.SVG) -> Affine:
    """Exact viewBox -> viewport map (SVG 2, section 8.2, preserveAspectRatio)."""
    vb = doc.viewbox
    ex, ey, ew, eh = (float(v or 0.0) for v in (doc.x, doc.y, doc.width, doc.height))
    parts = (vb.preserve_aspect_ratio or "xMidYMid meet").split()
    align = parts[0].lower()
    mode = parts[1].lower() if len(parts) > 1 else "meet"
    sx, sy = ew / vb.width, eh / vb.height
    if align != "none":
        sx = sy = min(sx, sy) if mode == "meet" else max(sx, sy)
    tx, ty = ex - vb.x * sx, ey - vb.y * sy
    if "xmid" in align:
        tx += (ew - vb.width * sx) / 2.0
    elif "xmax" in align:
        tx += ew - vb.width * sx
    if "ymid" in align:
        ty += (eh - vb.height * sy) / 2.0
    elif "ymax" in align:
        ty += eh - vb.height * sy
    return Affine(sx, 0.0, 0.0, sy, tx, ty)


def _page_and_correction(doc: se.SVG) -> tuple[Bounds | None, Affine]:
    """The page (viewBox in px, or 0,0..width,height) and a matrix correction.

    svgelements bakes the viewBox map into every element matrix but writes it
    with 12 decimals; ``correction @ element_matrix`` restores full precision.
    """
    own = doc.values.get(ATTRS, {})
    if doc.viewbox is not None and doc.viewbox.width and doc.viewbox.height and doc.width and doc.height:
        vb = doc.viewbox
        root = own.get("transform", "")
        approx = Affine.from_svg(se.Matrix(f"{root} {doc.viewbox_transform}"))
        exact = Affine.from_svg(se.Matrix(root)) @ _viewbox_affine(doc)
        x0, y0 = exact.apply((vb.x, vb.y))
        x1, y1 = exact.apply((vb.x + vb.width, vb.y + vb.height))
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), exact @ approx.inverse()
    w, h = own.get("width"), own.get("height")
    if w and h and "%" not in w and "%" not in h:
        return (0.0, 0.0, float(doc.width), float(doc.height)), Affine()
    return None, Affine()


def _number(value: object, default: float = 1.0) -> float:
    if value is None:
        return default
    text = str(value).strip()
    try:
        return float(text[:-1]) / 100.0 if text.endswith("%") else float(text)
    except ValueError:
        return default


def _hidden_here(own: dict) -> bool:
    return str(own.get("display", "")).strip().lower() == "none" or _number(own.get("opacity")) <= 0.0


def _rgb(color: se.Color | None) -> RGB | None:
    if color is None or color.value is None or color.alpha == 0:
        return None
    return (color.red, color.green, color.blue)


def _walk(node: se.Group, ctx: _Context, out: SvgDrawing, include_hidden: bool, fix: Affine) -> None:
    for child in node:
        values = getattr(child, "values", None) or {}
        own = values.get(ATTRS, {})
        hidden = ctx.hidden or _hidden_here(own)
        if "clip-path" in own or "mask" in own:
            out.clipped += 1
        if isinstance(child, (se.Group, se.Use)):
            group = ctx.group
            if own.get("tag") == "g":
                label = own.get(INKSCAPE + "label") or own.get("data-name") or own.get("id")
                if label and (own.get(INKSCAPE + "groupmode") == "layer" or group is None):
                    group = str(label)
            _walk(child, _Context(hidden, group), out, include_hidden, fix)
            continue
        if not isinstance(child, (se.Shape, se.Text)):
            if isinstance(child, se.Image):
                out.images += 1
            continue
        stroke = _rgb(child.stroke) if (child.stroke_width or 0) > 0 else None
        fill = _rgb(child.fill)
        invisible = hidden or str(values.get("visibility", "")).lower() in ("hidden", "collapse")
        if isinstance(child, se.Text):
            text = (child.text or "").strip()
            if not text:
                continue
            if invisible and not include_hidden:
                out.hidden += 1
                continue
            out.texts += 1
            out.items.append(SvgItem(_text_item(child, text, fix), stroke, fill, ctx.group, "text"))
            continue
        if (invisible or (stroke is None and fill is None)) and not include_hidden:
            out.hidden += 1
            continue
        if any(str(values.get(k, "")).startswith("url(") for k in ("stroke", "fill")):
            out.gradients += 1
        if include_hidden and stroke is None and fill is None:
            stroke = _rgb(child.stroke) or _rgb(child.fill)
        geometry = _shape_geometry(child, fix)
        if geometry:
            out.items.append(SvgItem(geometry, stroke, fill, ctx.group, str(own.get("tag", "path"))))


def _text_item(t: se.Text, text: str, fix: Affine) -> TextItem:
    m = fix @ Affine.from_svg(t.transform)
    pos = (float(t.x) + float(t.dx or 0), float(t.y) + float(t.dy or 0))
    anchor = t.anchor if t.anchor in ("start", "middle", "end") else "start"
    return TextItem(text, m.apply(pos), float(t.font_size) * m.scale, m.apply_vector((1.0, 0.0)), anchor)


def _pt(p: se.Point) -> Point:
    return (float(p.x), float(p.y))


def _shape_geometry(shape: se.Shape, fix: Affine) -> list[Subpath] | FullEllipse | None:
    """Exact geometry of a shape in document space (its matrix applied)."""
    m = fix @ Affine.from_svg(shape.transform)
    if isinstance(shape, (se.Circle, se.Ellipse)):
        rx, ry = float(shape.rx), float(shape.ry)
        if rx <= 0 or ry <= 0:
            return None
        center = m.apply((float(shape.cx), float(shape.cy)))
        return FullEllipse(center, m.apply_vector((rx, 0.0)), m.apply_vector((0.0, ry)))

    subpaths: list[Subpath] = []
    segs: list[Segment] = []

    def flush(closed: bool) -> None:
        if segs:
            if not closed and dist(segs[0].start, segs[-1].end) <= CLOSE_EPS:
                closed = len(segs) > 1 or not isinstance(segs[0], Line)
            subpaths.append(Subpath(tuple(segs), closed))
        segs.clear()

    for seg in shape.segments(transformed=False):
        if isinstance(seg, se.Move):
            flush(False)
            continue
        new = _segment(seg, m)
        if new is not None:
            segs.append(new)
        if isinstance(seg, se.Close):
            flush(True)
    flush(False)
    return subpaths


def _segment(seg: se.PathSegment, m: Affine) -> Segment | None:
    """Convert one svgelements segment (local coordinates) through ``m``."""
    if isinstance(seg, (se.Line, se.Close)):
        if seg.start is None or seg.end is None:
            return None
        line = Line(m.apply(_pt(seg.start)), m.apply(_pt(seg.end)))
        return line if dist(line.start, line.end) > EPS else None
    if isinstance(seg, se.QuadraticBezier):
        return Bezier(tuple(m.apply(_pt(p)) for p in (seg.start, seg.control, seg.end)))
    if isinstance(seg, se.CubicBezier):
        return Bezier(tuple(m.apply(_pt(p)) for p in (seg.start, seg.control1, seg.control2, seg.end)))
    if isinstance(seg, se.Arc):
        start, end = _pt(seg.start), _pt(seg.end)
        if seg.sweep and seg.center is not None:
            c = _pt(seg.center)
            u = (seg.prx.x - c[0], seg.prx.y - c[1])
            v = (seg.pry.x - c[0], seg.pry.y - c[1])
            det = cross(u, v)
            if abs(det) > 1e-18:
                d = (start[0] - c[0], start[1] - c[1])
                t0 = math.atan2(cross(u, d) / det, cross(d, v) / det)
                return EllipticArc(c, u, v, t0, float(seg.sweep), start, end).transformed(m)
        # rx or ry is zero: SVG draws a straight line
        line = Line(m.apply(start), m.apply(end))
        return line if dist(line.start, line.end) > EPS else None
    return None
