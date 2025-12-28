import math
import os
from typing import List, Tuple

import numpy as np

from core.outline_extract import extract_outline_xy_from_triangles


Point2D = Tuple[float, float]


def load_2d_geometry(path: str) -> List[Point2D]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".stl":
        return _load_stl(path)
    if ext == ".dxf":
        return _load_dxf(path)
    raise ValueError("Desteklenmeyen dosya türü (yalnızca STL/DXF)")


def compute_tangent_a(points_xy: List[Point2D]) -> List[float]:
    if not points_xy or len(points_xy) < 2:
        return []
    angles: List[float] = []
    for i in range(len(points_xy) - 1):
        x0, y0 = points_xy[i]
        x1, y1 = points_xy[i + 1]
        dx = x1 - x0
        dy = y1 - y0
        angles.append(math.degrees(math.atan2(dy, dx)))
    angles.append(angles[-1])
    return angles


def build_2d_toolpath(path: str) -> dict:
    points_xy = load_2d_geometry(path)
    if not points_xy or len(points_xy) < 2:
        raise RuntimeError("Geometri bulunamadı")
    angles_a = compute_tangent_a(points_xy)
    return {
        "points_xy": points_xy,
        "angles_a": angles_a,
    }


def _load_stl(path: str) -> List[Point2D]:
    try:
        from stl import mesh as stl_mesh
    except Exception as exc:
        raise RuntimeError("STL için numpy-stl gerekli") from exc

    stl = stl_mesh.Mesh.from_file(path)
    tris = np.asarray(stl.vectors, dtype=np.float32)
    outline = extract_outline_xy_from_triangles(tris, sample_step_mm=1.0)
    if outline is None or outline.size == 0:
        return []
    return [(float(x), float(y)) for x, y in outline]


def _load_dxf(path: str) -> List[Point2D]:
    try:
        import ezdxf
    except Exception as exc:
        raise RuntimeError("DXF için ezdxf gerekli") from exc

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    paths: List[List[Point2D]] = []

    for entity in msp:
        dtype = entity.dxftype()
        if dtype == "LINE":
            start = entity.dxf.start
            end = entity.dxf.end
            paths.append([(float(start.x), float(start.y)), (float(end.x), float(end.y))])
        elif dtype == "LWPOLYLINE":
            pts = [(float(x), float(y)) for x, y in entity.get_points("xy")]
            if entity.closed and pts:
                pts.append(pts[0])
            if len(pts) >= 2:
                paths.append(pts)
        elif dtype == "POLYLINE":
            pts = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices()]
            if entity.is_closed and pts:
                pts.append(pts[0])
            if len(pts) >= 2:
                paths.append(pts)

    return _select_best_path(paths)


def _select_best_path(paths: List[List[Point2D]]) -> List[Point2D]:
    if not paths:
        return []
    best = None
    best_score = (-1, -1.0)
    for path in paths:
        score = (len(path), _path_length(path))
        if score > best_score:
            best = path
            best_score = score
    return best or []


def _path_length(points: List[Point2D]) -> float:
    total = 0.0
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        total += math.hypot(x1 - x0, y1 - y0)
    return total
