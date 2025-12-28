from typing import List, Optional, Tuple

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
)


def _strip_comments(line: str) -> str:
    """Remove simple ';' and '(...)' comments from a G-code line."""
    if ";" in line:
        line = line.split(";", 1)[0]
    if "(" in line and ")" in line:
        # basic removal, not handling nested parentheses (sufficient for viewer)
        start = line.find("(")
        end = line.find(")", start + 1)
        if end != -1:
            line = line[:start] + line[end + 1 :]
    return line.strip()


class GCodeViewerQGV(QGraphicsView):
    """
    Basit Mach3 benzeri 2D G-code viewer.
    - QGraphicsView/QGraphicsScene tabanlı
    - G0 (rapid) ve G1 (feed) yolları farklı renkte/dashed çizilir
    - Kozmetik kalem: zoom yapınca çizgi kalınlığı değişmez
    - Mouse wheel zoom, orta tuş pan, çift tıklama fit
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHints(self.renderHints() | QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.ScrollHandDrag)

        # Path items
        self._rapid_item = QGraphicsPathItem()
        pen_rapid = QPen(Qt.darkBlue)
        pen_rapid.setStyle(Qt.DashLine)
        pen_rapid.setWidthF(1.5)
        pen_rapid.setCosmetic(True)
        self._rapid_item.setPen(pen_rapid)
        self.scene.addItem(self._rapid_item)

        self._feed_item = QGraphicsPathItem()
        pen_feed = QPen(Qt.darkGreen)
        pen_feed.setStyle(Qt.SolidLine)
        pen_feed.setWidthF(1.8)
        pen_feed.setCosmetic(True)
        self._feed_item.setPen(pen_feed)
        self.scene.addItem(self._feed_item)

        self._bbox = None  # type: Optional[Tuple[float, float, float, float]]

    # ----------------------------
    # Public API
    # ----------------------------
    def clear(self) -> None:
        self._rapid_item.setPath(QPainterPath())
        self._feed_item.setPath(QPainterPath())
        self.scene.setSceneRect(0, 0, 0, 0)
        self._bbox = None

    def set_gcode(self, text: str) -> None:
        """Parse given G-code text and render rapid/feed paths."""
        self.clear()
        if not text:
            return
        rapid_path, feed_path, bbox = self._parse_gcode_to_paths(text)
        self._rapid_item.setPath(rapid_path)
        self._feed_item.setPath(feed_path)
        if bbox:
            xmin, xmax, ymin, ymax = bbox
            self._bbox = bbox
            self.scene.setSceneRect(xmin, ymin, xmax - xmin, ymax - ymin)
            self.fit_to_path()

    def fit_to_path(self, padding: float = 10.0) -> None:
        if self._bbox is None:
            return
        xmin, xmax, ymin, ymax = self._bbox
        w = max(1e-3, (xmax - xmin) + padding * 2)
        h = max(1e-3, (ymax - ymin) + padding * 2)
        self.fitInView(xmin - padding, ymin - padding, w, h, Qt.KeepAspectRatio)

    # ----------------------------
    # Event handlers
    # ----------------------------
    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.25 if delta > 0 else 0.8
        self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self._pan_start = event.pos()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_pan_start", None) is not None and event.buttons() & Qt.MiddleButton:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._pan_start = None
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.fit_to_path()
        event.accept()

    # ----------------------------
    # Internal helpers
    # ----------------------------
    def _parse_gcode_to_paths(self, text: str) -> Tuple[QPainterPath, QPainterPath, Optional[Tuple[float, float, float, float]]]:
        rapid_path = QPainterPath()
        feed_path = QPainterPath()

        last_x = last_y = last_z = last_a = None
        mode = "G0"  # default modal mode
        points_feed: List[Tuple[float, float]] = []
        points_rapid: List[Tuple[float, float]] = []

        def add_segment(container: List[Tuple[float, float]], x: float, y: float):
            container.append((x, y))

        for raw in text.splitlines():
            line = _strip_comments(raw).upper()
            if not line:
                continue

            # modal mode detect
            if "G0" in line or "G00" in line:
                mode = "G0"
            elif "G1" in line or "G01" in line:
                mode = "G1"

            def _extract(prefix: str, current: Optional[float]) -> Optional[float]:
                if prefix not in line:
                    return current
                try:
                    start = line.find(prefix) + len(prefix)
                    end = start
                    while end < len(line) and (line[end].isdigit() or line[end] in ".-+"):
                        end += 1
                    return float(line[start:end])
                except Exception:
                    return current

            x = _extract("X", last_x)
            y = _extract("Y", last_y)
            z = _extract("Z", last_z)
            a = _extract("A", last_a)
            # update modal coordinates
            last_x, last_y, last_z, last_a = x, y, z, a

            if x is None or y is None:
                continue

            if mode == "G1":
                add_segment(points_feed, x, y)
            else:
                add_segment(points_rapid, x, y)

        # Build painter paths from collected points
        def build_path(pts: List[Tuple[float, float]]) -> QPainterPath:
            if not pts:
                return QPainterPath()
            path = QPainterPath(QPointF(pts[0][0], pts[0][1]))
            for px, py in pts[1:]:
                path.lineTo(QPointF(px, py))
            return path

        rapid_path = build_path(points_rapid)
        feed_path = build_path(points_feed)

        bbox = None
        all_pts = points_feed + points_rapid
        if all_pts:
            xs = [p[0] for p in all_pts]
            ys = [p[1] for p in all_pts]
            bbox = (min(xs), max(xs), min(ys), max(ys))

        return rapid_path, feed_path, bbox
