from dataclasses import dataclass
from typing import Callable, List, Optional
import time

from project_state import ToolpathPoint, ToolpathResult
from toolpath_generator import (
    generate_outline_toolpath,
    validate_toolpath,
    analyze_toolpath,
    PathIssue,
)


ProgressCallback = Callable[[int, str], None]


def _noop_progress(pct: int, msg: str = "") -> None:
    return


class ToolpathPipeline:
    """
    UI-agnostic toolpath pipeline: contour -> Z -> optional QA.
    """

    def generate(
        self,
        gl_viewer,
        settings_tab,
        sample_step_mm: float,
        offset_mm: float,
        z_mode_index: int,
        progress_cb: Optional[ProgressCallback] = None,
        generate_gcode: bool = False,
        mesh_intersector_cache=None,
        mesh_version: Optional[int] = None,
    ) -> ToolpathResult:
        cb = progress_cb or _noop_progress
        t0 = time.perf_counter()
        points, gcode_text, z_stats = generate_outline_toolpath(
            gl_viewer,
            settings_tab,
            sample_step_mm=sample_step_mm,
            offset_mm=offset_mm,
            z_mode_index=z_mode_index,
            progress_cb=lambda p, m="": cb(int(p), m),
            generate_gcode=generate_gcode,
            mesh_intersector_cache=mesh_intersector_cache,
            mesh_version=mesh_version,
        )
        elapsed = time.perf_counter() - t0
        result = ToolpathResult(
            points=list(points) if points else [],
            gcode_text=gcode_text or "",
            z_stats=z_stats or {},
        )
        result.meta.update(
            {
                "offset_mm": float(offset_mm),
                "step_mm": float(sample_step_mm),
                "z_mode_index": int(z_mode_index),
                "elapsed_sec": float(elapsed),
                "point_count": len(result.points),
            }
        )
        return result

    def validate(
        self,
        points: List[ToolpathPoint],
        table_width_mm: Optional[float] = None,
        table_height_mm: Optional[float] = None,
        z_min_mm: Optional[float] = None,
        z_max_mm: Optional[float] = None,
        enable_z_max_check: bool = False,
        a_min_deg: Optional[float] = None,
        a_max_deg: Optional[float] = None,
    ) -> List[PathIssue]:
        if not points:
            return []
        return validate_toolpath(
            points,
            table_width_mm=table_width_mm,
            table_height_mm=table_height_mm,
            z_min_mm=z_min_mm,
            z_max_mm=z_max_mm,
            enable_z_max_check=enable_z_max_check,
            a_min_deg=a_min_deg,
            a_max_deg=a_max_deg,
        )

    def analyze(
        self,
        points: List[ToolpathPoint],
        angle_threshold_deg: float = 30.0,
        z_threshold_mm: float = 2.0,
        dir_threshold_deg: float = 30.0,
        xy_spike_threshold_mm: float = 0.3,
    ) -> List[PathIssue]:
        if not points:
            return []
        return analyze_toolpath(
            points,
            angle_threshold_deg=angle_threshold_deg,
            z_threshold_mm=z_threshold_mm,
            dir_threshold_deg=dir_threshold_deg,
            xy_spike_threshold_mm=xy_spike_threshold_mm,
        )
