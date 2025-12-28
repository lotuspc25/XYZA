from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Any
import math

Point2D = Tuple[float, float]


@dataclass
class KnifeParams:
    blade_length_mm: float
    tip_diameter_mm: float
    shank_diameter_mm: float
    bevel_angle_deg: float = 30.0
    shoulder_length_mm: Optional[float] = None
    tip_round_radius_mm: Optional[float] = None


@dataclass
class RotaryParams:
    disk_diameter_mm: float
    hub_diameter_mm: Optional[float] = None
    kerf_mm: float = 0.3


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _to_dict(params: Any) -> Dict[str, float]:
    if isinstance(params, dict):
        return params
    if hasattr(params, "__dict__"):
        return dict(params.__dict__)
    return {}


def _get(params: Dict[str, float], key: str, default: float) -> float:
    try:
        return float(params.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _arc_points(cx: float, cy: float, r: float, start_deg: float, end_deg: float, steps: int) -> List[Point2D]:
    if steps < 2:
        steps = 2
    pts = []
    for i in range(steps):
        t = i / (steps - 1)
        ang = math.radians(start_deg + (end_deg - start_deg) * t)
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def _circle_points(cx: float, cy: float, r: float, steps: int) -> List[Point2D]:
    pts = []
    for i in range(steps):
        ang = (2.0 * math.pi) * (i / steps)
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    if pts:
        pts.append(pts[0])
    return pts


def _normalize_profile_name(name: str) -> str:
    n = (name or "").strip().lower().replace("-", "_").replace(" ", "")
    if n in ("scalpel", "scalpelpointed", "scalpel_pointed", "pointed"):
        return "scalpel_pointed"
    if n in ("scalpelrounded", "scalpel_rounded", "rounded"):
        return "scalpel_rounded"
    if n in ("rotarydisk", "rotary_disk", "disk", "rotary"):
        return "rotary_disk"
    return n or "scalpel_pointed"


def _build_scalpel_pointed(params: Dict[str, float]) -> Dict[str, Any]:
    length = max(_get(params, "blade_length_mm", 30.0), 1.0)
    tip_d = max(_get(params, "tip_diameter_mm", 1.0), 0.01)
    body_d = max(_get(params, "shank_diameter_mm", 3.0), 0.1)
    shoulder = _get(params, "shoulder_length_mm", length * 0.25)
    shoulder = _clamp(shoulder, length * 0.1, length * 0.6)

    shank_len = max(shoulder, body_d * 1.2)
    x_tip = length
    x_shoulder = 0.0
    x_shank = -shank_len

    shank_half = body_d / 2.0
    blade_base_half = min(shank_half, max(tip_d * 0.6, shank_half * 0.6))

    outline = [
        (x_shank, shank_half),
        (x_shoulder, shank_half),
        (x_shoulder, blade_base_half),
        (x_tip, 0.0),
        (x_shoulder, -blade_base_half),
        (x_shoulder, -shank_half),
        (x_shank, -shank_half),
        (x_shank, shank_half),
    ]
    return {
        "outline": outline,
        "tip": (x_tip, 0.0),
        "centerline": [(x_shank, 0.0), (x_tip, 0.0)],
        "extras": {},
    }


def _build_scalpel_rounded(params: Dict[str, float]) -> Dict[str, Any]:
    length = max(_get(params, "blade_length_mm", 30.0), 1.0)
    tip_d = max(_get(params, "tip_diameter_mm", 1.0), 0.01)
    body_d = max(_get(params, "shank_diameter_mm", 3.0), 0.1)
    shoulder = _get(params, "shoulder_length_mm", length * 0.25)
    shoulder = _clamp(shoulder, length * 0.1, length * 0.6)

    shank_len = max(shoulder, body_d * 1.2)
    x_tip = length
    x_shoulder = 0.0
    x_shank = -shank_len

    shank_half = body_d / 2.0
    blade_base_half = min(shank_half, max(tip_d * 0.6, shank_half * 0.6))
    r = _get(params, "tip_round_radius_mm", tip_d * 0.5)
    r = max(r, blade_base_half, tip_d * 0.5)

    cx = x_tip - r
    arc = _arc_points(cx, 0.0, r, 90.0, -90.0, 9)
    outline = [
        (x_shank, shank_half),
        (x_shoulder, shank_half),
        (x_shoulder, blade_base_half),
    ] + arc + [
        (x_shoulder, -blade_base_half),
        (x_shoulder, -shank_half),
        (x_shank, -shank_half),
        (x_shank, shank_half),
    ]
    return {
        "outline": outline,
        "tip": (x_tip, 0.0),
        "centerline": [(x_shank, 0.0), (x_tip, 0.0)],
        "extras": {},
    }


def _build_rotary_disk(params: Dict[str, float]) -> Dict[str, Any]:
    diam = max(_get(params, "disk_diameter_mm", 10.0), 0.1)
    r = diam / 2.0
    hub_d = _get(params, "hub_diameter_mm", diam * 0.3)
    hub_r = max(min(hub_d / 2.0, r * 0.9), 0.0)
    kerf = max(_get(params, "kerf_mm", 0.3), 0.0)

    outline = _circle_points(0.0, 0.0, r, 48)
    return {
        "outline": outline,
        "tip": (r, 0.0),
        "centerline": [(-r, 0.0), (r, 0.0)],
        "extras": {
            "disk_radius": r,
            "hub_radius": hub_r,
            "kerf": kerf,
        },
    }


def build_profile_points(profile_name: str, params: Any) -> Dict[str, Any]:
    name = _normalize_profile_name(profile_name)
    p = _to_dict(params)
    if name == "rotary_disk":
        return _build_rotary_disk(p)
    if name == "scalpel_rounded":
        return _build_scalpel_rounded(p)
    return _build_scalpel_pointed(p)
