import math
from typing import Any, Dict, Optional, Tuple

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QOpenGLWidget

from OpenGL.GL import (
    GL_AMBIENT,
    GL_AMBIENT_AND_DIFFUSE,
    GL_BLEND,
    GL_COLOR_BUFFER_BIT,
    GL_COLOR_MATERIAL,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_TEST,
    GL_DIFFUSE,
    GL_FLOAT,
    GL_FRONT_AND_BACK,
    GL_LIGHT0,
    GL_LIGHTING,
    GL_LINE_SMOOTH,
    GL_MODELVIEW,
    GL_NORMAL_ARRAY,
    GL_NORMALIZE,
    GL_POSITION,
    GL_PROJECTION,
    GL_SRC_ALPHA,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_TRIANGLE_FAN,
    GL_TRIANGLES,
    GL_LINES,
    GL_VERTEX_ARRAY,
    glBegin,
    glBlendFunc,
    glClear,
    glClearColor,
    glColor3f,
    glColor4f,
    glColorMaterial,
    glDisable,
    glDisableClientState,
    glDrawArrays,
    glEnable,
    glEnableClientState,
    glEnd,
    glLightfv,
    glLineWidth,
    glLoadIdentity,
    glMatrixMode,
    glNormalPointer,
    glPopMatrix,
    glPushMatrix,
    glRotatef,
    glRasterPos3f,
    glTranslatef,
    glVertex3f,
    glVertexPointer,
    glViewport,
)
from OpenGL.GLU import gluPerspective
from OpenGL.GLUT import glutInit, glutBitmapCharacter, GLUT_BITMAP_HELVETICA_18

from core.knife_mesh import build_knife_mesh

_GLUT_READY = False


class KnifePreview3DWidget(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._profile_name = ""
        self._params: Dict[str, Any] = {}
        self._mesh_key: Optional[Tuple[Any, ...]] = None
        self._mesh = {}
        self._mesh_dirty = True
        self._length = 30.0
        self._knife_angle_deg = 0.0
        self._last_pos = None
        self._ground_visible = True

        self.dist = 160.0
        self.rot_x = 22.0
        self.rot_y = -35.0

        self.setFocusPolicy(Qt.WheelFocus)
        self._ensure_glut()

    def set_blade(self, profile_name: str, params: Dict[str, Any]):
        profile = (profile_name or "").strip()
        params = dict(params or {})
        angle = params.get("a0_deg", params.get("knife_angle_deg", 0.0))
        prev_angle = self._knife_angle_deg
        self._knife_angle_deg = float(angle or 0.0)
        params.pop("a0_deg", None)
        params.pop("knife_angle_deg", None)
        key_items = []
        for k in sorted(params.keys()):
            v = params[k]
            if isinstance(v, float):
                v = round(v, 6)
            key_items.append((k, v))
        key = (profile, tuple(key_items))
        if key == self._mesh_key:
            if abs(self._knife_angle_deg - prev_angle) > 1e-6:
                self.update()
            return

        self._profile_name = profile
        self._params = params
        self._mesh_key = key
        self._mesh_dirty = True
        self.update()

    def set_ground_visible(self, visible: bool):
        self._ground_visible = bool(visible)
        self.update()

    def _ensure_glut(self):
        global _GLUT_READY
        if _GLUT_READY:
            return
        try:
            glutInit()
            _GLUT_READY = True
        except Exception:
            _GLUT_READY = False

    def initializeGL(self):
        glClearColor(0.92, 0.92, 0.95, 1.0)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_NORMALIZE)
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)

        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, (0.6, 0.8, 1.0, 0.0))
        glLightfv(GL_LIGHT0, GL_AMBIENT, (0.2, 0.2, 0.2, 1.0))
        glLightfv(GL_LIGHT0, GL_DIFFUSE, (0.85, 0.85, 0.9, 1.0))

    def resizeGL(self, w, h):
        if h == 0:
            h = 1
        glViewport(0, 0, w, h)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(35.0, float(w) / float(h), 1.0, 10000.0)

    def _ensure_mesh(self):
        if not self._mesh_dirty:
            return
        self._mesh = build_knife_mesh(self._profile_name, self._params)
        self._length = float(self._mesh.get("length", self._params.get("blade_length_mm", 30.0)))
        span = max(self._length, float(self._params.get("body_diameter_mm", 6.0)) * 2.0, 20.0)
        self.dist = max(span * 2.8, 120.0)
        self._mesh_dirty = False

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self._ensure_mesh()

        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        glTranslatef(0.0, 0.0, -self.dist)
        glRotatef(self.rot_x, 1.0, 0.0, 0.0)
        glRotatef(self.rot_y, 0.0, 0.0, 1.0)

        if self._ground_visible:
            self._draw_reference_plane()
            self._draw_shadow()
        self._draw_direction_arrow()

        glPushMatrix()
        glTranslatef(0.0, 0.0, self._length)
        glRotatef(self._knife_angle_deg, 0.0, 0.0, 1.0)
        glRotatef(90.0, 1.0, 0.0, 0.0)
        self._draw_mesh()
        self._draw_pivot_marker()
        glPopMatrix()
        self._draw_axis_gizmo(self.width(), self.height())

    def _draw_mesh(self):
        body = self._mesh.get("body", (np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32)))
        blade = self._mesh.get("blade", (np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32)))
        kerf = self._mesh.get("kerf", (np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32)))

        self._draw_arrays(body[0], body[1], (0.65, 0.66, 0.7, 1.0))
        self._draw_arrays(blade[0], blade[1], (0.84, 0.84, 0.9, 1.0))

        if kerf[0].size > 0:
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glDisable(GL_LIGHTING)
            self._draw_arrays(kerf[0], kerf[1], (1.0, 0.7, 0.25, 0.25), use_lighting=False)
            glEnable(GL_LIGHTING)
            glDisable(GL_BLEND)

    def _draw_arrays(self, verts: np.ndarray, norms: np.ndarray, color, use_lighting: bool = True):
        if verts.size == 0:
            return
        glColor4f(*color)
        glEnableClientState(GL_VERTEX_ARRAY)
        glVertexPointer(3, GL_FLOAT, 0, verts)
        if use_lighting and norms is not None and norms.size == verts.size:
            glEnableClientState(GL_NORMAL_ARRAY)
            glNormalPointer(GL_FLOAT, 0, norms)
        else:
            glDisableClientState(GL_NORMAL_ARRAY)
        glDrawArrays(GL_TRIANGLES, 0, int(verts.shape[0]))
        glDisableClientState(GL_VERTEX_ARRAY)
        glDisableClientState(GL_NORMAL_ARRAY)

    def _draw_reference_plane(self):
        glDisable(GL_LIGHTING)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glColor4f(0.5, 0.5, 0.55, 0.25)
        grid = max(self._length * 0.6, 20.0)
        step = grid / 4.0
        glLineWidth(1.0)
        for i in range(-4, 5):
            x = i * step
            glBegin(GL_LINES)
            glVertex3f(x, -grid, 0.0)
            glVertex3f(x, grid, 0.0)
            glEnd()
        for i in range(-4, 5):
            y = i * step
            glBegin(GL_LINES)
            glVertex3f(-grid, y, 0.0)
            glVertex3f(grid, y, 0.0)
            glEnd()
        glDisable(GL_BLEND)
        glEnable(GL_LIGHTING)

    def _draw_shadow(self):
        glDisable(GL_LIGHTING)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glColor4f(0.0, 0.0, 0.0, 0.12)
        radius = max(self._length * 0.25, 8.0)
        steps = 24
        glBegin(GL_TRIANGLE_FAN)
        glVertex3f(0.0, 0.0, 0.01)
        for i in range(steps + 1):
            ang = (2.0 * math.pi) * (i / steps)
            glVertex3f(math.cos(ang) * radius, math.sin(ang) * radius * 0.6, 0.01)
        glEnd()
        glDisable(GL_BLEND)
        glEnable(GL_LIGHTING)

    def _draw_direction_arrow(self):
        ang = math.radians(self._knife_angle_deg)
        dx = math.cos(ang)
        dy = math.sin(ang)
        length = max(self._length * 0.25, 10.0)
        head = length * 0.25

        glDisable(GL_LIGHTING)
        glColor3f(0.2, 0.7, 0.2)
        glLineWidth(2.0)
        glBegin(GL_LINES)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(dx * length, dy * length, 0.0)
        glEnd()

        back = ang + math.pi
        left = back + math.radians(25.0)
        right = back - math.radians(25.0)
        glBegin(GL_LINES)
        glVertex3f(dx * length, dy * length, 0.0)
        glVertex3f(dx * length + math.cos(left) * head, dy * length + math.sin(left) * head, 0.0)
        glVertex3f(dx * length, dy * length, 0.0)
        glVertex3f(dx * length + math.cos(right) * head, dy * length + math.sin(right) * head, 0.0)
        glEnd()
        glLineWidth(1.0)
        glEnable(GL_LIGHTING)

    def _draw_pivot_marker(self):
        marker = max(self._length * 0.05, 2.5)
        glDisable(GL_LIGHTING)
        glColor3f(0.9, 0.2, 0.2)
        glLineWidth(2.0)
        glBegin(GL_LINES)
        glVertex3f(-marker, 0.0, 0.0)
        glVertex3f(marker, 0.0, 0.0)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(0.0, -marker, 0.0)
        glEnd()

        glColor3f(0.2, 0.2, 0.2)
        glBegin(GL_LINES)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(0.0, -self._length, 0.0)
        glEnd()
        glLineWidth(1.0)
        glEnable(GL_LIGHTING)

    def _draw_axis_gizmo(self, w: int, h: int):
        if not _GLUT_READY:
            return
        size = 120
        pad = 10
        y = h - size - pad
        if y < 0:
            y = 0
        glViewport(pad, y, size, size)

        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)

        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        gluPerspective(35.0, 1.0, 0.1, 100.0)

        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glTranslatef(0.0, 0.0, -3.0)
        glRotatef(self.rot_x, 1.0, 0.0, 0.0)
        glRotatef(self.rot_y, 0.0, 0.0, 1.0)

        glLineWidth(3.0)
        glBegin(GL_LINES)
        glColor3f(1.0, 0.0, 0.0)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(1.0, 0.0, 0.0)
        glColor3f(0.0, 1.0, 0.0)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(0.0, 1.0, 0.0)
        glColor3f(0.0, 0.0, 1.0)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(0.0, 0.0, 1.0)
        glEnd()
        glLineWidth(1.0)

        glColor3f(1.0, 0.0, 0.0)
        glRasterPos3f(1.1, 0.0, 0.0)
        glutBitmapCharacter(GLUT_BITMAP_HELVETICA_18, ord("X"))
        glColor3f(0.0, 1.0, 0.0)
        glRasterPos3f(0.0, 1.1, 0.0)
        glutBitmapCharacter(GLUT_BITMAP_HELVETICA_18, ord("Y"))
        glColor3f(0.0, 0.0, 1.0)
        glRasterPos3f(0.0, 0.0, 1.1)
        glutBitmapCharacter(GLUT_BITMAP_HELVETICA_18, ord("Z"))

        glMatrixMode(GL_MODELVIEW)
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)

        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)
        glViewport(0, 0, w, h)

    def wheelEvent(self, event):
        delta = event.angleDelta().y() / 120.0
        self.dist *= (1.0 - delta * 0.08)
        self.dist = max(40.0, min(2000.0, self.dist))
        self.update()

    def mousePressEvent(self, event):
        self._last_pos = event.pos()

    def mouseMoveEvent(self, event):
        if self._last_pos is None:
            return
        dx = event.x() - self._last_pos.x()
        dy = event.y() - self._last_pos.y()
        if event.buttons() & Qt.LeftButton:
            self.rot_y += dx * 0.6
            self.rot_x += dy * 0.6
        self._last_pos = event.pos()
        self.update()

    def mouseReleaseEvent(self, event):
        self._last_pos = None
