"""Conversion options, the ``--laser`` preset and length parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Any

UNITS = ("mm", "in")
ORIGINS = ("bottom-left", "top-left", "center", "bbox")
CURVES = ("spline", "polyline")
LAYER_MODES = ("color", "group", "none")
TEXT_MODES = ("skip", "dxf")
DXF_VERSIONS = {"R12": "AC1009", "R2000": "AC1015", "R2010": "AC1024", "R2018": "AC1032"}
DEFAULT_TOLERANCE_MM = 0.05

#: ``--laser``: the safest settings for laser software (old DXF importers).
LASER_PRESET: dict[str, Any] = {"dxf_version": "R12", "curves": "polyline", "join": True, "units": "mm"}

_MM_PER_UNIT = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, '"': 25.4, "pt": 25.4 / 72, "pc": 25.4 / 6}
_LENGTH = re.compile(r'^\s*([+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(mm|cm|m|in|"|pt|pc|px)?\s*$')


def parse_length(value: str | float | int, units: str = "mm", dpi: float = 96.0) -> float:
    """Parse ``"200mm"``, ``"8in"``, ``"20cm"`` or a bare number into ``units``.

    A bare number is already in ``units``; ``px`` uses ``dpi``.
    """
    if isinstance(value, (int, float)):
        return float(value)
    match = _LENGTH.match(value)
    if not match:
        raise ValueError(f"invalid length {value!r} (examples: 200mm, 8in, 20cm)")
    number, unit = float(match.group(1)), match.group(2)
    if unit is None:
        return number
    mm = number * (25.4 / dpi if unit == "px" else _MM_PER_UNIT[unit])
    return mm if units == "mm" else mm / 25.4


def _choice(name: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(allowed)} (got {value!r})")


@dataclass(frozen=True)
class ConvertOptions:
    """All settings for one conversion. Lengths are in output ``units``."""

    units: str = "mm"
    dpi: float = 96.0
    scale: float = 1.0
    fit_width: float | str | None = None
    fit_height: float | str | None = None
    origin: str = "bottom-left"
    curves: str = "spline"
    tolerance: float | None = None
    join: bool = False
    layers: str = "color"
    fill_as_hatch: bool = False
    include_hidden: bool = False
    text: str = "skip"
    dxf_version: str = "R2010"

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "dxf_version", str(self.dxf_version).upper())
        _choice("units", self.units, UNITS)
        _choice("origin", self.origin, ORIGINS)
        _choice("curves", self.curves, CURVES)
        _choice("layers", self.layers, LAYER_MODES)
        _choice("text", self.text, TEXT_MODES)
        _choice("dxf_version", self.dxf_version, tuple(DXF_VERSIONS))
        if not self.dpi > 0:
            raise ValueError("dpi must be positive")
        if not self.scale > 0:
            raise ValueError("scale must be positive")
        if self.tolerance is not None and not self.tolerance > 0:
            raise ValueError("tolerance must be positive")
        if self.fit_width is not None and self.fit_height is not None:
            raise ValueError("use either fit_width or fit_height, not both")
        for name in ("fit_width", "fit_height"):
            raw = getattr(self, name)
            if raw is not None:
                value = parse_length(raw, self.units, self.dpi)
                if not value > 0:
                    raise ValueError(f"{name} must be positive")
                if self.scale != 1.0:
                    raise ValueError(f"use either scale or {name}, not both")
                set_(self, name, value)

    @property
    def flatten_tolerance(self) -> float:
        """Max deviation for flattened curves, in output units (default 0.05 mm)."""
        if self.tolerance is not None:
            return self.tolerance
        return DEFAULT_TOLERANCE_MM if self.units == "mm" else DEFAULT_TOLERANCE_MM / 25.4

    @property
    def dxf_code(self) -> str:
        return DXF_VERSIONS[self.dxf_version]

    @classmethod
    def create(cls, laser: bool = False, **kwargs: Any) -> ConvertOptions:
        """Build options; ``laser=True`` applies :data:`LASER_PRESET` first.

        Explicit keyword arguments always win over the preset.
        """
        known = {f.name for f in fields(cls)}
        unknown = set(kwargs) - known
        if unknown:
            raise TypeError(f"unknown option(s): {', '.join(sorted(unknown))}")
        values = dict(LASER_PRESET) if laser else {}
        values.update({k: v for k, v in kwargs.items() if v is not None})
        return cls(**values)
