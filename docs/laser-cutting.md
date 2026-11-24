---
title: SVG to DXF for laser cutting - practical guide
description: Convert SVG to DXF for laser cutters with the right size in mm, cut and engrave colors as layers, R12 for older laser software, kerf notes and import tips for LightBurn, RDWorks and LaserGRBL.
---

# SVG to DXF for laser cutting

This guide covers the settings that matter when a DXF is going to a laser cutter.

## The short version

```bash
svg-to-dxf design.svg --laser --report
```

`--laser` writes DXF R12 (the oldest and most widely readable version), in millimetres, with curves as plain polylines and touching segments joined into continuous paths. `--report` prints the size so you can compare it with your design before you cut.

## Cut and engrave: use colors

Laser software usually assigns cut, score and engrave settings per layer, and layers usually come from colors. A common convention is red for cutting and blue for engraving or scoring, but any colors work as long as each operation has its own.

svg-to-dxf keeps that separation:

- by default every stroke color becomes its own DXF layer (`RED_FF0000`, `BLUE_0000FF`, ...) with the matching color;
- with `--layers group` your Inkscape layers (for example "Cut" and "Engrave") become DXF layers, and each entity keeps its color.

Line thickness is not a signal in DXF: there is no stroke width, so your laser software decides by layer or color. Strokes are exported as centerlines.

## Closed shapes

Cut paths should be closed so the software can tell inside from outside (for fills, offsets and cut order). Closed SVG paths become closed polylines, and `--join` (part of `--laser`) stitches open pieces whose ends touch within the tolerance (0.05 mm by default, `--tolerance` to change). The report shows how many entities are closed and open per layer; an engrave layer can be open, a cut layer usually should not be.

## Kerf

The beam removes a thin strip of material (the kerf), often in the range of a tenth to a few tenths of a millimetre depending on the machine, lens, material and settings. svg-to-dxf exports the geometry exactly as drawn and does not compensate for kerf. Compensate in your laser software (LightBurn, for example, has a kerf offset setting per layer) or in the design itself, and test with a small piece first. Tight-fitting parts such as finger joints are especially sensitive to kerf.

## Why R12 for older laser software

Newer DXF versions can contain entity types that simpler importers do not read, such as `SPLINE`, `ELLIPSE` or `LWPOLYLINE`. Some programs bundled with laser controllers only understand the old R12 dialect: lines, arcs, circles and `POLYLINE`. If a DXF opens empty, opens with missing curves, or is rejected, convert with `--laser` (or `--dxf-version R12`). svg-to-dxf prints every change it made for R12, for example how many curves were flattened.

R12 cannot store drawing units, so the importing program decides whether the numbers are millimetres or inches. svg-to-dxf writes millimetres with `--laser`; set your import unit to millimetres and check the size after import.

If your software reads modern DXF, the default R2010 output keeps curves exact as splines, which gives smoother cuts and smaller files.

## Import tips

### LightBurn

- Import with File > Import or by dragging the DXF onto the workspace.
- Compare the size in LightBurn's width and height fields with the size from `--report`. A factor of 25.4 means one side assumed inches.
- LightBurn assigns imported shapes to its layers by color, so keep cut and engrave in different colors (the default `--layers color` does this).
- If shapes import as open paths, convert with `--join` or use LightBurn's own tools to join and close paths.

### RDWorks (Ruida controllers)

- Import the DXF with File > Import.
- RDWorks organizes cut and engrave settings by color layers, so keep operations in separate colors.
- Older RDWorks versions are frequently reported to handle R12 files with polylines better than newer DXF features such as splines; start with `--laser`.

### LaserGRBL

LaserGRBL is built mainly around raster images, SVG import and G-code. If your version does not open DXF files, import the original SVG there instead and keep the DXF for CAD or CAM tools.

## Checklist before cutting

1. `svg-to-dxf design.svg --laser --report` and check the size.
2. Check that each operation (cut, engrave) is on its own layer and color.
3. Check that the cut layer shows closed shapes in the report.
4. Text: convert it to paths in your editor first (Inkscape: Path > Object to Path; Illustrator: Type > Create Outlines). svg-to-dxf warns when it skips text.
5. Run a small test cut to confirm kerf and power settings.
