# -*- coding: utf-8 -*-
import os
import configparser
import logging
import time
from typing import Optional

import numpy as np
from stl import mesh as stl_mesh
from PyQt5.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
    QFileDialog,
    QGroupBox,
    QGridLayout,
    QDoubleSpinBox,
    QMessageBox,
    QApplication,
    QProgressBar,
    QSizePolicy,
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QThreadPool

from gl_viewer import GLTableViewer
from project_state import STLModel
from async_workers import WorkerRunnable
from ui_strings import (
    TITLE_MODEL,
    TITLE_TOOLPATH,
    MSG_MODEL_LOAD_ERROR,
    MSG_OPERATION_CANCELLED,
    MSG_MODEL_REQUIRED,
    MSG_TOOLPATH_TAB_MISSING,
    MSG_TOOLPATH_ERROR,
    BTN_LOAD_MODEL,
    BTN_CREATE_TOOLPATH,
    BTN_RESET_VIEW,
    LABEL_MODEL_RIGHT_INFO_EMPTY,
    LABEL_MODEL_INFO_EMPTY,
    LABEL_BOTTOM_TITLE_MODEL,
    MSG_MODEL_LOADED_SHORT,
)


logger = logging.getLogger(__name__)
INI_PATH = "settings.ini"


class TabModel(QWidget):
    def __init__(self, main_window, state=None, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.state = state

        # Table / model state
        self.table_width_mm = 800.0
        self.table_height_mm = 400.0
        self.origin_mode = "center"
        self.table_fill_enabled = True

        self.model_loaded = False
        self.model_path: Optional[str] = None
        self.model_rot_x = 0.0
        self.model_rot_y = 0.0
        self.model_rot_z = 0.0

        # UI helpers
        self.threadpool = QThreadPool.globalInstance()
        self._load_worker: Optional[WorkerRunnable] = None

        self.viewer = GLTableViewer(self)
        if hasattr(self.viewer, "reset_camera"):
            self.viewer.reset_camera()
        self.viewer.on_load_error = self._on_viewer_load_error

        self._build_ui()
        self._load_settings_from_ini()

    # ------------------------------------------------------
    # UI
    # ------------------------------------------------------
    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        self.left_panel = self._build_left_panel()
        self.right_panel = self._build_right_panel()

        center_frame = QFrame()
        center_frame.setFrameShape(QFrame.StyledPanel)
        center_layout = QVBoxLayout(center_frame)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addWidget(self.viewer)

        top_layout.addWidget(self.left_panel)
        top_layout.addWidget(center_frame, 1)
        top_layout.addWidget(self.right_panel)

        self.bottom_frame = QFrame()
        self.bottom_frame.setFrameShape(QFrame.StyledPanel)
        bottom_layout = QVBoxLayout(self.bottom_frame)
        bottom_layout.setContentsMargins(6, 4, 6, 4)

        self.bottom_label_title = QLabel(LABEL_BOTTOM_TITLE_MODEL)
        self.bottom_label_title.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.bottom_label_info = QLabel("")
        self.bottom_label_info.setFont(QFont("Segoe UI", 8))
        self.bottom_label_info.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.bottom_label_info.setWordWrap(True)

        bottom_layout.addWidget(self.bottom_label_title)
        bottom_layout.addWidget(self.bottom_label_info)

        main_layout.addLayout(top_layout, 1)
        main_layout.addWidget(self.bottom_frame, 0)
        self.setLayout(main_layout)
        self._update_bottom_panel_text()

    def _build_left_panel(self):
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setMinimumWidth(220)
        frame.setMaximumWidth(260)
        frame.setStyleSheet("background-color: #f5f5fa;")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        lbl_title = QLabel("Modeller")
        lbl_title.setFont(QFont("Segoe UI", 9, QFont.Bold))
        layout.addWidget(lbl_title)

        self.btn_load_model = QPushButton(BTN_LOAD_MODEL)
        self.btn_load_model.setCursor(Qt.PointingHandCursor)
        self.btn_load_model.clicked.connect(self._on_load_clicked)
        layout.addWidget(self.btn_load_model)

        lbl_offset = QLabel("Kontur Ofseti (mm)")
        lbl_offset.setFont(QFont("Segoe UI", 8))
        layout.addWidget(lbl_offset)

        self.spin_model_offset = QDoubleSpinBox()
        self.spin_model_offset.setRange(-5.0, 5.0)
        self.spin_model_offset.setDecimals(2)
        self.spin_model_offset.setSingleStep(0.1)
        self.spin_model_offset.setValue(0.0)
        self.spin_model_offset.valueChanged.connect(self._on_model_offset_changed)
        layout.addWidget(self.spin_model_offset)
        self.spin_contour_offset = self.spin_model_offset

        self.btn_create_path = QPushButton(BTN_CREATE_TOOLPATH)
        self.btn_create_path.setCursor(Qt.PointingHandCursor)
        self.btn_create_path.setEnabled(False)
        self.btn_create_path.clicked.connect(self._on_create_toolpath)
        layout.addWidget(self.btn_create_path)

        self.btn_generate_gcode = QPushButton("Takım Yolu Oluştur (G-code)")
        self.btn_generate_gcode.setObjectName("btn_generate_gcode")
        self.btn_generate_gcode.setCursor(Qt.PointingHandCursor)
        self.btn_generate_gcode.setEnabled(False)
        self.btn_generate_gcode.clicked.connect(self._on_generate_gcode_clicked)
        self.btn_generate_gcode.setVisible(False)
        self.btn_generate_gcode.setToolTip("Geçici olarak devre dışı")
        layout.addWidget(self.btn_generate_gcode)

        layout.addStretch(1)
        return frame

    def _build_right_panel(self):
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setMinimumWidth(230)
        frame.setMaximumWidth(270)
        frame.setStyleSheet("background-color: #f0f0f0;")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.label_right_info = QLabel(LABEL_MODEL_RIGHT_INFO_EMPTY)
        self.label_right_info.setFont(QFont("Segoe UI", 8))
        self.label_right_info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.label_right_info)

        grp_rot = QGroupBox("Model Döndürme (90° adımlar)")
        grp_rot_layout = QVBoxLayout(grp_rot)
        grp_rot_layout.setSpacing(4)

        def add_rot_row(text, minus_cb, plus_cb):
            row = QHBoxLayout()
            lbl = QLabel(text)
            btn_minus = QPushButton("-90°")
            btn_plus = QPushButton("+90°")
            for b in (btn_minus, btn_plus):
                b.setCursor(Qt.PointingHandCursor)
                b.setFixedWidth(60)
            btn_minus.clicked.connect(minus_cb)
            btn_plus.clicked.connect(plus_cb)
            row.addWidget(lbl)
            row.addStretch(1)
            row.addWidget(btn_minus)
            row.addWidget(btn_plus)
            grp_rot_layout.addLayout(row)

        add_rot_row("Rot X:", self._on_rot_x_minus, self._on_rot_x_plus)
        add_rot_row("Rot Y:", self._on_rot_y_minus, self._on_rot_y_plus)
        add_rot_row("Rot Z:", self._on_rot_z_minus, self._on_rot_z_plus)
        grp_rot.setEnabled(False)
        self.grp_model_rotate = grp_rot
        layout.addWidget(grp_rot)

        self.btn_reset_view = QPushButton(BTN_RESET_VIEW)
        self.btn_reset_view.setCursor(Qt.PointingHandCursor)
        self.btn_reset_view.clicked.connect(self._on_reset_view_clicked)
        layout.addWidget(self.btn_reset_view)

        pos_grp = QGroupBox("Model Pozisyonu (mm)")
        pos_layout = QGridLayout(pos_grp)

        self.spin_pos_x = QDoubleSpinBox()
        self.spin_pos_y = QDoubleSpinBox()
        self.spin_pos_z = QDoubleSpinBox()
        for sp in (self.spin_pos_x, self.spin_pos_y, self.spin_pos_z):
            sp.setRange(-1000.0, 1000.0)
            sp.setDecimals(2)
            sp.setSingleStep(1.0)
        self.spin_pos_x.valueChanged.connect(self._on_position_changed)
        self.spin_pos_y.valueChanged.connect(self._on_position_changed)
        self.spin_pos_z.valueChanged.connect(self._on_position_changed)

        pos_layout.addWidget(QLabel("X:"), 0, 0)
        pos_layout.addWidget(self.spin_pos_x, 0, 1)
        pos_layout.addWidget(QLabel("Y:"), 1, 0)
        pos_layout.addWidget(self.spin_pos_y, 1, 1)
        pos_layout.addWidget(QLabel("Z:"), 2, 0)
        pos_layout.addWidget(self.spin_pos_z, 2, 1)

        btn_pos_reset = QPushButton("Sıfırla")
        btn_pos_reset.setCursor(Qt.PointingHandCursor)
        btn_pos_reset.clicked.connect(self._on_position_reset)
        pos_layout.addWidget(btn_pos_reset, 3, 0, 1, 2)

        pos_grp.setEnabled(False)
        self.grp_model_position = pos_grp
        layout.addWidget(pos_grp)

        info_grp = QGroupBox("Model Bilgileri")
        info_layout = QVBoxLayout(info_grp)
        info_layout.setContentsMargins(6, 6, 6, 6)

        self.label_model_info = QLabel(LABEL_MODEL_INFO_EMPTY)
        self.label_model_info.setFont(QFont("Segoe UI", 8))
        self.label_model_info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.label_model_info.setWordWrap(True)
        info_layout.addWidget(self.label_model_info)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        info_layout.addWidget(self.progress_bar)

        self.label_progress = QLabel("")
        self.label_progress.setFont(QFont("Segoe UI", 8))
        self.label_progress.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.label_progress.setWordWrap(True)
        info_layout.addWidget(self.label_progress)

        self.label_timer = QLabel("")
        self.label_timer.setFont(QFont("Segoe UI", 8))
        self.label_timer.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.label_timer.setWordWrap(True)
        info_layout.addWidget(self.label_timer)
        info_grp.setEnabled(False)
        self.grp_model_info = info_grp

        layout.addWidget(info_grp)
        layout.addStretch(1)
        return frame

    # ------------------------------------------------------
    # Settings
    # ------------------------------------------------------
    def _load_settings_from_ini(self):
        if not os.path.exists(INI_PATH):
            self.apply_table_settings(
                width_mm=self.table_width_mm,
                height_mm=self.table_height_mm,
                origin_mode="center",
                bg_color="#E6E6EB",
                table_color="#D5E4F0",
                stl_color="#FF6699",
                table_fill_enabled=True,
            )
            return

        cfg = configparser.ConfigParser()
        cfg.read(INI_PATH, encoding="utf-8")

        width = cfg.getfloat("TABLE", "width_mm", fallback=self.table_width_mm)
        height = cfg.getfloat("TABLE", "height_mm", fallback=self.table_height_mm)
        origin_mode = cfg.get("TABLE", "origin_mode", fallback="center")
        bg = cfg.get("COLORS", "background", fallback="#E6E6EB")
        table_c = cfg.get("COLORS", "table", fallback="#D5E4F0")
        stl_c = cfg.get("COLORS", "stl", fallback="#FF6699")
        show_fill = cfg.getboolean("TABLE", "show_table_fill", fallback=True)
        contour_offset = cfg.getfloat("APP", "contour_offset_mm", fallback=0.0)

        self.apply_table_settings(
            width_mm=width,
            height_mm=height,
            origin_mode=origin_mode,
            bg_color=bg,
            table_color=table_c,
            stl_color=stl_c,
            table_fill_enabled=show_fill,
        )
        try:
            self.spin_model_offset.blockSignals(True)
            self.spin_model_offset.setValue(contour_offset)
        finally:
            self.spin_model_offset.blockSignals(False)

    def apply_table_settings(
        self,
        width_mm: float,
        height_mm: float,
        origin_mode: str,
        bg_color: Optional[str] = None,
        table_color: Optional[str] = None,
        stl_color: Optional[str] = None,
        table_fill_enabled: bool = True,
    ):
        self.table_width_mm = float(width_mm)
        self.table_height_mm = float(height_mm)
        self.origin_mode = origin_mode
        self.table_fill_enabled = bool(table_fill_enabled)

        self.viewer.set_table_size(self.table_width_mm, self.table_height_mm)
        self.viewer.set_origin_mode(self.origin_mode)
        if bg_color and table_color and stl_color:
            self.viewer.set_colors(bg_color, table_color, stl_color)
        self.viewer.set_table_fill_enabled(self.table_fill_enabled)
        self._update_bottom_panel_text()

    def _origin_mode_human(self) -> str:
        mapping = {
            "center": "Orta",
            "front_left": "Sol Alt (X min, Y min)",
            "front_right": "Sağ Alt (X max, Y min)",
            "back_left": "Sol Üst (X min, Y max)",
            "back_right": "Sağ Üst (X max, Y max)",
        }
        return mapping.get(self.origin_mode, self.origin_mode)

    def _update_bottom_panel_text(self, model_name: Optional[str] = None):
        lines = [
            f"Tabla boyutu: {self.table_width_mm:.1f} x {self.table_height_mm:.1f} mm",
            f"G54 Orjini: {self._origin_mode_human()}",
        ]
        if model_name:
            lines.append(f"Yüklü model: {model_name}")
        elif self.model_path:
            lines.append(f"Yüklü model: {os.path.basename(self.model_path)}")
        else:
            lines.append("Henüz model yüklenmedi.")
        self.bottom_label_info.setText("\n".join(lines))

    # ------------------------------------------------------
    # Async STL load
    # ------------------------------------------------------
    def _on_load_clicked(self):
        dlg = QFileDialog(self)
        dlg.setWindowTitle(TITLE_MODEL)
        dlg.setNameFilter("STL Dosyaları (*.stl *.STL)")
        dlg.setFileMode(QFileDialog.ExistingFile)
        if dlg.exec_() != QFileDialog.Accepted:
            return
        filenames = dlg.selectedFiles()
        if not filenames:
            return

        filename = filenames[0]
        self.model_path = filename

        if self._load_worker:
            try:
                self._load_worker.cancel()
            except Exception:
                logger.exception("Önceki STL yükleme iptal edilemedi")

        if hasattr(self, "progress_bar"):
            self.progress_bar.setValue(0)
            self.label_progress.setText("Yükleniyor...")
            self.label_timer.setText("")

        self._load_worker = WorkerRunnable(self._load_stl_async, filename)
        self._load_worker.signals.progress.connect(self._on_load_progress)
        self._load_worker.signals.result.connect(self._on_load_result)
        self._load_worker.signals.error.connect(self._on_load_error_signal)
        self._load_worker.signals.finished.connect(self._on_load_finished)
        self.threadpool.start(self._load_worker)

    def _load_stl_async(self, worker, filename: str):
        worker.signals.progress.emit("Dosya okunuyor", 5)
        m = stl_mesh.Mesh.from_file(filename)
        vectors = m.vectors.astype(np.float32)
        num_triangles = vectors.shape[0]
        verts = vectors.reshape(-1, 3)
        tri_normals = m.normals.astype(np.float32)
        normals = np.repeat(tri_normals, 3, axis=0)
        min_xyz = verts.min(axis=0)
        max_xyz = verts.max(axis=0)
        size_xyz = max_xyz - min_xyz
        center_xy = (min_xyz[0:2] + max_xyz[0:2]) / 2.0
        verts[:, 0] -= center_xy[0]
        verts[:, 1] -= center_xy[1]
        verts[:, 2] -= min_xyz[2]
        worker.signals.progress.emit("Veri hazır", 90)
        return {
            "vertices": verts.astype(np.float32),
            "normals": normals.astype(np.float32),
            "size": size_xyz.astype(np.float32),
            "triangles": num_triangles,
            "path": filename,
        }

    def _on_load_progress(self, message: str, percent: int):
        if hasattr(self, "progress_bar"):
            self.progress_bar.setValue(int(percent))
            self.label_progress.setText(message or "")
            QApplication.processEvents()

    def _on_load_result(self, payload: dict):
        try:
            verts = payload.get("vertices")
            size_xyz = payload.get("size")
            path = payload.get("path")
            self.viewer.set_mesh_data(verts, payload.get("normals"), size_xyz)
            if self.state is not None and verts is not None:
                # NOTE: Store mesh in state for other viewers (e.g., simulation).
                verts_list = [(float(x), float(y), float(z)) for x, y, z in verts.tolist()]
                self.state.model = STLModel(vertices=verts_list, faces=None, path=path)
                if hasattr(self.state, "mesh_intersector_cache"):
                    self.state.mesh_intersector_cache.invalidate()
            self.model_loaded = True
            base = os.path.basename(path) if path else ""
            self.model_path = path
            self._update_bottom_panel_text(model_name=base)
            self.label_right_info.setText(MSG_MODEL_LOADED_SHORT)
            self.grp_model_rotate.setEnabled(True)
            self.grp_model_position.setEnabled(True)
            self.grp_model_info.setEnabled(True)
            if self.btn_create_path:
                self.btn_create_path.setEnabled(True)

            if hasattr(self.main_window, "tab_toolpath"):
                try:
                    self.main_window.tab_toolpath.offset_spin.blockSignals(True)
                    self.main_window.tab_toolpath.offset_spin.setValue(self.spin_model_offset.value())
                finally:
                    self.main_window.tab_toolpath.offset_spin.blockSignals(False)

            self.model_rot_x = 0.0
            self.model_rot_y = 0.0
            self.model_rot_z = 0.0
            self._apply_model_rotation()

            self.spin_pos_x.blockSignals(True)
            self.spin_pos_y.blockSignals(True)
            self.spin_pos_z.blockSignals(True)
            self.spin_pos_x.setValue(0.0)
            self.spin_pos_y.setValue(0.0)
            self.spin_pos_z.setValue(0.0)
            self.spin_pos_x.blockSignals(False)
            self.spin_pos_y.blockSignals(False)
            self.spin_pos_z.blockSignals(False)
            self.viewer.set_model_offset(0.0, 0.0, 0.0)

            if verts is not None and size_xyz is not None:
                txt = (
                    f"Vertex sayısı : {len(verts)}\n"
                    f"Üçgen sayısı : {payload.get('triangles', 0)}\n"
                    f"Boyutlar (X x Y x Z):\n"
                    f"{size_xyz[0]:.3f} x {size_xyz[1]:.3f} x {size_xyz[2]:.3f} mm"
                )
            else:
                txt = "Bilgi alınamadı."
            self.label_model_info.setText(txt)
        except Exception:
            logger.exception("STL yükleme sonucu UI'a uygulanamadı")
            QMessageBox.critical(self, TITLE_MODEL, MSG_MODEL_LOAD_ERROR)
        finally:
            if hasattr(self, "progress_bar"):
                self.progress_bar.setValue(100)
                self.label_progress.setText("Hazır")
                self.label_timer.setText("")

    def _on_viewer_load_error(self, message: str):
        logger.error("STL yükleme hatası: %s", message)
        QMessageBox.critical(self, TITLE_MODEL, MSG_MODEL_LOAD_ERROR)

    def _on_load_error_signal(self, user_message: str, exc_text: str):
        logger.error("STL yükleme hatası: %s", exc_text)
        QMessageBox.critical(self, TITLE_MODEL, MSG_MODEL_LOAD_ERROR)
        if hasattr(self, "progress_bar"):
            self.progress_bar.setValue(0)
            self.label_progress.setText("")
            self.label_timer.setText("")

    def _on_load_finished(self):
        self._load_worker = None

    # ------------------------------------------------------
    # Toolpath generation (Model tab trigger)
    # ------------------------------------------------------
    def _on_create_toolpath(self):
        """Sol paneldeki 'Yol Oluştur' butonuna basılınca çağrılır."""
        main = self.main_window
        if main is None or not hasattr(main, "tab_toolpath"):
            QMessageBox.warning(self, TITLE_TOOLPATH, MSG_TOOLPATH_TAB_MISSING)
            return

        if not getattr(self, "model_loaded", False):
            QMessageBox.warning(self, TITLE_TOOLPATH, MSG_MODEL_REQUIRED)
            return

        tool_tab = main.tab_toolpath

        try:
            tool_tab.offset_spin.blockSignals(True)
            tool_tab.offset_spin.setValue(self.spin_model_offset.value())
        finally:
            tool_tab.offset_spin.blockSignals(False)

        try:
            tool_tab._on_params_changed()
        except Exception:
            logger.exception("Takım yolu parametreleri senkronize edilirken hata")

        self._set_toolpath_busy(True)  # NOTE: Disable UI while async generation runs.
        try:
            tool_tab.start_generation_from_external(progress_cb=self._on_toolpath_progress)
        except Exception:
            logger.exception("Takım yolu üretimi başlatılamadı")
            self._set_toolpath_busy(False)  # NOTE: Restore UI on early failure.
            QMessageBox.critical(self, TITLE_TOOLPATH, MSG_TOOLPATH_ERROR)
            return
        # NOTE: Completion message/section switch happens after async finishes.

    def _set_toolpath_busy(self, busy: bool):
        """UI'yi async süreçte kilitle/serbest bırak (Model sekmesi)."""
        if busy:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()
        for w in (self.btn_create_path, self.btn_load_model, self.spin_model_offset):
            if w is not None:
                w.setEnabled(not busy)
        if hasattr(self, "progress_bar"):
            self.progress_bar.setValue(0 if busy else 100)
            self.label_progress.setText("Yol oluşturuluyor..." if busy else "Hazır")

    def _on_toolpath_progress(self, message: str, percent: int):
        """Async toolpath ilerlemesini Model sekmesinde gösterir."""
        if hasattr(self, "progress_bar"):
            self.progress_bar.setValue(int(percent))
            label = f"{percent}% - {message}" if message else f"{percent}%"
            self.label_progress.setText(label)

    def _on_toolpath_generation_done(self, ok: bool):
        """Async toolpath tamamlandığında Model sekmesini günceller."""
        self._set_toolpath_busy(False)  # NOTE: Restore UI when async finishes.
        if not ok:
            return
        QMessageBox.information(self, TITLE_TOOLPATH, "Takım yolu üretimi tamamlandı.")
        main = self.main_window
        if main is not None:
            try:
                # NOTE: Switch to 3D tab and keep 'Yol Hazırlama' selected.
                if hasattr(main, "tabs"):
                    main.tabs.setCurrentWidget(main.page_3d)
                if hasattr(main, "tabs_3d") and hasattr(main, "tab_toolpath"):
                    main.tabs_3d.setCurrentWidget(main.tab_toolpath)
            except Exception:
                logger.exception("3D sekme geçişi başarısız")

    def _on_generate_gcode_clicked(self):
        """Model sekmesinden G-code üretimini başlatır (devre dışı)."""
        return  # Geçici olarak tamamen iptal edildi

    def _on_model_offset_changed(self, value: float):
        if hasattr(self.main_window, "tab_toolpath"):
            tp = self.main_window.tab_toolpath
            try:
                tp.offset_spin.blockSignals(True)
                tp.offset_spin.setValue(float(value))
            finally:
                tp.offset_spin.blockSignals(False)
        if hasattr(self.main_window, "tab_settings") and self.main_window.tab_settings:
            self.main_window.tab_settings.contour_offset_mm = float(value)
            if hasattr(self.main_window.tab_settings, "spin_contour_offset"):
                try:
                    self.main_window.tab_settings.spin_contour_offset.blockSignals(True)
                    self.main_window.tab_settings.spin_contour_offset.setValue(float(value))
                finally:
                    self.main_window.tab_settings.spin_contour_offset.blockSignals(False)

    def set_contour_offset_from_settings(self, value: float):
        try:
            self.spin_model_offset.blockSignals(True)
            self.spin_model_offset.setValue(float(value))
        finally:
            self.spin_model_offset.blockSignals(False)
        if hasattr(self.main_window, "tab_settings") and self.main_window.tab_settings:
            self.main_window.tab_settings.contour_offset_mm = float(value)

    # ------------------------------------------------------
    # Rotation / position helpers
    # ------------------------------------------------------
    def _apply_model_rotation(self):
        if self.viewer is not None:
            self.viewer.set_model_rotation(self.model_rot_x, self.model_rot_y, self.model_rot_z)

    def _on_rot_x_minus(self):
        self.model_rot_x -= 90.0
        self._apply_model_rotation()

    def _on_rot_x_plus(self):
        self.model_rot_x += 90.0
        self._apply_model_rotation()

    def _on_rot_y_minus(self):
        self.model_rot_y -= 90.0
        self._apply_model_rotation()

    def _on_rot_y_plus(self):
        self.model_rot_y += 90.0
        self._apply_model_rotation()

    def _on_rot_z_minus(self):
        self.model_rot_z -= 90.0
        self._apply_model_rotation()

    def _on_rot_z_plus(self):
        self.model_rot_z += 90.0
        self._apply_model_rotation()

    def _on_reset_view_clicked(self):
        if self.viewer is not None and hasattr(self.viewer, "reset_view"):
            self.viewer.reset_view()

    def _on_position_changed(self, value=None):
        if self.viewer is None:
            return
        x = self.spin_pos_x.value()
        y = self.spin_pos_y.value()
        z = self.spin_pos_z.value()
        self.viewer.set_model_offset(x, y, z)

    def _on_position_reset(self):
        for spin in (self.spin_pos_x, self.spin_pos_y, self.spin_pos_z):
            spin.blockSignals(True)
            spin.setValue(0.0)
            spin.blockSignals(False)
        if self.viewer:
            self.viewer.set_model_offset(0.0, 0.0, 0.0)
