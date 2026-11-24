"""The conversion pipeline and its result: SVG -> geometry -> DXF + report."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import IO, Any

import ezdxf.bbox
from ezdxf.document import Drawing

from .colors import RGB, color_layer_name
from .geometry import Affine, Bounds, FullEllipse, SnapAffine, Subpath, join_subpaths, union_bounds
from .options import LASER_PRESET, ConvertOptions
from .svgread import SvgDrawing, SvgItem, TextItem, read_svg
from .writer import INSUNITS, DxfBuilder, LayerStats

Source = str | os.PathLike[str] | bytes | IO[bytes]


class ConversionError(Exception):
    """The SVG could not be read or converted."""


@dataclass
class ConversionResult:
    """Outcome of one conversion: the ezdxf document plus a summary."""

    doc: Drawing
    options: ConvertOptions
    source: str | None = None
    output: Path | None = None
    layers: dict[str, LayerStats] = field(default_factory=dict)
    extents: Bounds | None = None
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def size(self) -> tuple[float, float]:
        """Width and height of the output in output units (0, 0 if empty)."""
        if self.extents is None:
            return (0.0, 0.0)
        return (self.extents[2] - self.extents[0], self.extents[3] - self.extents[1])

    @property
    def entity_count(self) -> int:
        return sum(s.entities for s in self.layers.values())

    def _size_text(self) -> str:
        w, h = self.size
        u = self.options.units
        other = ("in", 1 / 25.4) if u == "mm" else ("mm", 25.4)
        return f"{w:.3f} x {h:.3f} {u}  ({w * other[1]:.3f} x {h * other[1]:.3f} {other[0]})"

    def summary(self) -> str:
        """One line: ``in.svg -> out.dxf: 12 entities on 2 layers, 100.000 x 50.000 mm``."""
        dst = self.output if self.output is not None else "(not saved)"
        n_layers = sum(1 for s in self.layers.values() if s.entities)
        return (
            f"{self.source or '<svg>'} -> {dst}: {self.entity_count} entities on {n_layers} layer(s), "
            f"{self._size_text()}, DXF {self.options.dxf_version}"
        )

    def report(self) -> str:
        """Multi-line report: size, extents, entities per layer, changes, warnings."""
        o = self.options
        lines = [f"{self.source or '<svg>'} -> {self.output if self.output is not None else '(not saved)'}"]
        units = f"units {o.units}" + ("" if o.dxf_version == "R12" else f" ($INSUNITS={INSUNITS[o.units]})")
        lines.append(f"  DXF {o.dxf_version} ({o.dxf_code}), {units}")
        if self.extents is None:
            lines.append("  size      (empty drawing)")
        else:
            x0, y0, x1, y1 = self.extents
            lines.append(f"  size      {self._size_text()}")
            lines.append(f"  extents   X {x0:.3f} .. {x1:.3f}   Y {y0:.3f} .. {y1:.3f}")
        rows = [s for s in self.layers.values() if s.entities]
        width = max([len(s.name) for s in rows] + [5])
        lines.append(f"  {'layer':<{width}}  entities  closed  open  types")
        for s in rows:
            types = ", ".join(f"{k} {v}" for k, v in sorted(s.types.items()))
            lines.append(f"  {s.name:<{width}}  {s.entities:>8}  {s.closed:>6}  {s.open:>4}  {types}")
        total = (self.entity_count, sum(s.closed for s in rows), sum(s.open for s in rows))
        lines.append(f"  {'total':<{width}}  {total[0]:>8}  {total[1]:>6}  {total[2]:>4}")
        for title, items in (("changes", self.changes), ("warnings", self.warnings)):
            if items:
                lines.append(f"  {title}:")
                lines.extend(f"    - {item}" for item in items)
        return "\n".join(lines)


def _read_source(source: Source) -> tuple[bytes, str | None]:
    if isinstance(source, bytes):
        return source, None
    if hasattr(source, "read"):
        return source.read(), getattr(source, "name", None)  # type: ignore[union-attr]
    path = Path(source)  # type: ignore[arg-type]
    return path.read_bytes(), str(path)


def _reader_warnings(svg: SvgDrawing, opts: ConvertOptions) -> list[str]:
    out = []
    if svg.texts and opts.text == "skip":
        out.append(
            f"{svg.texts} text element(s) skipped: DXF cannot hold SVG fonts reliably. Convert text to "
            "paths first (Inkscape: Path > Object to Path; Illustrator: Type > Create Outlines) "
            "or use --text dxf for best-effort TEXT entities"
        )
    if svg.hidden and not opts.include_hidden:
        out.append(
            f"{svg.hidden} hidden or unpainted element(s) skipped (display:none, visibility:hidden, "
            "opacity 0, or no stroke and no fill); use --include-hidden to export them"
        )
    if svg.images:
        out.append(f"{svg.images} embedded image(s) ignored (raster images have no DXF geometry)")
    if svg.gradients:
        out.append(f"{svg.gradients} element(s) painted with a gradient or pattern: exported with color black")
    if svg.clipped:
        out.append(f"{svg.clipped} clip-path/mask reference(s) ignored: the unclipped shapes are exported")
    if not svg.items:
        out.append("no drawable geometry found in the SVG")
    return out


def output_transform(svg: SvgDrawing, opts: ConvertOptions, warnings: list[str]) -> Affine:
    """Map SVG px (y down) to output units (y up) with scale, fit and origin."""
    px = (25.4 if opts.units == "mm" else 1.0) / opts.dpi
    use_text = opts.text == "dxf"
    bounds = union_bounds(i.bounds() for i in svg.items if use_text or not isinstance(i.geometry, TextItem))
    s = px * opts.scale
    target = opts.fit_width if opts.fit_width is not None else opts.fit_height
    if target is not None:
        axis = 0 if opts.fit_width is not None else 1
        extent = (bounds[2 + axis] - bounds[axis]) if bounds else 0.0
        if extent > 0:
            s = float(target) / extent
        else:
            warnings.append("cannot fit an empty drawing; scale unchanged")
    origin, page = opts.origin, svg.page
    if origin != "bbox" and page is None:
        warnings.append("the SVG has no width/height or viewBox: origin placed at the drawing's bounding box")
        origin = "bbox"
    ref = bounds if origin == "bbox" else page
    if ref is None:
        ref = (0.0, 0.0, 0.0, 0.0)
    ox = (ref[0] + ref[2]) / 2 if origin == "center" else ref[0]
    oy = {"top-left": ref[1], "center": (ref[1] + ref[3]) / 2}.get(origin, ref[3])
    # x' = s*(x - ox), y' = s*(oy - y): scale, flip Y, origin to (0, 0)
    return SnapAffine(s, 0.0, 0.0, -s, -s * ox, s * oy)


def _layer_for(item: SvgItem, opts: ConvertOptions) -> tuple[str, RGB | None]:
    """(layer name, layer color) for the chosen --layers mode."""
    if opts.layers == "color":
        return color_layer_name(item.color), item.color
    if opts.layers == "group":
        return item.group or "0", None
    return "0", None


def convert(
    source: Source,
    output: str | os.PathLike[str] | None = None,
    *,
    options: ConvertOptions | None = None,
    laser: bool = False,
    **kwargs: Any,
) -> ConversionResult:
    """Convert an SVG to DXF.

    ``source`` is a path, raw SVG bytes or a binary file object; ``output`` is
    the DXF path (``None``: build the document without saving it). Settings come
    from ``options`` and/or keyword arguments named like :class:`ConvertOptions`
    fields, e.g. ``convert("in.svg", "out.dxf", units="mm", curves="polyline")``.
    ``laser=True`` applies the ``--laser`` preset (R12, polylines, join, mm).
    """
    if options is None:
        opts = ConvertOptions.create(laser=laser, **kwargs)
    else:
        changes = {**(LASER_PRESET if laser else {}), **kwargs}
        opts = replace(options, **changes) if changes else options
    data, name = _read_source(source)
    try:
        svg = read_svg(data, dpi=opts.dpi, include_hidden=opts.include_hidden)
    except Exception as exc:  # malformed XML, unsupported content
        raise ConversionError(f"cannot read SVG: {exc}") from exc

    warnings = _reader_warnings(svg, opts)
    to_out = output_transform(svg, opts, warnings)
    builder = DxfBuilder(
        opts.dxf_version, opts.units, opts.curves, opts.flatten_tolerance, entity_colors=opts.layers != "color"
    )
    outlines: dict[tuple[str, RGB | None], list[Subpath | FullEllipse]] = {}
    for item in svg.items:
        layer_name, layer_rgb = _layer_for(item, opts)
        layer = builder.layer(layer_name, layer_rgb)
        geom = item.geometry
        if isinstance(geom, TextItem):
            if opts.text == "dxf":
                builder.add_text(geom.transformed(to_out), layer, item.fill or item.stroke)
            continue
        shapes = (
            [geom.transformed(to_out)] if isinstance(geom, FullEllipse) else [sp.transformed(to_out) for sp in geom]
        )
        if opts.fill_as_hatch and item.fill is not None and item.tag != "line":
            builder.add_hatch(shapes, layer, item.fill)
        outlines.setdefault((layer, item.color), []).extend(shapes)

    for (layer, rgb), shapes in outlines.items():
        if opts.join:
            subpaths = [s for s in shapes if isinstance(s, Subpath)]
            shapes = [s for s in shapes if isinstance(s, FullEllipse)]
            shapes += join_subpaths(subpaths, opts.flatten_tolerance)
        for shape in shapes:
            builder.add_outline(shape, layer, rgb)

    doc = builder.doc
    geometry = [e for e in doc.modelspace() if e.dxftype() not in ("TEXT", "HATCH")]
    box = ezdxf.bbox.extents(geometry) if geometry else None
    extents = (box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y) if box and box.has_data else None
    result = ConversionResult(
        doc=doc,
        options=opts,
        source=name,
        layers=builder.layers,
        extents=extents,
        changes=builder.notes(),
        warnings=warnings,
    )
    if output is not None:
        path = Path(output)
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(path)
        result.output = path
    return result
