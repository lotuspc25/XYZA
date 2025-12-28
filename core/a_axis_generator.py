import logging
import math
import time
from typing import Iterable, List, Optional, Sequence, Tuple

from project_state import ToolpathPoint
from core.knife_orientation import axis_from_direction

logger = logging.getLogger(__name__)


def _extract_xy(points: Iterable[ToolpathPoint]) -> List[Tuple[float, float]]:
    return [(float(p.x), float(p.y)) for p in points]


def _angle_delta_deg(a0: float, a1: float) -> float:
    return (a1 - a0 + 180.0) % 360.0 - 180.0


def _unwrap_deg(angles_deg: Sequence[float]) -> List[float]:
    if not angles_deg:
        return []
    unwrapped = [float(angles_deg[0])]
    for ang in angles_deg[1:]:
        prev = unwrapped[-1]
        delta = _angle_delta_deg(prev, float(ang))
        unwrapped.append(prev + delta)
    return unwrapped


def _circular_smooth_deg(angles_deg: Sequence[float], window: int) -> List[float]:
    if not angles_deg:
        return []
    window = int(window)
    if window <= 1:
        return [float(a) for a in angles_deg]
    half = window // 2
    out: List[float] = []
    for i in range(len(angles_deg)):
        start = max(0, i - half)
        end = min(len(angles_deg), i + half + 1)
        sin_sum = 0.0
        cos_sum = 0.0
        count = 0
        for j in range(start, end):
            ang = math.radians(float(angles_deg[j]))
            sin_sum += math.sin(ang)
            cos_sum += math.cos(ang)
            count += 1
        if count <= 0:
            out.append(float(angles_deg[i]))
        else:
            out.append(math.degrees(math.atan2(sin_sum / count, cos_sum / count)))
    return out


def _compute_segment_angles_deg(points_xy: Sequence[Tuple[float, float]]) -> List[float]:
    if len(points_xy) < 2:
        return []
    angles: List[float] = []
    for i in range(len(points_xy) - 1):
        x0, y0 = points_xy[i]
        x1, y1 = points_xy[i + 1]
        dx = x1 - x0
        dy = y1 - y0
        angles.append(math.degrees(math.atan2(dy, dx)))
    return angles


def _detect_corners(angles_seg_deg: Sequence[float], threshold_deg: float) -> List[int]:
    if len(angles_seg_deg) < 2:
        return []
    threshold = float(threshold_deg)
    if threshold <= 0.0:
        return []
    corners: List[int] = []
    for i in range(1, len(angles_seg_deg)):
        delta = abs(_angle_delta_deg(float(angles_seg_deg[i - 1]), float(angles_seg_deg[i])))
        if delta >= threshold:
            corners.append(i)
    return corners


def _apply_mount_offset_deg(direction: str, reverse: bool, extra_offset_deg: float) -> float:
    axis = axis_from_direction(direction)
    offset = 0.0
    if axis == "y":
        offset += 90.0
    if reverse:
        offset += 180.0
    offset += float(extra_offset_deg)
    return offset


def generate_a_overlay(
    points: Sequence[ToolpathPoint],
    smooth_window: int = 5,
    corner_threshold_deg: float = 25.0,
    pivot_enable: bool = False,
    pivot_steps: int = 6,
    knife_direction: str = "X_parallel",
    a_reverse: bool = False,
    a_offset_deg: float = 0.0,
) -> Tuple[List[ToolpathPoint], dict]:
    """
    Generate A overlay from XY tangent only. Returns new ToolpathPoint list + meta.
    """
    t0 = time.perf_counter()
    points_list = list(points)
    points_xy = _extract_xy(points_list)
    if len(points_xy) < 2:
        return list(points_list), {"angles_deg": [], "corners": []}

    angles_seg_raw = _compute_segment_angles_deg(points_xy)
    angles_seg_smoothed = _circular_smooth_deg(angles_seg_raw, smooth_window)
    angles_seg_unwrapped = _unwrap_deg(angles_seg_smoothed)
    angles_point = angles_seg_unwrapped + [angles_seg_unwrapped[-1]]

    mount_offset = _apply_mount_offset_deg(knife_direction, a_reverse, a_offset_deg)
    angles_point = [a + mount_offset for a in angles_point]

    corner_indices = _detect_corners(angles_seg_raw, corner_threshold_deg)
    new_points: List[ToolpathPoint] = []
    new_angles: List[float] = []

    prev_angle = angles_point[0]
    for i, pt in enumerate(points_list):
        cur_angle = angles_point[i]
        if pivot_enable and i in corner_indices:
            diff = cur_angle - prev_angle
            if abs(diff) > 1e-6 and pivot_steps > 0:
                for step in range(1, int(pivot_steps) + 1):
                    t = step / float(int(pivot_steps) + 1)
                    ang = prev_angle + diff * t
                    new_points.append(ToolpathPoint(pt.x, pt.y, pt.z, ang))
                    new_angles.append(ang)
        new_points.append(ToolpathPoint(pt.x, pt.y, pt.z, cur_angle))
        new_angles.append(cur_angle)
        prev_angle = cur_angle

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if len(points_list) >= 10000:
        logger.info("A generation benchmark: n=%d time_ms=%.2f", len(points_list), elapsed_ms)

    meta = {
        "angles_deg": new_angles,
        "corners": corner_indices,
        "smooth_window": int(smooth_window),
        "corner_threshold_deg": float(corner_threshold_deg),
        "pivot_enable": bool(pivot_enable),
        "pivot_steps": int(pivot_steps),
        "mount_offset_deg": float(mount_offset),
        "point_count": len(new_points),
        "min_a_deg": float(min(new_angles)) if new_angles else 0.0,
        "max_a_deg": float(max(new_angles)) if new_angles else 0.0,
        "elapsed_ms": float(elapsed_ms),
    }
    return new_points, meta


def _is_number(val) -> bool:
    try:
        return math.isfinite(float(val))
    except Exception:
        return False


def _extract_a_path(a_path2d) -> Tuple[List[Tuple[float, float]], List[float]]:
    if not a_path2d:
        return [], []
    points_xy: List[Tuple[float, float]] = []
    angles: List[float] = []
    if isinstance(a_path2d, dict):
        raw_xy = a_path2d.get("points_xy") or []
        raw_ang = (
            a_path2d.get("angles_deg")
            or a_path2d.get("angles")
            or a_path2d.get("a")
            or []
        )
        for pt in raw_xy:
            try:
                points_xy.append((float(pt[0]), float(pt[1])))
            except Exception:
                continue
        for ang in raw_ang:
            if _is_number(ang):
                angles.append(float(ang))
        return points_xy, angles
    if isinstance(a_path2d, (list, tuple)):
        if (
            len(a_path2d) == 2
            and isinstance(a_path2d[0], (list, tuple))
            and isinstance(a_path2d[1], (list, tuple))
        ):
            for pt in a_path2d[0]:
                try:
                    points_xy.append((float(pt[0]), float(pt[1])))
                except Exception:
                    continue
            for ang in a_path2d[1]:
                if _is_number(ang):
                    angles.append(float(ang))
            return points_xy, angles
        for pt in a_path2d:
            try:
                if hasattr(pt, "x"):
                    x = float(pt.x)
                    y = float(pt.y)
                    a_val = getattr(pt, "a", None)
                else:
                    x = float(pt[0])
                    y = float(pt[1])
                    a_val = pt[2] if len(pt) > 2 else None
                if _is_number(a_val):
                    points_xy.append((x, y))
                    angles.append(float(a_val))
            except Exception:
                continue
    return points_xy, angles


def _extract_xy_from_points(points: Sequence) -> List[Tuple[float, float]]:
    points_xy: List[Tuple[float, float]] = []
    for pt in points:
        try:
            if hasattr(pt, "x"):
                x = float(pt.x)
                y = float(pt.y)
            elif isinstance(pt, dict):
                x = float(pt.get("x", 0.0))
                y = float(pt.get("y", 0.0))
            else:
                x = float(pt[0])
                y = float(pt[1])
            points_xy.append((x, y))
        except Exception:
            continue
    return points_xy


def _cumulative_lengths_xy(points_xy: Sequence[Tuple[float, float]]) -> List[float]:
    if not points_xy:
        return []
    s = [0.0]
    for i in range(1, len(points_xy)):
        x0, y0 = points_xy[i - 1]
        x1, y1 = points_xy[i]
        s.append(s[-1] + math.hypot(x1 - x0, y1 - y0))
    return s


def _interp_by_s(
    s_src: Sequence[float],
    v_src: Sequence[float],
    s_query: Sequence[float],
) -> List[float]:
    if not s_src or not v_src or not s_query:
        return []
    if len(s_src) != len(v_src):
        n = min(len(s_src), len(v_src))
        s_src = s_src[:n]
        v_src = v_src[:n]
    out: List[float] = []
    if not s_src:
        return out
    max_s = s_src[-1]
    idx = 0
    for s in s_query:
        if s <= s_src[0]:
            out.append(float(v_src[0]))
            continue
        if s >= max_s:
            out.append(float(v_src[-1]))
            continue
        while idx < len(s_src) - 2 and s_src[idx + 1] < s:
            idx += 1
        s0 = s_src[idx]
        s1 = s_src[idx + 1]
        v0 = v_src[idx]
        v1 = v_src[idx + 1]
        if abs(s1 - s0) < 1e-9:
            out.append(float(v0))
        else:
            t = (s - s0) / (s1 - s0)
            out.append(float(v0 + (v1 - v0) * t))
    return out


def _clone_point_with_a(pt, a_val: Optional[float]):
    try:
        if isinstance(pt, ToolpathPoint):
            out = ToolpathPoint(pt.x, pt.y, pt.z, a_val)
            setattr(out, "a_cont", a_val)
            return out
        if hasattr(pt, "x") and hasattr(pt, "y") and hasattr(pt, "z"):
            out = ToolpathPoint(float(pt.x), float(pt.y), float(pt.z), a_val)
            setattr(out, "a_cont", a_val)
            return out
        if isinstance(pt, dict):
            clone = dict(pt)
            clone["a"] = a_val
            clone.setdefault("a_cont", a_val)
            return clone
        x, y, z = float(pt[0]), float(pt[1]), float(pt[2])
        return (x, y, z, a_val)
    except Exception:
        return pt


def attach_a_to_3d_points(
    points3d: Sequence,
    a_path2d,
    method: str = "arc_length",
    return_meta: bool = False,
):
    """
    Attach A values from 2D path to 3D points using arc-length mapping.
    """
    pts3d = list(points3d or [])
    points_xy, angles = _extract_a_path(a_path2d)
    meta = {
        "ok": False,
        "method": method,
        "n3d": len(pts3d),
        "n2d": len(points_xy),
    }
    if not pts3d or not points_xy or not angles:
        return (pts3d, meta) if return_meta else pts3d
    if method not in ("arc_length", "arc-length"):
        meta["error"] = f"Unsupported method: {method}"
        return (pts3d, meta) if return_meta else pts3d
    n2d = min(len(points_xy), len(angles))
    points_xy = points_xy[:n2d]
    angles = angles[:n2d]

    s2d = _cumulative_lengths_xy(points_xy)
    s3d = _cumulative_lengths_xy(_extract_xy_from_points(pts3d))
    mapped_a = _interp_by_s(s2d, angles, s3d)
    out = [_clone_point_with_a(p, a) for p, a in zip(pts3d, mapped_a)]

    if mapped_a:
        meta.update(
            {
                "ok": True,
                "s2d_max": float(s2d[-1]) if s2d else 0.0,
                "s3d_max": float(s3d[-1]) if s3d else 0.0,
                "min_a": float(min(mapped_a)),
                "max_a": float(max(mapped_a)),
            }
        )
    return (out, meta) if return_meta else out
