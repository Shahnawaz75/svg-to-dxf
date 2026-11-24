# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-24

First release.

### Added

- `svg-to-dxf` command (also `python -m svg_to_dxf`) and Python API `convert()`.
- Geometry: `path`, `rect` (including rounded corners), `circle`, `ellipse`, `line`,
  `polyline`, `polygon` and `use`, with every nested transform applied exactly.
- Exact entities: `CIRCLE`, `ARC` and polyline bulges, `ELLIPSE`, `LWPOLYLINE`, and
  Bezier curves as clamped B-spline `SPLINE`s whose control points are the Bezier points.
  Paths made of arcs that form a full circle or ellipse become `CIRCLE`/`ELLIPSE`.
- `--curves polyline --tolerance`: flattening with a guaranteed maximum deviation.
- Units and scale: root `width`/`height` units (mm, cm, in, pt, pc, px), `viewBox` and
  `preserveAspectRatio`, `--units mm|in` with `$INSUNITS`, `--dpi`, `--scale`,
  `--fit-width`/`--fit-height`, Y flip and `--origin`.
- Exact physical unit factors and a full-precision `viewBox` transform (works around
  rounding in svgelements 1.9).
- Layers: `--layers color` (named like `RED_FF0000`, true color and nearest ACI),
  `--layers group` (Inkscape layers, top-level groups), `--layers none`.
- `--fill-as-hatch`, `--include-hidden`, `--text skip|dxf`, `--join`.
- DXF versions R12, R2000, R2010 (default) and R2018; R12 uses `POLYLINE` and flattens
  splines and ellipses, and reports every change. `--laser` preset.
- `--report`: size, extents, entities per layer with closed/open counts, changes and
  warnings. Batch conversion of files and folders (`--recursive`). Exit codes 0 and 2.
- `.svgz` input.
- Examples (`examples/`), a screenshot script and a pytest suite that reads every
  output back with ezdxf and runs `audit()`.
