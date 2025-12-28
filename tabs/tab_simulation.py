# tabs/tab_simulation.py
# ----------------------------------------------------------
# STL bıçak modelini 3D OpenGL sahnesinde gösterir.
# Özellikler:
#   - STL yükleme tabs/knife_model.py üzerinden
#   - Bıçak A açısı (Z ekseninde dönüş)
#   - Bıçak yönü: X eksenine paralel veya Y eksenine paralel
#   - Ölçek: bıçak çapını büyütme/küçültme
#   - Orbit / Pan / Zoom kontrolleri
# ----------------------------------------------------------

import numpy as np
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtCore import Qt

from OpenGL.GL import *
from OpenGL.GLU import gluPerspective

from core.blade_profiles import build_profile_points
from core.knife_spec import load_knife_spec
from tabs.knife_model import load_knife_stl
from core.path_utils import find_or_create_config


class GLKnifeViewer(QOpenGLWidget):
    def __init__(self, parent=None, state=None):
        super().__init__(parent)
        self.state = state

        # STL mesh
        self.vertices = None
        self.normals = None
        self.tri_count = 0

        # Görsel ayarlar
        self.bg_color = (0.92, 0.92, 0.96)

        # Kamera parametreleri
        self.dist = 200.0
        self.rot_x = 20.0
        self.rot_y = -30.0
        self.pan_x = 0.0
        self.pan_y = 0.0

        # Bıçak ayarları
        self.scale_factor = 1.0        # çap ölçeği
        self.knife_angle_deg = 0.0     # Z ekseninde dönüş
        self.axis_mode = "z"           # "x" veya "y"

        # Mouse kontrol
        self._last_pos = None
        self._last_button = None

        # STL yükle
        self.reload_knife_from_settings()

    # ------------------------------------------------------
    # STL YÜKLEME
    # ------------------------------------------------------
    def load_stl(self):
        v, n = load_knife_stl()
        self.vertices = v
        self.normals = n
        self.tri_count = len(v)
        self.update()

    # Dışarıdan mesh (ölçeklenmiş) ver

    def reload_knife_from_settings(self, cfg_path: str = None):
        if cfg_path is None:
            cfg_path = str(find_or_create_config()[0])
        spec = load_knife_spec(cfg_path)
        self._apply_knife_spec(spec)

    def _apply_knife_spec(self, spec):
        if not spec:
            return
        self.knife_angle_deg = float(spec.get("a0_deg", 0.0))
        profile = spec.get("profile", "scalpel_pointed")
        params = {
            "blade_length_mm": float(spec.get("length_mm", 30.0)),
            "tip_diameter_mm": float(spec.get("tip_diameter_mm", 2.0)),
            "shank_diameter_mm": float(spec.get("body_diameter_mm", 6.0)),
            "disk_diameter_mm": float(spec.get("tip_diameter_mm", 2.0)),
            "hub_diameter_mm": float(spec.get("body_diameter_mm", 6.0)),
            "kerf_mm": 0.3,
        }
        verts, norms = self._build_profile_mesh(profile, params)
        length_mm = max(params["blade_length_mm"], params["tip_diameter_mm"])
        if verts.size == 0:
            self.load_stl()
            return
        self.set_knife_mesh(verts, norms, length_mm)
    def set_knife_mesh(self, vertices: np.ndarray, normals: np.ndarray, length_mm: float):
        self.vertices = vertices
        self.normals = normals
        self.tri_count = 0 if vertices is None else vertices.shape[0]
        # Boya göre kamera uzaklığı
        self.dist = max(10.0, float(length_mm) * 3.0)
        self.update()

    def set_knife_angle(self, angle_deg: float):
        self.knife_angle_deg = float(angle_deg)
        self.update()

    # ------------------------------------------------------
    # DIŞARIDAN ÇAĞRILAN AYARLAR
    # ------------------------------------------------------
    def set_scale(self, s: float):
        self.scale_factor = max(0.01, float(s))
        self.update()

    def set_angle(self, ang):
        self.knife_angle_deg = float(ang)
        self.update()

    def set_axis_mode(self, mode: str):
        if mode in ("x", "y", "z"):
            self.axis_mode = mode
            self.update()

    # ------------------------------------------------------
    # OPENGL
    # ------------------------------------------------------
    def initializeGL(self):
        glClearColor(*self.bg_color, 1.0)
        glEnable(GL_DEPTH_TEST)

        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, (0.5, 0.8, 1.0, 0.0))
        glLightfv(GL_LIGHT0, GL_AMBIENT, (0.15, 0.15, 0.18, 1.0))
        glLightfv(GL_LIGHT0, GL_DIFFUSE, (0.9, 0.9, 0.9, 1.0))

        glLightModeli(GL_LIGHT_MODEL_TWO_SIDE, GL_TRUE)
        glEnable(GL_NORMALIZE)

        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)

    def resizeGL(self, w, h):
        if h == 0:
            h = 1

        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(30.0, w / float(h), 5.0, 5000.0)

    def paintGL(self):
        glClearColor(*self.bg_color, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

        # Kamera dönüşleri
        glTranslatef(0.0, 0.0, -self.dist)
        glRotatef(self.rot_x, 1.0, 0.0, 0.0)
        glRotatef(self.rot_y, 0.0, 1.0, 0.0)

        # Pan
        glTranslatef(self.pan_x, self.pan_y, 0.0)

        self._draw_axes()
        self._draw_stl()

    # ------------------------------------------------------
    # EKSENLER
    # ------------------------------------------------------
    def _draw_axes(self):
        glDisable(GL_LIGHTING)
        glLineWidth(2.0)

        L = 50.0

        # X – kırmızı
        glColor3f(1.0, 0.0, 0.0)
        glBegin(GL_LINES)
        glVertex3f(0, 0, 0)
        glVertex3f(L, 0, 0)
        glEnd()

        # Y – yeşil
        glColor3f(0.0, 1.0, 0.0)
        glBegin(GL_LINES)
        glVertex3f(0, 0, 0)
        glVertex3f(0, L, 0)
        glEnd()

        # Z – mavi
        glColor3f(0.0, 0.0, 1.0)
        glBegin(GL_LINES)
        glVertex3f(0, 0, 0)
        glVertex3f(0, 0, L)
        glEnd()

        glLineWidth(1.0)
        glEnable(GL_LIGHTING)

    # ------------------------------------------------------
    # STL ÇİZİMİ
    # ------------------------------------------------------
    def _draw_stl(self):
        if self.vertices is None:
            return

        glPushMatrix()

        # Ölçek
        glScalef(self.scale_factor, self.scale_factor, self.scale_factor)

        # Yön ayarı (bıçak ekseni)
        if self.axis_mode == "x":
            # Bıçak X eksenine paralel
            glRotatef(-90, 0, 1, 0)
        elif self.axis_mode == "y":
            # Bıçak Y eksenine paralel
            glRotatef(90, 1, 0, 0)

        # A açısı (Z etrafında dönüş)
        glRotatef(self.knife_angle_deg, 0, 0, 1)

        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_NORMAL_ARRAY)

        glVertexPointer(3, GL_FLOAT, 0, self.vertices)
        glNormalPointer(GL_FLOAT, 0, self.normals)

        glColor3f(0.85, 0.85, 0.9)
        glDrawArrays(GL_TRIANGLES, 0, self.tri_count)

        glDisableClientState(GL_VERTEX_ARRAY)
        glDisableClientState(GL_NORMAL_ARRAY)

        glPopMatrix()

    # ------------------------------------------------------
    # MOUSE KONTROLLERİ
    # ------------------------------------------------------
    def mousePressEvent(self, event):
        self._last_pos = event.pos()
        self._last_button = event.button()

    def mouseMoveEvent(self, event):
        if self._last_pos is None:
            return

        dx = event.x() - self._last_pos.x()
        dy = event.y() - self._last_pos.y()

        if self._last_button == Qt.LeftButton:
            self.rot_y += dx * 0.5
            self.rot_x += dy * 0.5
        else:
            self.pan_x += dx * 0.05
            self.pan_y -= dy * 0.05

        self._last_pos = event.pos()
        self.update()

    def wheelEvent(self, event):
        delta = event.angleDelta().y() / 120.0
        self.dist *= (1.0 - delta * 0.1)
        self.dist = max(10.0, min(5000.0, self.dist))
        self.update()

    def _build_profile_mesh(self, profile: str, params: dict):
        data = build_profile_points(profile, params)
        outline = data.get("outline") or []
        if len(outline) < 3:
            return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32)
        if outline[0] == outline[-1]:
            outline = outline[:-1]
        if len(outline) < 3:
            return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32)

        cx = sum(p[0] for p in outline) / len(outline)
        cz = sum(p[1] for p in outline) / len(outline)
        center = (cx, cz)

        thickness = max(0.4, min(float(params.get("shank_diameter_mm", 2.0)) * 0.2, 2.0))
        y_front = thickness * 0.5
        y_back = -y_front

        verts = []
        norms = []

        def map_pt(pt, y):
            x2, z2 = pt
            return (z2, y, -x2)

        normal_front = (0.0, 1.0, 0.0)
        normal_back = (0.0, -1.0, 0.0)

        for i in range(len(outline)):
            p1 = outline[i]
            p2 = outline[(i + 1) % len(outline)]
            verts.extend([map_pt(center, y_front), map_pt(p1, y_front), map_pt(p2, y_front)])
            norms.extend([normal_front, normal_front, normal_front])
            verts.extend([map_pt(center, y_back), map_pt(p2, y_back), map_pt(p1, y_back)])
            norms.extend([normal_back, normal_back, normal_back])

        return np.array(verts, dtype=np.float32), np.array(norms, dtype=np.float32)
