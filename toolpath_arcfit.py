import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)


Point = Tuple[float, float, float, Optional[float]]


@dataclass
class LineSeg:
    p0: Point
    p1: Point


@dataclass
class ArcSeg:
    p0: Point
    p1: Point
    center_xy: Tuple[float, float]
    radius: float
    cw: bool
    z_mode: str  # "const" veya "interp"
    z0: float
    z1: float
    start_ang: float
    end_ang: float


@dataclass
class ToolpathSegments:
    segments: List[Union[LineSeg, ArcSeg]]
    stats: Dict[str, Union[int, float, Dict[str, int]]]


def _as_point(item) -> Optional[Point]:
    try:
        if hasattr(item, "x"):
            x = float(item.x)
        else:
            x = float(item[0])
        if hasattr(item, "y"):
            y = float(item.y)
        else:
            y = float(item[1])
        if hasattr(item, "z"):
            z = float(item.z)
        else:
            z = float(item[2])
        a_val = getattr(item, "a", None)
        if a_val is None:
            try:
                a_val = item[3]
            except Exception:
                a_val = None
        a_val = float(a_val) if a_val is not None else None
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            return None
        return (x, y, z, a_val)
    except Exception:
        return None


def _circle_from_three(p0: Point, p1: Point, p2: Point) -> Optional[Tuple[Tuple[float, float], float]]:
    x1, y1 = p0[0], p0[1]
    x2, y2 = p1[0], p1[1]
    x3, y3 = p2[0], p2[1]
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-9:
        return None
    ux = (
        ((x1 * x1 + y1 * y1) * (y2 - y3)
         + (x2 * x2 + y2 * y2) * (y3 - y1)
         + (x3 * x3 + y3 * y3) * (y1 - y2)) / d
    )
    uy = (
        ((x1 * x1 + y1 * y1) * (x3 - x2)
         + (x2 * x2 + y2 * y2) * (x1 - x3)
         + (x3 * x3 + y3 * y3) * (x2 - x1)) / d
    )
    r = math.hypot(x1 - ux, y1 - uy)
    return (ux, uy), r


def _radial_error(points: Sequence[Point], center: Tuple[float, float], radius: float) -> Tuple[float, float]:
    if radius < 1e-9:
        return float("inf"), float("inf")
    errs = []
    cx, cy = center
    for p in points:
        dist = math.hypot(p[0] - cx, p[1] - cy)
        errs.append(abs(dist - radius))
    if not errs:
        return 0.0, 0.0
    max_err = max(errs)
    rms = math.sqrt(sum(e * e for e in errs) / len(errs))
    return max_err, rms


def _angle(center: Tuple[float, float], pt: Point) -> float:
    return math.atan2(pt[1] - center[1], pt[0] - center[0])


def _angle_diff(a1: float, a2: float, cw: bool) -> float:
    if cw:
        diff = a1 - a2
        while diff < 0:
            diff += 2 * math.pi
    else:
        diff = a2 - a1
        while diff < 0:
            diff += 2 * math.pi
    return diff


def build_segments(points: Sequence, params: Optional[Dict[str, float]] = None) -> ToolpathSegments:
    """
    Nokta dizisini line/arc segmentlerine böler.
    - params: arc_max_dev_mm, arc_min_points, arc_min_len_mm, arc_z_eps_mm
    """
    defaults = {
        "arc_max_dev_mm": 0.03,
        "arc_min_points": 8,
        "arc_min_len_mm": 2.0,
        "arc_z_eps_mm": 0.005,
    }
    if params:
        defaults.update({k: v for k, v in params.items() if v is not None})
    max_dev = float(defaults["arc_max_dev_mm"])
    min_pts = int(defaults["arc_min_points"])
    min_len = float(defaults["arc_min_len_mm"])
    z_eps = float(defaults["arc_z_eps_mm"])

    cleaned: List[Point] = []
    for p in points or []:
        cp = _as_point(p)
        if cp is not None:
            cleaned.append(cp)
    if len(cleaned) < 2:
        return ToolpathSegments([], {"point_count": len(cleaned), "arcs": 0, "lines": 0, "fallback": {}})

    segs: List[Union[LineSeg, ArcSeg]] = []
    fallback: Dict[str, int] = {"dev": 0, "len": 0, "geom": 0}
    i = 0
    n = len(cleaned)

    while i < n - 1:
        # Arc denemesi
        if (n - i) >= min_pts:
            j = i + min_pts - 1
            p0 = cleaned[i]
            pmid = cleaned[(i + j) // 2]
            plast = cleaned[j]
            circle = _circle_from_three(p0, pmid, plast)
            if circle is None:
                fallback["geom"] += 1
            else:
                center, radius = circle
                max_err, _ = _radial_error(cleaned[i:j + 1], center, radius)
                chord = math.hypot(plast[0] - p0[0], plast[1] - p0[1])
                ang = _angle(center, pmid)
                cross = (pmid[0] - p0[0]) * (plast[1] - p0[1]) - (pmid[1] - p0[1]) * (plast[0] - p0[0])
                cw = cross < 0
                arc_ang = _angle_diff(_angle(center, p0), _angle(center, plast), cw)
                arc_len = arc_ang * radius
                if max_err <= max_dev and arc_len >= min_len and radius > 1e-6 and chord > 1e-6:
                    # Greedy uzatma
                    best_j = j
                    best_center = center
                    best_r = radius
                    k = j + 1
                    while k < n:
                        circle_k = _circle_from_three(p0, cleaned[(i + k) // 2], cleaned[k])
                        if circle_k is None:
                            fallback["geom"] += 1
                            break
                        center_k, r_k = circle_k
                        max_err_k, _ = _radial_error(cleaned[i:k + 1], center_k, r_k)
                        arc_ang_k = _angle_diff(_angle(center_k, p0), _angle(center_k, cleaned[k]), cw)
                        arc_len_k = arc_ang_k * r_k
                        if max_err_k <= max_dev and arc_len_k >= min_len:
                            best_j = k
                            best_center = center_k
                            best_r = r_k
                            k += 1
                        else:
                            break

                    p_start = cleaned[i]
                    p_end = cleaned[best_j]
                    z_vals = [p[2] for p in cleaned[i: best_j + 1]]
                    z_range = max(z_vals) - min(z_vals)
                    if z_range <= z_eps:
                        z_mode = "const"
                        z0 = z1 = sum(z_vals) / len(z_vals)
                    else:
                        z_mode = "interp"
                        z0 = p_start[2]
                        z1 = p_end[2]

                    arc_seg = ArcSeg(
                        p0=p_start,
                        p1=p_end,
                        center_xy=best_center,
                        radius=best_r,
                        cw=cw,
                        z_mode=z_mode,
                        z0=z0,
                        z1=z1,
                        start_ang=_angle(best_center, p_start),
                        end_ang=_angle(best_center, p_end),
                    )
                    segs.append(arc_seg)
                    i = best_j
                    i += 1
                    continue
                else:
                    if max_err > max_dev:
                        fallback["dev"] += 1
                    elif arc_len < min_len:
                        fallback["len"] += 1
        # Arc uygun değilse line
        segs.append(LineSeg(cleaned[i], cleaned[i + 1]))
        i += 1

    stats = {
        "point_count": len(cleaned),
        "arcs": sum(1 for s in segs if isinstance(s, ArcSeg)),
        "lines": sum(1 for s in segs if isinstance(s, LineSeg)),
        "fallback": fallback,
        "has_a": any(p[3] is not None for p in cleaned),
    }
    logger.info(
        "ArcFit: pts=%s arcs=%s lines=%s fallback=%s",
        stats["point_count"],
        stats["arcs"],
        stats["lines"],
        stats["fallback"],
    )
    return ToolpathSegments(segs, stats)
