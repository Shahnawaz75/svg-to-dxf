"""Shared helpers: build small SVGs with known answers and read the DXF back."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import ezdxf
import pytest
from ezdxf.document import Drawing

from svg_to_dxf import ConversionResult, convert

# 100 x 100 mm page where one user unit is exactly 1 mm (SVG y down, DXF y up)
PAGE = 'width="100mm" height="100mm" viewBox="0 0 100 100"'
NS = (
    'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'
)


def svg(body: str, attrs: str = PAGE) -> bytes:
    return f"<svg {NS} {attrs}>{body}</svg>".encode()


def entities(doc: Drawing, dxftype: str) -> list[Any]:
    return list(doc.modelspace().query(dxftype))


def xy(p: Any) -> tuple[float, float]:
    return (float(p[0]), float(p[1]))


def flat(points: Any) -> list[float]:
    """Flatten [(x, y), ...] so pytest.approx can compare it."""
    return [float(c) for p in points for c in p]


Run = Callable[..., tuple[Drawing, ConversionResult]]


@pytest.fixture
def run(tmp_path: Path) -> Run:
    """Convert SVG markup to a DXF file, read it back with ezdxf and audit it."""
    counter = itertools.count()

    def _run(body: str, attrs: str = PAGE, **options: Any) -> tuple[Drawing, ConversionResult]:
        path = tmp_path / f"out{next(counter)}.dxf"
        result = convert(svg(body, attrs), path, **options)
        doc = ezdxf.readfile(path)
        auditor = doc.audit()
        assert not auditor.has_errors, [str(e) for e in auditor.errors]
        return doc, result

    return _run
