from typing import List, Sequence

import numpy as np


def compute_tangent_angles_deg(points_xy: np.ndarray) -> np.ndarray:
    pts = _ensure_xy(points_xy)
    if pts.shape[0] < 2:
        return np.zeros((0,), dtype=np.float64)
    diffs = np.diff(pts, axis=0)
    angles = np.degrees(np.arctan2(diffs[:, 1], diffs[:, 0]))
    if angles.size == 0:
        return angles.astype(np.float64)
    angles = np.concatenate([angles, angles[-1:]])
    return angles.astype(np.float64, copy=False)


def unwrap_deg(angles_deg: np.ndarray) -> np.ndarray:
    angles = np.asarray(angles_deg, dtype=np.float64).reshape(-1)
    if angles.size == 0:
        return angles
    return np.rad2deg(np.unwrap(np.deg2rad(angles)))


def rewrap_deg(angles_deg: np.ndarray, mode: str = "signed") -> np.ndarray:
    angles = np.asarray(angles_deg, dtype=np.float64).reshape(-1)
    if angles.size == 0:
        return angles
    if mode == "unsigned":
        return np.mod(angles, 360.0)
    return (angles + 180.0) % 360.0 - 180.0


def smooth_angles_deg(angles_unwrapped: np.ndarray, window: int) -> np.ndarray:
    angles = np.asarray(angles_unwrapped, dtype=np.float64).reshape(-1)
    if angles.size == 0:
        return angles
    window = int(window)
    if window <= 1:
        return angles.copy()
    pad = window // 2
    padded = np.pad(angles, (pad, pad), mode="edge")
    kernel = np.ones(window, dtype=np.float64) / float(window)
    smoothed = np.convolve(padded, kernel, mode="valid")
    return smoothed


def detect_corners(
    points_xy: np.ndarray, angles_deg: np.ndarray, threshold_deg: float
) -> List[int]:
    pts = _ensure_xy(points_xy)
    angles = np.asarray(angles_deg, dtype=np.float64).reshape(-1)
    if pts.shape[0] < 2 or angles.size < 2:
        return []
    threshold = float(threshold_deg)
    if threshold <= 0.0:
        return []
    diffs = np.abs(np.diff(angles))
    indices = np.where(diffs >= threshold)[0] + 1
    indices = indices[indices < pts.shape[0]]
    return indices.tolist()


def pack_result(
    points_xy: np.ndarray, angles_deg: np.ndarray, corners: Sequence[int]
) -> dict:
    pts = _ensure_xy(points_xy)
    angles = np.asarray(angles_deg, dtype=np.float64).reshape(-1)
    if pts.shape[0] > 0 and angles.size > 0:
        if angles.size == pts.shape[0] - 1:
            angles = np.concatenate([angles, angles[-1:]])
        elif angles.size > pts.shape[0]:
            angles = angles[: pts.shape[0]]
    return {
        "points_xy": pts.astype(np.float32, copy=False).tolist(),
        "angles_deg": angles.tolist(),
        "corners": list(corners or []),
    }


def _ensure_xy(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] < 2:
        return np.zeros((0, 2), dtype=np.float64)
    return pts[:, :2]
