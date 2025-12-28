from typing import List, Optional

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView

from toolpath_gcode_parser import GcodeSegment


class SimViewerQGV(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHints(self.renderHints() | QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.ScrollHandDrag)

        self._done_item = QGraphicsPathItem()
        pen_done = QPen(Qt.green)
        pen_done.setCosmetic(True)
        pen_done.setWidthF(2.0)
        self._done_item.setPen(pen_done)
        self.scene.addItem(self._done_item)

        self._rem_item = QGraphicsPathItem()
        pen_rem = QPen(Qt.darkGray)
        pen_rem.setCosmetic(True)
        pen_rem.setWidthF(1.0)
        self._rem_item.setPen(pen_rem)
        self.scene.addItem(self._rem_item)

        self._marker = QGraphicsEllipseItem(-3, -3, 6, 6)
        marker_pen = QPen(Qt.red)
        marker_pen.setCosmetic(True)
        marker_pen.setWidthF(2.0)
        self._marker.setPen(marker_pen)
        self._marker.setBrush(Qt.red)
        self.scene.addItem(self._marker)
        self._marker.setVisible(False)

        self.segments: List[GcodeSegment] = []

    def clear(self):
        self.segments = []
        self._done_item.setPath(QPainterPath())
        self._rem_item.setPath(QPainterPath())
        self._marker.setVisible(False)
        self.scene.setSceneRect(0, 0, 0, 0)

    def set_segments(self, segments: List[GcodeSegment]):
        self.segments = segments or []
        self.set_progress(done_count=0)
        self._update_scene_rect()

    def _update_scene_rect(self):
        if not self.segments:
            self.scene.setSceneRect(0, 0, 0, 0)
            return
        xs = []
        ys = []
        for s in self.segments:
            xs.extend([s.start[0], s.end[0]])
            ys.extend([s.start[1], s.end[1]])
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        pad = 10.0
        self.scene.setSceneRect(xmin - pad, ymin - pad, (xmax - xmin) + 2 * pad, (ymax - ymin) + 2 * pad)

    def set_progress(self, done_count: int):
        if not self.segments:
            self.clear()
            return
        done_path = QPainterPath()
        rem_path = QPainterPath()
        all_pts: List[QPointF] = []

        for idx, seg in enumerate(self.segments):
            path = done_path if idx < done_count else rem_path
            path = self._append_segment(path, seg)
            if idx < done_count:
                done_path = path
            else:
                rem_path = path
            all_pts.append(QPointF(seg.end[0], seg.end[1]))

        self._done_item.setPath(done_path)
        self._rem_item.setPath(rem_path)

        if done_count > 0:
            end_pt = self.segments[min(done_count - 1, len(self.segments) - 1)].end
        else:
            end_pt = self.segments[0].start
        self._marker.setPos(end_pt[0], end_pt[1])
        self._marker.setVisible(True)

    def _append_segment(self, path: QPainterPath, seg: GcodeSegment) -> QPainterPath:
        if path.isEmpty():
            path.moveTo(seg.start[0], seg.start[1])
        if seg.type in ("RAPID", "FEED"):
            path.lineTo(seg.end[0], seg.end[1])
        elif seg.type in ("ARC_CW", "ARC_CCW") and seg.i is not None and seg.j is not None:
            cx = seg.start[0] + seg.i
            cy = seg.start[1] + seg.j
            # simple arc: approximate with lineTo for now
            path.lineTo(seg.end[0], seg.end[1])
        else:
            path.lineTo(seg.end[0], seg.end[1])
        return path

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.25 if delta > 0 else 0.8
        self.scale(factor, factor)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        event.accept()
