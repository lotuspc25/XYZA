from dataclasses import dataclass
from typing import Optional, Tuple


def _parse_rgba(val: Optional[str], default: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
    if not val:
        return default
    try:
        parts = [float(x.strip()) for x in str(val).split(",")]
        if len(parts) == 4:
            return tuple(parts)  # type: ignore
    except Exception:
        return default
    return default


@dataclass
class ToolVisualConfig:
    enabled: bool = True
    tool_type: str = "saw"
    kerf_mm: float = 1.0
    saw_radius_mm: float = 30.0
    saw_thickness_mm: float = 1.0
    tool_radius_mm: float = 0.5
    saw_color: Tuple[float, float, float, float] = (0.2, 0.2, 0.2, 0.65)
    kerf_color: Tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.18)
    kerf_visual_enabled: bool = True
    kerf_done_emphasis: bool = True
    sim_show_kerf_band: bool = True
    sim_tool_on_edge: bool = False
    kerf_side: int = 1
    kerf_show_band: bool = True
    kerf_miter_limit: float = 3.0
    done_path_width_mode: int = 1
    done_path_min_px: int = 2
    done_path_max_px: int = 10

    @classmethod
    def from_settings(cls, settings) -> "ToolVisualConfig":
        if settings is None:
            return cls()
        try:
            enabled = bool(int(getattr(settings, "tool_visual_enabled", 1)))
        except Exception:
            enabled = True
        tool_type = getattr(settings, "tool_type", "saw")
        # kerf / radius, eski anahtarlarla geriye uyumluluk
        kerf_raw = getattr(settings, "kerf_mm", None)
        if kerf_raw is None:
            kerf_raw = getattr(settings, "saw_kerf_mm", 1.0)
        kerf_mm = float(kerf_raw)

        # Radius öncelik: tool_saw_radius_mm > saw_radius_mm > saw_diameter_mm/2
        saw_radius_mm = None
        for key in ("tool_saw_radius_mm", "saw_radius_mm"):
            val = getattr(settings, key, None)
            if val is not None:
                try:
                    saw_radius_mm = float(val)
                    break
                except Exception:
                    pass
        if saw_radius_mm is None:
            dia = getattr(settings, "tool_saw_diameter_mm", None)
            if dia is None:
                dia = getattr(settings, "saw_diameter_mm", None)
            try:
                saw_radius_mm = float(dia) * 0.5
            except Exception:
                saw_radius_mm = 30.0

        saw_thickness_mm = float(getattr(settings, "saw_thickness_mm", 1.0))
        tool_radius_mm = getattr(settings, "tool_radius_mm", None)
        try:
            tool_radius_mm = float(tool_radius_mm) if tool_radius_mm is not None else kerf_mm * 0.5
        except Exception:
            tool_radius_mm = kerf_mm * 0.5
        saw_col = _parse_rgba(getattr(settings, "saw_color_rgba", None), (0.2, 0.2, 0.2, 0.65))
        kerf_col = _parse_rgba(getattr(settings, "kerf_color_rgba", None), (1.0, 0.0, 0.0, 0.18))
        kerf_visual_enabled = bool(int(getattr(settings, "kerf_visual_enabled", 1)))
        kerf_done_emphasis = bool(int(getattr(settings, "kerf_done_emphasis", 1)))
        sim_show_kerf_band = bool(int(getattr(settings, "sim_show_kerf_band", 1)))
        sim_tool_on_edge = bool(int(getattr(settings, "sim_tool_on_edge", 0)))
        kerf_side_raw = getattr(settings, "kerf_side", 1)
        try:
            kerf_side = int(kerf_side_raw)
        except Exception:
            kerf_side = 1
        if isinstance(kerf_side_raw, str):
            if kerf_side_raw.strip().upper() == "LEFT":
                kerf_side = 1
            elif kerf_side_raw.strip().upper() == "RIGHT":
                kerf_side = -1
        kerf_show_band = bool(int(getattr(settings, "kerf_show_band", 1)))
        if sim_show_kerf_band is False:
            kerf_show_band = False
        if not kerf_visual_enabled:
            kerf_show_band = False
        kerf_miter_limit = float(getattr(settings, "kerf_miter_limit", 3.0))
        done_path_width_mode = int(getattr(settings, "done_path_width_mode", 1))
        done_path_min_px = int(getattr(settings, "done_path_min_px", 2))
        done_path_max_px = int(getattr(settings, "done_path_max_px", 10))
        try:
            kerf_band_opacity = float(getattr(settings, "kerf_band_opacity", 0.35))
            kerf_col = (kerf_col[0], kerf_col[1], kerf_col[2], kerf_band_opacity)
        except Exception:
            pass
        try:
            done_band_opacity = float(getattr(settings, "done_band_opacity", kerf_col[3]))
            saw_col = (saw_col[0], saw_col[1], saw_col[2], done_band_opacity)
        except Exception:
            pass
        return cls(
            enabled=enabled,
            tool_type=str(tool_type).lower(),
            kerf_mm=kerf_mm,
            saw_radius_mm=saw_radius_mm,
            saw_thickness_mm=saw_thickness_mm,
            tool_radius_mm=tool_radius_mm,
            saw_color=saw_col,
            kerf_color=kerf_col,
            kerf_visual_enabled=kerf_visual_enabled,
            kerf_done_emphasis=kerf_done_emphasis,
            sim_show_kerf_band=sim_show_kerf_band,
            sim_tool_on_edge=sim_tool_on_edge,
            kerf_side=kerf_side,
            kerf_show_band=kerf_show_band,
            kerf_miter_limit=kerf_miter_limit,
            done_path_width_mode=done_path_width_mode,
            done_path_min_px=done_path_min_px,
            done_path_max_px=done_path_max_px,
        )
