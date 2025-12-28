import math
from typing import Iterable, Optional, Sequence

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QPainter, QPainterPath, QPen, QTransform
from PyQt5.QtWidgets import QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView


class GCodeViewer2D(QGraphicsView):
    """
    Basit 2D toolpath viewer.
    - QGraphicsView/QGraphicsScene tabanlı
    - Tek path item ile çizim (performans için)
    - Kozmetik kalem: zoom'da çizgi kalınlığı sabit
    - Seçili nokta için marker
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        # Antialiasing için QPainter sabiti kullan
        self.setRenderHints(self.renderHints() | QPainter.Antialiasing)
        self._path_item = QGraphicsPathItem()
        pen = QPen(Qt.darkGreen)
        pen.setWidthF(1.5)
        pen.setCosmetic(True)
        self._path_item.setPen(pen)
        self.scene.addItem(self._path_item)

        self._marker = QGraphicsEllipseItem()
        self._marker.setRect(-3, -3, 6, 6)
        mpen = QPen(Qt.red)
        mpen.setWidthF(2.0)
        mpen.setCosmetic(True)
        self._marker.setPen(mpen)
        self._marker.setBrush(Qt.red)
        self._marker.setVisible(False)
        self.scene.addItem(self._marker)

        self._points: list[tuple[float, float]] = []
        self._selected_index: Optional[int] = None

        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    # ----------------------------
    # API
    # ----------------------------
    def clear(self):
        self._points = []
        self._path_item.setPath(QPainterPath())
        self._marker.setVisible(False)
        self._selected_index = None
        self.scene.setSceneRect(0, 0, 0, 0)

    def set_points(self, points: Optional[Sequence]) -> None:
        """
        points: list of ToolpathPoint / dict / tuple with x,y.
        """
        self.clear()
        if not points:
            return
        parsed = []
        for p in points:
            try:
                if hasattr(p, "x"):
                    parsed.append((float(p.x), float(p.y)))
                elif isinstance(p, dict):
                    parsed.append((float(p.get("x", 0.0)), float(p.get("y", 0.0))))
                else:
                    x, y = p[0], p[1]
                    parsed.append((float(x), float(y)))
            except Exception:
                continue
        if len(parsed) < 2:
            return
        self._points = parsed
        path = QPainterPath(QPointF(parsed[0][0], parsed[0][1]))
        for x, y in parsed[1:]:
            path.lineTo(QPointF(x, y))
        self._path_item.setPath(path)

        # Scene rect
        xs = [pt[0] for pt in parsed]
        ys = [pt[1] for pt in parsed]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        self.scene.setSceneRect(min_x, min_y, max_x - min_x, max_y - min_y)
        self.fit_to_path()

    def set_selected_index(self, index: Optional[int]) -> None:
        self._selected_index = index
        if index is None or self._points is None or not self._points or index < 0 or index >= len(self._points):
            self._marker.setVisible(False)
            return
        x, y = self._points[index]
        self._marker.setRect(x - 2.5, y - 2.5, 5.0, 5.0)
        self._marker.setVisible(True)

    def fit_to_path(self, padding: float = 20.0) -> None:
        if not self._points:
            return
        xs = [pt[0] for pt in self._points]
        ys = [pt[1] for pt in self._points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        rect = self.scene.sceneRect()
        if rect.isNull():
            rect = self._path_item.path().boundingRect()
        rect.adjust(-padding, -padding, padding, padding)
        self.fitInView(rect, Qt.KeepAspectRatio)

    def focus_on_point(self, index: int, padding: float = 80.0) -> None:
        if index is None or self._points is None or not self._points:
            return
        if index < 0 or index >= len(self._points):
            return
        x, y = self._points[index]
        self.set_selected_index(index)
        rect = self.scene.sceneRect()
        cx, cy = x, y
        self.centerOn(QPointF(cx, cy))
        # Optional: zoom a bit
        self.fitInView(rect.adjusted(-padding, -padding, padding, padding), Qt.KeepAspectRatio)

    # ----------------------------
    # Etkileşim (zoom/pan)
    # ----------------------------
    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        space_mod = False
        try:
            # Qt6 style KeyboardModifier
            space_mod = bool(event.modifiers() & Qt.KeyboardModifier.SpaceModifier)
        except AttributeError:
            try:
                # Qt5 fallback
                space_mod = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            except Exception:
                space_mod = False

        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and space_mod):
            self.setDragMode(QGraphicsView.ScrollHandDrag)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.dragMode() == QGraphicsView.ScrollHandDrag:
            self.setDragMode(QGraphicsView.NoDrag)
        super().mouseReleaseEvent(event)

    # Optional: click to select nearest point (brute-force)
    def mouseDoubleClickEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        if self._points:
            best_idx = None
            best_d = None
            for i, (x, y) in enumerate(self._points):
                dx = x - scene_pos.x()
                dy = y - scene_pos.y()
                d = math.hypot(dx, dy)
                if best_d is None or d < best_d:
                    best_d = d
                    best_idx = i
            if best_idx is not None:
                self.set_selected_index(best_idx)
        super().mouseDoubleClickEvent(event)
