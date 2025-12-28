from typing import Optional

import numpy as np

try:
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
except Exception:
    Polygon = None
    unary_union = None

try:
    from toolpath_generator import smooth_closed_polyline, resample_polyline_ndarray
except Exception:
    smooth_closed_polyline = None
    resample_polyline_ndarray = None


def extract_outline_xy_from_triangles(tris: np.ndarray, sample_step_mm: float = 0.0) -> np.ndarray:
    if tris is None:
        return np.zeros((0, 2), dtype=np.float32)
    tris = np.asarray(tris, dtype=np.float32)
    if tris.size == 0:
        return np.zeros((0, 2), dtype=np.float32)

    faces = tris.reshape(-1, 3, 3)
    normals = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    faces = faces[normals[:, 2] > 0.0]
    if faces.size == 0:
        return np.zeros((0, 2), dtype=np.float32)

    outline_xy: Optional[np.ndarray] = None
    if Polygon is not None and unary_union is not None:
        try:
            polys = []
            for face in faces:
                poly = Polygon(face[:, :2])
                if poly.is_valid and not poly.is_empty:
                    polys.append(poly)
            if polys:
                merged = unary_union(polys)
                outer = None
                if isinstance(merged, Polygon):
                    outer = merged
                else:
                    max_area = 0.0
                    for g in getattr(merged, "geoms", []):
                        if isinstance(g, Polygon):
                            area = float(g.area)
                            if area > max_area:
                                max_area = area
                                outer = g
                if outer is not None:
                    x, y = outer.exterior.coords.xy
                    outline_xy = np.column_stack([x, y]).astype(np.float32)
        except Exception:
            outline_xy = None

    if outline_xy is None or outline_xy.shape[0] < 3:
        pts_xy = faces.reshape(-1, 3)[:, :2]
        outline_xy = _convex_hull(pts_xy)

    if outline_xy is None or outline_xy.size == 0:
        return np.zeros((0, 2), dtype=np.float32)

    if outline_xy.shape[0] > 1 and np.allclose(outline_xy[0], outline_xy[-1]):
        outline_xy = outline_xy[:-1]

    if sample_step_mm and sample_step_mm > 0.0:
        if smooth_closed_polyline is not None and resample_polyline_ndarray is not None:
            outline_xy = smooth_closed_polyline(outline_xy)
            outline_xy = resample_polyline_ndarray(outline_xy, float(sample_step_mm))

    return outline_xy.astype(np.float32, copy=False)


def _convex_hull(points_xy: np.ndarray) -> np.ndarray:
    pts = np.unique(np.round(points_xy, 6), axis=0)
    if pts.shape[0] < 3:
        return pts.astype(np.float32)
    pts = pts[pts[:, 0].argsort()]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(tuple(p))

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(tuple(p))

    hull = lower[:-1] + upper[:-1]
    return np.array(hull, dtype=np.float32)
