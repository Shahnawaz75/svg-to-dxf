"""DXF output: entity types per DXF version and curve mode, layers, statistics."""

from __future__ import annotations

import logging
import math
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import ezdxf
from ezdxf import units as dxf_units
from ezdxf.colors import rgb2int
from ezdxf.document import Drawing
from ezdxf.enums import TextEntityAlignment

from .colors import RGB, is_exact_aci, nearest_aci, sanitize_layer_name
from .geometry import (
    TAU,
    Bezier,
    EllipticArc,
    FullEllipse,
    Line,
    Subpath,
    Vertex,
    bspline_from_subpath,
    cross,
    flatten_segment,
    full_ellipse_of,
    principal_axes,
    subpath_vertices,
)
from .svgread import TextItem

INSUNITS = {"mm": dxf_units.MM, "in": dxf_units.IN}
CAP_HEIGHT = 0.7  # DXF text height is the capital height; SVG font-size is the em size
_ALIGN = {
    "start": TextEntityAlignment.LEFT,
    "middle": TextEntityAlignment.CENTER,
    "end": TextEntityAlignment.RIGHT,
}


@dataclass
class LayerStats:
    """Entity counts for one layer of the output."""

    name: str
    entities: int = 0
    closed: int = 0
    open: int = 0
    types: Counter = field(default_factory=Counter)


@contextmanager
def _quiet_ezdxf() -> Iterator[None]:
    """ezdxf logs a warning for every R12 document about $INSUNITS; mute it."""
    logger = logging.getLogger("ezdxf")
    level = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(level)


class DxfBuilder:
    """Turns geometry into the best-fitting DXF entities for one DXF version.

    * full circles -> CIRCLE, circular arcs -> ARC or polyline bulges
    * ellipses and elliptical arcs -> ELLIPSE (spline mode, R2000+)
    * Bezier paths -> one exact SPLINE (spline mode, R2000+), else a polyline
      flattened within ``tolerance``
    * straight runs -> LWPOLYLINE (R2000+) or POLYLINE (R12)
    """

    def __init__(self, version: str, units: str, curves: str, tolerance: float, entity_colors: bool) -> None:
        self.version = version
        self.units = units
        self.curves = curves
        self.tolerance = tolerance
        self.entity_colors = entity_colors
        self.r12 = version == "R12"
        self.splines = curves == "spline" and not self.r12
        self.true_color = version not in ("R12", "R2000")
        with _quiet_ezdxf():
            self.doc: Drawing = ezdxf.new(version, units=INSUNITS[units])
        if not self.r12:
            self.doc.header["$MEASUREMENT"] = 1 if units == "mm" else 0
        self.msp = self.doc.modelspace()
        self.layers: dict[str, LayerStats] = {}
        self.renamed: dict[str, str] = {}
        self.flattened: Counter = Counter()
        self.skipped_hatches = 0
        self.inexact_colors: set[RGB] = set()

    def layer(self, name: str, rgb: RGB | None = None) -> str:
        """Create the layer once (ACI + true color) and return its valid name."""
        clean = sanitize_layer_name(name, self.r12)
        if clean != name:
            self.renamed[name] = clean
        if clean not in self.layers:
            self.layers[clean] = LayerStats(clean)
            if clean not in self.doc.layers:
                layer = self.doc.layers.add(clean, color=nearest_aci(rgb) if rgb else 7)
                if rgb:
                    self._true_color(layer, rgb)
        return clean

    def _true_color(self, entity: Any, rgb: RGB) -> None:
        if self.true_color:
            entity.rgb = rgb
        elif not is_exact_aci(rgb):
            self.inexact_colors.add(rgb)

    def _attribs(self, layer: str, rgb: RGB | None) -> dict[str, Any]:
        attribs: dict[str, Any] = {"layer": layer}
        if self.entity_colors and rgb is not None:
            attribs["color"] = nearest_aci(rgb)
            if self.true_color:
                attribs["true_color"] = rgb2int(rgb)
            elif not is_exact_aci(rgb):
                self.inexact_colors.add(rgb)
        return attribs

    def _record(self, layer: str, dxftype: str, closed: bool | None) -> None:
        stats = self.layers[layer]
        stats.entities += 1
        stats.types[dxftype] += 1
        if closed is not None:
            if closed:
                stats.closed += 1
            else:
                stats.open += 1

    def add_outline(self, geom: Subpath | FullEllipse, layer: str, rgb: RGB | None) -> None:
        """Add one subpath or full ellipse as the most exact entity available."""
        attribs = self._attribs(layer, rgb)
        if isinstance(geom, Subpath):
            full = full_ellipse_of(geom)
            if full is None:
                self._add_subpath(geom, attribs)
                return
            geom = full
        self._add_full_ellipse(geom, attribs)

    def _add_full_ellipse(self, e: FullEllipse, attribs: dict[str, Any]) -> None:
        layer = attribs["layer"]
        if e.is_circle:
            self.msp.add_circle(e.center, e.radius, dxfattribs=attribs)
            self._record(layer, "CIRCLE", True)
        elif self.splines:
            major, minor, _ = principal_axes(e.u, e.v)
            ratio = math.hypot(*minor) / math.hypot(*major)
            self.msp.add_ellipse(e.center, major_axis=major, ratio=ratio, dxfattribs=attribs)
            self._record(layer, "ELLIPSE", True)
        else:
            self.flattened["ellipse"] += 1
            self._add_polyline(Subpath((e.as_arc(),), True), attribs)

    def _add_subpath(self, sp: Subpath, attribs: dict[str, Any]) -> None:
        layer = attribs["layer"]
        segs = sp.segments
        if len(segs) == 1 and not sp.closed:
            seg = segs[0]
            if isinstance(seg, Line):
                self.msp.add_line(seg.start, seg.end, dxfattribs=attribs)
                self._record(layer, "LINE", False)
                return
            if isinstance(seg, EllipticArc) and seg.is_circular:
                self._add_arc(seg, attribs)
                return
            if isinstance(seg, EllipticArc) and self.splines:
                self._add_ellipse_arc(seg, attribs)
                return
        curved = any(isinstance(s, Bezier) or (isinstance(s, EllipticArc) and not s.is_circular) for s in segs)
        if curved and self.splines:
            degree, ctrl, knots = bspline_from_subpath(sp)
            spline = self.msp.add_spline(dxfattribs=attribs)
            spline.dxf.degree = degree
            spline.control_points = ctrl
            spline.knots = knots
            self._record(layer, "SPLINE", sp.closed)
            return
        if curved:
            self.flattened["curve"] += 1
        self._add_polyline(sp, attribs)

    def _add_polyline(self, sp: Subpath, attribs: dict[str, Any]) -> None:
        verts = subpath_vertices(sp, self.tolerance)
        if self.r12:
            self.msp.add_polyline2d(verts, format="xyb", close=sp.closed, dxfattribs=attribs)
            self._record(attribs["layer"], "POLYLINE", sp.closed)
        else:
            self.msp.add_lwpolyline(verts, format="xyb", close=sp.closed, dxfattribs=attribs)
            self._record(attribs["layer"], "LWPOLYLINE", sp.closed)

    def _add_arc(self, arc: EllipticArc, attribs: dict[str, Any]) -> None:
        cx, cy = arc.center
        a0 = math.degrees(math.atan2(arc.start[1] - cy, arc.start[0] - cx))
        a1 = math.degrees(math.atan2(arc.end[1] - cy, arc.end[0] - cx))
        if arc.geometric_sweep < 0:  # DXF arcs always run counter-clockwise
            a0, a1 = a1, a0
        self.msp.add_arc(arc.center, arc.radius, a0, a1, dxfattribs=attribs)
        self._record(attribs["layer"], "ARC", False)

    def _add_ellipse_arc(self, arc: EllipticArc, attribs: dict[str, Any]) -> None:
        major, minor, t_star = principal_axes(arc.u, arc.v)
        ratio = math.hypot(*minor) / math.hypot(*major)
        # DXF: P(p) = c + major*cos(p) + ratio*rot90(major)*sin(p), p increasing (CCW)
        if cross(major, minor) > 0:
            p0, p1 = arc.t0 - t_star, arc.t0 - t_star + arc.sweep
        else:
            p0, p1 = t_star - arc.t0, t_star - arc.t0 - arc.sweep
        start = min(p0, p1) % TAU
        end = (start + abs(arc.sweep)) % TAU
        self.msp.add_ellipse(
            arc.center, major_axis=major, ratio=ratio, start_param=start, end_param=end, dxfattribs=attribs
        )
        self._record(attribs["layer"], "ELLIPSE", False)

    def add_hatch(self, boundaries: Sequence[Subpath | FullEllipse], layer: str, rgb: RGB) -> None:
        """Solid HATCH filled with ``rgb``; boundaries use the odd-parity rule."""
        if self.r12:
            self.skipped_hatches += 1
            return
        paths: list[list[Vertex]] = []
        for b in boundaries:
            if isinstance(b, FullEllipse) and b.is_circle:
                (cx, cy), r = b.center, b.radius
                paths.append([(cx + r, cy, 1.0), (cx - r, cy, 1.0)])
            elif isinstance(b, FullEllipse):
                paths.append([(x, y, 0.0) for x, y in flatten_segment(b.as_arc(), self.tolerance)])
            else:
                paths.append(subpath_vertices(b, self.tolerance))
        paths = [p for p in paths if len(p) >= 2]
        if not paths:
            return
        aci = nearest_aci(rgb)
        hatch = self.msp.add_hatch(color=aci, dxfattribs={"layer": layer})
        hatch.set_solid_fill(color=aci, rgb=rgb if self.true_color else None)
        if not self.true_color and not is_exact_aci(rgb):
            self.inexact_colors.add(rgb)
        for verts in paths:
            hatch.paths.add_polyline_path(verts, is_closed=True)
        self._record(layer, "HATCH", None)

    def add_text(self, item: TextItem, layer: str, rgb: RGB | None) -> None:
        """Best-effort TEXT entity at the SVG baseline anchor."""
        angle = math.degrees(math.atan2(item.direction[1], item.direction[0]))
        text = self.msp.add_text(
            item.text, height=item.height * CAP_HEIGHT, rotation=angle, dxfattribs=self._attribs(layer, rgb)
        )
        text.set_placement(item.position, align=_ALIGN[item.anchor])
        self._record(layer, "TEXT", None)

    def notes(self) -> list[str]:
        """What the DXF version or curve mode changed, in plain words."""
        out: list[str] = []
        tol = f"{self.tolerance:.4g} {self.units}"
        why = "R12 has no SPLINE" if self.r12 else "--curves polyline"
        if self.flattened["curve"]:
            out.append(f"{self.flattened['curve']} curved path(s) flattened to polylines within {tol} ({why})")
        if self.flattened["ellipse"]:
            why = "R12 has no ELLIPSE" if self.r12 else "--curves polyline"
            out.append(f"{self.flattened['ellipse']} ellipse(s) flattened to polylines within {tol} ({why})")
        if self.r12:
            polylines = sum(s.types["POLYLINE"] for s in self.layers.values())
            if polylines:
                out.append(f"{polylines} polyline(s) written as POLYLINE (R12 has no LWPOLYLINE)")
            if self.skipped_hatches:
                out.append(f"{self.skipped_hatches} fill(s) not exported (R12 has no HATCH)")
            out.append(f"R12 stores no drawing units: import the file as {self.units}")
        if self.inexact_colors:
            out.append(
                f"{len(self.inexact_colors)} color(s) written as the nearest ACI color "
                f"(DXF {self.version} has no true color)"
            )
        for old, new in self.renamed.items():
            out.append(f"layer {old!r} renamed to {new!r} (DXF {self.version} naming rules)")
        return out
