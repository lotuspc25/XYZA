from typing import Any, Dict, List, Optional, Tuple
import math

from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QWidget

from core.blade_profiles import build_profile_points

Point2D = Tuple[float, float]


class BladePreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._profile_name = ""
        self._params: Dict[str, Any] = {}
        self._profile_data: Dict[str, Any] = {}
        self._zoom = 1.0
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.WheelFocus)

    def _circle_points(self, radius: float, steps: int) -> List[Point2D]:
        pts = []
        if steps < 8:
            steps = 8
        for i in range(steps):
            ang = (2.0 * 3.141592653589793) * (i / steps)
            pts.append((radius * math.cos(ang), radius * math.sin(ang)))
        if pts:
            pts.append(pts[0])
        return pts

    def _arc_points(self, cx: float, cy: float, r: float, start_deg: float, end_deg: float, steps: int) -> List[Point2D]:
        if steps < 4:
            steps = 4
        pts = []
        for i in range(steps):
            t = i / (steps - 1)
            ang = math.radians(start_deg + (end_deg - start_deg) * t)
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        return pts

    def set_blade(self, profile_name: str, params: Dict[str, Any]):
        self._profile_name = profile_name or ""
        self._params = dict(params or {})
        try:
            self._profile_data = build_profile_points(self._profile_name, self._params)
        except Exception:
            self._profile_data = {}
        self.update()

    def _get_bounds(self, points: List[Point2D], extras: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
        if points:
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            return min(xs), max(xs), min(ys), max(ys)
        disk_r = float(extras.get("disk_radius", 0.0) or 0.0)
        if disk_r > 0.0:
            return -disk_r, disk_r, -disk_r, disk_r
        return None

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect()
        painter.fillRect(rect, self.palette().base())

        data = self._profile_data or {}
        outline = []
        tip = None
        centerline = []
        extras = {}

        profile = (self._profile_name or "").strip().lower().replace("-", "_").replace(" ", "")
        if profile in ("scalpel", "scalpelpointed", "scalpel_pointed"):
            profile = "scalpel_pointed"
        elif profile in ("scalpelrounded", "scalpel_rounded", "rounded"):
            profile = "scalpel_rounded"
        elif profile in ("rotarydisk", "rotary_disk", "disk", "rotary"):
            profile = "rotary_disk"

        length_mm = float(self._params.get("blade_length_mm", 30.0) or 30.0)
        tip_diam = float(self._params.get("tip_diameter_mm", 2.0) or 2.0)
        body_diam = float(self._params.get("shank_diameter_mm", 6.0) or 6.0)
        cut_len = float(self._params.get("cut_length_mm", 10.0) or 10.0)
        length_mm = max(length_mm, 0.1)
        cut_len = max(min(cut_len, length_mm), 0.1)
        shank_len = max(length_mm - cut_len, 0.0)
        body_half = max(body_diam * 0.5, 0.05)
        tip_half = max(tip_diam * 0.5, 0.01)
        tip_half = min(tip_half, cut_len)

        if profile == "rotary_disk":
            radius = max(length_mm * 0.5, 0.1)
            outline = self._circle_points(radius, 48)
            tip = (radius, 0.0)
            centerline = [(-radius, 0.0), (radius, 0.0)]
            extras = {
                "disk_radius": radius,
                "hub_radius": max(body_diam * 0.5, 0.0),
                "kerf": float(self._params.get("kerf_mm", 0.3) or 0.3),
            }
        else:
            if profile == "scalpel_rounded":
                arc_center_x = length_mm - tip_half
                arc = self._arc_points(arc_center_x, 0.0, tip_half, 90.0, -90.0, 9)
                outline = [
                    (0.0, body_half),
                    (shank_len, body_half),
                ] + arc + [
                    (shank_len, -body_half),
                    (0.0, -body_half),
                    (0.0, body_half),
                ]
            else:
                outline = [
                    (0.0, body_half),
                    (shank_len, body_half),
                    (length_mm, tip_half),
                    (length_mm, -tip_half),
                    (shank_len, -body_half),
                    (0.0, -body_half),
                    (0.0, body_half),
                ]
            tip = (length_mm, 0.0)
            centerline = [(0.0, 0.0), (length_mm, 0.0)]

        if not outline:
            outline = data.get("outline") or []
            tip = data.get("tip")
            centerline = data.get("centerline") or []
            extras = data.get("extras") or {}
        if outline and outline[0] == outline[-1]:
            outline = outline[:-1]

        direction_axis = str(self._params.get("direction_axis", "x") or "x").lower()
        if direction_axis not in ("x", "y"):
            direction_axis = "x"
        if profile == "rotary_disk":
            depth_mm = float(self._params.get("disk_thickness_mm", 2.0) or 2.0)
        else:
            depth_mm = float(self._params.get("blade_thickness_mm", 1.0) or 1.0)
        depth_mm = max(depth_mm, 0.0)

        bounds = self._get_bounds(outline, extras)
        if bounds is None:
            return

        min_x, max_x, min_y, max_y = bounds
        span_x = max(max_y - min_y, 1e-6)
        span_y = max(max_x - min_x, 1e-6)

        margin = 10.0
        avail_w = max(rect.width() - margin * 2.0, 1.0)
        avail_h = max(rect.height() - margin * 2.0, 1.0)
        scale = min(avail_w / span_x, avail_h / span_y) * self._zoom

        if scale > 0.0:
            max_depth_mm = 40.0 / scale
            if depth_mm > max_depth_mm:
                depth_mm = max_depth_mm

        vec = (-1.0, 1.0) if direction_axis == "x" else (-1.0, -1.0)
        inv_len = 1.0 / (2.0 ** 0.5)
        depth_dx = vec[0] * inv_len * depth_mm
        depth_dy = vec[1] * inv_len * depth_mm

        min_x2 = min_x + depth_dx
        max_x2 = max_x + depth_dx
        min_y2 = min_y + depth_dy
        max_y2 = max_y + depth_dy
        min_x = min(min_x, min_x2, max_x2)
        max_x = max(max_x, min_x2, max_x2)
        min_y = min(min_y, min_y2, max_y2)
        max_y = max(max_y, min_y2, max_y2)

        span_x = max(max_y - min_y, 1e-6)
        span_y = max(max_x - min_x, 1e-6)
        scale = min(avail_w / span_x, avail_h / span_y) * self._zoom

        cx = (min_x + max_x) * 0.5
        cy = (min_y + max_y) * 0.5
        px = rect.width() * 0.5
        py = rect.height() * 0.5

        def to_screen(pt: Point2D) -> QPointF:
            x, y = pt
            sx = (y - cy) * scale + px
            sy = (x - cx) * scale + py
            return QPointF(sx, sy)

        front_pts = []
        back_pts = []
        if outline:
            for pt in outline:
                front_pts.append(to_screen(pt))
                back_pts.append(to_screen((pt[0] + depth_dx, pt[1] + depth_dy)))

        if outline:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(120, 120, 120))
            painter.drawPolygon(QPolygonF(back_pts))

            painter.setBrush(QColor(170, 170, 170))
            for i in range(len(front_pts)):
                j = (i + 1) % len(front_pts)
                quad = QPolygonF([front_pts[i], front_pts[j], back_pts[j], back_pts[i]])
                painter.drawPolygon(quad)

            painter.setBrush(QColor(210, 210, 210))
            painter.drawPolygon(QPolygonF(front_pts))

            painter.setPen(QPen(QColor(30, 30, 30), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(QPolygonF(front_pts))

        if centerline:
            pen = QPen(QColor(160, 160, 160), 1, Qt.DashLine)
            painter.setPen(pen)
            for i in range(len(centerline) - 1):
                painter.drawLine(to_screen(centerline[i]), to_screen(centerline[i + 1]))

        disk_r = float(extras.get("disk_radius", 0.0) or 0.0)
        if disk_r > 0.0:
            center = to_screen((0.0, 0.0))
            center_back = to_screen((depth_dx, depth_dy))
            r_px = disk_r * scale
            kerf = float(extras.get("kerf", 0.0) or 0.0)
            hub_r = float(extras.get("hub_radius", 0.0) or 0.0)
            painter.setPen(QPen(QColor(80, 80, 80), 1))
            painter.drawEllipse(center_back, r_px, r_px)
            painter.setPen(QPen(QColor(40, 40, 40), 1))
            painter.drawEllipse(center, r_px, r_px)
            if kerf > 0.0 and r_px > 2.0:
                inner_r = max((disk_r - kerf) * scale, 0.0)
                painter.setPen(QPen(QColor(140, 140, 140), 1))
                painter.drawEllipse(center, inner_r, inner_r)
            if hub_r > 0.0:
                hub_px = hub_r * scale
                painter.setPen(QPen(QColor(90, 90, 90), 1))
                painter.drawEllipse(center, hub_px, hub_px)

        if tip is not None:
            tip_pt = to_screen(tip)
            painter.setPen(QPen(QColor(20, 140, 20), 1))
            painter.setBrush(QColor(20, 140, 20))
            painter.drawEllipse(tip_pt, 3.0, 3.0)

        axis_len = 18
        pad = 10
        ax_x = rect.left() + pad
        ax_y = rect.top() + pad
        painter.setPen(QPen(QColor(120, 120, 120), 1))
        painter.drawLine(ax_x, ax_y, ax_x + axis_len, ax_y)
        painter.drawLine(ax_x, ax_y, ax_x, ax_y + axis_len)
        painter.drawText(ax_x + axis_len + 2, ax_y + 4, "X")
        painter.drawText(ax_x - 2, ax_y + axis_len + 12, "Z")

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        step = 1.1 if delta > 0 else 1.0 / 1.1
        self._zoom = max(0.2, min(self._zoom * step, 10.0))
        self.update()
        event.accept()

    def mousePressEvent(self, event):
        event.ignore()

    def mouseMoveEvent(self, event):
        event.ignore()

    def mouseReleaseEvent(self, event):
        event.ignore()
