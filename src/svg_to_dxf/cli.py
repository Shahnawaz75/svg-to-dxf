"""Command line interface: ``svg-to-dxf`` and ``python -m svg_to_dxf``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .converter import convert
from .options import CURVES, DXF_VERSIONS, LAYER_MODES, ORIGINS, TEXT_MODES, UNITS, ConvertOptions

EXIT_OK, EXIT_ERROR = 0, 2
SVG_SUFFIXES = (".svg", ".svgz")

EXAMPLES = """\
examples:
  svg-to-dxf logo.svg                          logo.dxf next to the SVG (mm, R2010, splines)
  svg-to-dxf panel.svg --laser --report        R12 polylines for laser software + size check
  svg-to-dxf icon.svg --fit-width 80mm -o icon.dxf
  svg-to-dxf old_illustrator.svg --dpi 72      unitless px at 72 per inch
  svg-to-dxf designs/ -o dxf/ --layers group   a folder, one DXF per SVG, Inkscape layers
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="svg-to-dxf",
        description="Convert SVG files to DXF with real-world size, exact curves and layers. Runs offline.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("inputs", nargs="+", metavar="INPUT", help="SVG/SVGZ file(s) or folder(s)")
    p.add_argument("-o", "--output", help="output .dxf file (one input) or output folder")
    p.add_argument("-r", "--recursive", action="store_true", help="also convert SVGs in subfolders")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    size = p.add_argument_group("size and position")
    size.add_argument("--units", choices=UNITS, help="output units (default mm); sets $INSUNITS")
    size.add_argument(
        "--dpi",
        type=float,
        default=96.0,
        help="pixels per inch for unitless/px SVGs: 96 Inkscape and "
        "browsers (default), 72 older Illustrator, 90 Inkscape 0.91 and older",
    )
    fit = size.add_mutually_exclusive_group()
    fit.add_argument("--scale", type=float, default=1.0, help="extra scale factor (default 1)")
    fit.add_argument("--fit-width", metavar="LENGTH", help="scale the drawing to this width, e.g. 200mm or 8in")
    fit.add_argument("--fit-height", metavar="LENGTH", help="scale the drawing to this height")
    size.add_argument(
        "--origin",
        choices=ORIGINS,
        default="bottom-left",
        help="what lands on DXF (0,0): a page corner/center or the drawing's bounding box",
    )

    curves = p.add_argument_group("curves")
    curves.add_argument("--curves", choices=CURVES, help="spline: exact SPLINE entities (default); polyline: flatten")
    curves.add_argument(
        "--tolerance", type=float, help="max deviation of flattened curves, in output units (default 0.05 mm)"
    )
    curves.add_argument(
        "--join",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="merge open paths whose ends touch (within --tolerance) into one polyline",
    )

    content = p.add_argument_group("layers and content")
    content.add_argument(
        "--layers",
        choices=LAYER_MODES,
        default="color",
        help="color: one layer per stroke color (default); group: Inkscape layers / <g> labels; none: layer 0",
    )
    content.add_argument("--fill-as-hatch", action="store_true", help="export filled shapes as solid HATCH too")
    content.add_argument("--include-hidden", action="store_true", help="export hidden and unpainted elements")
    content.add_argument("--text", choices=TEXT_MODES, default="skip", help="skip (default, with a warning) or dxf")

    out = p.add_argument_group("output")
    out.add_argument("--dxf-version", type=str.upper, choices=list(DXF_VERSIONS), help="default R2010")
    out.add_argument("--laser", action="store_true", help="laser preset: R12 + polylines + --join + mm")
    out.add_argument("--report", action="store_true", help="print size, extents and entities per layer")
    out.add_argument("-q", "--quiet", action="store_true", help="print errors only")
    return p


def _options(args: argparse.Namespace) -> ConvertOptions:
    return ConvertOptions.create(
        laser=args.laser,
        units=args.units,
        dpi=args.dpi,
        scale=args.scale,
        fit_width=args.fit_width,
        fit_height=args.fit_height,
        origin=args.origin,
        curves=args.curves,
        tolerance=args.tolerance,
        join=args.join,
        layers=args.layers,
        fill_as_hatch=args.fill_as_hatch,
        include_hidden=args.include_hidden,
        text=args.text,
        dxf_version=args.dxf_version,
    )


def _find_svgs(folder: Path, recursive: bool) -> list[Path]:
    pattern = folder.rglob("*") if recursive else folder.glob("*")
    return sorted(p for p in pattern if p.is_file() and p.suffix.lower() in SVG_SUFFIXES)


def plan_jobs(inputs: Sequence[str], output: str | None, recursive: bool = False) -> list[tuple[Path, Path]]:
    """Pair every input SVG with its output DXF path."""
    sources: list[tuple[Path, Path]] = []  # (svg, path relative to the output folder)
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            found = _find_svgs(path, recursive)
            if not found:
                raise ValueError(f"no .svg files in folder {raw}")
            sources.extend((f, f.relative_to(path)) for f in found)
        elif path.is_file():
            sources.append((path, Path(path.name)))
        else:
            raise ValueError(f"input not found: {raw}")
    single = len(sources) == 1 and not Path(inputs[0]).is_dir()
    if output and output.lower().endswith(".dxf"):
        if not single:
            raise ValueError("-o must be a folder when converting several files")
        return [(sources[0][0], Path(output))]
    jobs = []
    for svg, rel in sources:
        target = (Path(output) / rel) if output else svg
        jobs.append((svg, target.with_suffix(".dxf")))
    return jobs


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI; returns the exit code (0 ok, 2 error)."""
    args = build_parser().parse_args(argv)
    try:
        options = _options(args)
        jobs = plan_jobs(args.inputs, args.output, args.recursive)
    except ValueError as exc:
        print(f"svg-to-dxf: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    failed = 0
    for svg, dxf in jobs:
        try:
            result = convert(svg, dxf, options=options)
        except Exception as exc:  # report and continue with the next file
            print(f"svg-to-dxf: error: {svg}: {exc}", file=sys.stderr)
            failed += 1
            continue
        if args.report:
            print(result.report())
        elif not args.quiet:
            print(result.summary())
            for note in result.changes:
                print(f"  changed: {note}")
            for warning in result.warnings:
                print(f"  warning: {warning}", file=sys.stderr)
    return EXIT_ERROR if failed else EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
