"""Colors and layer names: ``RED_FF0000`` style names and the nearest ACI."""

from __future__ import annotations

import re

from ezdxf.colors import DXF_DEFAULT_COLORS

RGB = tuple[int, int, int]
BLACK: RGB = (0, 0, 0)

# Coarse, human-friendly names used as the layer-name prefix. The hex code in
# the layer name is always exact; the name is only a hint.
_NAMES: tuple[tuple[str, RGB], ...] = (
    ("BLACK", (0, 0, 0)),
    ("GRAY", (64, 64, 64)),
    ("GRAY", (128, 128, 128)),
    ("GRAY", (192, 192, 192)),
    ("WHITE", (255, 255, 255)),
    ("RED", (255, 0, 0)),
    ("RED", (139, 0, 0)),
    ("RED", (220, 20, 60)),
    ("ORANGE", (255, 140, 0)),
    ("ORANGE", (255, 165, 0)),
    ("YELLOW", (255, 255, 0)),
    ("YELLOW", (255, 215, 0)),
    ("OLIVE", (128, 128, 0)),
    ("GREEN", (0, 255, 0)),
    ("GREEN", (0, 128, 0)),
    ("GREEN", (46, 139, 87)),
    ("CYAN", (0, 255, 255)),
    ("TEAL", (0, 128, 128)),
    ("BLUE", (0, 0, 255)),
    ("BLUE", (0, 0, 139)),
    ("BLUE", (25, 25, 112)),
    ("BLUE", (30, 144, 255)),
    ("BLUE", (70, 130, 180)),
    ("BLUE", (100, 149, 237)),
    ("PURPLE", (128, 0, 128)),
    ("PURPLE", (148, 0, 211)),
    ("MAGENTA", (255, 0, 255)),
    ("PINK", (255, 182, 193)),
    ("BROWN", (139, 69, 19)),
    ("BROWN", (160, 82, 45)),
)


def _distance(c1: RGB, c2: RGB) -> float:
    """'Redmean' weighted RGB distance, a cheap perceptual approximation."""
    rmean = (c1[0] + c2[0]) / 2.0
    dr, dg, db = c1[0] - c2[0], c1[1] - c2[1], c1[2] - c2[2]
    return (2 + rmean / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rmean) / 256) * db * db


def color_name(rgb: RGB) -> str:
    """Nearest coarse color name, e.g. ``(230, 20, 30) -> 'RED'``."""
    return min(_NAMES, key=lambda item: _distance(rgb, item[1]))[0]


def color_layer_name(rgb: RGB) -> str:
    """Layer name for a stroke color, e.g. ``RED_FF0000``."""
    return f"{color_name(rgb)}_{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def nearest_aci(rgb: RGB) -> int:
    """Nearest AutoCAD Color Index (1..255) for an RGB color.

    Near-black and near-white map to ACI 7, which CAD programs draw black on a
    light background and white on a dark one.
    """
    if max(rgb) <= 40 or min(rgb) >= 235:
        return 7
    best, best_d = 7, float("inf")
    for aci in range(1, 256):
        value = DXF_DEFAULT_COLORS[aci]
        d = _distance(rgb, ((value >> 16) & 255, (value >> 8) & 255, value & 255))
        if d < best_d:
            best, best_d = aci, d
    return best


def is_exact_aci(rgb: RGB) -> bool:
    """True if the color survives as an ACI color without change."""
    if rgb in (BLACK, (255, 255, 255)):
        return True
    value = (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]
    return DXF_DEFAULT_COLORS[nearest_aci(rgb)] == value


_FORBIDDEN = re.compile(r'[<>/\\":;?*|=`,]')
_R12_FORBIDDEN = re.compile(r"[^A-Z0-9_$-]")


def sanitize_layer_name(name: str, r12: bool = False) -> str:
    """Make a layer name valid for DXF (R12 rules: 31 chars of A-Z 0-9 _ $ -)."""
    name = _FORBIDDEN.sub("_", name).strip()
    if r12:
        name = _R12_FORBIDDEN.sub("_", name.upper())[:31]
    else:
        name = name[:255]
    return name or "0"
