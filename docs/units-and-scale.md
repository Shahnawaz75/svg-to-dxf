---
title: Units and scale - getting the real size when converting SVG to DXF
description: How SVG width, height, viewBox, px and DPI turn into millimetres or inches in DXF, and how to fix a DXF that comes out 3.78x, 1.33x or 25.4x the wrong size.
---

# Units and scale

A DXF that comes out the wrong size is the most common SVG-to-DXF problem. This page explains where the size of an SVG comes from and what `svg-to-dxf` does with it.

## Where an SVG's size comes from

An SVG has two coordinate systems:

1. **User units**: the numbers inside the drawing (`x="10"`, path data, `r="5"`). They have no unit of their own.
2. **The viewport**: the root `<svg>` element's `width` and `height`, which may carry a real unit.

The `viewBox` connects them. With

```xml
<svg width="100mm" height="50mm" viewBox="0 0 1000 500">
```

1000 user units span 100 mm, so one user unit is 0.1 mm, and a `<rect width="1000" height="500">` is exactly 100 x 50 mm. svg-to-dxf reproduces that exactly: the test suite checks this very file down to 1e-9 mm.

If the `viewBox` has a different aspect ratio than `width`/`height`, the SVG rules (`preserveAspectRatio`, default "xMidYMid meet") center and scale the content; svg-to-dxf applies the same rule.

## Physical units

`mm`, `cm`, `in`, `pt` (1/72 in) and `pc` (1/6 in) are absolute. A root element with `width="4in"` is 101.6 mm wide whatever DPI you choose. Lengths with units inside the drawing (for example `r="10mm"` in a document without a `viewBox`) are converted the same way.

## px, unitless sizes and --dpi

A size without a unit, or in `px`, is in CSS pixels, and the number of pixels per inch is a convention of the program that wrote the file:

| Written by | Pixels per inch | Option |
| --- | --- | --- |
| Inkscape 0.92 and newer, browsers, CSS | 96 | default |
| Inkscape 0.91 and older | 90 | `--dpi 90` |
| Files where 1 px = 1 pt, common in Illustrator exports | 72 | `--dpi 72` |

So `<svg width="400" height="200">` is 105.833 x 52.917 mm at 96 DPI but 141.111 x 70.556 mm at 72 DPI. If you are not sure, convert with `--report` and compare the printed size with a dimension you know.

An SVG with only a `viewBox` (no `width`/`height`, typical for icons) is treated as user units = px, like Inkscape does: `viewBox="0 0 24 24"` becomes 24 px = 6.35 mm at 96 DPI.

## Output units

`--units mm` (default) or `--units in` sets the unit of every coordinate in the DXF and the `$INSUNITS` header variable (4 = millimetres, 1 = inches) that CAD programs use to scale the drawing on import. DXF R12 has no `$INSUNITS`; with R12 you must tell the importing program which unit the file uses.

## Scaling on purpose

- `--scale 2` makes everything twice as large (after units and DPI are applied).
- `--fit-width 200mm` scales the drawing so its bounding box is exactly 200 mm wide; `--fit-height 3in` does the same for the height. Values without a unit are in the output units.

## Origin and Y axis

SVG's Y axis points down; DXF's points up. svg-to-dxf flips Y so the drawing appears upright, and `--origin` decides which point becomes DXF (0, 0):

| `--origin` | (0, 0) is |
| --- | --- |
| `bottom-left` (default) | the bottom-left corner of the viewBox (the page) |
| `top-left` | the top-left corner of the page; the drawing lies at negative Y |
| `center` | the center of the page |
| `bbox` | the bottom-left corner of the drawing's own bounding box |

If the SVG has no `width`/`height` and no `viewBox`, there is no page, and the bounding box is used.

## Diagnosing a wrong size

Compare the size you expected with the size you got:

| Off by about | Likely cause | Fix |
| --- | --- | --- |
| 3.78x (96 / 25.4) | px values read as mm, or mm as px | check the SVG root units, `--report` |
| 1.333x (96 / 72) | the file uses 72 px per inch | `--dpi 72` |
| 1.067x (96 / 90) | file from Inkscape 0.91 or older | `--dpi 90` |
| 25.4x | the importing program assumed inches instead of mm (or the reverse) | set the import unit, or use R2000+ so `$INSUNITS` is stored |
| any other factor | a `viewBox` that does not match the artwork, or a scale in a parent group | `--fit-width` with the size you need |

`svg-to-dxf design.svg --report` prints the final size in both mm and inches, so you can catch these before the file reaches a machine.
