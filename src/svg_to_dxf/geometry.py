"""Geometry kernel: affine maps, path segments, flattening, B-splines, joining.

The SVG reader produces segments in SVG document space (CSS px, y down) and the
converter maps them with an :class:`Affine` into DXF output space (mm or inch,
y up). Every segment type is affine-invariant, so that mapping is exact:
Bezier control points map to control points, and an elliptical arc is stored
as ``center + u*cos(t) + v*sin(t)``, which stays an exact arc under any affine
map, including skew and mirroring.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

Point = tuple[float, float]
Vertex = tuple[float, float, float]  # x, y, bulge
Bounds = tuple[float, float, float, float]  # xmin, ymin, xmax, ymax

TAU = 2.0 * math.pi
CIRCLE_REL_TOL = 1e-6  # relative tolerance for "these axes describe a circle"
ARC_SPAN = math.pi / 6  # arcs inside splines: cubic spans of <= 30 degrees
MAX_PIECES = 10_000  # flattening guard against absurdly small tolerances


def _add(p: Point, q: Point) -> Point:
    return (p[0] + q[0], p[1] + q[1])


def _sub(p: Point, q: Point) -> Point:
    return (p[0] - q[0], p[1] - q[1])


def _mul(p: Point, k: float) -> Point:
    return (p[0] * k, p[1] * k)


def dot(p: Point, q: Point) -> float:
    return p[0] * q[0] + p[1] * q[1]


def cross(p: Point, q: Point) -> float:
    return p[0] * q[1] - p[1] * q[0]


def dist(p: Point, q: Point) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _lerp(p: Point, q: Point, s: float) -> Point:
    return (p[0] + (q[0] - p[0]) * s, p[1] + (q[1] - p[1]) * s)


def _bounds_of(points: Iterable[Point]) -> Bounds:
    xs, ys = zip(*points)
    return (min(xs), min(ys), max(xs), max(ys))


def union_bounds(boxes: Iterable[Bounds | None]) -> Bounds | None:
    """Union of bounding boxes, ignoring ``None``; ``None`` if nothing is left."""
    result: Bounds | None = None
    for b in boxes:
        if b is None:
            continue
        if result is None:
            result = b
        else:
            result = (
                min(result[0], b[0]),
                min(result[1], b[1]),
                max(result[2], b[2]),
                max(result[3], b[3]),
            )
    return result


@dataclass(frozen=True)
class Affine:
    """2D affine map ``x' = a*x + c*y + e``, ``y' = b*x + d*y + f`` (SVG order)."""

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    @classmethod
    def from_svg(cls, matrix: object) -> Affine:
        """From any object with ``a``..``f`` attributes (an svgelements Matrix)."""
        return cls(*(float(getattr(matrix, k)) for k in "abcdef"))

    def apply(self, p: Point) -> Point:
        return (
            self.a * p[0] + self.c * p[1] + self.e,
            self.b * p[0] + self.d * p[1] + self.f,
        )

    def apply_vector(self, v: Point) -> Point:
        """Apply the linear part only (for directions and axis vectors)."""
        return (self.a * v[0] + self.c * v[1], self.b * v[0] + self.d * v[1])

    def __matmul__(self, other: Affine) -> Affine:
        """Composition: ``(self @ other).apply(p) == self.apply(other.apply(p))``."""
        return Affine(
            self.a * other.a + self.c * other.b,
            self.b * other.a + self.d * other.b,
            self.a * other.c + self.c * other.d,
            self.b * other.c + self.d * other.d,
            self.a * other.e + self.c * other.f + self.e,
            self.b * other.e + self.d * other.f + self.f,
        )

    def inverse(self) -> Affine:
        det = self.a * self.d - self.b * self.c
        if det == 0:
            raise ValueError("singular transform")
        a, b, c, d = self.d / det, -self.b / det, -self.c / det, self.a / det
        return Affine(a, b, c, d, -(a * self.e + c * self.f), -(b * self.e + d * self.f))

    @property
    def scale(self) -> float:
        """Mean scale factor, ``sqrt(|det|)`` (exact for similarity maps)."""
        return math.sqrt(abs(self.a * self.d - self.b * self.c))


@dataclass(frozen=True)
class SnapAffine(Affine):
    """An :class:`Affine` that rounds its results to ``digits`` decimals.

    Used for the final map into DXF units: unit round trips leave float noise
    such as ``14.999999999999998``; 1e-10 mm is far below any real tolerance.
    """

    digits: int = 10

    def apply(self, p: Point) -> Point:
        x, y = Affine.apply(self, p)
        return (round(x, self.digits) + 0.0, round(y, self.digits) + 0.0)  # +0.0 drops -0.0

    def apply_vector(self, v: Point) -> Point:
        x, y = Affine.apply_vector(self, v)
        return (round(x, self.digits) + 0.0, round(y, self.digits) + 0.0)


def is_circle_pair(u: Point, v: Point, rel: float = CIRCLE_REL_TOL) -> bool:
    """True if the conjugate semi-diameters ``u`` and ``v`` describe a circle."""
    uu, vv, uv = dot(u, u), dot(v, v), dot(u, v)
    size = max(uu, vv)
    return size > 0.0 and abs(uu - vv) <= rel * size and abs(uv) <= rel * size


def principal_axes(u: Point, v: Point) -> tuple[Point, Point, float]:
    """Principal axes of the ellipse ``u*cos(t) + v*sin(t)``.

    Returns ``(major, minor, t_star)`` such that
    ``u*cos(t) + v*sin(t) == major*cos(t - t_star) + minor*sin(t - t_star)``,
    with ``major`` perpendicular to ``minor`` and ``|minor| <= |major|``.
    """
    t = 0.5 * math.atan2(2.0 * dot(u, v), dot(u, u) - dot(v, v))
    major = _add(_mul(u, math.cos(t)), _mul(v, math.sin(t)))
    minor = _add(_mul(u, -math.sin(t)), _mul(v, math.cos(t)))
    if math.hypot(*minor) > math.hypot(*major):
        t += math.pi / 2.0
        major, minor = minor, _mul(major, -1.0)
    return major, minor, t


@dataclass(frozen=True)
class Line:
    """Straight segment."""

    start: Point
    end: Point

    def point(self, s: float) -> Point:
        return _lerp(self.start, self.end, s)

    def transformed(self, m: Affine) -> Line:
        return Line(m.apply(self.start), m.apply(self.end))

    def reversed(self) -> Line:
        return Line(self.end, self.start)

    def bounds(self) -> Bounds:
        return _bounds_of((self.start, self.end))


@dataclass(frozen=True)
class Bezier:
    """Quadratic (3 control points) or cubic (4 control points) Bezier curve."""

    points: tuple[Point, ...]

    @property
    def start(self) -> Point:
        return self.points[0]

    @property
    def end(self) -> Point:
        return self.points[-1]

    @property
    def degree(self) -> int:
        return len(self.points) - 1

    def point(self, s: float) -> Point:
        """Evaluate with de Casteljau's algorithm, ``s`` in [0, 1]."""
        pts = list(self.points)
        while len(pts) > 1:
            pts = [_lerp(p, q, s) for p, q in zip(pts, pts[1:])]
        return pts[0]

    def transformed(self, m: Affine) -> Bezier:
        return Bezier(tuple(m.apply(p) for p in self.points))

    def reversed(self) -> Bezier:
        return Bezier(self.points[::-1])

    def bounds(self) -> Bounds:
        pts = [self.start, self.end]
        n = self.degree
        deriv = [_mul(_sub(q, p), n) for p, q in zip(self.points, self.points[1:])]
        for axis in (0, 1):
            for t in _derivative_roots([d[axis] for d in deriv]):
                pts.append(self.point(t))
        return _bounds_of(pts)


def _derivative_roots(c: Sequence[float]) -> list[float]:
    """Roots in (0, 1) of a Bernstein polynomial of degree 0..2 (the derivative)."""
    if len(c) == 2:  # linear: c0 (1-t) + c1 t
        den = c[0] - c[1]
        return [c[0] / den] if den != 0 and 0 < c[0] / den < 1 else []
    if len(c) != 3:
        return []
    a = c[0] - 2 * c[1] + c[2]
    b = 2 * (c[1] - c[0])
    k = c[0]
    if abs(a) < 1e-12 * (abs(b) + abs(k) + 1e-300):
        roots = [-k / b] if b != 0 else []
    else:
        disc = b * b - 4 * a * k
        if disc < 0:
            return []
        sq = math.sqrt(disc)
        roots = [(-b + sq) / (2 * a), (-b - sq) / (2 * a)]
    return [t for t in roots if 0 < t < 1]


@dataclass(frozen=True)
class EllipticArc:
    """Arc ``P(t) = center + u*cos(t) + v*sin(t)`` for t from t0 to t0 + sweep.

    ``u`` and ``v`` are conjugate semi-diameters (the images of the SVG ``rx``
    and ``ry`` axes). ``start`` and ``end`` are stored so path joints stay exact.
    """

    center: Point
    u: Point
    v: Point
    t0: float
    sweep: float
    start: Point
    end: Point

    @classmethod
    def from_params(cls, center: Point, u: Point, v: Point, t0: float, sweep: float) -> EllipticArc:
        tmp = cls(center, u, v, t0, sweep, center, center)
        return cls(center, u, v, t0, sweep, tmp.point_at(t0), tmp.point_at(t0 + sweep))

    def point_at(self, t: float) -> Point:
        return (
            self.center[0] + self.u[0] * math.cos(t) + self.v[0] * math.sin(t),
            self.center[1] + self.u[1] * math.cos(t) + self.v[1] * math.sin(t),
        )

    def tangent_at(self, t: float) -> Point:
        return _add(_mul(self.u, -math.sin(t)), _mul(self.v, math.cos(t)))

    def point(self, s: float) -> Point:
        if s <= 0.0:
            return self.start
        if s >= 1.0:
            return self.end
        return self.point_at(self.t0 + s * self.sweep)

    def transformed(self, m: Affine) -> EllipticArc:
        return EllipticArc(
            m.apply(self.center),
            m.apply_vector(self.u),
            m.apply_vector(self.v),
            self.t0,
            self.sweep,
            m.apply(self.start),
            m.apply(self.end),
        )

    def reversed(self) -> EllipticArc:
        return EllipticArc(self.center, self.u, self.v, self.t0 + self.sweep, -self.sweep, self.end, self.start)

    @property
    def is_circular(self) -> bool:
        return is_circle_pair(self.u, self.v)

    @property
    def radius(self) -> float:
        return math.sqrt((dot(self.u, self.u) + dot(self.v, self.v)) / 2.0)

    @property
    def geometric_sweep(self) -> float:
        """Signed sweep angle in a y-up system: positive means counter-clockwise."""
        return self.sweep if cross(self.u, self.v) > 0 else -self.sweep

    @property
    def semi_major(self) -> float:
        return math.hypot(*principal_axes(self.u, self.v)[0])

    def to_beziers(self, max_span: float = ARC_SPAN) -> list[Bezier]:
        """Cubic Bezier approximation; spans of 30 deg have error < 4e-7 x radius."""
        n = max(1, math.ceil(abs(self.sweep) / max_span - 1e-9))
        h = self.sweep / n
        alpha = 4.0 / 3.0 * math.tan(h / 4.0)
        curves = []
        for i in range(n):
            ta, tb = self.t0 + i * h, self.t0 + (i + 1) * h
            p0 = self.start if i == 0 else self.point_at(ta)
            p3 = self.end if i == n - 1 else self.point_at(tb)
            p1 = _add(p0, _mul(self.tangent_at(ta), alpha))
            p2 = _sub(p3, _mul(self.tangent_at(tb), alpha))
            curves.append(Bezier((p0, p1, p2, p3)))
        return curves

    def bounds(self) -> Bounds:
        pts = [self.start, self.end]
        for axis in (0, 1):
            base = math.atan2(self.v[axis], self.u[axis])
            for t in (base, base + math.pi):
                offset = (t - self.t0) % TAU if self.sweep > 0 else (self.t0 - t) % TAU
                if offset <= abs(self.sweep):
                    pts.append(self.point_at(t))
        return _bounds_of(pts)


Segment = Line | Bezier | EllipticArc


@dataclass(frozen=True)
class FullEllipse:
    """Complete ellipse ``center + u*cos(t) + v*sin(t)``; a circle if u, v allow."""

    center: Point
    u: Point
    v: Point

    def transformed(self, m: Affine) -> FullEllipse:
        return FullEllipse(m.apply(self.center), m.apply_vector(self.u), m.apply_vector(self.v))

    @property
    def is_circle(self) -> bool:
        return is_circle_pair(self.u, self.v)

    @property
    def radius(self) -> float:
        return math.sqrt((dot(self.u, self.u) + dot(self.v, self.v)) / 2.0)

    def as_arc(self) -> EllipticArc:
        return EllipticArc.from_params(self.center, self.u, self.v, 0.0, TAU)

    def bounds(self) -> Bounds:
        rx = math.hypot(self.u[0], self.v[0])
        ry = math.hypot(self.u[1], self.v[1])
        cx, cy = self.center
        return (cx - rx, cy - ry, cx + rx, cy + ry)


@dataclass(frozen=True)
class Subpath:
    """Connected chain of segments; ``closed`` means it ends where it starts."""

    segments: tuple[Segment, ...]
    closed: bool = False

    @property
    def start(self) -> Point:
        return self.segments[0].start

    @property
    def end(self) -> Point:
        return self.segments[-1].end

    def transformed(self, m: Affine) -> Subpath:
        return Subpath(tuple(s.transformed(m) for s in self.segments), self.closed)

    def reversed(self) -> Subpath:
        return Subpath(tuple(s.reversed() for s in reversed(self.segments)), self.closed)

    def bounds(self) -> Bounds:
        result = union_bounds(s.bounds() for s in self.segments)
        assert result is not None
        return result


def bulge(arc: EllipticArc) -> float:
    """DXF bulge of a circular arc: ``tan(sweep / 4)``, positive = counter-clockwise."""
    return math.tan(arc.geometric_sweep / 4.0)


def _wang_pieces(points: Sequence[Point], tolerance: float) -> int:
    """Wang's formula: uniform pieces so a Bezier stays within ``tolerance``."""
    deg = len(points) - 1
    if deg < 2:
        return 1
    m = max(
        math.hypot(p[0] - 2 * q[0] + r[0], p[1] - 2 * q[1] + r[1]) for p, q, r in zip(points, points[1:], points[2:])
    )
    n = math.ceil(math.sqrt(deg * (deg - 1) / 8.0 * m / tolerance))
    return min(max(n, 1), MAX_PIECES)


def flatten_segment(seg: Segment, tolerance: float) -> list[Point]:
    """Polyline points from ``seg.start`` (included) to ``seg.end`` (excluded).

    The chords never deviate more than ``tolerance`` from the true curve: Wang's
    bound for Beziers, ``a*h^2/8 <= tolerance`` (a = semi-major axis) for arcs.
    """
    if isinstance(seg, Line):
        return [seg.start]
    if isinstance(seg, Bezier):
        n = _wang_pieces(seg.points, tolerance)
        return [seg.start] + [seg.point(i / n) for i in range(1, n)]
    step = math.sqrt(8.0 * tolerance / max(seg.semi_major, 1e-300))
    n = min(max(1, math.ceil(abs(seg.sweep) / step)), MAX_PIECES)
    return [seg.start] + [seg.point_at(seg.t0 + seg.sweep * i / n) for i in range(1, n)]


def subpath_vertices(sp: Subpath, tolerance: float) -> list[Vertex]:
    """Polyline vertices ``(x, y, bulge)``; circular arcs stay exact as bulges.

    For a closed subpath the closing edge is implied (use the polyline's closed
    flag); for an open one the end point is the last vertex.
    """
    verts: list[Vertex] = []
    for seg in sp.segments:
        if isinstance(seg, EllipticArc) and seg.is_circular:
            pieces = 1 if abs(seg.sweep) <= math.pi + 1e-9 else 2  # keep |bulge| <= 1
            b = math.tan(seg.geometric_sweep / pieces / 4.0)
            for k in range(pieces):
                p = seg.start if k == 0 else seg.point_at(seg.t0 + seg.sweep * k / pieces)
                verts.append((p[0], p[1], b))
        else:
            verts.extend((p[0], p[1], 0.0) for p in flatten_segment(seg, tolerance))
    if not sp.closed:
        verts.append((sp.end[0], sp.end[1], 0.0))
    return verts


def _elevate(points: Sequence[Point]) -> tuple[Point, ...]:
    """Raise the degree of a Bezier control polygon by one (exact)."""
    n = len(points)  # new degree
    out = [points[0]]
    for i in range(1, n):
        k = i / n
        out.append(_add(_mul(points[i - 1], k), _mul(points[i], 1.0 - k)))
    out.append(points[-1])
    return tuple(out)


def bspline_from_subpath(sp: Subpath) -> tuple[int, list[Point], list[float]]:
    """Clamped B-spline ``(degree, control_points, knots)`` equal to the subpath.

    Every segment becomes one Bezier span of the common degree (2 if there are
    only quadratics and lines, else 3); interior knots get multiplicity
    ``degree``, so each span is reproduced exactly and its control points are
    the Bezier control points. Lines and quadratics are degree-elevated (exact).
    Elliptical arcs become cubic spans (error < 4e-7 x radius).
    """
    spans: list[tuple[Point, ...]] = []
    for seg in sp.segments:
        if isinstance(seg, EllipticArc):
            spans.extend(b.points for b in seg.to_beziers())
        elif isinstance(seg, Bezier):
            spans.append(seg.points)
        else:
            spans.append((seg.start, seg.end))
    degree = max(2, max(len(s) - 1 for s in spans))
    ctrl: list[Point] = []
    for span in spans:
        while len(span) - 1 < degree:
            span = _elevate(span)
        ctrl.extend(span if not ctrl else span[1:])
    if sp.closed:
        ctrl[-1] = ctrl[0]
    n = len(spans)
    knots = [0.0] * (degree + 1)
    for i in range(1, n):
        knots.extend([float(i)] * degree)
    knots.extend([float(n)] * (degree + 1))
    return degree, ctrl, knots


def full_ellipse_of(sp: Subpath) -> FullEllipse | None:
    """Detect a closed subpath made only of arcs covering one whole ellipse."""
    segs = sp.segments
    if not sp.closed or not all(isinstance(s, EllipticArc) for s in segs):
        return None
    arcs: list[EllipticArc] = list(segs)  # type: ignore[arg-type]
    first = arcs[0]
    tol = CIRCLE_REL_TOL * first.radius
    if all(a.is_circular for a in arcs):
        same = all(dist(a.center, first.center) <= tol and abs(a.radius - first.radius) <= tol for a in arcs)
        sweeps = [a.geometric_sweep for a in arcs]
        if same and (all(s > 0 for s in sweeps) or all(s < 0 for s in sweeps)):
            if abs(abs(sum(sweeps)) - TAU) <= 1e-6:
                r = first.radius
                return FullEllipse(first.center, (r, 0.0), (0.0, r))
        return None
    for a in arcs:
        if dist(a.center, first.center) > tol or dist(a.u, first.u) > tol or dist(a.v, first.v) > tol:
            return None
        if a.sweep * first.sweep <= 0:
            return None
    if abs(abs(sum(a.sweep for a in arcs)) - TAU) <= 1e-6:
        return FullEllipse(first.center, first.u, first.v)
    return None


def join_subpaths(subpaths: Sequence[Subpath], tolerance: float) -> list[Subpath]:
    """Chain open subpaths whose end points meet within ``tolerance``.

    Pieces are reversed when needed; a chain whose two ends meet becomes
    closed. Closed subpaths pass through unchanged. Chains keep the order of
    their first piece.
    """
    tol = max(tolerance, 1e-12)
    pieces = [sp for sp in subpaths if not sp.closed]
    result: list[Subpath] = []

    def cell(p: Point) -> tuple[int, int]:
        return (math.floor(p[0] / tol), math.floor(p[1] / tol))

    grid: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for i, sp in enumerate(pieces):
        grid.setdefault(cell(sp.start), []).append((i, 0))
        grid.setdefault(cell(sp.end), []).append((i, 1))
    used = [False] * len(pieces)

    def take(p: Point) -> tuple[int, int] | None:
        """Claim the nearest unused piece end within ``tol`` of ``p``."""
        cx, cy = cell(p)
        best: tuple[float, int, int] | None = None
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for idx, which in grid.get((gx, gy), ()):
                    if used[idx]:
                        continue
                    d = dist(p, pieces[idx].start if which == 0 else pieces[idx].end)
                    if d <= tol and (best is None or d < best[0]):
                        best = (d, idx, which)
        if best is None:
            return None
        used[best[1]] = True
        return best[1], best[2]

    index = iter(range(len(pieces)))
    for sp in subpaths:
        if sp.closed:
            result.append(sp)
            continue
        i = next(index)
        if used[i]:
            continue
        used[i] = True
        chain: deque[Segment] = deque(sp.segments)
        while (hit := take(chain[-1].end)) is not None:
            piece = pieces[hit[0]] if hit[1] == 0 else pieces[hit[0]].reversed()
            chain.extend(piece.segments)
        while (hit := take(chain[0].start)) is not None:
            piece = pieces[hit[0]] if hit[1] == 1 else pieces[hit[0]].reversed()
            chain.extendleft(reversed(piece.segments))
        segs = tuple(chain)
        closes = dist(segs[0].start, segs[-1].end) <= tol
        closed = closes and not (len(segs) == 1 and isinstance(segs[0], Line))
        result.append(Subpath(segs, closed))
    return result
