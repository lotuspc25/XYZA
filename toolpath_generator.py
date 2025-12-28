import logging
import math
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

import numpy as np

from project_state import ToolpathPoint  # Use shared ToolpathPoint model (single source).

try:
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
except Exception:
    Polygon = None
    unary_union = None

try:
    import trimesh
except ImportError:
    trimesh = None

logger = logging.getLogger(__name__)

# toolpath_generator.py
# Tangential knife STL dış kontur + Z-takipli yol üretimi ve G-kod

def _signed_area(xy: np.ndarray) -> float:
    if xy is None or len(xy) < 3:
        return 0.0
    x = xy[:, 0]
    y = xy[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))

Z_MODE_CODES = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
Z_MODE_NAMES = {
    'A': 'A - Ust yuzey (max Z)',
    'B': 'B - Orta (min+max)/2',
    'C': 'C - Alt yuzey (min Z)',
    'D': 'D - Ust yuzey (Continuity / en yakin Z)',
    'E': 'E - Alt yuzey (Continuity / en yakin Z)',
    'F': 'F - Continuity (normal benzerligi + Z yakinligi)',
    'G': 'G - En yakin hit (3D mesafe)',
    'H': 'H - Cift yon ray + continuity',
}


Z_CONT_WZ = 1.0
Z_CONT_WN = 5.0
Z_CONT_GAP_MM = 5.0



# ----------------------------------------------------------
# Data class
# ----------------------------------------------------------

@dataclass
class GCodeConfig:
    """
    G-code üretiminde kullanılan format ve parametreler.
    """
    feed_xy_cut: float = 2000.0
    feed_z_cut: float = 500.0
    feed_travel: float = 4000.0
    safe_z_mm: float = 5.0
    spindle_on_cmd: str = "M3 S10000"
    spindle_off_cmd: str = "M5"
    header_lines: List[str] = None
    footer_lines: List[str] = None

    def __post_init__(self):
        if self.header_lines is None:
            self.header_lines = [
                "(Program start)",
                "G21",
                "G90 G94",
                "G17",
            ]
        if self.footer_lines is None:
            self.footer_lines = [
                "G0 Z{:.3f} F{:.2f}".format(self.safe_z_mm, self.feed_travel),
                self.spindle_off_cmd,
                "M30",
            ]


@dataclass
class PathIssue:
    """
    Takım yolu analizinde tespit edilen olası problem.
    type:
        - "A_JUMP" : A açısında ani sıçrama
        - "Z_SPIKE": Z ekseninde ani tepe veya çukur
        - "DIR_SHARP": Yön değiştirmede keskin kırılma
    severity:
        - A_JUMP için derece cinsinden mutlak değişim
        - Z_SPIKE için mm cinsinden mutlak değişim
    """
    index: int
    type: str
    severity: float
    description: str


def resample_polyline_by_step(points: List[ToolpathPoint], step_mm: float, max_dev_mm: float) -> List[ToolpathPoint]:
    """
    Polyline'ı hedef adım uzunluğuna göre yeniden örnekler; X/Y/Z/A değerleri lineer interpolasyonla hesaplanır.
    """
    if not points:
        return []
    if step_mm <= 0.0:
        return [ToolpathPoint(p.x, p.y, p.z, 0.0) for p in points]

    cum_s = [0.0]
    for i in range(1, len(points)):
        dx = points[i].x - points[i - 1].x
        dy = points[i].y - points[i - 1].y
        dz = points[i].z - points[i - 1].z
        ds = math.sqrt(dx * dx + dy * dy + dz * dz)
        cum_s.append(cum_s[-1] + ds)

    total_len = cum_s[-1]
    if total_len <= 1e-6:
        return [ToolpathPoint(p.x, p.y, p.z, 0.0) for p in points]

    target_s = []
    s = 0.0
    while s < total_len:
        target_s.append(s)
        s += step_mm
    if target_s[-1] < total_len:
        target_s.append(total_len)

    resampled: List[ToolpathPoint] = []
    j = 0
    for ts in target_s:
        while j < len(cum_s) - 2 and cum_s[j + 1] < ts:
            j += 1
        s0 = cum_s[j]
        s1 = cum_s[j + 1]
        t = 0.0 if (s1 - s0) < 1e-6 else (ts - s0) / (s1 - s0)

        p0 = points[j]
        p1 = points[j + 1]

        x = p0.x + t * (p1.x - p0.x)
        y = p0.y + t * (p1.y - p0.y)
        z = p0.z + t * (p1.z - p0.z)
        a = p0.a + t * (p1.a - p0.a)

        # A açısı bu aşamada hesaplanmaz, sonradan eklenecek
        resampled.append(ToolpathPoint(x, y, z, 0.0))

    # İsteğe bağlı chord error iyileştirmesi için max_dev_mm kullanılabilir; şimdilik örnekleme sabit tutuluyor.
    return resampled


# ----------------------------------------------------------
# Analiz yardımcıları
# ----------------------------------------------------------
def validate_toolpath(
    points: Iterable[ToolpathPoint],
    table_width_mm: Optional[float] = None,
    table_height_mm: Optional[float] = None,
    z_min_mm: Optional[float] = None,
    z_max_mm: Optional[float] = None,
    enable_z_max_check: bool = False,
    a_min_deg: Optional[float] = None,
    a_max_deg: Optional[float] = None,
) -> List[PathIssue]:
    """
    Takım yolu noktalarını temel geometrik ve mekanik sınırlara göre doğrular.

    Parametreler:
        points          : ToolpathPoint listesi
        table_width_mm  : tabla genişliği (X yönü, mm)
        table_height_mm : tabla yüksekliği (Y yönü, mm)
        z_min_mm        : izin verilen minimum Z
        z_max_mm        : izin verilen maksimum Z
        enable_z_max_check : True ise z_max_mm üst sınırı da kontrol edilir
        a_min_deg       : A açısı alt limiti
        a_max_deg       : A açısı üst limiti

    Dönen:
        PathIssue listesi (her biri bir uyarı/hata temsil eder)
    """
    issues: List[PathIssue] = []
    pts = list(points)

    for i, p in enumerate(pts):
        # NaN / eksik kontrolü
        if any(math.isnan(v) for v in (p.x, p.y, p.z, p.a)):
            issues.append(
                PathIssue(
                    index=i,
                    type="INVALID_NUM",
                    severity=0.0,
                    description="Nokta NaN veya geçersiz sayısal değer içeriyor.",
                )
            )
            continue

        if table_width_mm is not None:
            if p.x < 0.0 or p.x > table_width_mm:
                issues.append(
                    PathIssue(
                        index=i,
                        type="X_OUT_OF_TABLE",
                        severity=float(p.x),
                        description=f"X koordinatı tabla dışına taşıyor (X={p.x:.3f} mm).",
                    )
                )

        if table_height_mm is not None:
            if p.y < 0.0 or p.y > table_height_mm:
                issues.append(
                    PathIssue(
                        index=i,
                        type="Y_OUT_OF_TABLE",
                        severity=float(p.y),
                        description=f"Y koordinatı tabla dışına taşıyor (Y={p.y:.3f} mm).",
                    )
                )

        if z_min_mm is not None and p.z < z_min_mm:
            issues.append(
                PathIssue(
                    index=i,
                    type="Z_TOO_LOW",
                    severity=float(z_min_mm - p.z),
                    description=f"Z değeri izin verilen minimumun altında (Z={p.z:.3f} mm).",
                )
            )

        if enable_z_max_check and z_max_mm is not None and p.z > z_max_mm:
            issues.append(
                PathIssue(
                    index=i,
                    type="Z_TOO_HIGH",
                    severity=float(p.z - z_max_mm),
                    description=f"Z değeri izin verilen maksimumun üzerinde (Z={p.z:.3f} mm).",
                )
            )

        if a_min_deg is not None and p.a < a_min_deg:
            issues.append(
                PathIssue(
                    index=i,
                    type="A_BELOW_LIMIT",
                    severity=float(a_min_deg - p.a),
                    description=f"A açısı izin verilen minimumun altında (A={p.a:.2f}°).",
                )
            )

        if a_max_deg is not None and p.a > a_max_deg:
            issues.append(
                PathIssue(
                    index=i,
                    type="A_ABOVE_LIMIT",
                    severity=float(p.a - a_max_deg),
                    description=f"A açısı izin verilen maksimumun üzerinde (A={p.a:.2f}°).",
                )
            )

    return issues


def _unwrap_angle_delta(a1: float, a2: float) -> float:
    """
    A eksenindeki iki açı arasındaki gerçek farkı (-180, +180] aralığında döndürür.
    """
    delta = (a2 - a1 + 180.0) % 360.0 - 180.0
    return delta


def _angle_between_vectors(v1: Tuple[float, float], v2: Tuple[float, float]) -> float:
    """
    İki 2B vektör arasındaki açıyı derece cinsinden döndürür.
    Vektörlerden biri çok küçükse 0 döner.
    """
    x1, y1 = v1
    x2, y2 = v2
    n1 = math.hypot(x1, y1)
    n2 = math.hypot(x2, y2)
    if n1 < 1e-6 or n2 < 1e-6:
        return 0.0
    dot = (x1 * x2 + y1 * y2) / (n1 * n2)
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot))


def _point_segment_distance_xy(p: ToolpathPoint, a: ToolpathPoint, b: ToolpathPoint) -> float:
    """
    XY düzleminde bir noktanın [a,b] doğru parçasına olan en kısa uzaklığını (mm) döndürür.
    """
    ax, ay = a.x, a.y
    bx, by = b.x, b.y
    px, py = p.x, p.y

    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay

    seg_len2 = vx * vx + vy * vy
    if seg_len2 <= 1e-9:
        return math.hypot(wx, wy)

    t = (wx * vx + wy * vy) / seg_len2
    if t < 0.0:
        proj_x, proj_y = ax, ay
    elif t > 1.0:
        proj_x, proj_y = bx, by
    else:
        proj_x = ax + t * vx
        proj_y = ay + t * vy

    dx = px - proj_x
    dy = py - proj_y
    return math.hypot(dx, dy)


def analyze_toolpath(
    points: Iterable[ToolpathPoint],
    angle_threshold_deg: float = 60.0,
    z_threshold_mm: float = 5.0,
    dir_threshold_deg: float = 40.0,
    xy_spike_threshold_mm: float = 0.3,
) -> List[PathIssue]:
    """
    Takım yolu noktalarında olası problemleri analiz eder:
    - A ekseninde ani açı değişimi (A_JUMP)
    - Z ekseninde ani dalgalanma (Z_SPIKE)
    - XY düzleminde keskin yön değişimi (DIR_SHARP)
    - XY düzleminde lokal sapma / çıkıntı / oyuk (XY_SPIKE)
    """
    pts = list(points)
    issues: List[PathIssue] = []

    if len(pts) < 3:
        return issues

    for i in range(1, len(pts)):
        p_prev = pts[i - 1]
        p = pts[i]

        d_a = _unwrap_angle_delta(p_prev.a, p.a)
        if abs(d_a) >= angle_threshold_deg:
            desc = (
                f"A ekseninde ani değişim: {p_prev.a:.1f}° -> {p.a:.1f}° "
                f"(|ΔA| = {abs(d_a):.1f}°)"
            )
            issues.append(
                PathIssue(
                    index=i,
                    type="A_JUMP",
                    severity=abs(d_a),
                    description=desc,
                )
            )

        d_z = p.z - p_prev.z
        if abs(d_z) >= z_threshold_mm:
            desc = (
                f"Z ekseninde ani değişim: {p_prev.z:.3f} mm -> {p.z:.3f} mm "
                f"(|ΔZ| = {abs(d_z):.3f} mm)"
            )
            issues.append(
                PathIssue(
                    index=i,
                    type="Z_SPIKE",
                    severity=abs(d_z),
                    description=desc,
                )
            )

    for i in range(1, len(pts) - 1):
        p0 = pts[i - 1]
        p1 = pts[i]
        p2 = pts[i + 1]
        v1 = (p1.x - p0.x, p1.y - p0.y)
        v2 = (p2.x - p1.x, p2.y - p1.y)
        ang = _angle_between_vectors(v1, v2)

        if ang > 0.0 and ang <= dir_threshold_deg:
            desc = (
                f"XY düzleminde keskin yön değişimi: "
                f"nokta #{i} civarında (yaklaşık {ang:.1f}°)"
            )
            issues.append(
                PathIssue(
                    index=i,
                    type="DIR_SHARP",
                    severity=ang,
                    description=desc,
                )
            )

    # XY düzleminde lokal sapmalar için kontrol (XY_SPIKE)
    # XY düzleminde lokal sapmalar (XY_SPIKE)
    # Daha geniş bir pencere kullan: p[i-5] ile p[i+5] arasındaki doğru.
    # Böylece yumurta/böbrek benzeri 0.5 mm ve üzeri şişkinlikler daha net ortaya çıkıyor.
    if (
        xy_spike_threshold_mm is not None
        and xy_spike_threshold_mm > 0.0
        and len(pts) >= 11
    ):
        for i in range(5, len(pts) - 5):
            p = pts[i]
            p_a = pts[i - 5]
            p_b = pts[i + 5]

            d_xy = _point_segment_distance_xy(p, p_a, p_b)
            if d_xy >= xy_spike_threshold_mm:
                desc = (
                    "Kontur üzerinde lokal çıkıntı/oyuk: "
                    f"referans hattından sapma ≈ {d_xy:.3f} mm"
                )
                issues.append(
                    PathIssue(
                        index=i,
                        type="XY_SPIKE",
                        severity=float(d_xy),
                        description=desc,
                    )
                )

    return issues

# ----------------------------------------------------------
# GLTableViewer'dan dünya koordinatında üçgen üret
# ----------------------------------------------------------
def build_world_triangles(viewer) -> Optional[np.ndarray]:
    verts = viewer.mesh_vertices
    if verts is None or viewer.mesh_vertex_count == 0:
        return None

    verts = verts.reshape(-1, 3).copy()

    # G54 orijin + model offsetleri ekle (mesh zaten rotasyon + scale uygulanmış)
    ox, oy = viewer._compute_origin_point()
    verts[:, 0] += ox + viewer.model_offset_x
    verts[:, 1] += oy + viewer.model_offset_y
    verts[:, 2] += viewer.model_offset_z

    num_tris = verts.shape[0] // 3
    tris = verts[: num_tris * 3].reshape(num_tris, 3, 3)
    return tris.astype(np.float32)


def build_trimesh_from_viewer(viewer) -> Optional["trimesh.Trimesh"]:
    """GLTableViewer içindeki üçgenleri trimesh'e dönüştürür."""
    tris = build_world_triangles(viewer)
    if tris is None or tris.size == 0 or trimesh is None:
        return None
    verts = tris.reshape(-1, 3)
    faces = np.arange(verts.shape[0], dtype=np.int32).reshape(-1, 3)
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    if mesh.vertices.size == 0 or mesh.faces.size == 0:
        return None
    return mesh


# ----------------------------------------------------------
# Geometri yardımcıları
# ----------------------------------------------------------
def smooth_closed_polyline(xy: np.ndarray, w_center: float = 0.7, w_neighbor: float = 0.15) -> np.ndarray:
    """Kapalı halkada p_i = w_center*pi + w_neighbor*(p_{i-1}+p_{i+1}) uygular."""
    if xy is None or len(xy) < 3:
        return xy
    pts = xy.astype(np.float32, copy=False)
    n = len(pts)
    out = np.zeros_like(pts)
    for i in range(n):
        p_prev = pts[(i - 1) % n]
        p_curr = pts[i]
        p_next = pts[(i + 1) % n]
        out[i] = w_center * p_curr + w_neighbor * p_prev + w_neighbor * p_next
    return out


def resample_polyline_ndarray(poly: np.ndarray, step: float) -> np.ndarray:
    """Polyline'ı yaklaşık eşit aralıklı noktalarla yeniden örnekler."""
    if poly is None or len(poly) < 2 or step <= 0:
        return poly
    pts = poly.astype(np.float32, copy=False)
    if not np.allclose(pts[0], pts[-1]):
        pts = np.vstack([pts, pts[0]])
    segs = np.diff(pts, axis=0)
    seg_len = np.linalg.norm(segs, axis=1)
    total = float(np.sum(seg_len))
    if total <= 0.0:
        return poly
    n_samples = max(2, int(total / step))
    distances = np.concatenate([[0.0], np.cumsum(seg_len)])
    t_vals = np.linspace(0.0, total, n_samples, endpoint=True)
    res = []
    for t in t_vals:
        idx = np.searchsorted(distances, t, side="right") - 1
        idx = max(0, min(idx, len(seg_len) - 1))
        t0 = distances[idx]
        t1 = distances[idx + 1]
        alpha = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
        p = pts[idx] + alpha * (pts[idx + 1] - pts[idx])
        res.append(p)
    return np.array(res, dtype=np.float32)


def smooth_array(values: List[float], window: int = 5) -> List[float]:
    if values is None:
        return []
    if window <= 1:
        return list(values)
    arr = np.array(values, dtype=np.float32).flatten()
    if arr.size == 0:
        return []
    w = min(window, len(arr))
    pad = w // 2
    arr_pad = np.concatenate([arr[-pad:], arr, arr[:pad]])
    kernel = np.ones(w, dtype=np.float32) / w
    smoothed = np.convolve(arr_pad, kernel, mode="valid")
    return smoothed.tolist()


# ----------------------------------------------------------
# XY dış kontur üretimi
# ----------------------------------------------------------
def _convex_hull(points: np.ndarray) -> np.ndarray:
    """Monotone chain convex hull."""
    pts = np.unique(np.round(points, 6), axis=0)
    if pts.shape[0] < 3:
        return np.zeros((0, 2), dtype=np.float32)
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


def generate_outline_xy(
    gl_viewer,
    sample_step_mm: float = 1.0,
    offset_mm: float = 0.0,
    progress_cb=lambda p, m="": None,
) -> np.ndarray:
    """
    STL'nin üstten görünümdeki (XY) dış konturunu üretir.
    Döndürür: shape (N, 2) float32, kapalıya yakın (ilk ≈ son).
    """
    tris = build_world_triangles(gl_viewer)
    if tris is None or tris.size == 0:
        progress_cb(100, "Üçgen bulunamadı")
        return np.zeros((0, 2), dtype=np.float32)

    # Yukarı bakan üçgenleri filtrele (normal.z > 0)
    filtered_tris = []
    for tri in tris:
        v0, v1, v2 = tri
        n = np.cross(v1 - v0, v2 - v0)
        if n[2] > 0.0:
            filtered_tris.append(tri)

    if not filtered_tris:
        progress_cb(100, "Yukarı bakan üçgen bulunamadı")
        return np.zeros((0, 2), dtype=np.float32)

    tris_up = np.array(filtered_tris, dtype=np.float32)

    outline_xy = None
    if Polygon is not None and unary_union is not None:
        try:
            polys = []
            faces = tris_up.reshape(-1, 3, 3)
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
                        if isinstance(g, Polygon) and g.area > max_area:
                            max_area = g.area
                            outer = g
                if outer is not None and outer.exterior:
                    geom = outer
                    if abs(offset_mm) > 1e-9:
                        buffered = outer.buffer(offset_mm)
                        if buffered is not None:
                            if isinstance(buffered, Polygon):
                                geom = buffered
                            else:
                                max_area = 0.0
                                chosen = None
                                for g in getattr(buffered, "geoms", []):
                                    if isinstance(g, Polygon) and g.area > max_area:
                                        max_area = g.area
                                        chosen = g
                                if chosen is not None:
                                    geom = chosen
                    coords = np.array(geom.exterior.coords, dtype=np.float32)
                    outline_xy = coords[:, :2]
        except Exception:
            outline_xy = None

    if outline_xy is None or outline_xy.shape[0] < 3:
        verts = tris_up.reshape(-1, 3)
        outline_xy = _convex_hull(verts[:, :2])

    if outline_xy.shape[0] > 1 and np.allclose(outline_xy[0], outline_xy[-1]):
        outline_xy = outline_xy[:-1]

    outline_xy = smooth_closed_polyline(outline_xy)
    outline_xy = resample_polyline_ndarray(outline_xy, sample_step_mm)

    progress_cb(40, "XY dış kontur hazır...")
    return outline_xy


# ----------------------------------------------------------
# Açı hesabı ve Z takip
# ----------------------------------------------------------
def compute_angles_from_xy(xy: np.ndarray) -> np.ndarray:
    n = len(xy)
    if n < 2:
        return np.zeros((n,), dtype=np.float32)
    angles = np.zeros(n, dtype=np.float32)
    for i in range(n):
        p_prev = xy[(i - 1) % n]
        p_next = xy[(i + 1) % n]
        v = p_next - p_prev
        ang = np.degrees(np.arctan2(v[1], v[0]))
        angles[i] = ((ang + 180.0) % 360.0) - 180.0
    return angles.astype(np.float32)


def unwrap_angles_deg(angles: np.ndarray) -> np.ndarray:
    if angles is None or len(angles) == 0:
        return angles
    unwrapped = angles.astype(np.float64).copy()
    for i in range(1, len(unwrapped)):
        diff = unwrapped[i] - unwrapped[i - 1]
        if diff > 180.0:
            unwrapped[i:] -= 360.0
        elif diff < -180.0:
            unwrapped[i:] += 360.0
    return unwrapped.astype(np.float32)


def angle_diff_deg(target: float, current: float) -> float:
    diff = (target - current + 180.0) % 360.0 - 180.0
    return diff


def angle_lerp_deg(current: float, target: float, alpha: float) -> float:
    diff = angle_diff_deg(target, current)
    return current + alpha * diff


def compute_z_for_points(
    mesh,
    points_xy: np.ndarray,
    mode: str,
    out_stats: Optional[dict] = None,
    intersector_cache=None,
    mesh_version: Optional[int] = None,
) -> np.ndarray:
    """
    Verilen XY noktalar? i?in STL mesh'ine ???n g?ndererek Z de?eri bulur.
    Modlar:
        A: ?st y?zey (max Z)
        B: (min+max)/2
        C: alt y?zey (min Z)
        D: ?st y?zey continuity (prev Z'ye en yak?n, yoksa max)
        E: alt y?zey continuity (prev Z'ye en yak?n, yoksa min)
        F: continuity (normal benzerli?i + Z yak?nl???)
        G: en yak?n 3D hit
        H: ?ift y?n ray (?st+alt) + continuity
    """
    if out_stats is not None:
        out_stats.clear()
        out_stats.update({
            'multi_hit_points': 0,
            'continuity_used': 0,
            'fallback_count': 0,
            'mode': mode,
        })

    if mesh is None or points_xy is None or len(points_xy) == 0:
        return np.zeros((0,), dtype=np.float32)
    bounds = getattr(mesh, 'bounds', None)
    if bounds is None or len(bounds) < 2:
        return np.zeros((len(points_xy),), dtype=np.float32)
    z_min = float(bounds[0][2])
    z_max = float(bounds[1][2])
    margin = max(1.0, (z_max - z_min) * 0.1)
    cont_gap_thresh = max(Z_CONT_GAP_MM, (z_max - z_min) * 0.05)

    intersector = None
    if intersector_cache is not None:
        intersector = intersector_cache.get(mesh, mesh_version=mesh_version)
    if intersector is None:
        intersector = getattr(mesh, "ray", None)

    def _collect_hits(origins, directions):
        hits_per_point = [[] for _ in range(len(points_xy))]
        if intersector is None:
            return hits_per_point
        try:
            locs, ray_idx, tri_idx = intersector.intersects_location(
                ray_origins=origins, ray_directions=directions, multiple_hits=True
            )
        except Exception:
            return hits_per_point
        if locs is None or len(locs) == 0:
            return hits_per_point
        normals_mesh = getattr(intersector, "mesh", mesh)
        face_normals = getattr(normals_mesh, 'face_normals', None)
        for pt, ridx, fidx in zip(locs, ray_idx, tri_idx):
            if ridx is None or ridx < 0 or ridx >= len(hits_per_point):
                continue
            normal = None
            try:
                if face_normals is not None and fidx is not None and fidx < len(face_normals):
                    normal = np.array(face_normals[int(fidx)], dtype=np.float64)
            except Exception:
                normal = None
            hits_per_point[int(ridx)].append((float(pt[0]), float(pt[1]), float(pt[2]), normal))
        return hits_per_point

    origins_down = np.column_stack([
        points_xy.astype(np.float64),
        np.full(len(points_xy), z_max + margin, dtype=np.float64),
    ])
    directions_down = np.tile(np.array([0.0, 0.0, -1.0], dtype=np.float64), (len(points_xy), 1))
    hits_per_point = _collect_hits(origins_down, directions_down)

    if mode == 'H':
        origins_up = np.column_stack([
            points_xy.astype(np.float64),
            np.full(len(points_xy), z_min - margin, dtype=np.float64),
        ])
        directions_up = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float64), (len(points_xy), 1))
        hits_up = _collect_hits(origins_up, directions_up)
        for i, hits in enumerate(hits_up):
            if hits:
                hits_per_point[i].extend(hits)

    z_vals = np.full(len(points_xy), z_min, dtype=np.float32)
    prev_hit = None

    def _choose_hit(prev, hits_list):
        if not hits_list:
            return None, False
        zs = [h[2] for h in hits_list]
        z_hi = max(zs)
        z_lo = min(zs)
        if mode == 'A':
            return max(hits_list, key=lambda h: h[2]), False
        if mode == 'B':
            mid = (z_hi + z_lo) * 0.5
            return (hits_list[0][0], hits_list[0][1], mid, hits_list[0][3]), False
        if mode == 'C':
            return min(hits_list, key=lambda h: h[2]), False

        if prev is None:
            if mode in ('D', 'F', 'H'):
                return max(hits_list, key=lambda h: h[2]), False
            if mode == 'E':
                return min(hits_list, key=lambda h: h[2]), False
            if mode == 'G':
                return max(hits_list, key=lambda h: h[2]), False

        fallback = False
        if mode in ('D', 'E', 'H'):
            prev_z = prev[2] if prev is not None else None
            if prev_z is None:
                chosen = max(hits_list, key=lambda h: h[2])
            else:
                chosen = min(hits_list, key=lambda h: abs(h[2] - prev_z))
                if abs(chosen[2] - prev_z) > cont_gap_thresh:
                    fallback = True
                    chosen = max(hits_list, key=lambda h: h[2]) if mode in ('D', 'H') else min(hits_list, key=lambda h: h[2])
            return chosen, fallback

        if mode == 'F':
            prev_z = prev[2] if prev is not None else 0.0
            prev_n = prev[3]
            best = None
            best_score = None
            for h in hits_list:
                dz = abs(h[2] - prev_z)
                dot = 0.0
                if prev_n is not None and h[3] is not None:
                    try:
                        dot = float(np.dot(prev_n, h[3]) / (np.linalg.norm(prev_n) * np.linalg.norm(h[3]) + 1e-9))
                    except Exception:
                        dot = 0.0
                score = Z_CONT_WZ * dz - Z_CONT_WN * dot
                if best_score is None or score < best_score:
                    best_score = score
                    best = h
            return best, False

        if mode == 'G':
            prev_pt = prev
            if prev_pt is None:
                return max(hits_list, key=lambda h: h[2]), False
            best = None
            best_d = None
            for h in hits_list:
                dx = h[0] - prev_pt[0]
                dy = h[1] - prev_pt[1]
                dz = h[2] - prev_pt[2]
                d = math.sqrt(dx * dx + dy * dy + dz * dz)
                if best_d is None or d < best_d:
                    best_d = d
                    best = h
            return best, False

        return max(hits_list, key=lambda h: h[2]), False

    continuity_modes = {'D', 'E', 'F', 'G', 'H'}
    for i in range(len(points_xy)):
        hits = hits_per_point[i] if i < len(hits_per_point) else []
        if out_stats is not None and len(hits) > 1:
            out_stats['multi_hit_points'] += 1
        chosen, fallback = _choose_hit(prev_hit, hits)
        if chosen is None:
            z_vals[i] = z_min
            continue
        z_vals[i] = float(chosen[2])
        if out_stats is not None and prev_hit is not None and mode in continuity_modes and len(hits) > 0:
            out_stats['continuity_used'] += 1
        if out_stats is not None and fallback:
            out_stats['fallback_count'] += 1
        prev_hit = chosen

    if out_stats is not None:
        logger.info(
            'Z mode %s: multi_hit=%d continuity=%d fallback=%d',
            mode,
            out_stats.get('multi_hit_points', 0),
            out_stats.get('continuity_used', 0),
            out_stats.get('fallback_count', 0),
        )

    # NOTE: Return here; legacy fallback block was unreachable after the first return.
    return z_vals


def build_toolpath_points(xy: np.ndarray, z_vals: np.ndarray, angles_deg: np.ndarray) -> List[ToolpathPoint]:
    """XY, Z ve açı dizilerinden ToolpathPoint listesi oluşturur."""
    n = min(len(xy), len(z_vals), len(angles_deg))
    pts: List[ToolpathPoint] = []
    for i in range(n):
        pts.append(
            ToolpathPoint(
                x=float(xy[i, 0]),
                y=float(xy[i, 1]),
                z=float(z_vals[i]),
                a=float(angles_deg[i]),
            )
        )
    return pts


def _get_blade_radius_mm(settings) -> float:
    """
    Bıçak ucu çapı ayarından yarıçap (mm) okur.
    Öncelik: blade_diameter_mm > knife_tip_diam[_mm] > tip_diameter_mm > tool_radius_mm.
    """
    if settings is None:
        return 0.0
    diameter_keys = (
        "blade_diameter_mm",
        "knife_tip_diam",
        "knife_tip_diam_mm",
        "tip_diameter_mm",
        "tip_diameter",
    )
    for key in diameter_keys:
        try:
            val = float(getattr(settings, key, 0.0))
            if val > 0.0:
                return val * 0.5
        except Exception:
            continue
    try:
        rad = float(getattr(settings, "tool_radius_mm", 0.0))
        if rad > 0.0:
            return rad
    except Exception:
        pass
    return 0.0


# ----------------------------------------------------------
# G-kod
# ----------------------------------------------------------
def generate_gcode_from_points(points: Iterable[ToolpathPoint], cfg: GCodeConfig) -> str:
    if cfg is None:
        cfg = GCodeConfig()

    lines: List[str] = []
    lines.extend(cfg.header_lines)
    lines.append(f"G0 Z{cfg.safe_z_mm:.3f} F{cfg.feed_travel:.2f}")
    lines.append(cfg.spindle_on_cmd)

    pts = list(points)
    if not pts:
        lines.extend(cfg.footer_lines)
        return "\n".join(lines)

    p0 = pts[0]
    lines.append(f"G0 X{p0.x:.3f} Y{p0.y:.3f} F{cfg.feed_travel:.2f}")
    lines.append(f"G0 A{p0.a:.3f}")
    lines.append(f"G1 Z{p0.z:.3f} F{cfg.feed_z_cut:.2f}")

    for p in pts[1:]:
        lines.append(
            f"G1 X{p.x:.3f} Y{p.y:.3f} Z{p.z:.3f} A{p.a:.3f} F{cfg.feed_xy_cut:.2f}"
        )
    if len(pts) > 1:
        lines.append(
            f"G1 X{p0.x:.3f} Y{p0.y:.3f} Z{p0.z:.3f} A{p0.a:.3f} F{cfg.feed_xy_cut:.2f}"
        )

    lines.extend(cfg.footer_lines)
    return "\n".join(lines)


# ----------------------------------------------------------
# Ana fonksiyon
# ----------------------------------------------------------
def generate_outline_toolpath(
    gl_viewer,
    settings_tab,
    sample_step_mm: float = 1.0,
    offset_mm: float = 0.0,
    z_mode_index: int = 0,
    progress_cb=lambda p, m="": None,
    gcode_cfg: Optional[GCodeConfig] = None,
    generate_gcode: bool = True,
    mesh_intersector_cache=None,
    mesh_version: Optional[int] = None,
) -> Tuple[List[ToolpathPoint], str, dict]:
    """STL'den XY kontur + Z takibi + A açılarını hesaplar, ToolpathPoint listesi döndürür."""
    t0 = time.time()
    progress_cb(5, "Mesh hazırlanıyor...")
    mesh = build_trimesh_from_viewer(gl_viewer)
    if mesh is None:
        progress_cb(100, "HATA: Geçerli STL üçgeni bulunamadı.")
        return [], ""

    # Takım/kerf ayarları
    tool_type = getattr(settings_tab, "tool_type", "saw")
    tool_side = str(getattr(settings_tab, "tool_side", "center")).lower()
    try:
        saw_kerf = float(getattr(settings_tab, "saw_kerf_mm", 1.0))
    except Exception:
        saw_kerf = 1.0
    # PR-G7.2: G-code centerline, kerf telafisi uygulanmaz.
    effective_offset = offset_mm

    progress_cb(15, "XY dış kontur hesaplanıyor...")
    outline_xy = generate_outline_xy(gl_viewer, sample_step_mm, effective_offset, progress_cb)
    if outline_xy is None or outline_xy.shape[0] < 2:
        progress_cb(100, "HATA: Geçerli kontur bulunamadı.")
        return [], ""

    progress_cb(40, "Z değerleri hesaplanıyor...")
    mode = Z_MODE_CODES[z_mode_index] if 0 <= z_mode_index < len(Z_MODE_CODES) else "A"
    z_stats: dict = {}
    if mesh_version is None:
        mesh_version = getattr(gl_viewer, "mesh_version", None)
    z_vals = compute_z_for_points(
        mesh,
        outline_xy,
        mode,
        out_stats=z_stats,
        intersector_cache=mesh_intersector_cache,
        mesh_version=mesh_version,
    )

    progress_cb(60, "A a??lar? hesaplan?yor...")
    angles_raw = compute_angles_from_xy(outline_xy)
    # A ?retim kayna?? ve filtre parametreleri
    a_source = int(getattr(settings_tab, "a_source", 1)) if settings_tab is not None else 1
    a_deadband = float(getattr(settings_tab, "A_DEADBAND_DEG", getattr(settings_tab, "a_deadband_deg", 0.5))) if settings_tab is not None else 0.5
    a_max_step = float(getattr(settings_tab, "A_MAX_STEP_DEG", getattr(settings_tab, "a_max_step_deg", 5.0))) if settings_tab is not None else 5.0
    a_smooth_window = int(getattr(settings_tab, "A_SMOOTH_WINDOW", getattr(settings_tab, "a_smooth_window", 7))) if settings_tab is not None else 7
    a_corner_mode = str(getattr(settings_tab, "A_CORNER_MODE", getattr(settings_tab, "a_corner_mode", "blend"))).strip().lower() if settings_tab is not None else "blend"
    a_corner_threshold = float(getattr(settings_tab, "A_CORNER_THRESHOLD_DEG", getattr(settings_tab, "a_corner_turn_deg", 25.0))) if settings_tab is not None else 25.0
    a_alpha = float(getattr(settings_tab, "a_smooth_alpha", 0.25)) if settings_tab is not None else 0.25
    try:
        a_wrap = bool(getattr(settings_tab, "a_wrap", 1))
    except Exception:
        a_wrap = True
    try:
        a_deg_offset = float(
            getattr(
                settings_tab,
                "A_OFFSET_DEG",
                getattr(settings_tab, "a_offset_deg", getattr(settings_tab, "a_deg_offset", 0.0)),
            )
        )
    except Exception:
        a_deg_offset = 0.0
    a_reverse = bool(
        getattr(settings_tab, "A_REVERSE", getattr(settings_tab, "a_reverse", 0))
    )

    deadband_hits = 0
    hold_hits = 0
    snap_hits = 0
    max_da = 0.0
    # PR-G7.3: A source locked to XY_TANGENT
    a_source = 1
    a_min_xy_step = float(getattr(settings_tab, "a_min_xy_step_mm", 0.02)) if settings_tab is not None else 0.02
    a_alpha_straight = float(getattr(settings_tab, "a_smooth_alpha_straight", 0.25)) if settings_tab is not None else 0.25
    a_alpha_corner = float(getattr(settings_tab, "a_smooth_alpha_corner", 0.05)) if settings_tab is not None else 0.05
    a_corner_turn = float(getattr(settings_tab, "a_corner_turn_deg", 12.0)) if settings_tab is not None else 12.0
    a_snap_turn = float(getattr(settings_tab, "a_snap_turn_deg", a_corner_threshold)) if settings_tab is not None else a_corner_threshold

    # XY tangent tabanl?, unwrap + hold + deadband + corner mode + rate limit
    pts_xy = outline_xy
    n_pts = len(pts_xy)
    raw_angles = []
    turn_degs = []
    min_step_sq = a_min_xy_step * a_min_xy_step
    for i in range(n_pts):
        if n_pts < 2:
            raw_angles.append(0.0)
            turn_degs.append(0.0)
            continue
        if i == 0:
            v_c = pts_xy[1] - pts_xy[0]
        elif i == n_pts - 1:
            v_c = pts_xy[-1] - pts_xy[-2]
        else:
            v_c = pts_xy[i + 1] - pts_xy[i - 1]
        vlen2 = float(v_c[0] * v_c[0] + v_c[1] * v_c[1])
        if vlen2 < min_step_sq and raw_angles:
            ang = raw_angles[-1]
            hold_hits += 1
        else:
            ang = math.degrees(math.atan2(float(v_c[1]), float(v_c[0]))) if vlen2 > 0 else (raw_angles[-1] if raw_angles else 0.0)
        raw_angles.append(ang)
        # corner turn estimate
        if n_pts < 3:
            turn_degs.append(0.0)
        else:
            if i == 0:
                v_prev = pts_xy[1] - pts_xy[0]
                v_next = pts_xy[2] - pts_xy[1] if n_pts > 2 else v_prev
            elif i == n_pts - 1:
                v_prev = pts_xy[i] - pts_xy[i - 1]
                v_next = v_prev
            else:
                v_prev = pts_xy[i] - pts_xy[i - 1]
                v_next = pts_xy[i + 1] - pts_xy[i]
            n1 = math.hypot(float(v_prev[0]), float(v_prev[1]))
            n2 = math.hypot(float(v_next[0]), float(v_next[1]))
            if n1 < 1e-6 or n2 < 1e-6:
                turn_degs.append(0.0)
            else:
                dot = (float(v_prev[0]) * float(v_next[0]) + float(v_prev[1]) * float(v_next[1])) / (n1 * n2)
                dot = max(-1.0, min(1.0, dot))
                turn_degs.append(math.degrees(math.acos(dot)))

    angs = unwrap_angles_deg(np.array(raw_angles, dtype=np.float32)) if a_wrap else np.array(raw_angles, dtype=np.float32)
    filtered = []
    prev = angs[0] if len(angs) > 0 else 0.0
    if len(angs) > 0:
        filtered.append(prev)
    snap_left = 0
    for i in range(1, len(angs)):
        ang = angs[i]
        diff = angle_diff_deg(float(ang), float(prev))
        max_da = max(max_da, abs(diff))
        if abs(diff) < a_deadband:
            ang_target = prev
            deadband_hits += 1
        else:
            ang_target = ang
        turn = turn_degs[i] if i < len(turn_degs) else 0.0
        if a_corner_mode == "snap" and turn >= a_corner_threshold:
            alpha_eff = 1.0
            snap_hits += 1
        else:
            smooth_strength = a_alpha_straight
            if turn >= a_corner_turn:
                smooth_strength = a_alpha_corner
            if a_snap_turn > 0 and turn >= a_snap_turn:
                snap_left = max(snap_left, 2)
            if snap_left > 0:
                alpha_eff = 1.0
                snap_left -= 1
                snap_hits += 1
            else:
                alpha_eff = max(0.0, min(1.0, 1.0 - smooth_strength))
        ang_out = angle_lerp_deg(float(prev), float(ang_target), alpha_eff)
        filtered.append(ang_out)
        prev = ang_out
    angles = np.array(filtered, dtype=np.float32)
    if a_corner_mode != "snap" and a_smooth_window and a_smooth_window > 1 and len(angles) > 2:
        window = int(max(1, a_smooth_window))
        kernel = np.ones(window, dtype=np.float64) / float(window)
        angles = np.convolve(angles, kernel, mode="same").astype(np.float32)
    # rate limit
    total_a_travel = 0.0
    max_a_step = 0.0
    if len(angles) > 0:
        limited = [float(angles[0])]
        for i in range(1, len(angles)):
            step = angle_diff_deg(float(angles[i]), float(limited[-1]))
            if a_max_step > 0 and abs(step) > a_max_step:
                step = math.copysign(a_max_step, step)
            limited.append(limited[-1] + step)
            total_a_travel += abs(step)
            max_a_step = max(max_a_step, abs(step))
        angles = np.array(limited, dtype=np.float32)
    logger.info(
        "A polish: hold=%d deadband=%d snap=%d max_dA=%.3f",
        hold_hits,
        deadband_hits,
        snap_hits,
        max_da,
    )
    if isinstance(z_stats, dict):
        z_stats["total_a_travel_deg"] = float(total_a_travel)
        z_stats["max_a_step_deg"] = float(max_a_step)

    # Optional: Z-depth-based contact offset for rounded knife tip (centerline -> actual XY)
    contact_enabled = bool(getattr(settings_tab, "knife_contact_offset_enabled", 0)) if settings_tab is not None else False
    contact_side = int(getattr(settings_tab, "knife_contact_side", getattr(settings_tab, "kerf_side", 1))) if settings_tab is not None else 1
    try:
        knife_tip_diam = float(getattr(settings_tab, "knife_tip_diam", getattr(settings_tab, "knife_tip_diam_mm", 0.0)))
    except Exception:
        knife_tip_diam = 0.0
    try:
        contact_d_min = float(getattr(settings_tab, "knife_contact_d_min_mm", 0.3))
    except Exception:
        contact_d_min = 0.3
    radius = max(0.0, knife_tip_diam * 0.5)
    offset_xy = outline_xy
    if contact_enabled and radius > 0.0:
        sign = 1.0 if contact_side >= 0 else -1.0
        offset_xy = outline_xy.copy()
        for i in range(len(outline_xy)):
            z_val = float(z_vals[i]) if i < len(z_vals) else 0.0
            # NOTE: z is treated as positive-down depth; clamp to [0, R].
            zc = max(0.0, min(z_val, radius))
            d = (radius * radius - (radius - zc) ** 2) ** 0.5 if radius > 0 else 0.0
            if d < contact_d_min:
                d = 0.0
                if i > 0:
                    angles[i] = angles[i - 1]
            normal_deg = float(angles[i]) + (90.0 * sign)
            nx = math.cos(math.radians(normal_deg))
            ny = math.sin(math.radians(normal_deg))
            offset_xy[i, 0] = outline_xy[i, 0] + nx * d
            offset_xy[i, 1] = outline_xy[i, 1] + ny * d
        logger.info(
            "Knife contact offset: enabled=1 radius=%.3f d_min=%.3f side=%s",
            radius,
            contact_d_min,
            "LEFT" if sign >= 0 else "RIGHT",
        )
    elif contact_enabled:
        logger.info("Knife contact offset enabled but tip radius is invalid; using centerline.")

    # If contact model enabled, A should follow normal (not tangent).
    if contact_enabled:
        sign = 1.0 if contact_side >= 0 else -1.0
        angles = angles + (90.0 * sign)

    angles = angles + a_deg_offset
    if a_reverse:
        angles = angles + 180.0

    progress_cb(80, "Tak?m yolu noktalar? olu?turuluyor...")
    points = build_toolpath_points(offset_xy, z_vals, np.array(angles, dtype=np.float32))

    # Hedef adım (UI'daki Nokta Adımı) ile yeniden örnekle
    try:
        step_val = float(sample_step_mm)
    except Exception:
        step_val = 0.0
    if step_val > 0.0:
        max_dev = 0.05 if step_val <= 2.0 else 0.10
        points = resample_polyline_by_step(points, step_val, max_dev)

    gcode_text = ""
    if generate_gcode:
        progress_cb(90, "G-kod ?retiliyor...")
        if gcode_cfg is None:
            feed_xy = float(
                getattr(
                    settings_tab,
                    "feed_xy_mm_min",
                    getattr(settings_tab, "feed_xy", 2000.0) if settings_tab is not None else 2000.0,
                )
            )
            feed_z = float(
                getattr(
                    settings_tab,
                    "feed_z_mm_min",
                    getattr(settings_tab, "feed_z", 500.0) if settings_tab is not None else 500.0,
                )
            )
            feed_travel = float(
                getattr(settings_tab, "feed_travel_mm_min", 4000.0)
            ) if settings_tab is not None else 4000.0
            safe_z = float(
                getattr(
                    settings_tab,
                    "safe_z_mm",
                    getattr(settings_tab, "safe_z", 5.0) if settings_tab is not None else 5.0,
                )
            )
            gcode_cfg = GCodeConfig(
                feed_xy_cut=feed_xy,
                feed_z_cut=feed_z,
                feed_travel=feed_travel,
                safe_z_mm=safe_z,
                spindle_on_cmd=getattr(settings_tab, "spindle_on_cmd", "M3 S10000"),
                spindle_off_cmd=getattr(settings_tab, "spindle_off_cmd", "M5"),
            )
        gcode_text = generate_gcode_from_points(points, gcode_cfg)
    progress_cb(100, "Tamamlandı")

    t1 = time.time()
    mode_label = Z_MODE_NAMES.get(mode, mode)
    logger.info(
        "Z modu %s | multi_hit=%s continuity=%s fallback=%s | tool_type=%s tool_side=%s offset=%.3f",
        mode_label,
        z_stats.get("multi_hit_points", 0),
        z_stats.get("continuity_used", 0),
        z_stats.get("fallback_count", 0),
        tool_type,
        tool_side,
        effective_offset,
    )
    print(f"[TIMING] Takım yolu oluşturma süresi: {t1 - t0:.3f} saniye")
    return points, gcode_text, z_stats
