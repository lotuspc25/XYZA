import math
import logging
from typing import List, Optional, Tuple

from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtWidgets import QOpenGLWidget
from OpenGL.GL import *
from OpenGL.GLU import gluPerspective

from toolpath_gcode_parser import GcodeSegment
from tool_model import ToolVisualConfig
from core.knife_catalog import load_catalog
from core.knife_mesh import build_knife_mesh
from core.knife_orientation import preview_orientation, compute_tool_pose
from core.tool_library import load_active_tool_no, load_tool
from core.path_utils import find_or_create_config

logger = logging.getLogger(__name__)


def normalize_deg(angle: float) -> float:
    return (float(angle) + 180.0) % 360.0 - 180.0


class GCodeViewer3D(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments: List[GcodeSegment] = []
        self.current_index: int = -1
        self._bbox: Optional[Tuple[float, float, float, float, float, float]] = None
        self.done_count = 0
        self.tool_cfg = ToolVisualConfig()
        self.current_pose: Optional[tuple] = None
        self._kerf_quads: List[Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]] = []
        self._last_normal_xy = (1.0, 0.0)
        self.mesh_vertices: Optional[List[Tuple[float, float, float]]] = None
        self.mesh_faces: Optional[List[int]] = None
        self.mesh_visible: bool = False
        self.mesh_stride: int = 1
        self.mesh_mode: str = "solid"
        self._mesh_tris: List[Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]] = []
        self._mesh_list_id: Optional[int] = None
        self._mesh_dirty: bool = False
        self._tool_mesh_body: List[Tuple[float, float, float]] = []
        self._tool_mesh_blade: List[Tuple[float, float, float]] = []
        self._tool_profile: Optional[dict] = None
        self._tool_tip = (0.0, 0.0, 0.0)
        self._tool_base_rot_z_deg = 0.0
        self._tool_model_rx_deg = 0.0
        self._tool_model_ry_deg = 0.0
        self._tool_model_rz_deg = 0.0
        self._tool_angle_deg = 0.0
        self._tool_loaded = False
        self.origin_offset = (0.0, 0.0, 0.0)
        # Pivot turn visualization (sim-only)
        self.pivot_turn_enabled = False
        self.pivot_r_mm = 2.0
        self.pivot_steps = 12
        self.pivot_corner_deg = 25.0

        # Camera state
        self.pivot = (0.0, 0.0, 0.0)
        self.distance = 200.0
        self.yaw = -30.0
        self.pitch = 30.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._last_pos: Optional[QPoint] = None
        self._last_button: Optional[int] = None

    # ------------------------------------------------------------------ API
    def clear(self):
        self.segments = []
        self.current_index = -1
        self.done_count = 0
        self._bbox = None
        self.update()

    def set_segments(self, segments: List[GcodeSegment]):
        self.segments = segments or []
        self.current_index = -1
        self.done_count = 0
        self._update_bbox()
        self._auto_fit()
        self._build_kerf_mesh()
        self.update()

    def set_current_index(self, idx: int):
        self.current_index = max(-1, min(idx, len(self.segments) - 1))
        self.done_count = max(0, self.current_index + 1)
        if self.current_index >= 0:
            pos = self.segments[self.current_index].end
            # NOTE: Pivot uses origin-shifted coordinates to avoid jitter.
            px, py, pz = self._apply_origin(pos[0], pos[1], pos[2] or 0.0)
            self._set_pivot_to((px, py, pz), alpha=0.3)
            self.current_pose = pos
        self.update()

    def set_progress(self, done_count: int, pose: Optional[tuple] = None):
        self.done_count = max(0, min(done_count, len(self.segments)))
        self.current_index = self.done_count - 1
        if pose is not None:
            # NOTE: Pivot uses origin-shifted coordinates to avoid jitter.
            px, py, pz = self._apply_origin(pose[0], pose[1], pose[2] or 0.0)
            self._set_pivot_to((px, py, pz), alpha=0.3)
            self.current_pose = pose
        self.update()

    def fit_to_view(self):
        self._auto_fit()
        self.update()

    def _apply_view(self, pitch: float, yaw: float, fit: bool = False):
        self.pitch = float(pitch)
        self.yaw = float(yaw)
        if fit:
            self._auto_fit()
        self.update()

    def set_view_top(self):
        self._apply_view(0.0, 0.0)

    def set_view_front(self):
        self._apply_view(90.0, 0.0)

    def set_view_side(self):
        self._apply_view(0.0, 90.0)

    def set_view_isometric(self):
        self._apply_view(35.0, 45.0, fit=True)

    def set_tool_config(self, cfg: ToolVisualConfig):
        self.tool_cfg = cfg or ToolVisualConfig()
        self._build_kerf_mesh()
        logger.info(
            "Tool visual: type=%s radius=%.3f tool_r=%.3f kerf=%.3f side=%s tool_on_edge=%s",
            self.tool_cfg.tool_type,
            self.tool_cfg.saw_radius_mm,
            self.tool_cfg.tool_radius_mm,
            self.tool_cfg.kerf_mm,
            self.tool_cfg.kerf_side,
            self.tool_cfg.sim_tool_on_edge,
        )
        self.update()

    def load_knife_tool_from_settings(self, settings_ini_path: str = None, tool_ini_path: str = None):
        if settings_ini_path is None or tool_ini_path is None:
            cfg_paths = find_or_create_config()
            settings_ini_path = settings_ini_path or str(cfg_paths[0])
            tool_ini_path = tool_ini_path or str(cfg_paths[1])
        tool_no = load_active_tool_no(settings_ini_path)
        tool_data = load_tool(tool_ini_path, tool_no)
        if not tool_data:
            tool_data = self._default_tool_data()
        self._apply_tool_data(tool_data)
        self.update()

    def _default_tool_data(self) -> Optional[dict]:
        catalog = load_catalog()
        if not catalog:
            return None
        knife = catalog[0]
        data = dict(knife.defaults or {})
        data["knife_id"] = knife.id
        data["knife_profile"] = knife.kind
        data["knife_direction"] = "X_parallel"
        data["knife_angle_deg"] = 0.0
        return data

    def _profile_from_tool_data(self, tool_data: dict) -> str:
        profile = str(tool_data.get("knife_profile", "") or "").strip()
        if profile:
            return profile
        knife_id = str(tool_data.get("knife_id", "") or "").strip()
        if knife_id:
            for knife in load_catalog():
                if knife.id == knife_id:
                    return knife.kind
        return "scalpel_pointed"

    def _to_vertex_list(self, verts) -> List[Tuple[float, float, float]]:
        if verts is None:
            return []
        try:
            return [(float(x), float(y), float(z)) for x, y, z in verts]
        except Exception:
            return []

    def _apply_tool_data(self, tool_data: Optional[dict]):
        if not tool_data:
            self._tool_loaded = False
            self._tool_profile = None
            return
        profile = self._profile_from_tool_data(tool_data)
        orient = preview_orientation(str(tool_data.get("knife_direction", "")), profile)
        axis = orient.get("direction_axis", "x")
        self._tool_base_rot_z_deg = float(orient.get("base_rot_z_deg", 0.0))
        self._tool_model_rx_deg = float(orient.get("model_rx_deg", 0.0))
        self._tool_model_ry_deg = float(orient.get("model_ry_deg", 0.0))
        self._tool_model_rz_deg = float(orient.get("model_rz_deg", 0.0))
        params = {
            "blade_length_mm": float(tool_data.get("blade_length_mm", 30.0)),
            "cutting_edge_diam_mm": float(tool_data.get("cutting_edge_diam_mm", 0.2)),
            "body_diam_mm": float(tool_data.get("body_diam_mm", 6.0)),
            "blade_thickness_mm": float(tool_data.get("blade_thickness_mm", 1.0)),
            "cut_length_mm": float(tool_data.get("cut_length_mm", 10.0)),
            "disk_thickness_mm": float(tool_data.get("disk_thickness_mm", 1.0)),
            "direction_axis": axis,
        }
        self._tool_profile = dict(params)
        self._tool_profile.update(
            {
                "knife_id": tool_data.get("knife_id", ""),
                "knife_profile": profile,
                "knife_direction": tool_data.get("knife_direction", ""),
            }
        )
        if tool_data.get("disk_diameter_mm") is not None:
            try:
                self._tool_profile["disk_diameter_mm"] = float(tool_data.get("disk_diameter_mm"))
            except Exception:
                pass
        mesh = build_knife_mesh(profile, params)
        body = mesh.get("body", (None, None))
        blade = mesh.get("blade", (None, None))
        tip = mesh.get("tip", (0.0, 0.0, 0.0))
        body_verts = body[0] if isinstance(body, (list, tuple)) and len(body) > 0 else None
        blade_verts = blade[0] if isinstance(blade, (list, tuple)) and len(blade) > 0 else None
        self._tool_mesh_body = self._to_vertex_list(body_verts)
        self._tool_mesh_blade = self._to_vertex_list(blade_verts)
        try:
            self._tool_tip = (float(tip[0]), float(tip[1]), float(tip[2]))
        except Exception:
            self._tool_tip = (0.0, 0.0, 0.0)
        try:
            self._tool_angle_deg = float(tool_data.get("knife_angle_deg", 0.0))
        except Exception:
            self._tool_angle_deg = 0.0
        self._tool_loaded = True

    def set_mesh(self, vertices, faces=None, stride: int = 1, mode: str = "solid"):
        """Stl mesh verisini sim viewer'a yükle."""
        self.mesh_vertices = None
        self.mesh_faces = None
        self._mesh_tris = []
        self.mesh_stride = max(1, int(stride))
        self.mesh_mode = (mode or "solid").strip().lower()
        self._mesh_dirty = True
        if vertices is None:
            self.update()
            return
        verts_list: List[Tuple[float, float, float]] = []
        try:
            # destek: [(x,y,z), ...] veya düz liste
            if isinstance(vertices, (list, tuple)) and len(vertices) > 0 and isinstance(vertices[0], (list, tuple)):
                verts_list = [(float(x), float(y), float(z)) for x, y, z in vertices]  # type: ignore
            else:
                flat = list(vertices)
                for i in range(0, len(flat), 3):
                    verts_list.append((float(flat[i]), float(flat[i + 1]), float(flat[i + 2])))
        except Exception:
            logger.exception("Mesh vertices parse edilemedi")
            self.update()
            return
        self.mesh_vertices = verts_list
        if faces is not None:
            try:
                faces_list = list(map(int, faces))
                self.mesh_faces = faces_list
            except Exception:
                logger.exception("Mesh faces parse edilemedi")
                self.mesh_faces = None
        self._build_mesh_tris()
        self.mesh_visible = True
        self._mesh_dirty = True
        self._update_bbox()
        self.update()

    def set_mesh_visible(self, visible: bool):
        self.mesh_visible = bool(visible)
        self.update()

    def has_mesh(self) -> bool:
        return bool(self.mesh_vertices)

    def set_origin_offset(self, ox: float, oy: float, oz: float = 0.0):
        """G54 origin offset for simulation view."""
        self.origin_offset = (float(ox), float(oy), float(oz))
        self._mesh_dirty = True  # NOTE: Rebuild mesh display list after origin shift.
        self._update_bbox()
        self.update()

    def set_pivot_settings(self, enabled: bool, radius_mm: float, steps: int, corner_deg: float):
        """Köşelerde pivot dönüş için simülasyon görsel ayarları."""
        self.pivot_turn_enabled = bool(enabled)
        self.pivot_r_mm = max(0.0, float(radius_mm))
        self.pivot_steps = max(4, int(steps))
        self.pivot_corner_deg = max(0.0, float(corner_deg))
        self.update()

    def _apply_origin(self, x: float, y: float, z: float = 0.0):
        ox, oy, oz = self.origin_offset
        return (x - ox, y - oy, z - oz)

    def _build_pivot_polyline_from_segments(self, segments: List[GcodeSegment]) -> Optional[List[Tuple[float, float, float]]]:
        """Corner pivot polyline for simulation (visual-only)."""
        if not segments:
            return None
        r = float(self.pivot_r_mm)
        if r <= 0.0:
            return None
        steps = max(4, int(self.pivot_steps))
        corner_deg = float(self.pivot_corner_deg)
        # Build base polyline from cut segments only
        pts: List[Tuple[float, float, float]] = []
        for seg in segments:
            if seg.type not in ("FEED", "ARC_CW", "ARC_CCW"):
                continue
            if not pts:
                pts.append((seg.start[0], seg.start[1], seg.start[2] or 0.0))
            pts.append((seg.end[0], seg.end[1], seg.end[2] or 0.0))
        if len(pts) < 3:
            return pts
        out: List[Tuple[float, float, float]] = [pts[0]]
        for i in range(1, len(pts) - 1):
            p_prev = pts[i - 1]
            p = pts[i]
            p_next = pts[i + 1]
            v0x = p[0] - p_prev[0]
            v0y = p[1] - p_prev[1]
            v1x = p_next[0] - p[0]
            v1y = p_next[1] - p[1]
            n0 = math.hypot(v0x, v0y)
            n1 = math.hypot(v1x, v1y)
            if n0 < 1e-6 or n1 < 1e-6:
                out.append(p)
                continue
            if n0 < r * 1.05 or n1 < r * 1.05:
                out.append(p)
                continue
            dot = (v0x * v1x + v0y * v1y) / (n0 * n1)
            dot = max(-1.0, min(1.0, dot))
            turn = math.degrees(math.acos(dot))
            if turn < corner_deg:
                out.append(p)
                continue
            v0nx = v0x / n0
            v0ny = v0y / n0
            v1nx = v1x / n1
            v1ny = v1y / n1
            p_in = (p[0] - v0nx * r, p[1] - v0ny * r, p[2])
            p_out = (p[0] + v1nx * r, p[1] + v1ny * r, p[2])
            last = out[-1]
            if math.hypot(last[0] - p_in[0], last[1] - p_in[1]) > 1e-6:
                out.append(p_in)
            ang0 = math.atan2(p_in[1] - p[1], p_in[0] - p[0])
            ang1 = math.atan2(p_out[1] - p[1], p_out[0] - p[0])
            delta = ang1 - ang0
            if delta > math.pi:
                delta -= 2 * math.pi
            elif delta < -math.pi:
                delta += 2 * math.pi
            for s in range(1, steps):
                t = s / float(steps)
                ang = ang0 + delta * t
                out.append((p[0] + math.cos(ang) * r, p[1] + math.sin(ang) * r, p[2]))
            out.append(p_out)
        out.append(pts[-1])
        return out

    # ------------------------------------------------------------------ GL
    def initializeGL(self):
        glClearColor(1.0, 1.0, 1.0, 1.0)
        glEnable(GL_DEPTH_TEST)
        glLineWidth(1.5)

    def resizeGL(self, w, h):
        if h == 0:
            h = 1
        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        near = max(0.01, self.distance / 1000.0)
        far = max(1000.0, self.distance * 1000.0)
        gluPerspective(35.0, w / float(h), near, far)
        glMatrixMode(GL_MODELVIEW)

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        # camera transform
        glTranslatef(0.0, 0.0, -self.distance)
        glRotatef(self.pitch, 1.0, 0.0, 0.0)
        glRotatef(self.yaw, 0.0, 1.0, 0.0)
        glTranslatef(self.pan_x, self.pan_y, 0.0)
        glTranslatef(-self.pivot[0], -self.pivot[1], -self.pivot[2])

        self._draw_axes()
        self._draw_segments()
        self._draw_marker()
        self._draw_a_arrows()
        self._draw_tool_overlay()

    # ------------------------------------------------------------------ Draw helpers
    def _draw_axes(self):
        glDisable(GL_DEPTH_TEST)
        glBegin(GL_LINES)
        glColor3f(1.0, 0.0, 0.0)  # X
        glVertex3f(0, 0, 0)
        glVertex3f(20, 0, 0)
        glColor3f(0.0, 1.0, 0.0)  # Y
        glVertex3f(0, 0, 0)
        glVertex3f(0, 20, 0)
        glColor3f(0.0, 0.0, 1.0)  # Z
        glVertex3f(0, 0, 0)
        glVertex3f(0, 0, 20)
        glEnd()
        glEnable(GL_DEPTH_TEST)

    def _draw_segments(self):
        if not self.segments:
            return
        # STL mesh (opsiyonel)
        if self.mesh_visible and self._mesh_tris:
            self._draw_mesh_cached()
        # Remaining (center line)
        glLineWidth(1.0)
        glBegin(GL_LINES)
        for idx, seg in enumerate(self.segments):
            if idx < self.done_count:
                continue
            dx = seg.end[0] - seg.start[0]
            dy = seg.end[1] - seg.start[1]
            if math.hypot(dx, dy) < 1e-6:
                continue  # NOTE: Skip pure Z ticks in remaining path.
            glColor3f(0.5, 0.5, 0.5)
            sx, sy, sz = self._apply_origin(seg.start[0], seg.start[1], seg.start[2] or 0.0)
            ex, ey, ez = self._apply_origin(seg.end[0], seg.end[1], seg.end[2] or 0.0)
            glVertex3f(sx, sy, sz)
            glVertex3f(ex, ey, ez)
        glEnd()
        # Pivot preview overlay (visual-only)
        if self.pivot_turn_enabled and self.pivot_r_mm > 0:
            rem_segments = self.segments[self.done_count :]
            pivot_pts = self._build_pivot_polyline_from_segments(rem_segments)
            if pivot_pts and len(pivot_pts) > 2:
                glLineWidth(1.2)
                glColor3f(0.4, 0.4, 0.4)
                glBegin(GL_LINE_STRIP)
                for x, y, z in pivot_pts:
                    vx, vy, vz = self._apply_origin(x, y, z or 0.0)
                    glVertex3f(vx, vy, vz)
                glEnd()
        # Done path kerf band
        if self.tool_cfg and self.tool_cfg.enabled and self.tool_cfg.kerf_show_band and self._kerf_quads:
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            band_color = self.tool_cfg.kerf_color
            if self.tool_cfg.kerf_done_emphasis:
                alpha = min(1.0, band_color[3] * 1.5)
                band_color = (band_color[0], band_color[1], band_color[2], alpha)
            glColor4f(*band_color)
            glBegin(GL_QUADS)
            max_quads = min(self.done_count, len(self._kerf_quads))
            for i in range(max_quads):
                quad = self._kerf_quads[i]
                if quad is None:
                    continue
                v0, v1, v2, v3 = quad
                v0s = self._apply_origin(*v0)
                v1s = self._apply_origin(*v1)
                v2s = self._apply_origin(*v2)
                v3s = self._apply_origin(*v3)
                glVertex3f(*v0s); glVertex3f(*v1s); glVertex3f(*v2s); glVertex3f(*v3s)
            glEnd()
            glDisable(GL_BLEND)
        # Done centerline fallback (if kerf band off)
        if not (self.tool_cfg and self.tool_cfg.enabled and self.tool_cfg.kerf_show_band):
            width_px = 3.0
            if self.tool_cfg:
                if self.tool_cfg.done_path_width_mode == 1:
                    scale = max(0.2, min(5.0, 200.0 / max(self.distance, 1.0)))
                    width_px = max(
                        float(self.tool_cfg.done_path_min_px),
                        min(
                            float(self.tool_cfg.done_path_max_px),
                            self.tool_cfg.kerf_mm * 3.0 * scale,
                        ),
                    )
                else:
                    width_px = 3.0
            glLineWidth(width_px)
            glBegin(GL_LINES)
            for idx, seg in enumerate(self.segments):
                if idx >= self.done_count:
                    continue
                if seg.type == "RAPID":
                    glColor3f(0.3, 0.3, 0.3)
                else:
                    glColor3f(0.0, 0.6, 0.8)
                dx = seg.end[0] - seg.start[0]
                dy = seg.end[1] - seg.start[1]
                if math.hypot(dx, dy) < 1e-6:
                    continue  # NOTE: Skip pure Z ticks in done path.
                sx, sy, sz = self._apply_origin(seg.start[0], seg.start[1], seg.start[2] or 0.0)
                ex, ey, ez = self._apply_origin(seg.end[0], seg.end[1], seg.end[2] or 0.0)
                glVertex3f(sx, sy, sz)
                glVertex3f(ex, ey, ez)
            glEnd()
            glLineWidth(1.5)

    def _draw_marker(self):
        if not self.segments:
            return
        if self.current_index < 0:
            pos = self.segments[0].start
        else:
            idx = min(self.current_index, len(self.segments) - 1)
            pos = self.segments[idx].end
        glPointSize(6.0)
        glColor3f(1.0, 0.0, 0.0)
        pos = self._apply_origin(pos[0], pos[1], pos[2] or 0.0)
        glBegin(GL_POINTS)
        glVertex3f(pos[0], pos[1], pos[2])
        glEnd()
        # NOTE: Pivot follow is handled by set_progress/set_current_index.

    def _draw_a_arrows(self, step: int = 50):
        if not self.segments or self._bbox is None:
            return
        span = max(self._bbox[1] - self._bbox[0], self._bbox[3] - self._bbox[2])
        arrow_len = max(1.0, span * 0.01)
        glBegin(GL_LINES)
        glColor3f(0.2, 0.2, 0.8)
        for i in range(0, len(self.segments), step):
            seg = self.segments[i]
            a = seg.end[3] if len(seg.end) > 3 else None
            if a is None:
                continue
            rad = math.radians(normalize_deg(a))
            dx = math.cos(rad) * arrow_len
            dy = math.sin(rad) * arrow_len
            px = seg.end[0]
            py = seg.end[1]
            pz = seg.end[2] or 0.0
            px, py, pz = self._apply_origin(px, py, pz)
            glVertex3f(px, py, pz)
            glVertex3f(px + dx, py + dy, pz)
        glEnd()

    def _draw_tool_overlay(self):
        if not self.tool_cfg or not self.tool_cfg.enabled:
            return
        if not self.segments:
            return
        pose = self.current_pose
        if pose is None:
            if self.current_index >= 0:
                pose = self.segments[self.current_index].end
            else:
                pose = self.segments[0].start
        x, y, z, a = pose
        x, y, z = self._apply_origin(x, y, z or 0.0)
        a_val = a if a is not None else float(self._tool_angle_deg or 0.0)
        tool_mesh_drawn = False
        if self._tool_loaded and (self._tool_mesh_body or self._tool_mesh_blade):
            self._draw_tool_mesh(x, y, z, a_val)
            tool_mesh_drawn = True
        # Disk (saw)
        if not tool_mesh_drawn and self.tool_cfg.tool_type == "saw":
            glPushMatrix()
            # disk edge on centerline: shift by normal if enabled
            offset_x = 0.0
            offset_y = 0.0
            seg = None
            if self.current_index >= 0 and self.current_index < len(self.segments):
                seg = self.segments[self.current_index]
            elif self.segments:
                seg = self.segments[0]
            if seg is not None:
                dx = seg.end[0] - seg.start[0]
                dy = seg.end[1] - seg.start[1]
                length = math.hypot(dx, dy)
                if length > 1e-6:
                    nx = -dy / length
                    ny = dx / length
                    self._last_normal_xy = (nx, ny)
            nx, ny = self._last_normal_xy
            if self.tool_cfg.sim_tool_on_edge:
                side = 1.0 if self.tool_cfg.kerf_side >= 0 else -1.0
                offset = side * float(self.tool_cfg.tool_radius_mm)
                offset_x = nx * offset
                offset_y = ny * offset
            glTranslatef(x + offset_x, y + offset_y, z or 0.0)
            # Disk düzlemini A doğrultusuna dik (teğete paralel) konumlandır:
            # Önce Z ekseninde açıyı uygula, ardından X 90° ile diski dikey yap.
            # NOTE: Tool axis locked to world Z; only yaw around Z is applied.
            glRotatef(a_val, 0, 0, 1)
            glColor4f(*self.tool_cfg.saw_color)
            radius = max(0.1, self.tool_cfg.saw_radius_mm)
            if self.tool_cfg.sim_tool_on_edge and self.tool_cfg.tool_radius_mm > 0:
                radius = max(0.1, self.tool_cfg.tool_radius_mm)
            height = max(0.2, float(getattr(self.tool_cfg, "saw_thickness_mm", 0.5)))
            sides = 32
            # Bottom cap (at tool tip)
            glBegin(GL_TRIANGLE_FAN)
            glVertex3f(0, 0, 0)
            for i in range(sides + 1):
                ang = (2 * math.pi * i) / sides
                glVertex3f(math.cos(ang) * radius, math.sin(ang) * radius, 0)
            glEnd()
            # Top cap
            glBegin(GL_TRIANGLE_FAN)
            glVertex3f(0, 0, height)
            for i in range(sides + 1):
                ang = (2 * math.pi * i) / sides
                glVertex3f(math.cos(ang) * radius, math.sin(ang) * radius, height)
            glEnd()
            # Side wall
            glBegin(GL_QUAD_STRIP)
            for i in range(sides + 1):
                ang = (2 * math.pi * i) / sides
                cx = math.cos(ang) * radius
                cy = math.sin(ang) * radius
                glVertex3f(cx, cy, 0)
                glVertex3f(cx, cy, height)
            glEnd()
            glPopMatrix()
        # Kerf band on done path
        if self.tool_cfg.kerf_mm > 0 and self.done_count > 0:
            kerf_half = self.tool_cfg.kerf_mm * 0.5
            glColor4f(*self.tool_cfg.kerf_color)
            glLineWidth(1.0)
            glBegin(GL_LINES)
            max_idx = min(self.done_count, len(self.segments))
            for idx in range(max_idx):
                seg = self.segments[idx]
                dx = seg.end[0] - seg.start[0]
                dy = seg.end[1] - seg.start[1]
                length = math.hypot(dx, dy)
                if length < 1e-6:
                    continue
                nx = -dy / length
                ny = dx / length
                ox = nx * kerf_half
                oy = ny * kerf_half
                sx, sy, sz = self._apply_origin(seg.start[0], seg.start[1], seg.start[2] or 0.0)
                ex, ey, ez = self._apply_origin(seg.end[0], seg.end[1], seg.end[2] or 0.0)
                glVertex3f(sx + ox, sy + oy, sz)
                glVertex3f(ex + ox, ey + oy, ez)
                glVertex3f(sx - ox, sy - oy, sz)
                glVertex3f(ex - ox, ey - oy, ez)
            glEnd()

    # ------------------------------------------------------------------ Camera controls
    def wheelEvent(self, event):
        delta = event.angleDelta().y() / 120.0
        self.distance *= (1.0 - delta * 0.1)
        self.distance = max(5.0, min(10000.0, self.distance))
        self.update()

    def mousePressEvent(self, event):
        self._last_pos = event.pos()
        self._last_button = event.button()

    def mouseMoveEvent(self, event):
        if self._last_pos is None:
            return
        dx = event.x() - self._last_pos.x()
        dy = event.y() - self._last_pos.y()
        if self._last_button == Qt.LeftButton:
            self.yaw += dx * 0.4
            self.pitch += dy * 0.4
            self.pitch = max(-89.0, min(89.0, self.pitch))
        elif self._last_button == Qt.MiddleButton:
            self.pan_x += dx * 0.1
            self.pan_y -= dy * 0.1
        self._last_pos = event.pos()
        self.update()

    def mouseReleaseEvent(self, event):
        self._last_pos = None

    def mouseDoubleClickEvent(self, event):
        self.fit_to_view()
        event.accept()

    # ------------------------------------------------------------------ Helpers
    def _update_bbox(self):
        if not self.segments:
            self._bbox = None
            return
        ox, oy, oz = self.origin_offset
        xs = []
        ys = []
        zs = []
        for s in self.segments:
            xs.extend([s.start[0] - ox, s.end[0] - ox])
            ys.extend([s.start[1] - oy, s.end[1] - oy])
            zs.extend([ (s.start[2] or 0.0) - oz, (s.end[2] or 0.0) - oz ])
        if self.mesh_vertices:
            for vx, vy, vz in self.mesh_vertices:
                xs.append(vx - ox); ys.append(vy - oy); zs.append((vz or 0.0) - oz)
        self._bbox = (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))
        self.pivot = (
            0.5 * (self._bbox[0] + self._bbox[1]),
            0.5 * (self._bbox[2] + self._bbox[3]),
            0.5 * (self._bbox[4] + self._bbox[5]),
        )

    def _auto_fit(self):
        if self._bbox is None:
            return
        span = max(self._bbox[1] - self._bbox[0], self._bbox[3] - self._bbox[2], 1.0)
        self.distance = span * 1.5
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._update_bbox()

    def _set_pivot_to(self, pos: tuple, alpha: float = 0.3):
        if pos is None:
            return
        self.pivot = (
            (1 - alpha) * self.pivot[0] + alpha * pos[0],
            (1 - alpha) * self.pivot[1] + alpha * pos[1],
            (1 - alpha) * self.pivot[2] + alpha * (pos[2] or 0.0),
        )

    def _build_kerf_mesh(self):
        self._kerf_quads = []
        if not self.tool_cfg or not self.tool_cfg.enabled or not self.tool_cfg.kerf_show_band:
            return
        kerf = float(self.tool_cfg.kerf_mm)
        if kerf <= 0 or not self.segments:
            return

        kerf_half = kerf * 0.5
        miter_limit = max(1.0, float(getattr(self.tool_cfg, "kerf_miter_limit", 3.0)))
        tol = 1e-6
        self._kerf_quads = [None] * len(self.segments)
        skipped = 0

        def is_cut(seg):
            return seg.type in ("FEED", "ARC_CW", "ARC_CCW")

        def flush_run(run_points, run_seg_indices):
            if len(run_points) < 2:
                return
            # segment normals
            seg_normals = []
            for i in range(len(run_points) - 1):
                p0 = run_points[i]
                p1 = run_points[i + 1]
                dx = p1[0] - p0[0]
                dy = p1[1] - p0[1]
                length = math.hypot(dx, dy)
                if length < tol:
                    seg_normals.append((0.0, 0.0))
                    continue
                seg_normals.append((-dy / length, dx / length))

            # per-vertex offset with miter limit
            offsets = []
            for i in range(len(run_points)):
                if i == 0:
                    n = seg_normals[0]
                    offsets.append((n[0] * kerf_half, n[1] * kerf_half))
                    continue
                if i == len(run_points) - 1:
                    n = seg_normals[-1]
                    offsets.append((n[0] * kerf_half, n[1] * kerf_half))
                    continue
                n_prev = seg_normals[i - 1]
                n_next = seg_normals[i]
                mx = n_prev[0] + n_next[0]
                my = n_prev[1] + n_next[1]
                mlen = math.hypot(mx, my)
                if mlen < tol:
                    offsets.append((n_next[0] * kerf_half, n_next[1] * kerf_half))
                    continue
                mx /= mlen
                my /= mlen
                dot = mx * n_next[0] + my * n_next[1]
                if abs(dot) < tol:
                    offsets.append((n_next[0] * kerf_half, n_next[1] * kerf_half))
                    continue
                miter_len = kerf_half / dot
                if abs(miter_len) > (miter_limit * kerf_half):
                    offsets.append((n_next[0] * kerf_half, n_next[1] * kerf_half))
                else:
                    offsets.append((mx * miter_len, my * miter_len))

            # build quads per segment
            for i, seg_idx in enumerate(run_seg_indices):
                p0 = run_points[i]
                p1 = run_points[i + 1]
                o0 = offsets[i]
                o1 = offsets[i + 1]
                v0 = (p0[0] + o0[0], p0[1] + o0[1], p0[2] or 0.0)
                v1 = (p1[0] + o1[0], p1[1] + o1[1], p1[2] or 0.0)
                v2 = (p1[0] - o1[0], p1[1] - o1[1], p1[2] or 0.0)
                v3 = (p0[0] - o0[0], p0[1] - o0[1], p0[2] or 0.0)
                self._kerf_quads[seg_idx] = (v0, v1, v2, v3)

        run_points = []
        run_seg_indices = []
        last_end = None
        for idx, seg in enumerate(self.segments):
            if not is_cut(seg):
                if run_points:
                    flush_run(run_points, run_seg_indices)
                    run_points, run_seg_indices = [], []
                continue
            start = (seg.start[0], seg.start[1], seg.start[2] or 0.0)
            end = (seg.end[0], seg.end[1], seg.end[2] or 0.0)
            if not run_points:
                run_points = [start, end]
                run_seg_indices = [idx]
                last_end = end
                continue
            # continuity check
            dx = start[0] - last_end[0]
            dy = start[1] - last_end[1]
            if math.hypot(dx, dy) > 1e-4:
                flush_run(run_points, run_seg_indices)
                run_points = [start, end]
                run_seg_indices = [idx]
            else:
                run_points.append(end)
                run_seg_indices.append(idx)
            last_end = end

        if run_points:
            flush_run(run_points, run_seg_indices)

        logger.info(
            "Kerf mesh built: kerf=%.3f quads=%d skipped=%d",
            kerf,
            len(self._kerf_quads),
            skipped,
        )

    def _build_mesh_tris(self):
        self._mesh_tris = []
        self._mesh_dirty = True
        if not self.mesh_vertices:
            return
        verts = self.mesh_vertices
        if self.mesh_faces:
            faces = self.mesh_faces
            step = 3 * max(1, int(self.mesh_stride))
            for i in range(0, len(faces), step):
                try:
                    a, b, c = faces[i], faces[i + 1], faces[i + 2]
                    self._mesh_tris.append((verts[a], verts[b], verts[c]))
                except Exception:
                    continue
        else:
            step = 3 * max(1, int(self.mesh_stride))
            for i in range(0, len(verts), step):
                tri = verts[i : i + 3]
                if len(tri) == 3:
                    self._mesh_tris.append(tuple(tri))  # type: ignore
        self._mesh_dirty = True

    def _draw_mesh_cached(self):
        """Mesh'i display list ile çiz (performans için)."""
        if self._mesh_list_id is None:
            try:
                self._mesh_list_id = glGenLists(1)
            except Exception:
                self._mesh_list_id = None
        if self._mesh_list_id is None:
            self._draw_mesh_immediate()
            return
        if self._mesh_dirty:
            glNewList(self._mesh_list_id, GL_COMPILE)
            self._draw_mesh_immediate()
            glEndList()
            self._mesh_dirty = False
        glCallList(self._mesh_list_id)

    def _draw_mesh_immediate(self):
        """Mesh'i doğrudan glBegin ile çiz (fallback)."""
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glColor4f(0.0, 1.0, 0.0, 0.90)
        if self.mesh_mode == "wireframe":
            glBegin(GL_LINES)
            for tri in self._mesh_tris:
                (a, b, c) = tri
                a0 = self._apply_origin(*a); b0 = self._apply_origin(*b)
                glVertex3f(*a0); glVertex3f(*b0)
                b0 = self._apply_origin(*b); c0 = self._apply_origin(*c)
                glVertex3f(*b0); glVertex3f(*c0)
                c0 = self._apply_origin(*c); a0 = self._apply_origin(*a)
                glVertex3f(*c0); glVertex3f(*a0)
            glEnd()
        else:
            glBegin(GL_TRIANGLES)
            for tri in self._mesh_tris:
                for vx, vy, vz in tri:
                    vx0, vy0, vz0 = self._apply_origin(vx, vy, vz)
                    glVertex3f(vx0, vy0, vz0)
            glEnd()
        glDisable(GL_BLEND)

    def _draw_tool_mesh(self, x: float, y: float, z: float, a_val: float):
        glPushMatrix()
        pos_world, rot_world = compute_tool_pose(self._tool_profile or {}, x, y, z, a_val)
        glTranslatef(pos_world[0], pos_world[1], pos_world[2])
        rot = rot_world
        glMultMatrixf(
            (
                rot[0][0],
                rot[1][0],
                rot[2][0],
                0.0,
                rot[0][1],
                rot[1][1],
                rot[2][1],
                0.0,
                rot[0][2],
                rot[1][2],
                rot[2][2],
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
            )
        )

        if self._tool_mesh_body:
            glColor4f(0.65, 0.66, 0.7, 1.0)
            glBegin(GL_TRIANGLES)
            for vx, vy, vz in self._tool_mesh_body:
                glVertex3f(vx, vy, vz)
            glEnd()
        if self._tool_mesh_blade:
            glColor4f(0.84, 0.84, 0.9, 1.0)
            glBegin(GL_TRIANGLES)
            for vx, vy, vz in self._tool_mesh_blade:
                glVertex3f(vx, vy, vz)
            glEnd()
        glPopMatrix()
