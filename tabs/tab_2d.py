import logging
import os
from typing import Optional

import numpy as np

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QFileDialog,
    QCheckBox,
    QSpinBox,
)

from core.a_axis_generator import generate_a_overlay
from core.gcode_2d import build_xya_gcode
from core.io_json import write_json
from core.toolpath_2d import build_2d_toolpath
from project_state import ToolpathPoint
from render.viewer_2d import Viewer2DWidget

logger = logging.getLogger(__name__)


class Tab2DWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = getattr(parent, "state", None)
        self._toolpath: Optional[dict] = None
        self._toolpath_points: Optional[list] = None
        self._a_result: Optional[dict] = None

        self._btn_load = QPushButton("STL / DXF seç")
        self._btn_load.clicked.connect(self._on_open_file)

        self._status = QLabel("Dosya seçilmedi")
        self._status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._status.setWordWrap(True)

        self._viewer = Viewer2DWidget(self)

        self._chk_enable_a = QCheckBox("A üret (2D teğet)")
        self._chk_enable_a.setChecked(True)
        self._chk_enable_a.setVisible(False)
        self._chk_enable_a.toggled.connect(self._on_a_toggle)

        self._spin_smooth = QSpinBox()
        self._spin_smooth.setRange(1, 101)
        self._spin_smooth.setValue(5)
        self._spin_smooth.setSingleStep(1)
        self._spin_smooth.setEnabled(False)

        self._spin_corner = _make_spinbox(5.0, 170.0, 25.0, 1.0, 1)
        self._spin_corner.setEnabled(False)
        self._spin_corner.valueChanged.connect(self._apply_arrow_settings)

        self._btn_compute_a = QPushButton("A Yolu ?ret")
        self._btn_compute_a.setEnabled(False)
        self._btn_compute_a.clicked.connect(self._on_compute_a)

        self._btn_export_a = QPushButton("JSON Kaydet")
        self._btn_export_a.setEnabled(False)
        self._btn_export_a.clicked.connect(self._on_export_a)

        self._btn_export_gcode = QPushButton("G-code (XYA) Kaydet")
        self._btn_export_gcode.setEnabled(False)
        self._btn_export_gcode.clicked.connect(self._on_export_gcode)

        self._chk_show_arrows = QCheckBox("A yönünü göster")
        self._chk_show_arrows.setEnabled(False)
        self._chk_show_arrows.toggled.connect(self._apply_arrow_settings)

        self._spin_arrow_step = QSpinBox()
        self._spin_arrow_step.setRange(1, 5000)
        self._spin_arrow_step.setValue(10)
        self._spin_arrow_step.setSingleStep(1)
        self._spin_arrow_step.setEnabled(False)
        self._spin_arrow_step.valueChanged.connect(self._apply_arrow_settings)

        self._spin_arrow_len = QSpinBox()
        self._spin_arrow_len.setRange(4, 64)
        self._spin_arrow_len.setValue(14)
        self._spin_arrow_len.setSingleStep(1)
        self._spin_arrow_len.setEnabled(False)
        self._spin_arrow_len.valueChanged.connect(self._apply_arrow_settings)

        self._chk_highlight_corners = QCheckBox("Köşeleri vurgula")
        self._chk_highlight_corners.setChecked(True)
        self._chk_highlight_corners.setEnabled(False)
        self._chk_highlight_corners.toggled.connect(self._apply_arrow_settings)

        self._chk_pivot_preview = QCheckBox("Pivot önizleme")
        self._chk_pivot_preview.setChecked(True)
        self._chk_pivot_preview.setEnabled(False)
        self._chk_pivot_preview.toggled.connect(self._on_pivot_toggle)

        self._spin_pivot_window = QSpinBox()
        self._spin_pivot_window.setRange(1, 50)
        self._spin_pivot_window.setValue(6)
        self._spin_pivot_window.setSingleStep(1)
        self._spin_pivot_window.setEnabled(False)
        self._spin_pivot_window.valueChanged.connect(self._apply_arrow_settings)

        self._spin_pivot_thickness = QSpinBox()
        self._spin_pivot_thickness.setRange(1, 6)
        self._spin_pivot_thickness.setValue(2)
        self._spin_pivot_thickness.setSingleStep(1)
        self._spin_pivot_thickness.setEnabled(False)
        self._spin_pivot_thickness.valueChanged.connect(self._apply_arrow_settings)

        self._spin_rot = _make_spinbox(-360.0, 360.0, 0.0, 1.0, 1)
        self._spin_offset_x = _make_spinbox(-100000.0, 100000.0, 0.0, 1.0, 2)
        self._spin_offset_y = _make_spinbox(-100000.0, 100000.0, 0.0, 1.0, 2)
        self._spin_scale = _make_spinbox(0.01, 1000.0, 1.0, 0.1, 3)
        self._btn_fit = QPushButton("Sığdır")
        self._btn_fit.clicked.connect(self._on_fit)

        self._spin_rot.valueChanged.connect(self._apply_transform)
        self._spin_offset_x.valueChanged.connect(self._apply_transform)
        self._spin_offset_y.valueChanged.connect(self._apply_transform)
        self._spin_scale.valueChanged.connect(self._apply_transform)

        header = QHBoxLayout()
        header.addWidget(self._btn_load)
        header.addWidget(self._status, 1)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Döndür (°)"))
        controls.addWidget(self._spin_rot)
        controls.addSpacing(8)
        controls.addWidget(QLabel("Offset X"))
        controls.addWidget(self._spin_offset_x)
        controls.addSpacing(8)
        controls.addWidget(QLabel("Offset Y"))
        controls.addWidget(self._spin_offset_y)
        controls.addSpacing(8)
        controls.addWidget(QLabel("Ölçek"))
        controls.addWidget(self._spin_scale)
        controls.addSpacing(8)
        controls.addWidget(self._btn_fit)
        controls.addStretch(1)

        a_controls = QHBoxLayout()
        a_controls.addWidget(self._chk_enable_a)
        a_controls.addSpacing(8)
        a_controls.addWidget(QLabel("Yumuşatma (pencere)"))
        a_controls.addWidget(self._spin_smooth)
        a_controls.addSpacing(8)
        a_controls.addWidget(QLabel("Köşe eşiği (°)"))
        a_controls.addWidget(self._spin_corner)
        a_controls.addSpacing(8)
        a_controls.addWidget(self._chk_highlight_corners)
        a_controls.addSpacing(8)
        a_controls.addWidget(self._btn_compute_a)
        a_controls.addWidget(self._btn_export_a)
        a_controls.addWidget(self._btn_export_gcode)
        a_controls.addSpacing(12)
        a_controls.addWidget(self._chk_show_arrows)
        a_controls.addSpacing(8)
        a_controls.addWidget(QLabel("Ok adımı"))
        a_controls.addWidget(self._spin_arrow_step)
        a_controls.addSpacing(8)
        a_controls.addWidget(QLabel("Ok boyu(px)"))
        a_controls.addWidget(self._spin_arrow_len)
        a_controls.addSpacing(8)
        a_controls.addWidget(self._chk_pivot_preview)
        a_controls.addSpacing(8)
        a_controls.addWidget(QLabel("Pivot penceresi"))
        a_controls.addWidget(self._spin_pivot_window)
        a_controls.addSpacing(8)
        a_controls.addWidget(QLabel("Pivot kalınlık"))
        a_controls.addWidget(self._spin_pivot_thickness)
        a_controls.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(header)
        layout.addLayout(controls)
        layout.addLayout(a_controls)
        layout.addWidget(self._viewer, 1)

    def _on_open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "2D dosya seç",
            "",
            "2D Dosyalar (*.stl *.dxf)",
        )
        if not path:
            return
        self._load_path(path)

    def _load_path(self, path: str) -> None:
        self._status.setText("Yükleniyor...")
        try:
            result = build_2d_toolpath(path)
        except Exception as exc:
            self._toolpath = None
            self._toolpath_points = None
            self._a_result = None
            if self._state is not None:
                self._state.a_path_2d = None
            self._viewer.set_polyline([])
            self._status.setText(f"Hata: {exc}")
            self._btn_compute_a.setEnabled(False)
            self._btn_export_a.setEnabled(False)
            self._btn_export_gcode.setEnabled(False)
            self._apply_arrow_settings()
            return

        points_xy = result.get("points_xy", [])
        self._toolpath = result
        self._toolpath_points = [ToolpathPoint(x, y, 0.0, None) for x, y in points_xy]
        self._a_result = None
        if self._state is not None:
            self._state.a_path_2d = None
        self._viewer.set_polyline(points_xy)
        self._apply_transform()
        self._viewer.fit_to_view()

        name = os.path.basename(path)
        self._status.setText(f"{name} yüklendi (nokta: {len(points_xy)})")
        self._btn_compute_a.setEnabled(self._chk_enable_a.isChecked() and bool(self._toolpath_points))
        self._btn_export_a.setEnabled(False)
        self._btn_export_gcode.setEnabled(False)
        self._apply_arrow_settings()

    def set_toolpath_points(self, points, label: str = "3D Yol") -> None:
        pts = list(points) if points else []
        self._toolpath_points = pts
        self._toolpath = {"points_xy": [(p.x, p.y) for p in pts]}
        self._a_result = None
        if self._state is not None:
            self._state.a_path_2d = None
        if pts:
            self._viewer.set_polyline(self._toolpath["points_xy"])
            self._apply_transform()
            self._viewer.fit_to_view()
        else:
            self._viewer.set_polyline([])
        self._btn_compute_a.setEnabled(self._chk_enable_a.isChecked() and bool(pts))
        self._btn_export_a.setEnabled(False)
        self._btn_export_gcode.setEnabled(False)
        self._chk_show_arrows.setChecked(False)
        self._chk_highlight_corners.setChecked(False)
        self._chk_pivot_preview.setChecked(False)
        self._apply_arrow_settings()
        if pts:
            self._status.setText(f"{label} y?klendi (nokta: {len(pts)})")
        else:
            self._status.setText("Yol verisi yok")

    def clear_a_overlay(self) -> None:
        self._a_result = None
        if self._state is not None:
            self._state.a_path_2d = None
        self._btn_export_a.setEnabled(False)
        self._btn_export_gcode.setEnabled(False)
        self._chk_show_arrows.setChecked(False)
        self._chk_highlight_corners.setChecked(False)
        self._chk_pivot_preview.setChecked(False)
        if self._toolpath_points:
            points_xy = [(p.x, p.y) for p in self._toolpath_points]
            self._viewer.set_polyline(points_xy)
            self._apply_transform()
        self._apply_arrow_settings()

    def get_a_result(self) -> Optional[dict]:
        if self._a_result is None:
            return None
        return dict(self._a_result)

    def _apply_transform(self) -> None:
        self._viewer.set_transform(
            self._spin_offset_x.value(),
            self._spin_offset_y.value(),
            self._spin_rot.value(),
            self._spin_scale.value(),
        )

    def _on_fit(self) -> None:
        self._viewer.fit_to_view()

    def _on_a_toggle(self, checked: bool) -> None:
        self._spin_smooth.setEnabled(checked)
        self._spin_corner.setEnabled(checked)
        self._btn_compute_a.setEnabled(checked and bool(self._toolpath_points))
        self._chk_show_arrows.setEnabled(checked)
        self._spin_arrow_step.setEnabled(checked)
        self._spin_arrow_len.setEnabled(checked)
        self._chk_highlight_corners.setEnabled(checked)
        self._chk_pivot_preview.setEnabled(checked)
        self._spin_pivot_window.setEnabled(checked and self._chk_pivot_preview.isChecked())
        self._spin_pivot_thickness.setEnabled(checked and self._chk_pivot_preview.isChecked())
        if not checked:
            self._a_result = None
            self._btn_export_a.setEnabled(False)
            self._btn_export_gcode.setEnabled(False)
            self._chk_show_arrows.setChecked(False)
            self._chk_highlight_corners.setChecked(False)
            self._chk_pivot_preview.setChecked(False)
            if self._toolpath_points:
                points_xy = [(p.x, p.y) for p in self._toolpath_points]
                self._viewer.set_polyline(points_xy)
                self._apply_transform()
            self._apply_arrow_settings()
            return
        if not self._chk_show_arrows.isChecked():
            self._chk_show_arrows.setChecked(True)
        if not self._chk_highlight_corners.isChecked():
            self._chk_highlight_corners.setChecked(True)
        if not self._chk_pivot_preview.isChecked():
            self._chk_pivot_preview.setChecked(True)
        if self._a_result:
            self._viewer.set_polyline(
                self._a_result.get("points_xy", []),
                self._a_result.get("angles_deg", []),
                self._a_result.get("corners", []),
            )
            self._apply_transform()
            self._btn_export_gcode.setEnabled(True)
        self._apply_arrow_settings()

    def _on_pivot_toggle(self, checked: bool) -> None:
        enabled = checked and self._chk_enable_a.isChecked()
        self._spin_pivot_window.setEnabled(enabled)
        self._spin_pivot_thickness.setEnabled(enabled)
        self._apply_arrow_settings()

    def _on_compute_a(self) -> None:
        if not self._chk_enable_a.isChecked():
            self._status.setText("A ?ret kapal?.")
            return
        if not self._toolpath_points:
            self._status.setText("?nce bir yol olu?turun.")
            return

        settings_tab = getattr(self.parent(), "tab_settings", None)
        knife_direction = "X_parallel"
        a_reverse = False
        a_offset = 0.0
        pivot_enable = False
        pivot_steps = int(self._spin_pivot_window.value())
        if settings_tab is not None:
            axis = getattr(settings_tab, "knife_direction_axis", "x")
            knife_direction = "Y_parallel" if str(axis).lower() == "y" else "X_parallel"
            a_reverse = bool(getattr(settings_tab, "A_REVERSE", getattr(settings_tab, "a_reverse", 0)))
            try:
                a_offset = float(getattr(settings_tab, "A_OFFSET_DEG", getattr(settings_tab, "a_offset_deg", 0.0)))
            except Exception:
                a_offset = 0.0
            pivot_enable = bool(getattr(settings_tab, "A_PIVOT_ENABLE", getattr(settings_tab, "a_pivot_enable", 0)))
            try:
                pivot_steps = int(getattr(settings_tab, "A_PIVOT_STEPS", getattr(settings_tab, "a_pivot_steps", pivot_steps)))
            except Exception:
                pass

        smooth_window = int(self._spin_smooth.value())
        corner_threshold = float(self._spin_corner.value())

        new_points, meta = generate_a_overlay(
            self._toolpath_points,
            smooth_window=smooth_window,
            corner_threshold_deg=corner_threshold,
            pivot_enable=pivot_enable,
            pivot_steps=pivot_steps,
            knife_direction=knife_direction,
            a_reverse=a_reverse,
            a_offset_deg=a_offset,
        )

        points_xy = [(p.x, p.y) for p in new_points]
        result = {
            "points_xy": points_xy,
            "angles_deg": meta.get("angles_deg", []),
            "corners": meta.get("corners", []),
            "meta": meta,
        }
        self._a_result = result
        if self._state is not None:
            self._state.a_path_2d = dict(result)
        self._toolpath_points = list(new_points)

        self._viewer.set_polyline(result["points_xy"], result["angles_deg"], result["corners"])
        self._apply_transform()
        self._apply_arrow_settings()
        self._btn_export_a.setEnabled(True)
        self._btn_export_gcode.setEnabled(True)

        min_a = float(meta.get("min_a_deg", 0.0))
        max_a = float(meta.get("max_a_deg", 0.0))
        corner_count = len(result["corners"])
        self._status.setText(f"A ?retildi: min={min_a:.1f}? , max={max_a:.1f}? , k??e={corner_count}")
        logger.info("A ?retildi: min=%.2f max=%.2f corners=%d", min_a, max_a, corner_count)

    def _on_export_a(self) -> None:
        if not self._a_result:
            self._status.setText("Önce A hesaplayın.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "A verisini kaydet",
            "",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            write_json(path, self._a_result)
        except Exception as exc:
            self._status.setText(f"JSON yazılamadı: {exc}")
            return
        name = os.path.basename(path)
        self._status.setText(f"JSON kaydedildi: {name}")

    def _on_export_gcode(self) -> None:
        if not self._a_result:
            self._status.setText("Once A hesaplayin.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "G-code kaydet",
            "",
            "G-code (*.gcode *.nc *.tap *.txt)",
        )
        if not path:
            return
        points_xy = self._a_result.get("points_xy", [])
        angles_deg = self._a_result.get("angles_deg", [])
        try:
            gcode_text = build_xya_gcode(points_xy, angles_deg, feed_rate=2000.0, precision=3)
        except Exception as exc:
            self._status.setText(f"G-code olusturulamadi: {exc}")
            return
        if not gcode_text:
            self._status.setText("G-code olusturulamadi.")
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(gcode_text)
                handle.write("\n")
        except Exception as exc:
            self._status.setText(f"G-code yazilamadi: {exc}")
            return
        name = os.path.basename(path)
        self._status.setText(f"G-code kaydedildi: {name}")

    def _apply_arrow_settings(self) -> None:
        enable = bool(self._a_result)
        self._viewer.set_render_params(
            {
                "show_arrows": enable and self._chk_show_arrows.isChecked(),
                "arrow_step": self._spin_arrow_step.value(),
                "arrow_len_base_px": self._spin_arrow_len.value(),
                "arrow_len_min_px": 8,
                "arrow_len_max_px": 28,
                "arrow_speed_scale": True,
                "max_arrows": 500,
                "highlight_corners": enable and self._chk_highlight_corners.isChecked(),
                "corner_threshold_deg": float(self._spin_corner.value()),
                "pivot_preview": enable and self._chk_pivot_preview.isChecked(),
                "pivot_steps": self._spin_pivot_window.value(),
                "pivot_span_deg": 60.0,
                "pivot_max_corners": 200,
                "pivot_thickness": float(self._spin_pivot_thickness.value()),
            }
        )


def _make_spinbox(min_val: float, max_val: float, value: float, step: float, decimals: int):
    from PyQt5.QtWidgets import QDoubleSpinBox

    spin = QDoubleSpinBox()
    spin.setRange(min_val, max_val)
    spin.setValue(value)
    spin.setSingleStep(step)
    spin.setDecimals(decimals)
    return spin
