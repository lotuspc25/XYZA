import math
from typing import Dict, Tuple, List

import numpy as np


def _normalize_profile(name: str) -> str:
    n = (name or "").strip().lower().replace("-", "_").replace(" ", "")
    if n in ("scalpel", "scalpelpointed", "scalpel_pointed", "pointed"):
        return "scalpel_pointed"
    if n in ("scalpelrounded", "scalpel_rounded", "rounded"):
        return "scalpel_rounded"
    if n in ("rotarydisk", "rotary_disk", "disk", "rotary"):
        return "rotary_disk"
    return n or "scalpel_pointed"


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _normalize(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length <= 1e-8:
        return (0.0, 1.0, 0.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _add_tri(verts: List[Tuple[float, float, float]], norms: List[Tuple[float, float, float]], v0, v1, v2):
    n = _normalize(_cross(_sub(v1, v0), _sub(v2, v0)))
    verts.extend([v0, v1, v2])
    norms.extend([n, n, n])


def _add_quad(verts: List[Tuple[float, float, float]], norms: List[Tuple[float, float, float]], v0, v1, v2, v3):
    _add_tri(verts, norms, v0, v1, v2)
    _add_tri(verts, norms, v0, v2, v3)


def _map_uvy(u: float, v: float, y: float, axis: str) -> Tuple[float, float, float]:
    if axis == "y":
        return (v, y, u)
    return (u, y, v)


def _add_prism(
    verts: List[Tuple[float, float, float]],
    norms: List[Tuple[float, float, float]],
    width: float,
    thick0: float,
    thick1: float,
    y0: float,
    y1: float,
    axis: str,
):
    half_w = width * 0.5
    half_t0 = thick0 * 0.5
    half_t1 = thick1 * 0.5

    p0 = _map_uvy(-half_w, -half_t0, y0, axis)
    p1 = _map_uvy(half_w, -half_t0, y0, axis)
    p2 = _map_uvy(half_w, half_t0, y0, axis)
    p3 = _map_uvy(-half_w, half_t0, y0, axis)

    q0 = _map_uvy(-half_w, -half_t1, y1, axis)
    q1 = _map_uvy(half_w, -half_t1, y1, axis)
    q2 = _map_uvy(half_w, half_t1, y1, axis)
    q3 = _map_uvy(-half_w, half_t1, y1, axis)

    _add_quad(verts, norms, p0, p1, q1, q0)
    _add_quad(verts, norms, p1, p2, q2, q1)
    _add_quad(verts, norms, p2, p3, q3, q2)
    _add_quad(verts, norms, p3, p0, q0, q3)

    _add_quad(verts, norms, p3, p2, p1, p0)
    _add_quad(verts, norms, q0, q1, q2, q3)


def _add_cylinder(
    verts: List[Tuple[float, float, float]],
    norms: List[Tuple[float, float, float]],
    radius: float,
    length: float,
    axis: str,
    segments: int = 20,
):
    if radius <= 0.0 or length <= 0.0:
        return
    y0 = 0.0
    y1 = -length
    step = (2.0 * math.pi) / segments
    for i in range(segments):
        a0 = i * step
        a1 = (i + 1) * step
        u0 = radius * math.cos(a0)
        v0 = radius * math.sin(a0)
        u1 = radius * math.cos(a1)
        v1 = radius * math.sin(a1)
        p0 = _map_uvy(u0, v0, y0, axis)
        p1 = _map_uvy(u1, v1, y0, axis)
        p2 = _map_uvy(u1, v1, y1, axis)
        p3 = _map_uvy(u0, v0, y1, axis)
        _add_quad(verts, norms, p0, p1, p2, p3)

    center_top = _map_uvy(0.0, 0.0, y0, axis)
    center_bot = _map_uvy(0.0, 0.0, y1, axis)
    for i in range(segments):
        a0 = i * step
        a1 = (i + 1) * step
        u0 = radius * math.cos(a0)
        v0 = radius * math.sin(a0)
        u1 = radius * math.cos(a1)
        v1 = radius * math.sin(a1)
        p0 = _map_uvy(u0, v0, y0, axis)
        p1 = _map_uvy(u1, v1, y0, axis)
        _add_tri(verts, norms, center_top, p1, p0)
        q0 = _map_uvy(u0, v0, y1, axis)
        q1 = _map_uvy(u1, v1, y1, axis)
        _add_tri(verts, norms, center_bot, q0, q1)


def _add_disk(
    verts: List[Tuple[float, float, float]],
    norms: List[Tuple[float, float, float]],
    radius: float,
    thickness: float,
    axis: str,
    segments: int = 32,
):
    if radius <= 0.0 or thickness <= 0.0:
        return
    half_t = thickness * 0.5
    step = (2.0 * math.pi) / segments
    for i in range(segments):
        a0 = i * step
        a1 = (i + 1) * step
        u0 = radius * math.cos(a0)
        y0 = radius * math.sin(a0)
        u1 = radius * math.cos(a1)
        y1 = radius * math.sin(a1)

        p0 = _map_uvy(u0, -half_t, y0, axis)
        p1 = _map_uvy(u1, -half_t, y1, axis)
        p2 = _map_uvy(u1, half_t, y1, axis)
        p3 = _map_uvy(u0, half_t, y0, axis)
        _add_quad(verts, norms, p0, p1, p2, p3)

        center_front = _map_uvy(0.0, -half_t, 0.0, axis)
        center_back = _map_uvy(0.0, half_t, 0.0, axis)
        f0 = _map_uvy(u0, -half_t, y0, axis)
        f1 = _map_uvy(u1, -half_t, y1, axis)
        b0 = _map_uvy(u0, half_t, y0, axis)
        b1 = _map_uvy(u1, half_t, y1, axis)
        _add_tri(verts, norms, center_front, f1, f0)
        _add_tri(verts, norms, center_back, b0, b1)


def build_knife_mesh(profile_name: str, params: Dict[str, float]) -> Dict[str, object]:
    profile = _normalize_profile(profile_name)
    axis = params.get("direction_axis", "x")
    axis = axis if axis in ("x", "y") else "x"

    length = float(params.get("blade_length_mm", 30.0))
    cut_len = float(params.get("cut_length_mm", 10.0))
    blade_thick = float(params.get("blade_thickness_mm", 1.0))
    edge_thick = float(params.get("cutting_edge_diam_mm", params.get("tip_diameter_mm", 0.2)))
    body_diam = float(params.get("body_diam_mm", params.get("body_diameter_mm", 6.0)))
    disk_thick = float(params.get("disk_thickness_mm", 2.0))

    length = max(length, 0.1)
    cut_len = max(min(cut_len, length), 0.0)
    body_len = max(length - cut_len, 0.0)
    blade_width = max(body_diam * 0.7, edge_thick)
    blade_thick = max(blade_thick, 0.05)
    edge_thick = max(edge_thick, 0.02)
    body_radius = max(body_diam * 0.5, blade_width * 0.5)

    body_verts: List[Tuple[float, float, float]] = []
    body_norms: List[Tuple[float, float, float]] = []
    blade_verts: List[Tuple[float, float, float]] = []
    blade_norms: List[Tuple[float, float, float]] = []
    kerf_verts: List[Tuple[float, float, float]] = []
    kerf_norms: List[Tuple[float, float, float]] = []

    if profile == "rotary_disk":
        radius = max(length * 0.5, 0.1)
        _add_disk(blade_verts, blade_norms, radius, max(disk_thick, 0.1), axis)
        tip = _map_uvy(0.0, 0.0, -radius, axis)
        return {
            "body": (np.array(body_verts, dtype=np.float32), np.array(body_norms, dtype=np.float32)),
            "blade": (np.array(blade_verts, dtype=np.float32), np.array(blade_norms, dtype=np.float32)),
            "kerf": (np.array(kerf_verts, dtype=np.float32), np.array(kerf_norms, dtype=np.float32)),
            "tip": tip,
            "length": radius * 2.0,
        }

    if body_len > 0.0:
        _add_cylinder(body_verts, body_norms, body_radius, body_len, "x", segments=20)

    if body_len > 0.0:
        _add_prism(blade_verts, blade_norms, blade_width, blade_thick, blade_thick, 0.0, -body_len, axis)
    if cut_len > 0.0:
        _add_prism(blade_verts, blade_norms, blade_width, blade_thick, edge_thick, -body_len, -length, axis)

    kerf_offset = blade_thick * 0.5
    kerf_width = blade_width
    if cut_len > 0.0:
        y0 = -body_len
        y1 = -length
    else:
        y0 = 0.0
        y1 = -body_len
    if abs(y1 - y0) > 1e-6:
        for sign in (-1.0, 1.0):
            v = sign * kerf_offset
            a = _map_uvy(-kerf_width * 0.5, v, y0, axis)
            b = _map_uvy(kerf_width * 0.5, v, y0, axis)
            c = _map_uvy(kerf_width * 0.5, v, y1, axis)
            d = _map_uvy(-kerf_width * 0.5, v, y1, axis)
            _add_quad(kerf_verts, kerf_norms, a, b, c, d)

    tip = _map_uvy(0.0, 0.0, -length, axis)
    return {
        "body": (np.array(body_verts, dtype=np.float32), np.array(body_norms, dtype=np.float32)),
        "blade": (np.array(blade_verts, dtype=np.float32), np.array(blade_norms, dtype=np.float32)),
        "kerf": (np.array(kerf_verts, dtype=np.float32), np.array(kerf_norms, dtype=np.float32)),
        "tip": tip,
        "length": length,
    }
