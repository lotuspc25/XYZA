import configparser
import logging
import math
import os
from typing import Dict, Iterable, List, Tuple, Union

from core.path_utils import find_or_create_config

logger = logging.getLogger(__name__)


def _get_setting(obj, name: str, default):
    try:
        return float(getattr(obj, name, default))
    except Exception:
        try:
            return float(getattr(obj, name.replace("_mm", ""), default))
        except Exception:
            return default


def _get_jump_threshold(settings) -> float:
    default_step = _get_setting(settings, "step_mm", 0.5)
    base = max(2.0, 4 * default_step)
    return max(base, _get_setting(settings, "jump_threshold_mm", base))


def _get_a_safety_params(settings):
    return {
        "a_lift_enabled": bool(getattr(settings, "a_lift_enabled", 1)),
        "a_sharp_deg": _get_setting(settings, "a_sharp_deg", 25.0),
        "a_critical_deg": _get_setting(settings, "a_critical_deg", 45.0),
        "xy_small_mm": _get_setting(settings, "xy_small_mm", 0.30),
        "a_lift_mode": _get_setting(settings, "a_lift_mode", 1),
        "a_lift_safe_z_mm": _get_setting(
            settings,
            "a_lift_safe_z_mm",
            _get_setting(settings, "safe_z_mm", 20.0),
        ),
        "feed_a_deg_min": _get_setting(settings, "feed_a_deg_min", _get_setting(settings, "feed_xy_mm_min", 2000.0)),
    }


def _read_ini() -> Union[configparser.ConfigParser, None]:
    cfg = configparser.ConfigParser()
    try:
        settings_path = str(find_or_create_config()[0])
        if os.path.exists(settings_path):
            cfg.read(settings_path, encoding="utf-8")
            return cfg
    except Exception:
        return None
    return None


def _get_ini_str(section: str, option: str, fallback: str) -> str:
    cfg = _read_ini()
    if cfg is None:
        return fallback
    try:
        if cfg.has_option(section, option):
            return cfg.get(section, option, fallback=fallback)
    except Exception:
        return fallback
    return fallback


def _get_ini_float(section: str, option: str, fallback: float) -> float:
    cfg = _read_ini()
    if cfg is None:
        return fallback
    try:
        if cfg.has_option(section, option):
            return cfg.getfloat(section, option, fallback=fallback)
    except Exception:
        return fallback
    return fallback


def _get_ini_int(section: str, option: str, fallback: int) -> int:
    cfg = _read_ini()
    if cfg is None:
        return fallback
    try:
        if cfg.has_option(section, option):
            return cfg.getint(section, option, fallback=fallback)
    except Exception:
        return fallback
    return fallback


def _parse_bool(val, default: Union[bool, None] = False) -> Union[bool, None]:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(int(val))
    if isinstance(val, str):
        text = val.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
    return default


def _get_output_axes(settings) -> str:
    axes = None
    if settings is not None:
        axes = getattr(settings, "output_axes", None)
    if axes is None:
        axes = _get_ini_str("GCODE", "output_axes", "XYZA")
    axes = str(axes or "XYZA").strip().upper().replace(" ", "")
    return axes if axes else "XYZA"


def _get_turn_retract_params(settings) -> dict:
    enabled = None
    if settings is not None and hasattr(settings, "turn_retract_enabled"):
        enabled = _parse_bool(getattr(settings, "turn_retract_enabled"), None)
    if enabled is None:
        enabled = _parse_bool(_get_ini_int("GCODE", "turn_retract_enabled", 1), True)

    threshold = None
    if settings is not None and hasattr(settings, "turn_retract_threshold_deg"):
        threshold = _get_setting(settings, "turn_retract_threshold_deg", None)
    if threshold is None:
        threshold = _get_ini_float("GCODE", "turn_retract_threshold_deg", 45.0)
    return {"enabled": bool(enabled), "threshold_deg": float(threshold)}


def _get_park_params(settings) -> dict:
    enabled = None
    for attr in ("use_g53_park", "park_enabled"):
        if settings is not None and hasattr(settings, attr):
            enabled = _parse_bool(getattr(settings, attr), None)
            break
    if enabled is None:
        enabled = _parse_bool(_get_ini_int("MACHINE", "use_g53_park", _get_ini_int("MACHINE", "park_enabled", 0)), False)

    def _val(names, fallback):
        for name in names:
            if settings is not None and hasattr(settings, name):
                try:
                    return float(getattr(settings, name))
                except Exception:
                    pass
            ini_val = _get_ini_float("MACHINE", name, None)
            if ini_val is not None:
                return ini_val
        return fallback

    return {
        "enabled": bool(enabled),
        "x": _val(["g53_park_x", "park_x"], 0.0),
        "y": _val(["g53_park_y", "park_y"], 0.0),
        "z": _val(["g53_park_z", "park_z"], 0.0),
        "a": _val(["g53_park_a", "park_a"], None),
    }


def _get_spindle_params(settings) -> dict:
    enabled = None
    if settings is not None and hasattr(settings, "spindle_enabled"):
        enabled = _parse_bool(getattr(settings, "spindle_enabled"), None)
    if enabled is None:
        enabled = _parse_bool(_get_ini_int("GCODE", "spindle_enabled", 0), False)

    use_s = None
    if settings is not None and hasattr(settings, "spindle_use_s"):
        use_s = _parse_bool(getattr(settings, "spindle_use_s"), None)
    if use_s is None:
        use_s = _parse_bool(_get_ini_int("GCODE", "spindle_use_s", 0), False)

    def _s_val(name, fallback):
        if settings is not None and hasattr(settings, name):
            try:
                return getattr(settings, name)
            except Exception:
                pass
        if isinstance(fallback, str):
            val = _get_ini_str("GCODE", name, None)
            if val is not None:
                return val
        else:
            val = _get_ini_float("GCODE", name, None)
            if val is not None:
                return val
        return fallback

    rpm = _s_val("spindle_rpm", 10000.0)
    try:
        rpm = float(rpm)
    except Exception:
        rpm = 10000.0

    emit_off = None
    if settings is not None and hasattr(settings, "spindle_emit_off_at_end"):
        emit_off = _parse_bool(getattr(settings, "spindle_emit_off_at_end"), None)
    if emit_off is None:
        emit_off = _parse_bool(_get_ini_int("GCODE", "spindle_emit_off_at_end", 0), False)

    return {
        "enabled": bool(enabled),
        "use_s": bool(use_s),
        "rpm": rpm,
        "on": _s_val("spindle_on_mcode", "M3"),
        "off": _s_val("spindle_off_mcode", "M5"),
        "emit_off": bool(emit_off),
    }


def _get_a_min_step_deg(settings) -> float:
    if settings is not None and hasattr(settings, "a_min_step_deg"):
        try:
            return float(getattr(settings, "a_min_step_deg"))
        except Exception:
            pass
    val = _get_ini_float("GCODE", "a_min_step_deg", 0.0)
    if not val:
        val = _get_ini_float("APP", "a_min_step_deg", 0.0)
    return float(val)


def _angle_delta_deg(a0: float, a1: float) -> float:
    return (a1 - a0 + 180.0) % 360.0 - 180.0


def _clean_points(points: Iterable) -> Tuple[List[Tuple[float, float, float, Union[float, None]]], int]:
    cleaned = []
    skipped = 0
    for p in points or []:
        try:
            if isinstance(p, dict):
                x = float(p.get("x", 0.0))
                y = float(p.get("y", 0.0))
                z = float(p.get("z", 0.0))
                a_val = p.get("a", p.get("a_cont", p.get("a_norm", None)))
            else:
                if hasattr(p, "x"):
                    x = float(p.x)
                else:
                    x = float(p[0])
                if hasattr(p, "y"):
                    y = float(p.y)
                else:
                    y = float(p[1])
                if hasattr(p, "z"):
                    z = float(p.z)
                else:
                    z = float(p[2])
                a_val = getattr(p, "a", None)
                if a_val is None:
                    try:
                        a_val = p[3]
                    except Exception:
                        a_val = None
            a_val = float(a_val) if a_val is not None else None
            if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                skipped += 1
                continue
            cleaned.append((x, y, z, a_val))
        except Exception:
            skipped += 1
    return cleaned, skipped


def _format_ax(x: float) -> str:
    return f"{x:.3f}"


def should_a_lift(prev_pt, pt, cfg):
    try:
        if not cfg.get("a_lift_enabled", True):
            return False, "A_DISABLED", 0.0, 0.0
        if prev_pt is None or pt is None:
            return False, "A_MISSING", 0.0, 0.0
        if prev_pt[3] is None or pt[3] is None:
            return False, "A_MISSING", 0.0, 0.0
        da = abs(pt[3] - prev_pt[3])
        dx = pt[0] - prev_pt[0]
        dy = pt[1] - prev_pt[1]
        dxy = math.hypot(dx, dy)
        if da >= cfg.get("a_critical_deg", 45.0):
            return True, "A_CRITICAL", da, dxy
        if da >= cfg.get("a_sharp_deg", 25.0) and dxy <= cfg.get("xy_small_mm", 0.3):
            return True, "A_SHARP_XY_SMALL", da, dxy
        return False, "OK", da, dxy
    except Exception:
        return False, "ERR", 0.0, 0.0


def build_gcode_from_segments(segments, settings, include_a: bool = False, arc_fallback_count: int = 0):
    """
    Line/Arc segment listesinden Mach3 uyumlu G-code Ç¬retir.
    - Header: yorum, G21 G90 G17 G94 G40 G49 G54, spindle on, G0 Zsafe
    - Jump tespitinde Z safe lift + rapid + tekrar inme
    - Arc: G2/G3 I/J, opsiyonel Z/A
    """
    from toolpath_arcfit import ArcSeg, LineSeg  # local import

    safe_z = _get_setting(settings, "safe_z_mm", 5.0)
    feed_xy = _get_setting(settings, "feed_xy_mm_min", 2000.0)
    feed_z = _get_setting(settings, "feed_z_mm_min", 500.0)
    feed_travel = _get_setting(settings, "feed_travel_mm_min", 4000.0)
    spindle_cfg = _get_spindle_params(settings)
    spindle_enabled = bool(spindle_cfg.get("enabled", False))
    spindle_use_s = bool(spindle_cfg.get("use_s", False))
    spindle_rpm = float(spindle_cfg.get("rpm", 0.0))
    spindle_on_mcode = spindle_cfg.get("on", "")
    spindle_off_mcode = spindle_cfg.get("off", "")
    spindle_emit_off = bool(spindle_cfg.get("emit_off", False))
    arc_z_eps = _get_setting(settings, "arc_z_eps_mm", 0.005)
    jump_threshold = _get_jump_threshold(settings)
    a_params = _get_a_safety_params(settings)
    safe_z_for_a = safe_z if math.isfinite(safe_z) else a_params.get("a_lift_safe_z_mm", 20.0)
    feed_a = a_params.get("feed_a_deg_min", feed_xy)
    turn_retract = _get_turn_retract_params(settings)
    turn_retract_enabled = bool(turn_retract.get("enabled", False))
    turn_retract_threshold = float(turn_retract.get("threshold_deg", 45.0))
    turn_retract_count = 0
    a_min_step_deg = _get_a_min_step_deg(settings)
    park_params = _get_park_params(settings)
    park_enabled = bool(park_params.get("enabled", False))
    park_x = float(park_params.get("x", 0.0))
    park_y = float(park_params.get("y", 0.0))
    park_z = float(park_params.get("z", 0.0))
    park_a = park_params.get("a", None)

    lines: List[str] = []
    moves = {"G0": 0, "G1": 0, "G2": 0, "G3": 0}
    a_stats = {"detected": 0, "applied": 0, "max_deltaA": 0.0}
    a_stats["max_deltaXY"] = 0.0
    last_a = None

    def should_emit_a(target_a: Union[float, None]) -> bool:
        nonlocal last_a
        if not include_a or target_a is None:
            return False
        if last_a is None:
            last_a = float(target_a)
            return True
        if abs(float(target_a) - float(last_a)) >= a_min_step_deg:
            last_a = float(target_a)
            return True
        return False

    def add_raw(cmd: str, move_code: str = None):
        lines.append(cmd)
        if move_code in moves:
            moves[move_code] += 1

    last_motion = None
    last_feed = None

    def emit_move(motion: str, x=None, y=None, z=None, a=None, feed=None):
        nonlocal last_motion, last_feed
        base_motion = motion or last_motion
        if base_motion is None:
            base_motion = "G1"
        parts: List[str] = []
        if base_motion != last_motion:
            parts.append(base_motion)
            last_motion = base_motion
        else:
            parts.append(base_motion) if motion in ("G2", "G3") else None
        if x is not None:
            parts.append(f"X{_format_ax(float(x))}")
        if y is not None:
            parts.append(f"Y{_format_ax(float(y))}")
        if z is not None:
            parts.append(f"Z{_format_ax(float(z))}")
        if a is not None:
            parts.append(f"A{_format_ax(float(a))}")
        if base_motion != "G0" and feed is not None:
            if last_feed is None or abs(feed - last_feed) > 1e-9:
                parts.append(f"F{float(feed):.2f}")
                last_feed = float(feed)
        line = " ".join(parts)
        lines.append(line)
        if base_motion in moves:
            moves[base_motion] += 1

    # Header
    add_raw("(Generated by ZYZA Toolpath)")
    add_raw("G21")
    add_raw("G90")
    add_raw("G17")
    add_raw("G94")
    add_raw("G40")
    add_raw("G49")
    if spindle_enabled and spindle_on_mcode:
        if spindle_use_s:
            add_raw(f"{spindle_on_mcode} S{spindle_rpm:.0f}")
        else:
            add_raw(str(spindle_on_mcode))
    if park_enabled:
        add_raw(f"G53 G0 Z{_format_ax(park_z)}", "G0")
        add_raw(f"G53 G0 X{_format_ax(park_x)} Y{_format_ax(park_y)}", "G0")
        if park_a is not None:
            add_raw(f"G53 G0 A{_format_ax(park_a)}", "G0")
    add_raw("G54")
    emit_move("G0", z=safe_z)

    if not segments:
        stats = {
            "line_count": len(lines),
            "lines_total": len(lines),
            "moves_g0": moves["G0"],
            "moves_g1": 0,
            "moves_g2": 0,
            "moves_g3": 0,
            "arc_ok": 0,
            "arc_fallback": arc_fallback_count,
        }
        return "\n".join(lines), stats

    cur = None  # type: ignore
    arc_count = 0
    line_count = 0
    xs: List[float] = []
    ys: List[float] = []
    zs: List[float] = []
    a_vals: List[float] = []

    def ensure_at_start(start_pt):
        nonlocal cur
        sx, sy, sz, sa = start_pt
        did_reposition = False
        if cur is None:
            emit_move("G0", x=sx, y=sy)
            emit_move("G1", z=sz, a=sa if should_emit_a(sa) else None, feed=feed_z)
            cur = (sx, sy, sz, sa)
            return True
        gap = math.hypot(sx - cur[0], sy - cur[1])
        if gap > jump_threshold:
            emit_move("G0", z=safe_z)
            emit_move("G0", x=sx, y=sy)
            emit_move("G1", z=sz, a=sa if should_emit_a(sa) else None, feed=feed_z)
            cur = (sx, sy, sz, sa)
            did_reposition = True
        return did_reposition

    def is_cut_active(cur_z, target_z):
        if safe_z is None or not math.isfinite(safe_z):
            return False
        z_ref = target_z if target_z is not None else cur_z
        if z_ref is None:
            return False
        return z_ref < (safe_z - 1e-6)

    move_idx = 0
    prev_heading = None

    def _segment_heading(x0, y0, x1, y1):
        dx = x1 - x0
        dy = y1 - y0
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return None
        return math.degrees(math.atan2(dy, dx))
    for seg in segments:
        sx, sy, sz, sa = seg.p0
        repositioned = ensure_at_start(seg.p0)

        def maybe_turn_retract(target_a, target_z, target_xy, heading, prev_head):
            nonlocal cur, turn_retract_count
            if not turn_retract_enabled:
                return False
            if prev_head is None or heading is None:
                return False
            if target_z is None:
                return False
            if not is_cut_active(cur[2], target_z if cur is not None else target_z):
                return False
            delta_h = abs(_angle_delta_deg(prev_head, heading))
            if delta_h < turn_retract_threshold:
                return False
            if safe_z is None or not math.isfinite(safe_z):
                return False
            # Retract: Zsafe, A (if needed), XY, then plunge
            emit_move("G0", z=safe_z)
            new_a = cur[3] if (cur is not None and len(cur) > 3) else None
            if target_a is not None and should_emit_a(target_a):
                emit_move("G0", a=target_a)
                new_a = target_a
            emit_move("G0", x=target_xy[0], y=target_xy[1])
            emit_move("G1", z=target_z, feed=feed_z)
            cur = (target_xy[0], target_xy[1], target_z, new_a)
            turn_retract_count += 1
            return True

        def maybe_a_lift(target_a, target_z, target_xy):
            nonlocal cur
            if not include_a or cur is None:
                return
            if target_a is None or cur[3] is None:
                return
            dx = target_xy[0] - cur[0]
            dy = target_xy[1] - cur[1]
            xy_dist = math.hypot(dx, dy)
            delta_a = abs(target_a - cur[3])
            a_stats["max_deltaA"] = max(a_stats["max_deltaA"], delta_a)
            a_stats["max_deltaXY"] = max(a_stats["max_deltaXY"], xy_dist)
            lift_needed, reason, da, dxy = should_a_lift(cur, (target_xy[0], target_xy[1], target_z, target_a), a_params)
            if lift_needed:
                a_stats["detected"] += 1
                if a_params.get("a_lift_mode", 1) and safe_z_for_a is not None and math.isfinite(target_z):
                    add_raw(f"(A_LIFT reason={reason} dA={da:.3f} dXY={dxy:.3f} idx={move_idx})")
                    emit_move("G0", z=safe_z_for_a)
                    emitted = False
                    if should_emit_a(target_a):
                        emit_move("G1", a=target_a, feed=feed_a)
                        new_a = target_a
                        emitted = True
                    else:
                        new_a = cur[3]
                    emit_move("G1", z=target_z, feed=feed_z)
                    cur = (cur[0], cur[1], target_z, new_a)
                    if emitted:
                        a_stats["applied"] += 1
                    return True
            return False

        if isinstance(seg, LineSeg):
            x1, y1, z1, a1 = seg.p1
            heading = _segment_heading(sx, sy, x1, y1)
            turn_retract_applied = maybe_turn_retract(a1, z1, (x1, y1), heading, prev_heading)
            if not turn_retract_applied:
                maybe_a_lift(a1, z1, (x1, y1))
                emit_move("G1", x=x1, y=y1, z=z1, a=a1 if should_emit_a(a1) else None, feed=feed_xy)
                cur = (x1, y1, z1, a1)
                line_count += 1
            xs.extend([sx, x1])
            ys.extend([sy, y1])
            zs.extend([sz, z1])
            if include_a:
                if cur[3] is not None:
                    a_vals.append(cur[3])
                if a1 is not None:
                    a_vals.append(a1)
            prev_heading = heading
        elif isinstance(seg, ArcSeg):
            x1, y1, z1, a1 = seg.p1
            arc_target_z = z1 if z1 is not None else (cur[2] if cur is not None else None)
            heading = _segment_heading(sx, sy, x1, y1)
            turn_retract_applied = maybe_turn_retract(a1, arc_target_z, (x1, y1), heading, prev_heading)
            if not turn_retract_applied:
                maybe_a_lift(a1, arc_target_z, (x1, y1))
            i_off = seg.center_xy[0] - cur[0]
            j_off = seg.center_xy[1] - cur[1]
            z_target = None
            if abs((z1 or 0) - (cur[2] or 0)) > arc_z_eps and seg.z_mode == "interp":
                z_target = z1
            cmd = "G2" if seg.cw else "G3"
            parts = [cmd]
            parts.append(f"X{_format_ax(x1)}")
            parts.append(f"Y{_format_ax(y1)}")
            if z_target is not None:
                parts.append(f"Z{_format_ax(z_target)}")
            parts.append(f"I{_format_ax(i_off)}")
            parts.append(f"J{_format_ax(j_off)}")
            if should_emit_a(a1):
                parts.append(f"A{_format_ax(a1)}")
            if last_feed is None or abs(feed_xy - last_feed) > 1e-9:
                parts.append(f"F{feed_xy:.2f}")
                last_feed = feed_xy
            line = " ".join(parts)
            lines.append(line)
            moves[cmd] += 1
            cur = (x1, y1, z1, a1)
            arc_count += 1
            xs.extend([sx, x1])
            ys.extend([sy, y1])
            zs.extend([sz, z1])
            if include_a:
                if cur[3] is not None:
                    a_vals.append(cur[3])
                if a1 is not None:
                    a_vals.append(a1)
            prev_heading = heading
        else:
            continue
        move_idx += 1

    emit_move("G0", z=safe_z)
    if park_enabled:
        add_raw(f"G53 G0 Z{_format_ax(park_z)}", "G0")
        add_raw(f"G53 G0 X{_format_ax(park_x)} Y{_format_ax(park_y)}", "G0")
        if park_a is not None:
            add_raw(f"G53 G0 A{_format_ax(park_a)}", "G0")
    if spindle_emit_off and spindle_enabled and spindle_off_mcode:
        add_raw(str(spindle_off_mcode))
    add_raw("M30")

    stats = {
        "line_count": len(lines),
        "lines_total": len(lines),
        "moves_g0": moves["G0"],
        "moves_g1": moves["G1"],
        "moves_g2": moves["G2"],
        "moves_g3": moves["G3"],
        "arc_ok": arc_count,
        "arc_fallback": arc_fallback_count,
        "min_x": min(xs) if xs else 0.0,
        "max_x": max(xs) if xs else 0.0,
        "min_y": min(ys) if ys else 0.0,
        "max_y": max(ys) if ys else 0.0,
        "min_z": min(zs) if zs else 0.0,
        "max_z": max(zs) if zs else 0.0,
        "a_lift_detected": a_stats["detected"],
        "a_lift_applied": a_stats["applied"],
        "a_max_delta": a_stats["max_deltaA"],
        "a_max_delta_xy": a_stats.get("max_deltaXY", 0.0),
        "min_a": min(a_vals) if a_vals else None,
        "max_a": max(a_vals) if a_vals else None,
        "turn_retract_applied": turn_retract_count,
    }
    return "\n".join(lines), stats


def build_gcode_from_points(points: Iterable, settings) -> Tuple[str, Dict[str, float]]:
    """
    Verilen noktaların (x,y,z[,_]) kullanarak G-code üretir.
    - Arc enable açık ise G2/G3; aksi halde G1
    - Jump tespitinde Z safe lift
    """
    from toolpath_arcfit import LineSeg, build_segments

    arc_enable = None
    try:
        arc_enable = bool(getattr(settings, "arc_enable"))
    except Exception:
        arc_enable = None
    if arc_enable is None:
        arc_enable = bool(_get_ini_int("GCODE", "enable_xy_arcs", 0))
    disable_arc_due_to_a = False

    cleaned, skipped = _clean_points(points)
    if not cleaned:
        return "", {"point_count": 0, "line_count": 0, "skipped": skipped}

    output_axes = _get_output_axes(settings)
    has_a = any(p[3] is not None for p in cleaned)
    include_a = ("A" in output_axes) and has_a
    if include_a:
        disable_arc_due_to_a = True

    if arc_enable and not disable_arc_due_to_a:
        try:
            params = {
                "arc_max_dev_mm": getattr(settings, "arc_max_dev_mm", _get_ini_float("GCODE", "arc_tol_mm", None)),
                "arc_min_points": getattr(settings, "arc_min_points", None),
                "arc_min_len_mm": getattr(settings, "arc_min_len_mm", None),
                "arc_z_eps_mm": getattr(settings, "arc_z_eps_mm", None),
            }
            segs_obj = build_segments(cleaned, params=params)
            segs = segs_obj.segments
            if segs:
                fallback_count = 0
                fb = segs_obj.stats.get("fallback", {}) if segs_obj.stats else {}
                if isinstance(fb, dict):
                    fallback_count = sum(fb.values())
                gcode, stats = build_gcode_from_segments(
                    segs,
                    settings,
                    include_a=include_a,
                    arc_fallback_count=fallback_count,
                )
                stats.update(
                    {
                        "skipped": skipped,
                        "arc_mode": True,
                        "point_count": len(cleaned),
                        "a_lift_detected": stats.get("a_lift_detected", 0),
                        "a_lift_applied": stats.get("a_lift_applied", 0),
                        "a_max_delta": stats.get("a_max_delta", 0.0),
                    }
                )
                logger.info(
                    "G-code (arc): arcs=%s lineseg=%s fallback=%s skipped=%s a_lift=%s",
                    stats.get("arc_ok"),
                    stats.get("moves_g1"),
                    stats.get("arc_fallback"),
                    skipped,
                    stats.get("a_lift_applied"),
                )
                return gcode, stats
            else:
                logger.info("Arc fit boş segment döndürdü, G1'e fallback.")
        except Exception:
            logger.exception("Arc fit/gcode üretimi başarısız, G1'e fallback.")

    # G1 fallback (eski davranış)
    segs = [LineSeg(cleaned[i], cleaned[i + 1]) for i in range(len(cleaned) - 1)]
    gcode, stats = build_gcode_from_segments(
        segs,
        settings,
        include_a=include_a,
        arc_fallback_count=0,
    )
    stats.update(
        {
            "skipped": skipped,
            "arc_mode": False,
            "arc_ok": 0,
            "arc_fallback": 0,
            "point_count": len(cleaned),
        }
    )
    logger.info(
        "G-code (line): moves_g1=%s skipped=%s",
        stats.get("moves_g1"),
        skipped,
    )
    return gcode, stats


def micro_test_a_modal_and_retract() -> bool:
    class Dummy:
        pass

    settings = Dummy()
    settings.safe_z_mm = 5.0
    settings.feed_xy_mm_min = 1000.0
    settings.feed_z_mm_min = 300.0
    settings.feed_travel_mm_min = 2000.0
    settings.spindle_on_cmd = ""
    settings.spindle_off_cmd = ""
    settings.output_axes = "XYZA"
    settings.turn_retract_enabled = 1
    settings.turn_retract_threshold_deg = 45.0
    settings.a_min_step_deg = 5.0
    settings.a_lift_enabled = 0
    settings.feed_a_deg_min = 500.0

    points = [
        (0.0, 0.0, -1.0, 0.0),
        (1.0, 0.0, -1.0, 20.0),
        (1.0, 1.0, -1.0, 80.0),  # 90 deg turn triggers retract
        (2.0, 1.0, -1.0, 80.0),
    ]

    gcode_text, _stats = build_gcode_from_points(points, settings)
    lines = [line.strip() for line in gcode_text.splitlines() if line.strip()]

    assert any(("X" in line and "A" in line) for line in lines), "Modal A not emitted with XYZ"
    assert "A22.000" not in gcode_text, "A emitted below a_min_step_deg"

    seq_found = False
    for i in range(len(lines) - 3):
        if ("Z5.000" in lines[i]) and ("A80.000" in lines[i + 1]) and ("X1.000" in lines[i + 2] and "Y1.000" in lines[i + 2]) and ("Z-1.000" in lines[i + 3]):
            seq_found = True
            break
    assert seq_found, "Turn retract sequence not found"
    return True
