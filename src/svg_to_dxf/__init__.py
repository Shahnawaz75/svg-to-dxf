"""svg-to-dxf: convert SVG to DXF with the right size, real curves and layers.

>>> from svg_to_dxf import convert
>>> result = convert("in.svg", "out.dxf", units="mm")  # doctest: +SKIP
>>> result.size  # doctest: +SKIP
(100.0, 50.0)
"""

__version__ = "0.1.0"

from .converter import ConversionError, ConversionResult, convert  # noqa: E402
from .options import LASER_PRESET, ConvertOptions, parse_length  # noqa: E402
from .writer import LayerStats  # noqa: E402

__all__ = [
    "ConversionError",
    "ConversionResult",
    "ConvertOptions",
    "LASER_PRESET",
    "LayerStats",
    "__version__",
    "convert",
    "parse_length",
]
