"""Regenerate the example DXF files from the example SVGs.

    python examples/make_examples.py

Prints the same report as ``svg-to-dxf --report`` for every file.
"""

from pathlib import Path

import ezdxf

from svg_to_dxf import convert

HERE = Path(__file__).resolve().parent

JOBS = [
    # (svg, dxf, options)
    ("box-panel.svg", "box-panel.dxf", {}),  # defaults: mm, R2010, exact curves, layers by color
    ("box-panel.svg", "box-panel-laser.dxf", {"laser": True}),  # R12 + polylines + join
    ("logo.svg", "logo.dxf", {"fit_width": "80mm"}),  # unitless px logo scaled to 80 mm
]


def main() -> None:
    # Fixed timestamps and GUIDs: regenerating unchanged examples gives identical files.
    ezdxf.options.write_fixed_meta_data_for_testing = True
    for svg, dxf, options in JOBS:
        result = convert(HERE / svg, HERE / dxf, **options)
        result.source, result.output = svg, Path(dxf)  # short names in the report
        print(result.report(), end="\n\n")


if __name__ == "__main__":
    main()
