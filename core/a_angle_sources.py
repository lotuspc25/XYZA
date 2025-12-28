import math
from typing import Iterable, Sequence, Tuple

import numpy as np


def compute_a_from_2d_tangent(points_xyz: Sequence[Sequence[float]]) -> np.ndarray:
    pts = np.asarray(points_xyz, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] == 0:
        return np.zeros((0,), dtype=np.float64)
    if pts.shape[1] < 2:
        return np.zeros((pts.shape[0],), dtype=np.float64)
    xy = pts[:, :2]
    n = xy.shape[0]
    angles = np.zeros((n,), dtype=np.float64)
    for i in range(n):
        if n < 2:
            angles[i] = 0.0
            continue
        if i == 0:
            v = xy[1] - xy[0]
        elif i == n - 1:
            v = xy[-1] - xy[-2]
        else:
            v = xy[i + 1] - xy[i - 1]
        vx = float(v[0])
        vy = float(v[1])
        if abs(vx) < 1e-9 and abs(vy) < 1e-9:
            angles[i] = angles[i - 1] if i > 0 else 0.0
        else:
            ang = math.degrees(math.atan2(vy, vx))
            angles[i] = ((ang + 180.0) % 360.0) - 180.0
    return angles


def compute_a_from_mesh_normal(mesh, points_xyz: Sequence[Sequence[float]]) -> np.ndarray:
    if mesh is None:
        return compute_a_from_2d_tangent(points_xyz)
    return compute_a_from_2d_tangent(points_xyz)


def unwrap_angles_deg(angles_deg: Iterable[float]) -> np.ndarray:
    angles = np.asarray(list(angles_deg), dtype=np.float64)
    if angles.size == 0:
        return angles
    unwrapped = angles.copy()
    for i in range(1, len(unwrapped)):
        diff = unwrapped[i] - unwrapped[i - 1]
        if diff > 180.0:
            unwrapped[i:] -= 360.0
        elif diff < -180.0:
            unwrapped[i:] += 360.0
    return unwrapped


def smooth_angles_deg(angles_deg: Iterable[float], window: int) -> np.ndarray:
    angles = np.asarray(list(angles_deg), dtype=np.float64)
    if angles.size == 0:
        return angles
    window = int(window)
    if window <= 1:
        return angles.copy()
    pad = window // 2
    padded = np.pad(angles, (pad, pad), mode="edge")
    kernel = np.ones(window, dtype=np.float64) / float(window)
    return np.convolve(padded, kernel, mode="valid")


def compute_a_angles(mesh, points_xyz: Sequence[Sequence[float]], mode: str) -> Tuple[np.ndarray, dict]:
    meta = {}
    mode_norm = str(mode or "2d_tangent").strip().lower()
    if mode_norm not in ("2d_tangent", "mesh_normal", "hybrid"):
        meta["fallback"] = "2d_tangent"
        meta["invalid_mode"] = mode
        mode_norm = "2d_tangent"
    if mode_norm == "mesh_normal":
        if mesh is None:
            meta["fallback"] = "2d_tangent"
            meta["reason"] = "mesh_missing"
            angles = compute_a_from_2d_tangent(points_xyz)
        else:
            angles = compute_a_from_mesh_normal(mesh, points_xyz)
            meta["fallback"] = "2d_tangent"
            meta["reason"] = "mesh_normal_not_implemented"
    else:
        angles = compute_a_from_2d_tangent(points_xyz)
        if mode_norm == "hybrid":
            meta["mode"] = "hybrid"
    pts = np.asarray(points_xyz, dtype=np.float64)
    if pts.ndim != 2:
        pts = np.zeros((0, 2), dtype=np.float64)
    if angles.size != pts.shape[0]:
        meta["fallback"] = "2d_tangent"
        meta["reason"] = "length_mismatch"
        angles = compute_a_from_2d_tangent(points_xyz)
    return angles.astype(np.float32, copy=False), meta
