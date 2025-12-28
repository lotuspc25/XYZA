# gl_viewer_guncel.py
# ----------------------------------------------------------
# Tabla + STL Ã¶nizleyici (QOpenGLWidget)
# - Tabla boyutu + G54 orijini
# - 10 mm grid, 50 / 100 mm kalÄ±n Ã§izgiler
# - Transparan tabla zemini
# - X/Y/Z eksen oklarÄ±
# - Kamera dÃ¶ndÃ¼rme / zoom / pan
# - STL yÃ¼kleme, rotasyon ve offset
# - Ã‡ift yÃ¼zlÃ¼ renkli STL (Ã¼st / alt yÃ¼z)
# ----------------------------------------------------------
# pyright: reportMissingImports=false, reportUndefinedVariable=false

import configparser
import logging
import math
import os
import numpy as np
from typing import Callable, Optional, Iterable, List
from stl import mesh as stl_mesh
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtCore import Qt, QPoint, pyqtSignal
from PyQt5.QtGui import QMatrix4x4, QVector3D, QCursor

from OpenGL.GL import *
from OpenGL.GLU import (
    gluPerspective,
    gluOrtho2D,
    gluProject,
)
from OpenGL.GLUT import glutInit, glutBitmapCharacter, GLUT_BITMAP_HELVETICA_18


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    fh = logging.FileHandler("gl_viewer.log", encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

INI_PATH = os.path.join(os.path.dirname(__file__), "settings.ini")


class GLTableViewer(QOpenGLWidget):
    zAnchorPicked = pyqtSignal(int)
    zAnchorFromMeshPicked = pyqtSignal(int, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Tabla boyutu (mm)
        self.table_width = 800.0
        self.table_height = 400.0

        # G54 orjin modu
        #  center, front_left, front_right, back_left, back_right
        self.origin_mode = "center"

        # Tabla dolu mu sadece grid mi?
        self.table_fill_enabled = True
        self.table_visible = True

        # Renkler (varsayÄ±lan)
        self.bg_color = (0.55, 0.55, 0.6)     # arka plan
        self.table_color = (0.75, 0.8, 0.85)  # tabla zemini

        # STL renkleri (Ã¼st yÃ¼z / alt yÃ¼z)
        base_stl = (0.95, 0.45, 0.6)
        self.stl_color_top = base_stl               # Ã¼st yÃ¼z
        self.stl_color_bottom = (0.95, 0.6, 0.30)   # alt yÃ¼z (biraz sÄ±cak ton)

        # Kamera parametreleri
        self.orbit_sensitivity = 0.3
        self.pan_sensitivity = 0.005
        self.zoom_sensitivity = 1.1
        self.dist = 1452.0
        self.rot_x = 0.0
        self.rot_y = 0.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self._last_pos = QPoint()

        # Model rotasyonu (derece)
        self.model_rot_x = 0.0
        self.model_rot_y = 0.0
        self.model_rot_z = 0.0

        # Model pozisyon offsetleri (mm)
        self.model_offset_x = 0.0
        self.model_offset_y = 0.0
        self.model_offset_z = 0.0
        # TakÄ±m yolu polyline (X,Y,Z) dÃ¼nya koordinatÄ±
        self.toolpath_polyline = None  # np.ndarray (N,3) veya None
        self.original_toolpath_polyline = None
        self.show_original_toolpath = False
        # Pivot preview (visual-only) for corner turns
        self.pivot_preview_enabled = False
        self.pivot_preview_r_mm = 2.0
        self.pivot_preview_steps = 12
        self.pivot_preview_corner_deg = 25.0
        self._pivot_preview_polyline = None
        # GerÃ§ek yay gÃ¶rÃ¼nÃ¼mÃ¼ iÃ§in yoÄŸun Ã¶rnekleme
        self.toolpath_color = (1.0, 0.0, 0.0)  # varsayilan kirmizi
        self.toolpath_width = 2.0
        self.point_color = (1.0, 1.0, 0.0)
        self.point_size_px = 4.0
        self.first_point_color = (1.0, 0.0, 0.0)
        self.second_point_color = (0.0, 1.0, 0.0)
        self.primary_index = -1
        self.secondary_index = -1
        self.issue_indices: List[int] = []
        self.edit_mode = False
        self.selected_index = -1
        self._dragging = False
        self._drag_depth = 0.0
        self.on_point_moved: Optional[Callable[[int, float, float, float], None]] = None
        self.on_point_selected: Optional[Callable[[int, Optional[np.ndarray]], None]] = None
        # SeÃ§im deÄŸiÅŸimi (primary, secondary) bildirimi
        self.on_selection_changed: Optional[Callable[[int, int], None]] = None
        self.on_drag_finished: Optional[Callable[[], None]] = None
        self.z_depth_mode = False
        self.z_anchor_indices: list[int] = []
        self.z_anchor_hit_positions: list[tuple[float, float, float]] = []
        self.z_anchor_color = (1.0, 0.2, 0.0)
        # Model Ã¶lÃ§eÄŸi (ÅŸimdilik kullanÄ±lmÄ±yor ama dursun)
        self.model_scale = 1.0
        self.mesh_version = 0

        # STL mesh verileri
        self.mesh_vertices_original = None  # (N,3) float32
        self.mesh_normals_original = None   # (N,3) float32
        self.mesh_vertices = None           # (N,3) float32 - dÃ¶nÃ¼ÅŸtÃ¼rÃ¼lmÃ¼ÅŸ
        self.mesh_normals = None            # (N,3) float32 - dÃ¶nÃ¼ÅŸtÃ¼rÃ¼lmÃ¼ÅŸ
        self.mesh_vertex_count = 0
        self.mesh_visible = True
        self.axes_visible = True

        # Model boyutlarÄ±
        self.model_size = None  # np.array([size_x, size_y, size_z])

        # Kamera overlay iÃ§in GLUT baÅŸlat
        glutInit()

        # Varsayilan kamera acisi ve mesafesi (2. goruntudeki gibi)
        self._set_camera_defaults()
        self._load_camera_settings()

    # ------------------------------------------------------
    # DÄ±ÅŸarÄ±dan Ã§aÄŸrÄ±lan ayar fonksiyonlarÄ±
    # ------------------------------------------------------
    def set_table_size(self, width_mm, height_mm):
        self.table_width = float(width_mm)
        self.table_height = float(height_mm)
        self._bump_mesh_version()
        self.update()

    def set_origin_mode(self, mode):
        # mode: center, front_left, front_right, back_left, back_right
        self.origin_mode = mode
        self._bump_mesh_version()
        self.update()

    def _bump_mesh_version(self):
        self.mesh_version = int(getattr(self, "mesh_version", 0)) + 1

    def set_camera_angles(self, rx: Optional[float] = None, ry: Optional[float] = None, rz: Optional[float] = None):
        if rx is not None:
            self.rot_x = float(rx)
        if ry is not None:
            self.rot_y = float(ry)
        if rz is not None:
            self.rot_z = float(rz)
        self.update()

    def set_zoom(self, dist: float):
        try:
            d = float(dist)
        except (TypeError, ValueError):
            return
        self.dist = max(10.0, min(d, 5000.0))
        self.update()

    def set_focus_point(self, x: float, y: float, _z: float = 0.0, auto_zoom: bool = True):
        # Pan deÄŸerlerini seÃ§ilen nokta tablo merkezine gelecek ÅŸekilde ayarla
        cx = self.table_width / 2.0
        cy = self.table_height / 2.0
        self.pan_x = -(float(x) - cx)
        self.pan_y = -(float(y) - cy)
        if auto_zoom:
            self.dist = self._compute_default_distance()
        else:
            # Ã‡ok yakÄ±n zoom deÄŸerlerinde (Ã¶r. <60) odak kaybolmasÄ±n
            if self.dist < 60.0:
                self.dist = 60.0
        self.update()

    def focus_point(self, x: float, y: float, z: float, keep_distance: bool = True):
        """Kameray? verilen noktaya odaklar."""
        self.set_focus_point(x, y, z, auto_zoom=not keep_distance)

    def zoom_towards_point(self, factor: float = 0.85):
        """Mevcut oda?a do?ru zoom yapar."""
        try:
            f = float(factor)
        except (TypeError, ValueError):
            f = 0.85
        if f <= 0.0 or f >= 1.0:
            f = 0.85
        self.dist = max(10.0, self.dist * f)
        self.update()

    def fit_all(self):
        """Kameray? varsay?lan konuma d?nd?r?r."""
        self.reset_camera()

    def reset_camera(self):
        """KamerayÄ± varsayÄ±lan baÅŸlangÄ±Ã§ pozisyonuna getirir."""
        self.rot_x = 0.0
        self.rot_y = 0.0
        self.dist = 1452.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.update()

    def _load_camera_settings(self):
        cfg = configparser.ConfigParser()
        if not cfg.read(INI_PATH, encoding="utf-8"):
            return
        if cfg.has_section("CAMERA"):
            sec = cfg["CAMERA"]
            self.orbit_sensitivity = sec.getfloat("orbit_sensitivity", fallback=self.orbit_sensitivity)
            self.pan_sensitivity = sec.getfloat("pan_sensitivity", fallback=self.pan_sensitivity)
            self.zoom_sensitivity = sec.getfloat("zoom_sensitivity", fallback=self.zoom_sensitivity)
            self.dist = sec.getfloat("initial_distance", fallback=self.dist)
            self.rot_x = sec.getfloat("initial_rot_x", fallback=self.rot_x)
            self.rot_y = sec.getfloat("initial_rot_y", fallback=self.rot_y)

    def _hex_to_rgb_f(self, hex_str):
        """'#RRGGBB' -> (r, g, b) float (0..1)."""
        h = hex_str.strip().lstrip("#")
        if len(h) != 6:
            return (0.8, 0.8, 0.8)
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        return (r, g, b)

    def set_colors(self, bg_hex, table_hex, stl_hex):
        """Ayarlar sekmesinden gelen arka plan / tabla / STL rengi."""
        self.bg_color = self._hex_to_rgb_f(bg_hex)
        self.table_color = self._hex_to_rgb_f(table_hex)

        base = self._hex_to_rgb_f(stl_hex)
        # Ãœst yÃ¼z: seÃ§ilen renk
        self.stl_color_top = base
        # Alt yÃ¼z: biraz daha sÄ±cak / koyu versiyon
        self.stl_color_bottom = (
            min(base[0] * 0.6 + 0.3, 1.0),
            base[1] * 0.5,
            base[2] * 0.2,
        )
        self.update()

    def set_toolpath_style(
        self,
        color_hex: str,
        width_px: float,
        point_color_hex: Optional[str] = None,
        point_size_px: Optional[float] = None,
        first_point_hex: Optional[str] = None,
        second_point_hex: Optional[str] = None,
    ):
        """TakÄ±m yolu rengi/kalÄ±nlÄ±ÄŸÄ± ve nokta stilini ayarlar."""
        try:
            if color_hex.startswith("#"):
                color_hex = color_hex[1:]
            if len(color_hex) == 6:
                r = int(color_hex[0:2], 16) / 255.0
                g = int(color_hex[2:4], 16) / 255.0
                b = int(color_hex[4:6], 16) / 255.0
                self.toolpath_color = (r, g, b)
        except Exception:
            logger.exception('Toolpath rengi uygulanamadi')

        try:
            width_val = float(width_px)
        except Exception:
            width_val = self.toolpath_width
        self.toolpath_width = max(0.5, min(width_val, 10.0))
        # GÃ¶rsel tÃ¼p yarÄ±Ã§apÄ±nÄ± px deÄŸerinden tÃ¼ret (mm cinsinden yaklaÅŸÄ±k)
        # Nokta stili
        if point_color_hex:
            self.point_color = self._hex_to_rgb_f(point_color_hex)
        if point_size_px is not None:
            try:
                self.point_size_px = max(1.0, min(float(point_size_px), 40.0))
            except Exception:
                logger.exception('Nokta boyutu ayarlanamadi')


        if second_point_hex:
            self.second_point_color = self._hex_to_rgb_f(second_point_hex)
        self.update()

    def set_mesh_visible(self, visible: bool):
        self.mesh_visible = bool(visible)
        self.update()

    def set_table_fill_enabled(self, enabled: bool):
        """Tabla zemini dolu mu sadece grid mi gÃ¶stersin."""
        self.table_fill_enabled = bool(enabled)
        self.update()

    # ------------------------------------------------------
    # STL yÃ¼kleme
    # ------------------------------------------------------
    def load_stl(self, filename):
        """STL dosyasini yukler, XY merkezini 0,0'a ve Z tabanini 0'a ceker."""
        try:
            m = stl_mesh.Mesh.from_file(filename)
        except Exception as e:
            logger.exception('STL yuklenemedi: %s', filename)
            if hasattr(self, 'on_load_error') and callable(getattr(self, 'on_load_error')):
                try:
                    self.on_load_error(str(e))
                except Exception:
                    logger.exception('STL yukleme callback basarisiz')
            return


        # vektÃ¶rler: (num_triangles, 3, 3)
        vectors = m.vectors.astype(np.float32)
        num_triangles = vectors.shape[0]

        # Vertexleri dÃ¼z diziye Ã§evir (N,3)
        verts = vectors.reshape(-1, 3)  # 3 vertex * triangle

        # Normalleri her vertex iÃ§in tekrar et (N,3)
        tri_normals = m.normals.astype(np.float32)
        normals = np.repeat(tri_normals, 3, axis=0)

        # Bounding box
        min_xyz = verts.min(axis=0)
        max_xyz = verts.max(axis=0)
        size_xyz = max_xyz - min_xyz
        self.model_size = size_xyz

        # XY merkezini 0,0 yap
        center_xy = (min_xyz[0:2] + max_xyz[0:2]) / 2.0
        verts[:, 0] -= center_xy[0]
        verts[:, 1] -= center_xy[1]

        # Alt yÃ¼zeyi Z=0'a Ã§ek
        verts[:, 2] -= min_xyz[2]

        self.mesh_vertices_original = verts.astype(np.float32)
        self.mesh_normals_original = normals.astype(np.float32)
        self.mesh_vertex_count = self.mesh_vertices_original.shape[0]
        self.mesh_visible = True

        # Rotasyon / scale uygulayÄ±p gÃ¼ncel veriyi Ã¼ret
        self._update_model_transform()
        self._bump_mesh_version()

        self.update()

    def get_model_info(self):
        """TabModel saÄŸ paneli iÃ§in model bilgileri."""
        if self.mesh_vertices_original is None or self.model_size is None:
            return None

        info = {
            "vertices": int(self.mesh_vertex_count),
            "triangles": int(self.mesh_vertex_count // 3),
            "size_x": float(self.model_size[0]),
            "size_y": float(self.model_size[1]),
            "size_z": float(self.model_size[2]),
        }
        return info

    # ------------------------------------------------------
    # Kamera ve gÃ¶rÃ¼nÃ¼m
    # ------------------------------------------------------
    def _compute_default_distance(self):
        """Tabla boyutuna gore baslangic zoom (mesafe) hesaplar."""
        return 1452.0

    def _set_camera_defaults(self):
        """2. ekrandaki gibi ustten bakis icin varsayilan kamera ayari."""
        self.reset_camera()

    def reset_view(self):
        """Kamerayi varsayilan aciya ve uzakliga getirir."""
        self._set_camera_defaults()
        self.update()

    # ------------------------------------------------------
    # Model transform (rotasyon + scale + Z taban)
    # ------------------------------------------------------
    def set_model_rotation(self, rx, ry, rz):
        self.model_rot_x = float(rx)
        self.model_rot_y = float(ry)
        self.model_rot_z = float(rz)
        self._update_model_transform()
        self._bump_mesh_version()
        self.update()

    def set_model_offset(self, x, y, z):
        """Modeli tablo Ã¼zerinde X/Y/Z yÃ¶nlerinde kaydÄ±rÄ±r."""
        try:
            self.model_offset_x = float(x)
            self.model_offset_y = float(y)
            self.model_offset_z = float(z)
        except (TypeError, ValueError):
            return
        self._bump_mesh_version()
        self.update()

    def _update_model_transform(self):
        """Orijinal vertex ve normallere rotasyon (ve scale) uygular,
        sonra min Z'yi tekrar 0'a Ã§eker. BÃ¶ylece model tablaya yapÄ±ÅŸÄ±k kalÄ±r."""
        if self.mesh_vertices_original is None:
            return

        verts = self.mesh_vertices_original
        norms = self.mesh_normals_original

        # Dereceleri radyana Ã§evir
        rx = np.deg2rad(self.model_rot_x)
        ry = np.deg2rad(self.model_rot_y)
        rz = np.deg2rad(self.model_rot_z)

        # Rotasyon matrisleri (X, Y, Z)
        Rx = np.array(
            [
                [1, 0, 0],
                [0, np.cos(rx), -np.sin(rx)],
                [0, np.sin(rx), np.cos(rx)],
            ],
            dtype=np.float32,
        )

        Ry = np.array(
            [
                [np.cos(ry), 0, np.sin(ry)],
                [0, 1, 0],
                [-np.sin(ry), 0, np.cos(ry)],
            ],
            dtype=np.float32,
        )

        Rz = np.array(
            [
                [np.cos(rz), -np.sin(rz), 0],
                [np.sin(rz), np.cos(rz), 0],
                [0, 0, 1],
            ],
            dtype=np.float32,
        )

        # Rotasyon sÄ±rasÄ±: X -> Y -> Z
        R = Rz @ Ry @ Rx

        verts_rot = verts @ R.T
        norms_rot = norms @ R.T

        # (Ä°leride istersen scale de eklenebilir)
        s = float(self.model_scale)
        verts_rot *= s

        # Min Z'yi tekrar 0'a Ã§ek -> tabla yÃ¼zeyine otursun
        min_z = np.min(verts_rot[:, 2])
        verts_rot[:, 2] -= min_z

        self.mesh_vertices = verts_rot.astype(np.float32)
        self.mesh_normals = norms_rot.astype(np.float32)

    # ------------------------------------------------------
    # OpenGL temel fonksiyonlarÄ±
    # ------------------------------------------------------
    def initializeGL(self):
        try:
            glClearColor(*self.bg_color, 1.0)
            glEnable(GL_DEPTH_TEST)

            # AydÄ±nlatma
            glEnable(GL_LIGHTING)
            glEnable(GL_LIGHT0)
            glLightfv(GL_LIGHT0, GL_POSITION, (1.0, 1.0, 1.0, 0.0))
            glLightfv(GL_LIGHT0, GL_AMBIENT, (0.15, 0.15, 0.15, 1.0))
            glLightfv(GL_LIGHT0, GL_DIFFUSE, (0.85, 0.85, 0.85, 1.0))

            glLightModeli(GL_LIGHT_MODEL_TWO_SIDE, GL_TRUE)
            glEnable(GL_NORMALIZE)

            # STL rengini glColor ile ayarlayabilelim
            glEnable(GL_COLOR_MATERIAL)
            glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)

            # Transparan tabla iÃ§in blend
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

            glShadeModel(GL_SMOOTH)
        except Exception:
            logger.exception("OpenGL initializeGL failed")


    def resizeGL(self, w, h):
        if h == 0:
            h = 1
        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        aspect = w / float(h)
        gluPerspective(35.0, aspect, 10.0, 20000.0)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

    def paintGL(self):
        glClearColor(*self.bg_color, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

        # Kamera konumu
        glTranslatef(0.0, 0.0, -self.dist)
        glRotatef(self.rot_x, 1.0, 0.0, 0.0)
        glRotatef(self.rot_y, 0.0, 1.0, 0.0)
        glTranslatef(self.pan_x, self.pan_y, 0.0)

        # Tabla merkezini sahnenin merkezine getir
        cx = self.table_width / 2.0
        cy = self.table_height / 2.0
        glTranslatef(-cx, -cy, 0.0)

        # Tabla ve grid
        self._draw_table()
        self._draw_grid()

        # G54 eksenleri
        self._draw_axes()

        # STL modeli
        self._draw_mesh()
        # TakÄ±m yolu (varsa)
        self._draw_toolpath()
        # Kamera overlay (2D)
        self._draw_camera_overlay()

    # ------------------------------------------------------
    # YardÄ±mcÄ± Ã§izim fonksiyonlarÄ±
    # ------------------------------------------------------
    def _draw_table(self):
        """Transparan tabla zemini (Z=0 dÃ¼zlemi)."""
        if not getattr(self, "table_visible", True):
            return
        w = self.table_width
        h = self.table_height

        r, g, b = self.table_color

        if not self.table_fill_enabled:
            return

        glDisable(GL_LIGHTING)
        glColor4f(r, g, b, 0.25)

        glBegin(GL_QUADS)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(w, 0.0, 0.0)
        glVertex3f(w, h, 0.0)
        glVertex3f(0.0, h, 0.0)
        glEnd()

        glEnable(GL_LIGHTING)

    def _draw_grid(self):
        """10 mm aralÄ±klarla grid, 50 ve 100 mm'de kalÄ±nlaÅŸtÄ±rÄ±lmÄ±ÅŸ Ã§izgiler."""
        if not getattr(self, "table_visible", True):
            return
        w = self.table_width
        h = self.table_height

        step = 10.0  # 10 mm

        glDisable(GL_LIGHTING)

        # X yÃ¶nÃ¼ Ã§izgileri
        x = 0.0
        while x <= w + 0.001:
            if abs(x) < 0.001:
                # X=0 Ã§izgisi (en koyu)
                glColor3f(0.1, 0.1, 0.15)
                glLineWidth(2.0)
            elif int(x) % 100 == 0:
                glColor3f(0.25, 0.25, 0.3)
                glLineWidth(2.0)
            elif int(x) % 50 == 0:
                glColor3f(0.4, 0.4, 0.5)
                glLineWidth(1.5)
            else:
                glColor3f(0.7, 0.7, 0.75)
                glLineWidth(1.0)

            glBegin(GL_LINES)
            glVertex3f(x, 0.0, 0.01)
            glVertex3f(x, h, 0.01)
            glEnd()

            x += step

        # Y yÃ¶nÃ¼ Ã§izgileri
        y = 0.0
        while y <= h + 0.001:
            if abs(y) < 0.001:
                glColor3f(0.1, 0.1, 0.15)
                glLineWidth(2.0)
            elif int(y) % 100 == 0:
                glColor3f(0.25, 0.25, 0.3)
                glLineWidth(2.0)
            elif int(y) % 50 == 0:
                glColor3f(0.4, 0.4, 0.5)
                glLineWidth(1.5)
            else:
                glColor3f(0.7, 0.7, 0.75)
                glLineWidth(1.0)

            glBegin(GL_LINES)
            glVertex3f(0.0, y, 0.01)
            glVertex3f(w, y, 0.01)
            glEnd()

            y += step

        glLineWidth(1.0)
        glEnable(GL_LIGHTING)

    def _compute_origin_point(self):
        """G54 orijin noktasÄ±nÄ±n tablo Ã¼zerindeki (x,y) koordinatÄ±."""
        w = self.table_width
        h = self.table_height

        if self.origin_mode == "front_left":
            return 0.0, 0.0
        elif self.origin_mode == "front_right":
            return w, 0.0
        elif self.origin_mode == "back_left":
            return 0.0, h
        elif self.origin_mode == "back_right":
            return w, h
        else:  # center
            return w / 2.0, h / 2.0

    def _draw_axes(self):
        """G54 orijininde X/Y/Z eksenlerini Ã§izer."""
        if not getattr(self, "axes_visible", True):
            return
        ox, oy = self._compute_origin_point()
        axis_len = min(self.table_width, self.table_height) * 0.15
        if axis_len < 40.0:
            axis_len = 40.0
        axis_len *= 1.5  # OklarÄ± %50 uzat

        glDisable(GL_LIGHTING)
        glLineWidth(6.0)

        # X ekseni (kÄ±rmÄ±zÄ±)
        glColor3f(1.0, 0.0, 0.0)
        glBegin(GL_LINES)
        glVertex3f(ox, oy, 0.0)
        glVertex3f(ox + axis_len, oy, 0.0)
        glEnd()

        # Y ekseni (yeÅŸil)
        glColor3f(0.0, 0.8, 0.0)
        glBegin(GL_LINES)
        glVertex3f(ox, oy, 0.0)
        glVertex3f(ox, oy + axis_len, 0.0)
        glEnd()

        # Z ekseni (mavi)
        glColor3f(0.0, 0.0, 1.0)
        glBegin(GL_LINES)
        glVertex3f(ox, oy, 0.0)
        glVertex3f(ox, oy, axis_len)
        glEnd()

        # Eksen harflerini uca yaz
        def _draw_label(text, x, y, z, color):
            glColor3f(*color)
            glRasterPos3f(x, y, z)
            for ch in text:
                glutBitmapCharacter(GLUT_BITMAP_HELVETICA_18, ord(ch))

        _draw_label("X", ox + axis_len + 6.0, oy, 0.0, (1.0, 0.0, 0.0))
        _draw_label("Y", ox, oy + axis_len + 6.0, 0.0, (0.0, 0.8, 0.0))
        _draw_label("Z", ox, oy, axis_len + 6.0, (0.0, 0.0, 1.0))

        glLineWidth(1.0)

        # Basit ok uÃ§larÄ± Ã§izilebilir; ÅŸimdilik sadece Ã§izgi yeterli.

        glEnable(GL_LIGHTING)

    def _draw_mesh(self):
        if not getattr(self, "mesh_visible", True):
            return
        if (
            self.mesh_vertices is None
            or self.mesh_normals is None
            or self.mesh_vertex_count == 0
        ):
            return

        ox, oy = self._compute_origin_point()

        glPushMatrix()

        # G54 orijinine ve kullanÄ±cÄ± offset'ine taÅŸÄ±
        glTranslatef(
            ox + self.model_offset_x,
            oy + self.model_offset_y,
            self.model_offset_z,
        )

        glEnableClientState(GL_NORMAL_ARRAY)
        glEnableClientState(GL_VERTEX_ARRAY)
        glNormalPointer(GL_FLOAT, 0, self.mesh_normals)
        glVertexPointer(3, GL_FLOAT, 0, self.mesh_vertices)

        glEnable(GL_CULL_FACE)

        # Ã–n yÃ¼zler (dÄ±ÅŸ taraf) -> Ã¼st renk
        glCullFace(GL_BACK)
        glColor3f(*self.stl_color_top)
        glDrawArrays(GL_TRIANGLES, 0, self.mesh_vertex_count)

        # Arka yÃ¼zler (iÃ§ taraf) -> alt renk
        glCullFace(GL_FRONT)
        glColor3f(*self.stl_color_bottom)
        glDrawArrays(GL_TRIANGLES, 0, self.mesh_vertex_count)

        glDisable(GL_CULL_FACE)

        glDisableClientState(GL_VERTEX_ARRAY)
        glDisableClientState(GL_NORMAL_ARRAY)

        glPopMatrix()

    def _draw_camera_overlay(self):
        """EkranÄ±n sol Ã¼stÃ¼ne kamera aÃ§Ä±larÄ±nÄ± yaz."""
        w = self.width()
        h = self.height()
        text = f"Kamera: Rx={self.rot_x:.1f}Â°, Ry={self.rot_y:.1f}Â°, Zoom={int(self.dist)}"

        # 2D ortografik projeksiyona geÃ§
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        gluOrtho2D(0, w, 0, h)

        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()

        glDisable(GL_LIGHTING)
        glDisable(GL_DEPTH_TEST)

        glColor3f(0.0, 0.0, 0.0)
        glRasterPos2f(10, h - 20)

        for ch in text:
            glutBitmapCharacter(GLUT_BITMAP_HELVETICA_18, ord(ch))

        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)

        glMatrixMode(GL_MODELVIEW)
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)

    # ------------------------------------------------------
    # TakÄ±m yolu projeksiyonu / edit yardÄ±mcÄ±larÄ±
    # ------------------------------------------------------
    def _build_view_matrix(self) -> QMatrix4x4:
        view = QMatrix4x4()
        view.translate(0.0, 0.0, -self.dist)
        view.rotate(self.rot_x, 1.0, 0.0, 0.0)
        view.rotate(self.rot_y, 0.0, 1.0, 0.0)
        view.translate(self.pan_x, self.pan_y, 0.0)
        cx = self.table_width / 2.0
        cy = self.table_height / 2.0
        view.translate(-cx, -cy, 0.0)
        return view

    def _build_proj_matrix(self) -> QMatrix4x4:
        proj = QMatrix4x4()
        w = max(1, self.width())
        h = max(1, self.height())
        aspect = w / float(h)
        proj.perspective(35.0, aspect, 10.0, 20000.0)
        return proj

    def _mvp_matrix(self) -> QMatrix4x4:
        return self._build_proj_matrix() * self._build_view_matrix()

    def _project_point_to_screen(self, pt: np.ndarray):
        """DÃ¼nyadaki bir noktayÄ± ekran koordinatÄ±na Ã§evirir."""
        mvp = self._mvp_matrix()
        ndc = mvp.map(QVector3D(float(pt[0]), float(pt[1]), float(pt[2])))
        w = max(1, self.width())
        h = max(1, self.height())
        sx = (ndc.x() + 1.0) * 0.5 * w
        sy = (1.0 - (ndc.y() + 1.0) * 0.5) * h
        return sx, sy, ndc.z()

    def _project_polyline_to_screen(self) -> Optional[np.ndarray]:
        if self.toolpath_polyline is None:
            return None
        pts_2d = []
        for pt in self.toolpath_polyline:
            sx, sy, _ = self._project_point_to_screen(pt)
            pts_2d.append((sx, sy))
        return np.array(pts_2d, dtype=np.float32)

    def _unproject_ray(self, screen_x: float, screen_y: float):
        """Ekran noktasÄ±ndan dÃ¼nyaya giden Ã§izgi (near->far)."""
        w = max(1, self.width())
        h = max(1, self.height())
        ndc_x = (screen_x / w) * 2.0 - 1.0
        ndc_y = 1.0 - (screen_y / h) * 2.0
        mvp = self._mvp_matrix()
        inv, ok = mvp.inverted()
        if not ok:
            return None
        near = inv.map(QVector3D(ndc_x, ndc_y, -1.0))
        far = inv.map(QVector3D(ndc_x, ndc_y, 1.0))
        direction = far - near
        return near, direction

    def _point_on_plane(self, screen_x: float, screen_y: float, plane_z: float):
        ray = self._unproject_ray(screen_x, screen_y)
        if ray is None:
            return None
        origin, direction = ray
        if abs(direction.z()) < 1e-6:
            return None
        t = (plane_z - origin.z()) / direction.z()
        if t < 0.0:
            return None
        hit = origin + direction * t
        return np.array([hit.x(), hit.y(), plane_z], dtype=np.float32)

    def _raycast_mesh(self, screen_x: float, screen_y: float) -> Optional[np.ndarray]:
        if (
            self.mesh_vertices is None
            or self.mesh_vertex_count <= 0
            or self.mesh_vertices.shape[0] < 3
        ):
            return None

        ray = self._unproject_ray(screen_x, screen_y)
        if ray is None:
            return None
        origin_qt, direction_qt = ray
        origin = np.array([origin_qt.x(), origin_qt.y(), origin_qt.z()], dtype=np.float32)
        direction = np.array([direction_qt.x(), direction_qt.y(), direction_qt.z()], dtype=np.float32)
        norm = np.linalg.norm(direction)
        if norm < 1e-6:
            return None
        direction /= norm

        verts = self.mesh_vertices
        # Model, Ã§izimde G54 orijini + offset ile taÅŸÄ±nÄ±yor
        ox, oy = self._compute_origin_point()
        tx = ox + self.model_offset_x
        ty = oy + self.model_offset_y
        tz = self.model_offset_z

        closest_t = None
        closest_hit = None

        # MÃ¶llerâ€“Trumbore
        eps = 1e-6
        for i in range(0, self.mesh_vertex_count - 2, 3):
            v0 = verts[i] + np.array([tx, ty, tz], dtype=np.float32)
            v1 = verts[i + 1] + np.array([tx, ty, tz], dtype=np.float32)
            v2 = verts[i + 2] + np.array([tx, ty, tz], dtype=np.float32)

            edge1 = v1 - v0
            edge2 = v2 - v0
            h = np.cross(direction, edge2)
            a = np.dot(edge1, h)
            if -eps < a < eps:
                continue
            f = 1.0 / a
            s = origin - v0
            u = f * np.dot(s, h)
            if u < 0.0 or u > 1.0:
                continue
            q = np.cross(s, edge1)
            v = f * np.dot(direction, q)
            if v < 0.0 or u + v > 1.0:
                continue
            t = f * np.dot(edge2, q)
            if t > eps:
                if closest_t is None or t < closest_t:
                    closest_t = t
                    closest_hit = origin + direction * t

        return closest_hit

    def set_toolpath_polyline(self, points: Optional[np.ndarray]):
        """DÄ±ÅŸarÄ±dan takÄ±m yolu polyline'Ä± verilir (X,Y,Z)."""
        if points is None:
            self.toolpath_polyline = None
        else:
            arr = np.asarray(points, dtype=np.float32)
            if arr.ndim != 2 or arr.shape[1] != 3:
                self.toolpath_polyline = None
            else:
                self.toolpath_polyline = arr.copy()
        # NOTE: Pivot preview polyline is visual-only and rebuilt on new data.
        if self.pivot_preview_enabled and self.toolpath_polyline is not None:
            self._pivot_preview_polyline = self._build_pivot_preview_polyline(self.toolpath_polyline)
        else:
            self._pivot_preview_polyline = None
        self.z_anchor_indices = []
        self.z_anchor_hit_positions = []
        self.selected_index = -1
        self.primary_index = -1
        self.secondary_index = -1
        self._dragging = False
        self.update()
        if self.on_point_selected is not None:
            self.on_point_selected(-1, None)
        if self.on_selection_changed is not None:
            self.on_selection_changed(self.primary_index, self.secondary_index)

    def set_original_toolpath_polyline(self, points: np.ndarray):
        """
        Eski/orijinal takÄ±m yolunu (XYZ noktalarÄ±) viewer'a verir.
        points: shape (N, 3) float32
        """
        try:
            arr = np.asarray(points, dtype=np.float32)
            if arr.ndim == 2 and arr.shape[1] == 3:
                self.original_toolpath_polyline = arr.copy()
            else:
                self.original_toolpath_polyline = None
        except Exception:
            self.original_toolpath_polyline = None
        self.update()

    def set_show_original_toolpath(self, show: bool):
        """
        Orijinal yolun Ã§izilip Ã§izilmeyeceÄŸini kontrol eder.
        """
        self.show_original_toolpath = bool(show)
        self.update()

    def set_pivot_preview_settings(self, enabled: bool, radius_mm: float, steps: int, corner_deg: float):
        """Köşelerde pivot dönüş için görsel önizleme ayarları."""
        self.pivot_preview_enabled = bool(enabled)
        self.pivot_preview_r_mm = max(0.0, float(radius_mm))
        self.pivot_preview_steps = max(4, int(steps))
        self.pivot_preview_corner_deg = max(0.0, float(corner_deg))
        if self.pivot_preview_enabled and self.toolpath_polyline is not None:
            self._pivot_preview_polyline = self._build_pivot_preview_polyline(self.toolpath_polyline)
        else:
            self._pivot_preview_polyline = None
        self.update()

        """
        GerÃ§ek yay Ã¶nizlemesi iÃ§in yoÄŸun Ã¶rneklemeli polyline.
        points: numpy array shape (N,3) veya None.
        """
        self.update()

    def set_mesh_data(self, vertices, normals, size_xyz):
        """Arka planda hazırlanan mesh verisini UI thread'inde uygular."""
        self.mesh_vertices_original = vertices
        self.mesh_normals_original = normals
        self.mesh_vertex_count = 0 if vertices is None else vertices.shape[0]
        self.model_size = size_xyz
        self.mesh_visible = True
        self._update_model_transform()
        self._bump_mesh_version()
        self.update()

        self.update()

    def set_edit_mode(self, enabled: bool):
        self.edit_mode = bool(enabled)
        if not self.edit_mode:
            self.selected_index = -1
            self.primary_index = -1
            self.secondary_index = -1
            self._dragging = False
            self.setCursor(Qt.ArrowCursor)
            if self.on_point_selected is not None:
                self.on_point_selected(-1, None)
            if self.on_selection_changed is not None:
                self.on_selection_changed(-1, -1)
        else:
            self.setCursor(QCursor(Qt.PointingHandCursor))
        self.update()

    def set_z_depth_mode(self, enabled: bool):
        self.z_depth_mode = bool(enabled)
        if self.z_depth_mode:
            self.setCursor(QCursor(Qt.PointingHandCursor))
        elif not self.edit_mode:
            self.setCursor(Qt.ArrowCursor)
        self.update()

    def set_z_anchor_indices(self, indices, hit_positions=None):
        try:
            self.z_anchor_indices = list(indices) if indices is not None else []
        except Exception:
            self.z_anchor_indices = []
        try:
            self.z_anchor_hit_positions = list(hit_positions) if hit_positions is not None else []
        except Exception:
            self.z_anchor_hit_positions = []
        self.update()

    def set_selected_index(self, index: int):
        if self.toolpath_polyline is None or index is None or index < 0 or index >= len(self.toolpath_polyline):
            self.selected_index = -1
            self.primary_index = -1
            self.secondary_index = -1
            if self.on_point_selected is not None:
                self.on_point_selected(-1, None)
            if self.on_selection_changed is not None:
                self.on_selection_changed(-1, -1)
        else:
            self.selected_index = int(index)
            self.primary_index = self.selected_index
            self.secondary_index = -1
            if self.on_point_selected is not None:
                self.on_point_selected(self.selected_index, self.toolpath_polyline[self.selected_index])
            if self.on_selection_changed is not None:
                self.on_selection_changed(self.primary_index, self.secondary_index)
        self.update()

    def set_issue_indices(self, indices: Iterable[int]):
        """
        Problemli takÄ±m yolu noktalarÄ±nÄ±n index listesini alÄ±r.
        Ã‡izim sÄ±rasÄ±nda bu noktalara kÄ±rmÄ±zÄ± marker Ã§izilir.
        """
        if indices is None:
            self.issue_indices = []
        else:
            try:
                uniq = sorted({int(i) for i in indices if i is not None})
            except Exception:
                uniq = []
            self.issue_indices = uniq
        self.update()

    def _pick_toolpath_point(self, pos, max_px: float = 12.0) -> int:
        """Ekrandaki en yakÄ±n polyline noktasÄ±nÄ± seÃ§er."""
        pts_2d = self._project_polyline_to_screen()
        if pts_2d is None or pts_2d.shape[0] == 0:
            return -1
        dx = pts_2d[:, 0] - pos.x()
        dy = pts_2d[:, 1] - pos.y()
        dist2 = dx * dx + dy * dy
        idx = int(dist2.argmin())
        if dist2[idx] <= max_px * max_px:
            return idx
        return -1

    def _update_selected_point(self, idx: int, new_pt: np.ndarray):
        if self.toolpath_polyline is None or idx < 0 or idx >= len(self.toolpath_polyline):
            return
        self.toolpath_polyline[idx] = new_pt
        if self.on_point_moved is not None:
            self.on_point_moved(idx, float(new_pt[0]), float(new_pt[1]), float(new_pt[2]))
        if self.on_point_selected is not None:
            self.on_point_selected(idx, new_pt)
        self.update()

    # ------------------------------------------------------
    # Mouse / tekerlek etkileÅŸimleri
    # ------------------------------------------------------
    def mousePressEvent(self, event):
        self._last_pos = event.pos()
        if self.z_depth_mode and event.button() == Qt.LeftButton:
            hit = self._raycast_mesh(event.x(), event.y())
            if hit is not None and self.toolpath_polyline is not None and len(self.toolpath_polyline) > 0:
                # Toolpath Ã¼zerindeki XY'ye en yakÄ±n noktayÄ± bul
                xy = self.toolpath_polyline[:, :2]
                dx = xy[:, 0] - float(hit[0])
                dy = xy[:, 1] - float(hit[1])
                dist2 = dx * dx + dy * dy
                idx = int(dist2.argmin())
                if self.zAnchorFromMeshPicked is not None:
                    self.zAnchorFromMeshPicked.emit(idx, float(hit[0]), float(hit[1]), float(hit[2]))
                    event.accept()
                    return
            # STL vurulamazsa, eski davranÄ±ÅŸa bÄ±rak
        # Ctrl ile iki nokta seÃ§imi / normal seÃ§im
        if event.button() == Qt.LeftButton and self.toolpath_polyline is not None:
            idx = self._pick_toolpath_point(event.pos())
            if idx >= 0:
                mods = event.modifiers()
                if mods & Qt.ControlModifier:
                    if self.primary_index < 0:
                        self.primary_index = idx
                    elif self.secondary_index < 0:
                        self.secondary_index = idx
                    else:
                        self.secondary_index = idx
                    if self.on_selection_changed is not None:
                        self.on_selection_changed(self.primary_index, self.secondary_index)
                    self.update()
                else:
                    self.set_selected_index(idx)

        if (
            self.edit_mode
            and event.button() == Qt.LeftButton
            and self.toolpath_polyline is not None
            and not (event.modifiers() & Qt.ControlModifier)
        ):
            idx = self._pick_toolpath_point(event.pos())
            self.set_selected_index(idx)
            if idx >= 0:
                _, _, depth = self._project_point_to_screen(self.toolpath_polyline[idx])
                self._drag_depth = depth
                self._dragging = True
                event.accept()
                return
        # Varsayilan davranisa don
        super().mousePressEvent(event) if hasattr(super(), "mousePressEvent") else None

    def mouseMoveEvent(self, event):
        dx = event.x() - self._last_pos.x()
        dy = event.y() - self._last_pos.y()

        if (
            self.edit_mode
            and (event.buttons() & Qt.LeftButton)
            and self.toolpath_polyline is not None
            and self.selected_index >= 0
        ):
            current = self.toolpath_polyline[self.selected_index].copy()
            if event.modifiers() & Qt.ShiftModifier:
                # Shift basÄ±lÄ± ise Z ayarÄ± (ekran dikey hareketi -> Z)
                new_z = current[2] - dy * 0.2
                new_pt = np.array([current[0], current[1], new_z], dtype=np.float32)
            else:
                new_pt = self._point_on_plane(event.x(), event.y(), current[2])
                if new_pt is None:
                    new_pt = current
            self._update_selected_point(self.selected_index, new_pt)
            self._last_pos = event.pos()
            self._dragging = True
            return

        if event.buttons() & Qt.LeftButton:
            # DÃ¶ndÃ¼rme
            self.rot_x += dy * self.orbit_sensitivity
            self.rot_y += dx * self.orbit_sensitivity
        elif (event.buttons() & Qt.RightButton) and (event.modifiers() & Qt.AltModifier):
            # Pan (Alt + saÄŸ tuÅŸ)
            self.pan_x += dx * self.pan_sensitivity
            self.pan_y -= dy * self.pan_sensitivity

        self._last_pos = event.pos()
        self.update()

    def mouseReleaseEvent(self, event):
        was_dragging = self._dragging
        self._dragging = False
        self._last_pos = event.pos()
        if self.edit_mode and was_dragging and self.on_drag_finished is not None:
            self.on_drag_finished()
        super().mouseReleaseEvent(event) if hasattr(super(), "mouseReleaseEvent") else None

    def wheelEvent(self, event):
        delta = event.angleDelta().y() / 120.0  # her tik ~ 1
        if delta > 0:
            self.dist /= self.zoom_sensitivity
        else:
            self.dist *= self.zoom_sensitivity
        self.dist = max(10.0, min(self.dist, 5000.0))
        self.update()

    def _build_pivot_preview_polyline(self, pts: np.ndarray) -> Optional[np.ndarray]:
        """Köşe pivotları için görsel-only polyline üretir (toolpath verisini değiştirmez)."""
        try:
            if pts is None or len(pts) < 3:
                return pts
            r = float(self.pivot_preview_r_mm)
            if r <= 0.0:
                return pts
            steps = max(4, int(self.pivot_preview_steps))
            corner_deg = float(self.pivot_preview_corner_deg)
            out = [pts[0]]
            for i in range(1, len(pts) - 1):
                p_prev = pts[i - 1]
                p = pts[i]
                p_next = pts[i + 1]
                v0 = p - p_prev
                v1 = p_next - p
                n0 = math.hypot(float(v0[0]), float(v0[1]))
                n1 = math.hypot(float(v1[0]), float(v1[1]))
                if n0 < 1e-6 or n1 < 1e-6:
                    out.append(p)
                    continue
                if n0 < r * 1.05 or n1 < r * 1.05:
                    out.append(p)
                    continue
                dot = (float(v0[0]) * float(v1[0]) + float(v0[1]) * float(v1[1])) / (n0 * n1)
                dot = max(-1.0, min(1.0, dot))
                turn = math.degrees(math.acos(dot))
                if turn < corner_deg:
                    out.append(p)
                    continue
                v0n = v0 / n0
                v1n = v1 / n1
                p_in = p - v0n * r
                p_out = p + v1n * r
                if np.linalg.norm(out[-1][:2] - p_in[:2]) > 1e-6:
                    out.append(p_in)
                ang0 = math.atan2(float(p_in[1] - p[1]), float(p_in[0] - p[0]))
                ang1 = math.atan2(float(p_out[1] - p[1]), float(p_out[0] - p[0]))
                delta = ang1 - ang0
                if delta > math.pi:
                    delta -= 2 * math.pi
                elif delta < -math.pi:
                    delta += 2 * math.pi
                for s in range(1, steps):
                    t = s / float(steps)
                    ang = ang0 + delta * t
                    out.append(
                        np.array(
                            [p[0] + math.cos(ang) * r, p[1] + math.sin(ang) * r, p[2]],
                            dtype=np.float32,
                        )
                    )
                out.append(p_out)
            out.append(pts[-1])
            return np.asarray(out, dtype=np.float32)
        except Exception:
            logger.exception("Pivot preview polyline oluşturulamadı")
            return pts

    def _draw_toolpath(self):
        """Toolpath'? basit polyline olarak ?izer."""
        if self.toolpath_polyline is None:
            return
        pts = self.toolpath_polyline
        if not isinstance(pts, np.ndarray) or pts.shape[0] < 2:
            return
        # NOTE: Pivot preview uses a separate polyline for visual-only rounding.
        draw_pts = pts
        if self.pivot_preview_enabled and self._pivot_preview_polyline is not None:
            draw_pts = self._pivot_preview_polyline
        glDisable(GL_LIGHTING)
        glLineWidth(self.toolpath_width)
        r, g, b = self.toolpath_color
        glColor3f(r, g, b)
        glBegin(GL_LINE_STRIP)
        for x, y, z in draw_pts:
            glVertex3f(float(x), float(y), float(z))
        glEnd()

        # Orijinal yolu ince Ã§izgi olarak Ã§iz
        if self.show_original_toolpath and self.original_toolpath_polyline is not None:
            glDisable(GL_LIGHTING)
            glLineWidth(1.0)
            glColor3f(1.0, 0.0, 1.0)
            glBegin(GL_LINE_STRIP)
            for x, y, z in self.original_toolpath_polyline:
                glVertex3f(float(x), float(y), float(z))
            glEnd()

        # Nokta ve marker katmanÄ±
        glDisable(GL_LIGHTING)
        base_point_size = max(1.0, float(getattr(self, "point_size_px", 4.0)))

        # TÃ¼m noktalarÄ± Ã§iz
        pr, pg, pb = getattr(self, "point_color", (1.0, 1.0, 0.0))
        glPointSize(base_point_size)
        glColor3f(pr, pg, pb)
        glBegin(GL_POINTS)
        for x, y, z in pts:
            glVertex3f(float(x), float(y), float(z))
        glEnd()
        glPointSize(1.0)

        # HatalÄ± noktalar / 1. nokta rengi
        issue_color = getattr(self, "first_point_color", (1.0, 0.0, 0.0))
        if getattr(self, "issue_indices", None):
            glPointSize(base_point_size + 1.0)
            glColor3f(*issue_color)
            glBegin(GL_POINTS)
            for idx in self.issue_indices:
                if 0 <= idx < len(pts):
                    x, y, z = pts[idx]
                    glVertex3f(float(x), float(y), float(z))
            glEnd()
            glPointSize(1.0)

        # SeÃ§ili 1. ve 2. noktalar
        if self.primary_index is not None and 0 <= self.primary_index < len(pts):
            glPointSize(base_point_size + 2.0)
            glColor3f(*issue_color)
            glBegin(GL_POINTS)
            px, py, pz = pts[self.primary_index]
            glVertex3f(float(px), float(py), float(pz))
            glEnd()
            glPointSize(1.0)

        if self.secondary_index is not None and 0 <= self.secondary_index < len(pts):
            glPointSize(base_point_size + 2.0)
            sr, sg, sb = getattr(self, "second_point_color", (0.0, 1.0, 0.0))
            glColor3f(sr, sg, sb)
            glBegin(GL_POINTS)
            sx, sy, sz = pts[self.secondary_index]
            glVertex3f(float(sx), float(sy), float(sz))
            glEnd()
            glPointSize(1.0)

        # Toolpath Ã¼zerindeki anchor marker'larÄ±
        if getattr(self, "z_anchor_indices", None):
            glPointSize(max(base_point_size + 2.0, 8.0))
            glColor3f(*self.z_anchor_color)
            glBegin(GL_POINTS)
            for idx in self.z_anchor_indices:
                if 0 <= idx < len(pts):
                    x, y, z = pts[idx]
                    glVertex3f(float(x), float(y), float(z))
            glEnd()
            glPointSize(1.0)

        # STL Ã¼zerinde vurulan nokta marker'larÄ± ve baÄŸlantÄ± Ã§izgileri
        if self.z_anchor_hit_positions:
            glPointSize(base_point_size + 1.0)
            glColor3f(0.1, 0.6, 1.0)
            glBegin(GL_POINTS)
            for hit in self.z_anchor_hit_positions:
                if hit is None:
                    continue
                hx, hy, hz = hit
                glVertex3f(float(hx), float(hy), float(hz))
            glEnd()
            glPointSize(1.0)

            glColor3f(0.1, 0.6, 1.0)
            glLineWidth(1.5)
            glBegin(GL_LINES)
            for idx, hit in zip(self.z_anchor_indices, self.z_anchor_hit_positions):
                if hit is None:
                    continue
                if 0 <= idx < len(pts):
                    px, py, pz = pts[idx]
                    hx, hy, hz = hit
                    glVertex3f(float(px), float(py), float(pz))
                    glVertex3f(float(hx), float(hy), float(hz))
            glEnd()
            glLineWidth(1.0)

        glEnable(GL_LIGHTING)
