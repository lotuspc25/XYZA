import math
from typing import Dict, Tuple


def axis_from_direction(direction: str) -> str:
    value = (direction or "").strip().lower()
    if value in ("y", "y_parallel", "y-parallel", "yparallel"):
        return "y"
    if value in ("x", "x_parallel", "x-parallel", "xparallel"):
        return "x"
    if "y" in value:
        return "y"
    return "x"


def preview_orientation(knife_direction: str, profile_kind: str = "") -> Dict[str, float]:
    """Match Settings preview base orientation: mesh axis + Rx(90) after yaw."""
    _ = profile_kind  # Preview uses the same correction for all profile kinds.
    return {
        "direction_axis": axis_from_direction(knife_direction),
        "base_rot_z_deg": 0.0,
        "model_rx_deg": 90.0,
        "model_ry_deg": 0.0,
        "model_rz_deg": 0.0,
    }


def _normalize_profile(profile: str, knife_id: str = "") -> str:
    value = (profile or "").strip().lower().replace("-", "_").replace(" ", "")
    if value in ("scalpel", "scalpelpointed", "scalpel_pointed", "pointed"):
        return "scalpel_pointed"
    if value in ("scalpelrounded", "scalpel_rounded", "rounded"):
        return "scalpel_rounded"
    if value in ("rotarydisk", "rotary_disk", "disk", "rotary", "doner", "döner"):
        return "rotary_disk"
    if not value and knife_id:
        try:
            from core.knife_catalog import load_catalog

            for knife in load_catalog():
                if knife.id == knife_id:
                    return _normalize_profile(knife.kind, "")
        except Exception:
            pass
    return value or "scalpel_pointed"


def _rot_x(deg: float):
    rad = math.radians(deg)
    c = math.cos(rad)
    s = math.sin(rad)
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def _rot_y(deg: float):
    rad = math.radians(deg)
    c = math.cos(rad)
    s = math.sin(rad)
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def _rot_z(deg: float):
    rad = math.radians(deg)
    c = math.cos(rad)
    s = math.sin(rad)
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def _mat_mul(a, b):
    return (
        (
            a[0][0] * b[0][0] + a[0][1] * b[1][0] + a[0][2] * b[2][0],
            a[0][0] * b[0][1] + a[0][1] * b[1][1] + a[0][2] * b[2][1],
            a[0][0] * b[0][2] + a[0][1] * b[1][2] + a[0][2] * b[2][2],
        ),
        (
            a[1][0] * b[0][0] + a[1][1] * b[1][0] + a[1][2] * b[2][0],
            a[1][0] * b[0][1] + a[1][1] * b[1][1] + a[1][2] * b[2][1],
            a[1][0] * b[0][2] + a[1][1] * b[1][2] + a[1][2] * b[2][2],
        ),
        (
            a[2][0] * b[0][0] + a[2][1] * b[1][0] + a[2][2] * b[2][0],
            a[2][0] * b[0][1] + a[2][1] * b[1][1] + a[2][2] * b[2][1],
            a[2][0] * b[0][2] + a[2][1] * b[1][2] + a[2][2] * b[2][2],
        ),
    )


def _mat_vec(m, v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def compute_tool_pose(
    tool_profile: Dict[str, object],
    x: float,
    y: float,
    z: float,
    a_deg: float,
) -> Tuple[Tuple[float, float, float], Tuple[Tuple[float, float, float], ...]]:
    profile = _normalize_profile(
        str(tool_profile.get("knife_profile", "") or ""),
        str(tool_profile.get("knife_id", "") or ""),
    )
    orient = preview_orientation(str(tool_profile.get("knife_direction", "")), profile)
    rot = _rot_z(float(a_deg))
    base_z = float(orient.get("base_rot_z_deg", 0.0))
    if abs(base_z) > 1e-6:
        rot = _mat_mul(rot, _rot_z(base_z))
    model_rz = float(orient.get("model_rz_deg", 0.0))
    model_ry = float(orient.get("model_ry_deg", 0.0))
    model_rx = float(orient.get("model_rx_deg", 0.0))
    if abs(model_rz) > 1e-6:
        rot = _mat_mul(rot, _rot_z(model_rz))
    if abs(model_ry) > 1e-6:
        rot = _mat_mul(rot, _rot_y(model_ry))
    if abs(model_rx) > 1e-6:
        rot = _mat_mul(rot, _rot_x(model_rx))

    offset_local = (0.0, 0.0, 0.0)
    if profile == "rotary_disk":
        diam = tool_profile.get("cutting_edge_diam_mm", None)
        if diam is None:
            diam = tool_profile.get("disk_diameter_mm", None)
        if diam is None:
            diam = tool_profile.get("blade_length_mm", 0.0)
        try:
            radius = max(float(diam) * 0.5, 0.0)
        except Exception:
            radius = 0.0
        offset_local = (radius, 0.0, 0.0)
    else:
        try:
            length = float(tool_profile.get("blade_length_mm", 0.0))
        except Exception:
            length = 0.0
        if length > 0.0:
            offset_local = (0.0, length, 0.0)

    offset_world = _mat_vec(rot, offset_local)
    pos_world = (float(x) + offset_world[0], float(y) + offset_world[1], float(z) + offset_world[2])
    return pos_world, rot
