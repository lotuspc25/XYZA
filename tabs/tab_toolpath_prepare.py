import configparser
import csv
import json
import time
from typing import List, Optional
import math
import logging
from collections import Counter

import numpy as np
from PyQt5.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
    QGroupBox,
    QCheckBox,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QFileDialog,
    QMessageBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QAbstractItemView,
    QApplication,
    QSizePolicy,
    QShortcut,
    QSplitter,
)
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtCore import Qt, QThreadPool

from gl_viewer import GLTableViewer
from async_workers import WorkerRunnable
from ui_strings import (
    TITLE_TOOLPATH,
    MSG_TOOLPATH_ERROR,
    MSG_OPERATION_CANCELLED,
    MSG_MODEL_REQUIRED,
    MSG_MODEL_SETTINGS_MISSING,
    MSG_SELECT_POINT_FIRST,
    BTN_FOCUS_POINT,
    BTN_GENERATE_GCODE,
    Z_MODE_LABELS,
)
from project_state import ToolpathPoint, ToolpathResult  # Use shared ToolpathPoint model (single source).
from core.toolpath_pipeline import ToolpathPipeline
from toolpath_generator import (
    PathIssue,
    build_trimesh_from_viewer,
    compute_z_for_points,
    compute_angles_from_xy,
    build_toolpath_points,
    _get_blade_radius_mm,
    resample_polyline_by_step,
)

INI_PATH = "settings.ini"
logger = logging.getLogger(__name__)
A_SMOOTH_WINDOW = 7
A_MAX_STEP_DEG = 12.0



class TabToolpath(QWidget):
    """
    Takım Yolu sekmesi: STL'den Z-takipli kontur üretir, noktaları listeler ve dışa aktarır.
    Eski edit modları kaldırıldı; yalnızca hesapla, göster, listele ve kaydet akışı bulunur.
    """

    def __init__(self, main_window, state):
        super().__init__(main_window)
        self.main_window = main_window
        self.state = state

        # Genel ayarlar
        self.table_width_mm = 400.0
        self.table_height_mm = 800.0
        self.origin_mode = "center"
        self.table_fill_enabled = True
        self.stl_shown = False

        # Takım yolu verisi
        # STL'den ilk üretildiğinde gelen "orijinal" merkez yol
        self.original_toolpath_points: List[ToolpathPoint] = []
        # Şu anda aktif olan yol (viewer + tabloda görünen)
        self.toolpath_points: List[ToolpathPoint] = []
        # "Takım yolu hazırla" sonrasında gerçek ofset uygulanmış nihai yol
        self.prepared_toolpath_points: List[ToolpathPoint] = []
        self.gcode_lines: List[str] = []
        # Geri alma (undo) için geçmiş yığını
        self.toolpath_history: List[List[ToolpathPoint]] = []
        self.analysis_options = {
            "angle_threshold": 30.0,
            "z_threshold": 2.0,
            "dir_threshold": 30.0,
            "xy_spike_threshold": 0.3,
            "show_raw": False,
            "enable_z_max": False,
        }

        # Düzenleme modu durumu ve grup/buton referansları
        self.edit_mode = False
        self.grp_gen = None
        self.grp_summary = None
        self.grp_points = None
        self.grp_export = None
        self.grp_visibility = None
        self.grp_edit = None
        self.btn_edit_mode = None
        self.btn_edit_delete = None
        self.btn_edit_merge = None
        self.btn_edit_smooth = None
        self.btn_edit_arcs = None
        self.btn_edit_undo = None
        self.btn_edit_cancel = None
        self.btn_edit_apply = None
        self._original_points: List[ToolpathPoint] = []
        self._history: List[List[ToolpathPoint]] = []
        self._history_limit = 10
        self._has_edit_changes = False
        self._selected_primary = -1
        self._selected_secondary = -1
        self._points_table_updating = False
        self._issues: List[PathIssue] = []

        # Hesaplama durumu
        self._is_generating = False
        self.threadpool = QThreadPool.globalInstance()
        self._toolpath_worker: Optional[WorkerRunnable] = None
        self._external_trigger = False  # External trigger flag.
        self._last_toolpath_ok = False  # Track external generation result for UI feedback.
        self.pipeline = ToolpathPipeline()  # NOTE: Core pipeline for UI-independent computation.

        # Ana yerleşim
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(4)

        # Üst alan: sol panel + viewer + sağ panel
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(4, 4, 4, 0)
        top_layout.setSpacing(6)

        # Sol panel
        left_frame = QFrame()
        left_frame.setFrameShape(QFrame.StyledPanel)
        left_frame.setMinimumWidth(260)
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(10)

        self.grp_points = QGroupBox("Nokta Listesi")
        self.grp_points.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.grp_points.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        points_layout = QVBoxLayout(self.grp_points)
        points_layout.setContentsMargins(6, 6, 6, 6)
        self.points_table = QTableWidget()
        self.points_table.setColumnCount(5)
        self.points_table.setHorizontalHeaderLabels(["#", "X", "Y", "Z", "A (deg)"])
        self.points_table.verticalHeader().setVisible(False)
        self.points_table.setEditTriggers(
            QTableWidget.DoubleClicked
            | QTableWidget.SelectedClicked
            | QTableWidget.EditKeyPressed
        )
        self.points_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.points_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.points_table.cellClicked.connect(self._on_table_cell_clicked)
        self.points_table.itemChanged.connect(self._on_points_item_changed)
        points_layout.addWidget(self.points_table)

        grp_point_actions = QGroupBox("Nokta İşlemleri")
        grp_point_actions.setFont(QFont("Segoe UI", 9, QFont.Bold))
        grp_point_actions.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        actions_layout = QVBoxLayout(grp_point_actions)
        actions_layout.setSpacing(4)
        actions_layout.setContentsMargins(8, 4, 8, 4)
        self.btn_save_points = QPushButton("Noktaları Kaydet...")
        self.btn_save_points.setCursor(Qt.PointingHandCursor)
        self.btn_save_points.clicked.connect(self.on_save_points_clicked)
        actions_layout.addWidget(self.btn_save_points)
        self.btn_focus_point = QPushButton(BTN_FOCUS_POINT)
        self.btn_focus_point.setCursor(Qt.PointingHandCursor)
        self.btn_focus_point.clicked.connect(self.focus_selected_point)
        actions_layout.addWidget(self.btn_focus_point)

        left_layout.addWidget(self.grp_points, 3)
        left_layout.addWidget(grp_point_actions, 0)
        left_layout.setStretchFactor(self.grp_points, 3)
        left_layout.setStretchFactor(grp_point_actions, 0)

        # Viewer
        center_frame = QFrame()
        center_frame.setFrameShape(QFrame.StyledPanel)
        center_layout = QVBoxLayout(center_frame)
        center_layout.setContentsMargins(0, 0, 0, 0)
        self.viewer = GLTableViewer(self)

        # Takım yolu sekmesinde başlangıçta STL ve zemin gizli olsun
        if hasattr(self.viewer, "set_mesh_visible"):
            try:
                self.viewer.set_mesh_visible(False)
            except Exception:
                setattr(self.viewer, "mesh_visible", False)
        else:
            setattr(self.viewer, "mesh_visible", False)
        if hasattr(self.viewer, "table_visible"):
            self.viewer.table_visible = False
        if hasattr(self.viewer, "axes_visible"):
            self.viewer.axes_visible = False

        if hasattr(self.viewer, "reset_camera"):
            self.viewer.reset_camera()
        # Viewer'dan gelen nokta seçimlerini tabloyla senkron tut
        self.viewer.on_point_selected = self._on_viewer_point_selected
        self.viewer.on_selection_changed = self._on_viewer_selection_changed
        center_layout.addWidget(self.viewer)

        # Gerçek takım yolu hazırlık paneli (merkez altında, 100px)
        prep_frame = QFrame()
        prep_frame.setFrameShape(QFrame.StyledPanel)
        prep_frame.setMinimumHeight(100)
        prep_frame.setMaximumHeight(100)
        prep_layout = QHBoxLayout(prep_frame)
        prep_layout.setContentsMargins(8, 4, 8, 4)
        prep_layout.setSpacing(8)
        prep_layout.addStretch(1)

        self.lbl_real_offset = QLabel("Gerçek ofset (mm):")
        self.lbl_real_offset.setFont(QFont("Segoe UI", 9))
        prep_layout.addWidget(self.lbl_real_offset)

        self.real_offset_spin = QDoubleSpinBox()
        self.real_offset_spin.setRange(-5.0, 5.0)
        self.real_offset_spin.setDecimals(3)
        self.real_offset_spin.setSingleStep(0.05)
        self.real_offset_spin.setValue(0.0)
        self.real_offset_spin.setToolTip(
            "İkinci yol için kullanılacak telafi ofseti.\n"
            "Varsayılan olarak Kontur Ofseti değerinin tersidir."
        )
        prep_layout.addWidget(self.real_offset_spin)

        self.btn_generate_gcode = QPushButton(BTN_GENERATE_GCODE)
        self.btn_generate_gcode.setObjectName("btn_generate_gcode")
        self.btn_generate_gcode.setCursor(Qt.PointingHandCursor)
        self.btn_generate_gcode.setEnabled(False)
        self.btn_generate_gcode.clicked.connect(self._on_generate_gcode_clicked)
        prep_layout.addWidget(self.btn_generate_gcode)

        self.btn_prepare_toolpath = QPushButton("Takım yolu hazırla")
        self.btn_prepare_toolpath.setCursor(Qt.PointingHandCursor)
        self.btn_prepare_toolpath.clicked.connect(self.on_prepare_toolpath_clicked)
        prep_layout.addWidget(self.btn_prepare_toolpath)

        self.chk_show_original = QCheckBox("Eski yolu göster")
        self.chk_show_original.setChecked(False)
        self.chk_show_original.toggled.connect(self.on_show_original_toggled)
        prep_layout.addWidget(self.chk_show_original)
        prep_layout.addStretch(1)

        center_layout.addWidget(prep_frame)

        # Sağ panel
        right_frame = QFrame()
        right_frame.setFrameShape(QFrame.StyledPanel)
        right_frame.setMinimumWidth(260)
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(10)

        font_label = QFont("Segoe UI", 9)

        # Takım yolu oluşturma grubu
        self.grp_gen = QGroupBox("Takım yolu hazırlama")
        self.grp_gen.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.grp_gen.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        gen_layout = QVBoxLayout(self.grp_gen)
        gen_layout.setSpacing(6)

        offset_lbl = QLabel("Kontur Ofseti (mm)")
        offset_lbl.setFont(font_label)
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-5.0, 5.0)
        self.offset_spin.setDecimals(2)
        self.offset_spin.setSingleStep(0.1)
        self.offset_spin.setValue(0.0)
        self.offset_spin.setToolTip("Negatif = İÇERDEN, Pozitif = DIŞARIDAN")
        self.offset_spin.valueChanged.connect(self._on_params_changed)

        step_lbl = QLabel("Nokta Adımı (mm)")
        step_lbl.setFont(font_label)
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setObjectName("stepSpin")
        self.step_spin.setRange(0.01, 10.0)
        self.step_spin.setDecimals(3)
        self.step_spin.setSingleStep(0.01)
        self.step_spin.setValue(0.5)
        self.step_spin.valueChanged.connect(self._on_params_changed)

        zmode_lbl = QLabel("Z Takip Yöntemi")
        zmode_lbl.setFont(font_label)
        self.z_mode_combo = QComboBox()
        self.z_mode_combo.setObjectName("zModeCombo")
        self.z_mode_combo.addItems(Z_MODE_LABELS)
        self.z_mode_combo.currentIndexChanged.connect(self._on_params_changed)

        gen_layout.addWidget(offset_lbl)
        gen_layout.addWidget(self.offset_spin)
        gen_layout.addWidget(step_lbl)
        gen_layout.addWidget(self.step_spin)
        gen_layout.addWidget(zmode_lbl)
        gen_layout.addWidget(self.z_mode_combo)

        self.btn_generate = QPushButton("STL'den Z-Takipli Yol Oluştur")
        self.btn_generate.setCursor(Qt.PointingHandCursor)
        self.btn_generate.clicked.connect(self.generate_from_current_model)
        gen_layout.addWidget(self.btn_generate)

        self.btn_cancel_generate = QPushButton("?ptal")
        self.btn_cancel_generate.setCursor(Qt.PointingHandCursor)
        self.btn_cancel_generate.setEnabled(False)
        self.btn_cancel_generate.clicked.connect(self._cancel_generation)
        gen_layout.addWidget(self.btn_cancel_generate)

        self.btn_edit_mode = QPushButton("Yol Düzenle")
        self.btn_edit_mode.clicked.connect(self.on_edit_mode_clicked)
        gen_layout.addWidget(self.btn_edit_mode)

        # Özet Bilgiler artık Genel Bilgiler sekmesinde gösteriliyor.
        # Bu sekmede sadece takım yolu hazırlama paneli yer alacak.
        right_layout.addWidget(self.grp_gen)

        # Yol Analizi
        self.grp_analysis = QGroupBox("Yol Analizi")
        self.grp_analysis.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.grp_analysis.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        ana_layout = QVBoxLayout(self.grp_analysis)
        ana_layout.setSpacing(4)
        # Yol analizi son sonuçları ve filtre durumu
        self._last_issues = []
        self.filter_a_only = False
        btn_row = QHBoxLayout()
        self.btn_analyze = QPushButton("Olası Hataları Tara")
        self.btn_analyze.setCursor(Qt.PointingHandCursor)
        self.btn_analyze.clicked.connect(self.on_analyze_path_clicked)
        btn_row.addWidget(self.btn_analyze)
        self.btn_advanced_analysis = QPushButton("Gelişmiş Analiz Ayarları")
        self.btn_advanced_analysis.setCursor(Qt.PointingHandCursor)
        self.btn_advanced_analysis.clicked.connect(self.on_show_advanced_analysis_dialog)
        btn_row.addWidget(self.btn_advanced_analysis)
        ana_layout.addLayout(btn_row)

        self.chk_show_raw_issues = QCheckBox("Ham hataları göster (filtreleme kapalı)")
        self.chk_show_raw_issues.setChecked(False)
        self.chk_show_raw_issues.stateChanged.connect(self._on_raw_issue_toggle)
        ana_layout.addWidget(self.chk_show_raw_issues)

        self.tbl_issues = QTableWidget()
        self.tbl_issues.setColumnCount(3)
        self.tbl_issues.setHorizontalHeaderLabels(["#", "Tip", "Açıklama"])
        self.tbl_issues.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_issues.setSelectionMode(QTableWidget.SingleSelection)
        self.tbl_issues.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_issues.cellClicked.connect(self.on_issue_row_clicked)
        ana_layout.addWidget(self.tbl_issues)
        self.lbl_issue_count = QLabel("Toplam hata sayısı: 0")
        self.lbl_issue_count.setAlignment(Qt.AlignRight)
        self.lbl_issue_count.setFont(QFont("Segoe UI", 8))
        # Yeni filtre butonu: Sadece A hataları
        self.btn_filter_a_only = QPushButton("Sadece A hataları")
        self.btn_filter_a_only.setCheckable(True)
        self.btn_filter_a_only.setToolTip("Sadece A eksenindeki ani dönüş hatalarını göster")
        self.btn_filter_a_only.toggled.connect(self.on_filter_a_only_toggled)

        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 2, 0, 0)
        bottom_layout.addWidget(self.btn_filter_a_only)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.lbl_issue_count)
        ana_layout.addLayout(bottom_layout)

        right_layout.addWidget(self.grp_analysis, 1)
        # Yol Düzenleme paneli (UI geçişi)
        self.grp_edit = QGroupBox("Yol Düzenleme")
        self.grp_edit.setFont(QFont("Segoe UI", 9, QFont.Bold))
        edit_layout = QVBoxLayout(self.grp_edit)
        edit_layout.setSpacing(4)
        self.btn_edit_delete = QPushButton("Noktaları Düzenle / Sil")
        self.btn_edit_merge = QPushButton("Noktaları Birleştir")
        self.btn_edit_smooth = QPushButton("Noktaları Yumuşat")
        self.btn_edit_arcs = QPushButton("Yaylara Çevir")
        self.btn_edit_arcs.setEnabled(False)
        self.btn_edit_arcs.setVisible(False)
        self.btn_edit_undo = QPushButton("Geri Al")
        self.btn_edit_cancel = QPushButton("İptal")
        self.btn_edit_apply = QPushButton("Kaydet")
        for b in [
            self.btn_edit_delete,
            self.btn_edit_merge,
            self.btn_edit_smooth,
            self.btn_edit_arcs,
            self.btn_edit_undo,
            self.btn_edit_cancel,
            self.btn_edit_apply,
        ]:
            b.setCursor(Qt.PointingHandCursor)
            edit_layout.addWidget(b)
        self.btn_edit_delete.clicked.connect(self.on_edit_delete_clicked)
        self.btn_edit_merge.clicked.connect(self.on_edit_merge_clicked)
        self.btn_edit_smooth.clicked.connect(self.on_edit_smooth_clicked)
        self.btn_edit_arcs.clicked.connect(self.on_convert_to_arcs_clicked)
        self.btn_edit_undo.clicked.connect(self.on_edit_undo_clicked)
        self.btn_edit_cancel.clicked.connect(self.on_edit_cancel_clicked)
        self.btn_edit_apply.clicked.connect(self.on_edit_apply_clicked)
        self.grp_edit.setVisible(False)
        right_layout.addWidget(self.grp_edit)
        # Görünürlük kontrolleri
        self.grp_visibility = QGroupBox("Görünürlük")
        self.grp_visibility.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.grp_visibility.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.grp_visibility.setMinimumHeight(80)
        vis_layout = QVBoxLayout(self.grp_visibility)
        vis_layout.setSpacing(4)
        self.btn_toggle_stl = QPushButton("STL Göster")
        self.btn_toggle_stl.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_stl.clicked.connect(self._toggle_stl_visibility)
        self.btn_toggle_table = QPushButton("Zemini Göster")
        self.btn_toggle_table.setCursor(Qt.PointingHandCursor)
        self.btn_toggle_table.clicked.connect(self._toggle_table_visibility)
        vis_layout.addWidget(self.btn_toggle_stl)
        vis_layout.addWidget(self.btn_toggle_table)
        right_layout.addWidget(self.grp_visibility, 0, Qt.AlignBottom)
        right_layout.setStretchFactor(self.grp_gen, 0)
        right_layout.setStretchFactor(self.grp_analysis, 1)
        right_layout.setStretchFactor(self.grp_visibility, 0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_frame)
        splitter.addWidget(center_frame)
        splitter.addWidget(right_frame)
        splitter.setHandleWidth(6)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        top_layout.addWidget(splitter)

        # Alt bilgi paneli
        bottom_frame = QFrame()
        bottom_frame.setFrameShape(QFrame.StyledPanel)
        bottom_layout = QVBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(6, 4, 6, 4)

        self.bottom_label_title = QLabel("Takım Yolu Bilgileri / Mesajlar")
        self.bottom_label_title.setFont(QFont("Segoe UI", 8, QFont.Bold))

        self.bottom_label_info = QLabel("Takım yolu henüz oluşturulmadı.")
        self.bottom_label_info.setFont(QFont("Segoe UI", 8))
        self.bottom_label_info.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.bottom_label_info.setWordWrap(True)

        bottom_layout.addWidget(self.bottom_label_title)
        bottom_layout.addWidget(self.bottom_label_info)

        main_layout.addLayout(top_layout, 1)
        main_layout.addWidget(bottom_frame, 0)
        self._update_summary_info()
        self._refresh_visibility_buttons()
        # İni veya TabSettings'ten başlangıç değerlerini uygula
        self._apply_saved_toolpath_settings()
        self._on_params_changed()

        # Kısayol: Ctrl+Z -> Geri Al
        self.shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.shortcut_focus = QShortcut(QKeySequence("F"), self)
        self.shortcut_focus.setContext(Qt.WidgetWithChildrenShortcut)
        self.shortcut_focus.activated.connect(self.focus_selected_point)

        self.shortcut_zoom_focus = QShortcut(QKeySequence("Shift+F"), self)
        self.shortcut_zoom_focus.setContext(Qt.WidgetWithChildrenShortcut)
        self.shortcut_zoom_focus.activated.connect(self.zoom_selected_point)

        self.shortcut_fit_all = QShortcut(QKeySequence("Ctrl+F"), self)
        self.shortcut_fit_all.setContext(Qt.WidgetWithChildrenShortcut)
        self.shortcut_fit_all.activated.connect(self.fit_all_camera)


        self.shortcut_undo.setContext(Qt.WidgetWithChildrenShortcut)
        self.shortcut_undo.activated.connect(self.on_undo_toolpath)

    # --------------------------------------------------
    # Yol Düzenleme modu (sadece UI geçişi)
    # --------------------------------------------------
    def on_edit_mode_clicked(self):
        base_points = self.toolpath_points

        if not base_points:
            self.set_toolpath_info("Önce bir takım yolu oluşturmalısınız.")
            return

        # Geri alma için mevcut durumu sakla ve editörü baz yol ile başlat
        self._push_toolpath_history()
        self.toolpath_points = self._clone_points(base_points)
        self._apply_points_to_viewer_and_table()

        if self.edit_mode:
            return
        self.edit_mode = True
        self._original_points = self._clone_points(self.toolpath_points)
        self._history.clear()
        self._has_edit_changes = False
        if self.grp_gen:
            self.grp_gen.setVisible(False)
        if self.grp_summary:
            self.grp_summary.setVisible(False)
        if hasattr(self, "grp_analysis") and self.grp_analysis:
            self.grp_analysis.setVisible(False)
        if self.grp_export:
            self.grp_export.setVisible(False)
        if self.grp_edit:
            self.grp_edit.setVisible(True)
        if self.viewer is not None:
            if hasattr(self.viewer, "set_edit_mode"):
                self.viewer.set_edit_mode(True)
            else:
                self.viewer.edit_mode = True
            self.viewer.update()
        if self.btn_edit_mode:
            self.btn_edit_mode.setText("Yol Düzenleme (Aktif)")

    def _exit_edit_mode_ui(self):
        self.edit_mode = False
        if self.grp_gen:
            self.grp_gen.setVisible(True)
        if self.grp_summary:
            self.grp_summary.setVisible(True)
        if hasattr(self, "grp_analysis") and self.grp_analysis:
            self.grp_analysis.setVisible(True)
        if self.grp_points:
            self.grp_points.setVisible(True)
        if self.grp_export:
            self.grp_export.setVisible(True)
        if self.grp_edit:
            self.grp_edit.setVisible(False)
        if self.viewer is not None:
            if hasattr(self.viewer, "set_edit_mode"):
                self.viewer.set_edit_mode(False)
            else:
                self.viewer.edit_mode = False
            self.viewer.primary_index = -1
            self.viewer.secondary_index = -1
            self.viewer.update()
        self._selected_primary = -1
        self._selected_secondary = -1
        if self.btn_edit_mode:
            self.btn_edit_mode.setText("Yol Düzenle")

    def on_edit_cancel_clicked(self):
        if not self.edit_mode:
            return
        if not self._has_edit_changes:
            self._exit_edit_mode_ui()
            return
        reply = QMessageBox.question(
            self,
            "Düzenlemeleri İptal Et",
            "Yapılan değişiklikleri iptal etmek istediğinize emin misiniz?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            if self._original_points:
                self.toolpath_points = self._clone_points(self._original_points)
                self._apply_points_to_viewer_and_table()
            self._history.clear()
            self._has_edit_changes = False
            self._exit_edit_mode_ui()

    def on_edit_apply_clicked(self):
        if not self.edit_mode:
            return
        self._push_toolpath_history()
        self._original_points = self._clone_points(self.toolpath_points)
        # Düzenlenmiş yol aktif yol, hazırlanmış yol da buna eşitlensin
        self.prepared_toolpath_points = self._clone_points(self.toolpath_points)
        self._history.clear()
        self._has_edit_changes = False
        self.set_toolpath_info(f"Yol düzenlendi ve kaydedildi ({len(self.toolpath_points)} nokta).")
        self._exit_edit_mode_ui()

    def on_edit_undo_clicked(self):
        if not self.edit_mode:
            return
        if not self._history:
            self.set_toolpath_info("Geri alınacak bir değişiklik yok.")
            return
        snapshot = self._history.pop()
        self.toolpath_points = self._clone_points(snapshot)
        self._apply_points_to_viewer_and_table()
        self._has_edit_changes = bool(self._history)

    def _get_selection_range(self):
        i1 = self._selected_primary
        i2 = self._selected_secondary
        if i1 is None or i2 is None or i1 < 0 or i2 < 0:
            return None
        return tuple(sorted((i1, i2)))

    def on_edit_delete_clicked(self):
        if not self.edit_mode:
            return
        if not self.toolpath_points:
            self.set_toolpath_info("Önce bir takım yolu oluşturun.")
            return
        sel = self._get_selection_range()
        if sel is None:
            self.set_toolpath_info("Silmek için Ctrl ile iki nokta seçin.")
            return
        start, end = sel
        if end - start < 2:
            self.set_toolpath_info("Silmek için arada en az bir nokta olmalı.")
            return
        self._push_history("delete")
        pts = self.toolpath_points
        new_pts = pts[: start + 1] + pts[end:]
        self.toolpath_points = new_pts
        self._apply_points_to_viewer_and_table()
        self.set_toolpath_info(f"{end - start - 1} nokta silindi.")

    def on_edit_merge_clicked(self):
        if not self.edit_mode:
            return
        if not self.toolpath_points:
            self.set_toolpath_info("Önce bir takım yolu oluşturun.")
            return
        sel = self._get_selection_range()
        if sel is None:
            self.set_toolpath_info("Birleştirmek için Ctrl ile iki nokta seçin.")
            return
        start, end = sel
        if end - start < 2:
            self.set_toolpath_info("Birleştirme için arada nokta olmalı.")
            return

        self._push_history("merge")
        pts = self.toolpath_points
        p_start = pts[start]
        p_end = pts[end]
        count = end - start + 1
        new_segment: List[ToolpathPoint] = []
        for k in range(count):
            t = k / (count - 1) if count > 1 else 0.0
            x = p_start.x + (p_end.x - p_start.x) * t
            y = p_start.y + (p_end.y - p_start.y) * t
            z = p_start.z + (p_end.z - p_start.z) * t
            a_val = p_start.a + (p_end.a - p_start.a) * t
            new_segment.append(ToolpathPoint(x, y, z, a_val))

        new_pts = pts[:start] + new_segment + pts[end + 1 :]
        self.toolpath_points = new_pts
        self._apply_points_to_viewer_and_table()
        self.set_toolpath_info("Seçilen iki nokta arasındaki segment birleştirildi.")

    def on_edit_smooth_clicked(self):
        if not self.edit_mode:
            return
        if not self.toolpath_points:
            self.set_toolpath_info("Önce bir takım yolu oluşturun.")
            return
        sel = self._get_selection_range()
        if sel is None:
            self.set_toolpath_info("Yumuşatmak için Ctrl ile iki nokta seçin.")
            return
        start, end = sel
        if end - start < 3:
            self.set_toolpath_info("Yumuşatma için arada yeterli nokta yok.")
            return

        self._push_history("smooth")
        pts = self.toolpath_points
        window = 3
        half = window // 2
        for idx in range(start + 1, end):
            acc_z = 0.0
            acc_a = 0.0
            cnt = 0
            for k in range(idx - half, idx + half + 1):
                if k < start or k > end:
                    continue
                p = pts[k]
                acc_z += p.z
                acc_a += p.a
                cnt += 1
            if cnt > 0:
                pts[idx].z = acc_z / cnt
                pts[idx].a = acc_a / cnt
        self.toolpath_points = pts
        self._apply_points_to_viewer_and_table()
        self.set_toolpath_info("Seçilen aralıktaki noktalar yumuşatıldı.")

    def on_convert_to_arcs_clicked(self):
        """Yaylara çevir özelliği kaldırıldı."""
        self.set_toolpath_info("Yaylara çevirme devre dışı.")
        return

        bg = cfg.get("COLORS", "background", fallback="#E6E6EB")
        table_c = cfg.get("COLORS", "table", fallback="#D5E4F0")
        stl_c = cfg.get("COLORS", "stl", fallback="#FF6699")

        self.table_width_mm = width
        self.table_height_mm = height
        self.origin_mode = origin_mode
        self.table_fill_enabled = show_fill

        self.viewer.set_table_size(width, height)
        self.viewer.set_origin_mode(origin_mode)
        self.viewer.set_table_fill_enabled(show_fill)
        self.viewer.set_colors(bg, table_c, stl_c)

        self.bottom_label_info.setText(
            f"Tabla: {width:.1f} x {height:.1f} mm | G54 orjini: {origin_mode}"
        )

    def _apply_saved_toolpath_settings(self):
        """
        TabSettings içindeki değerler varsa başlangıçta spinbox/combobox'a uygular.
        """
        tab_settings = getattr(self.main_window, "tab_settings", None)
        contour_val = 0.0
        step_val = 0.5
        z_idx = 0
        color_hex = "#ff0000"
        width_px = 2.0
        if tab_settings is not None:
            contour_val = float(getattr(tab_settings, "contour_offset_mm", contour_val))
            step_val = float(getattr(tab_settings, "z_step_mm", step_val))
            z_idx = int(getattr(tab_settings, "z_mode_index", z_idx))
            color_hex = getattr(tab_settings, "toolpath_color_hex", color_hex)
            width_px = float(getattr(tab_settings, "toolpath_width_px", width_px))
        else:
            # TabSettings henüz yoksa ini dosyasından APP bölümünü oku
            try:
                cfg = configparser.ConfigParser()
                if cfg.read(INI_PATH, encoding="utf-8") and cfg.has_section("APP"):
                    contour_val = cfg.getfloat("APP", "contour_offset_mm", fallback=contour_val)
                    step_val = cfg.getfloat("APP", "z_step_mm", fallback=step_val)
                    z_idx = cfg.getint("APP", "z_mode", fallback=z_idx)

            except Exception:
                logger.exception("TabToolpath beklenmeyen hata")
        try:
            self.offset_spin.blockSignals(True)
            self.step_spin.blockSignals(True)
            self.z_mode_combo.blockSignals(True)
            self.offset_spin.setValue(contour_val)
            self.step_spin.setValue(step_val)
            self.z_mode_combo.setCurrentIndex(z_idx)
        finally:
            self.offset_spin.blockSignals(False)
            self.step_spin.blockSignals(False)
            self.z_mode_combo.blockSignals(False)
        self.apply_toolpath_style_from_settings(color_hex, width_px)
        # Model sekmesindeki spin ile senkron tut
        tab_model = getattr(self.main_window, "tab_model", None)
        if tab_model is not None and hasattr(tab_model, "spin_model_offset"):
            tab_model.spin_model_offset.blockSignals(True)
            tab_model.spin_model_offset.setValue(self.offset_spin.value())
            tab_model.spin_model_offset.blockSignals(False)

    # --------------------------------------------------
    # Bilgi güncelleme
    # --------------------------------------------------
    def set_toolpath_info(self, text: str):
        """Alt paneldeki bilgi yazısını günceller."""
        self.bottom_label_info.setText(text)

    # --------------------------------------------------
    # Takım yolu üretimi
    # --------------------------------------------------
    def generate_from_current_model(self, progress_cb=lambda p, m="": None):
        """
        Model sekmesindeki aktif STL'den Z-takipli kontur tak?m yolunu ?retir (async).
        """
        if self._is_generating:
            return
        main = self.main_window
        if main is None or not hasattr(main, "tab_model") or not hasattr(main, "tab_settings"):
            QMessageBox.warning(self, TITLE_TOOLPATH, MSG_MODEL_SETTINGS_MISSING)
            return

        model_tab = main.tab_model
        settings_tab = main.tab_settings

        if not getattr(model_tab, "model_loaded", False):
            QMessageBox.warning(self, TITLE_TOOLPATH, MSG_MODEL_REQUIRED)
            return

        viewer = model_tab.viewer
        offset_mm = float(self.offset_spin.value())
        step_mm = float(self.step_spin.value())
        mode_idx = int(self.z_mode_combo.currentIndex())

        self._write_params_to_settings_tab(offset_mm, step_mm, mode_idx)
        tab_model = getattr(self.main_window, "tab_model", None)
        if tab_model is not None and hasattr(tab_model, "spin_model_offset"):
            tab_model.spin_model_offset.blockSignals(True)
            tab_model.spin_model_offset.setValue(offset_mm)
            tab_model.spin_model_offset.blockSignals(False)

        self._set_generate_busy(True)
        self._is_generating = True
        self._toolpath_worker = WorkerRunnable(
            self._run_toolpath_generation,
            viewer,
            settings_tab,
            offset_mm,
            step_mm,
            mode_idx,
        )
        self._toolpath_worker.signals.progress.connect(self._on_toolpath_progress)
        self._toolpath_worker.signals.result.connect(self._on_toolpath_result)
        self._toolpath_worker.signals.error.connect(self._on_toolpath_error)
        self._toolpath_worker.signals.finished.connect(self._on_toolpath_finished)
        self.threadpool.start(self._toolpath_worker)

    def start_generation_from_external(self, progress_cb=None):
        """Dış tetik (Model sekmesi) ile üretimi başlatır."""
        if self._is_generating:
            return
        self._external_trigger = True  # NOTE: External trigger should not auto-switch or generate G-code.
        logger.info("Starting generation from external trigger")
        if progress_cb is None:
            self.generate_from_current_model()
        else:
            self.generate_from_current_model(progress_cb=progress_cb)
    def _run_toolpath_generation(self, worker, viewer, settings_tab, offset_mm, step_mm, mode_idx):


        def prog(p, msg=""):
            worker.signals.progress.emit(msg, int(p))
            if getattr(worker, "cancel_requested", False):
                raise RuntimeError("Cancelled")

        mesh_cache = None
        if self.state is not None:
            mesh_cache = getattr(self.state, "mesh_intersector_cache", None)
        mesh_version = getattr(viewer, "mesh_version", None)
        result = self.pipeline.generate(
            viewer,
            settings_tab,
            sample_step_mm=step_mm,
            offset_mm=offset_mm,
            z_mode_index=mode_idx,
            progress_cb=lambda p, m="": prog(p, m),
            generate_gcode=False,  # NOTE: Toolpath generation should not create G-code.
            mesh_intersector_cache=mesh_cache,
            mesh_version=mesh_version,
        )
        return result

    def _on_toolpath_progress(self, message: str, percent: int):
        label = f"{percent}% - {message}" if message else f"{percent}%"
        self.set_toolpath_info(label)
        if self.btn_generate:
            self.btn_generate.setText(label)
        if self._external_trigger and hasattr(self.main_window, "tab_model"):
            # NOTE: Forward progress to Model tab when triggered externally.
            try:
                self.main_window.tab_model._on_toolpath_progress(message, percent)
            except Exception:
                logger.exception("Model sekmesi ilerleme bildirimi başarısız")

    def _on_toolpath_result(self, payload: dict):
        result = payload if isinstance(payload, ToolpathResult) else None
        points = result.points if result is not None else (payload.get("points") or [])
        gcode_text = ""  # NOTE: G-code is generated only on explicit request.
        self._last_toolpath_ok = bool(points)  # NOTE: Track success for external UI flow.
        if result is not None:
            meta = result.meta or {}
            elapsed = meta.get("elapsed_sec", 0.0)
            z_mode_idx = meta.get("z_mode_index")
            z_stats = result.z_stats or {}
            offset_mm = meta.get("offset_mm", None)
            step_mm = meta.get("step_mm", None)
            if self.state is not None:
                self.state.toolpath_result = result  # NOTE: Store pipeline result as single source.
        else:
            meta = {}
            elapsed = payload.get("elapsed", 0.0)
            z_mode_idx = payload.get("z_mode_index")
            z_stats = payload.get("z_stats") or {}
            offset_mm = payload.get("offset_mm", None)
            step_mm = payload.get("step_mm", None)
        if not points:
            self.toolpath_points = []
            try:
                self.points_table.setRowCount(0)
            except Exception:
                logger.exception("Nokta tablosu s?f?rlanamad?")
            self._update_summary_info()
            self.set_toolpath_info("Tak?m yolu ?retilemedi.")
            QMessageBox.warning(self, "Tak?m Yolu", "Tak?m yolu ?retilemedi.")
            return

        self.original_toolpath_points = self._clone_points(points)
        self.toolpath_points = self._clone_points(points)
        self.gcode_lines = ""  # NOTE: Clear generated G-code during toolpath creation.
        self.prepared_toolpath_points = []
        self.toolpath_history.clear()
        self._issues = []
        self._last_issues = []
        if getattr(self, "tbl_issues", None) is not None:
            try:
                self.tbl_issues.setRowCount(0)
            except Exception:
                logger.exception("Issue tablosu s?f?rlanamad?")
        if self.viewer is not None and hasattr(self.viewer, "set_issue_indices"):
            try:
                self.viewer.set_issue_indices([])
            except Exception:
                logger.exception("Issue indexleri s?f?rlanamad?")

        offset_a = float(getattr(self, "knife_a_offset_deg", 0.0))
        self._recompute_a_for_points(self.toolpath_points, knife_offset_deg=offset_a)

        try:
            pts_arr = np.array([[p.x, p.y, p.z] for p in self.toolpath_points], dtype=np.float32)
            if self.viewer is not None and hasattr(self.viewer, "set_toolpath_polyline"):
                self.viewer.set_toolpath_polyline(pts_arr)
            if self.viewer is not None and hasattr(self.viewer, "set_original_toolpath_polyline"):
                orig_arr = np.array([[p.x, p.y, p.z] for p in self.original_toolpath_points], dtype=np.float32)
                self.viewer.set_original_toolpath_polyline(orig_arr)
        except Exception:
            logger.exception("Toolpath viewer'a yazılamadı")

        self._sync_viewer_from_model()
        self._update_summary_info()

        if getattr(self, "tbl_issues", None) is not None:
            try:
                self.tbl_issues.blockSignals(True)
                self.tbl_issues.setRowCount(0)
            finally:
                self.tbl_issues.blockSignals(False)
        if getattr(self, "lbl_issue_count", None) is not None:
            self.lbl_issue_count.setText("Toplam hata say?s?: 0")

        total_len = 0.0
        for i in range(1, len(points)):
            dx = points[i].x - points[i - 1].x
            dy = points[i].y - points[i - 1].y
            total_len += (dx * dx + dy * dy) ** 0.5

        mode_label = None
        try:
            if z_mode_idx is not None and 0 <= int(z_mode_idx) < len(Z_MODE_LABELS):
                mode_label = Z_MODE_LABELS[int(z_mode_idx)]
        except Exception:
            mode_label = None

        info_txt = (
            f"Tak?m yolu olu?turuldu: {len(points)} nokta, yakla??k {total_len:.1f} mm, "
            f"s?re {elapsed:.2f} sn."
        )
        if mode_label:
            info_txt += f" | Z modu: {mode_label}"
        if z_stats:
            try:
                info_txt += f" (multi-hit: {z_stats.get('multi_hit_points', 0)}, continuity: {z_stats.get('continuity_used', 0)})"
            except Exception:
                pass
        if z_stats and "total_a_travel_deg" in z_stats and "max_a_step_deg" in z_stats:
            try:
                total_a = float(z_stats.get("total_a_travel_deg", 0.0))
                max_a = float(z_stats.get("max_a_step_deg", 0.0))
                info_txt += f" | A toplam: {total_a:.1f}° max adım: {max_a:.1f}°"
            except Exception:
                logger.exception("A metrikleri yazılamadı")
        self.set_toolpath_info(info_txt)
        self._update_points_table()
        try:
            self._auto_validate_toolpath()
        except Exception:
            logger.exception("Otomatik kalite kontrolü başarısız")

        # Sonuçları builder sekmesine ve state'e aktar
        meta_prepared = dict(meta) if isinstance(meta, dict) else {}
        meta_prepared.update(
            {
                "offset_mm": float(offset_mm if offset_mm is not None else self.offset_spin.value()),
                "step_mm": float(step_mm if step_mm is not None else self.step_spin.value()),
                "z_mode_index": z_mode_idx,
                "z_stats": z_stats,
                "point_count": len(points),
                "elapsed_sec": elapsed,
            }
        )
        try:
            self.state.prepared_points = self._clone_points(points)
            self.state.prepared_meta = meta_prepared
            self.state.toolpath_points = self._clone_points(points)  # NOTE: Store toolpath for G-code stage.
            self.state.gcode_text = ""  # NOTE: Clear G-code until explicitly generated.
            if self.state.toolpath_result is not None:
                self.state.toolpath_result.points = self._clone_points(points)
                self.state.toolpath_result.meta.update(meta_prepared)
        except Exception:
            logger.exception("State'e prepared noktalar yazılamadı")

        try:
            builder = getattr(self.main_window, "tab_toolpath_builder", None)
            if builder is not None and hasattr(builder, "load_prepared_data"):
                builder.load_prepared_data(self.state.prepared_points, meta_prepared, "")
                if not self._external_trigger and hasattr(self.main_window, "tabs_3d"):
                    self.main_window.tabs_3d.setCurrentWidget(builder)
        except Exception:
            logger.exception("Builder sekmesine veri aktarılamadı")

    def _auto_validate_toolpath(self):
        """
        Yol üretiminden sonra otomatik kalite kontrolü yapar, tabloyu ve viewer işaretlerini günceller.
        """
        if not self.toolpath_points:
            return

        tab_settings = getattr(self.main_window, "tab_settings", None)
        if tab_settings is None:
            return

        table_w = getattr(tab_settings, "table_width_mm", None)
        table_h = getattr(tab_settings, "table_height_mm", None)
        z_max = getattr(tab_settings, "safe_z_mm", None)
        if z_max is None:
            z_max = getattr(tab_settings, "safe_z", None)
        z_min = getattr(tab_settings, "z_min_mm", None)
        a_min = getattr(tab_settings, "knife_a_min_deg", None)
        a_max = getattr(tab_settings, "knife_a_max_deg", None)
        opts = self.analysis_options or {}

        issues: List[PathIssue] = []

        try:
            issues.extend(
                self.pipeline.validate(
                    self.toolpath_points,
                    table_width_mm=table_w,
                    table_height_mm=table_h,
                    z_min_mm=z_min,
                    z_max_mm=z_max,
                    enable_z_max_check=bool(opts.get("enable_z_max", False)),
                    a_min_deg=a_min,
                    a_max_deg=a_max,
                )
            )
        except Exception:
            logger.exception("Otomatik validate_toolpath çalıştırılamadı")

        try:
            angle_threshold = float(opts.get("angle_threshold", 30.0))
            z_threshold = float(opts.get("z_threshold", 2.0))
            dir_threshold = float(opts.get("dir_threshold", 30.0))
            xy_spike_threshold = float(opts.get("xy_spike_threshold", 0.3))

            raw_issues = self.pipeline.analyze(
                self.toolpath_points,
                angle_threshold_deg=angle_threshold,
                z_threshold_mm=z_threshold,
                dir_threshold_deg=dir_threshold,
                xy_spike_threshold_mm=xy_spike_threshold,
            )
            issues.extend(self._filter_and_compress_issues(raw_issues))
        except Exception:
            logger.exception("Otomatik analyze_toolpath çalıştırılamadı")

        self._issues = issues
        self._last_issues = list(issues) if issues else []
        if self.state is not None and self.state.toolpath_result is not None:
            self.state.toolpath_result.issues = list(issues)  # NOTE: Store analysis in result.
        if self.viewer is not None and hasattr(self.viewer, "set_issue_indices"):
            try:
                indices = [iss.index for iss in self._issues]
                self.viewer.set_issue_indices(indices)
            except Exception:
                logger.exception("Issue indexleri viewer'a yazılamadı")

        self._refresh_issue_table_from_last()

        summary = self._build_quality_summary(self._issues)
        if summary:
            self.set_toolpath_info(summary)
            logger.info(summary)

    def _build_quality_summary(self, issues: List[PathIssue]) -> str:
        if not issues:
            return "Kalite: sorun bulunmadı."

        counter = Counter()
        for iss in issues:
            issue_type = getattr(iss, "type", None)
            if issue_type is None and isinstance(iss, dict):
                issue_type = iss.get("type") or iss.get("issue_type")
            if issue_type:
                counter[issue_type] += 1

        total = sum(counter.values())
        parts = [f"{k}={v}" for k, v in counter.items()]
        if total:
            parts.append(f"TOTAL={total}")
        return f"Kalite: {', '.join(parts)}" if parts else "Kalite: sorun bulunmadı."

    def _on_toolpath_error(self, user_message: str, exc_text: str):
        self._last_toolpath_ok = False  # NOTE: Mark failed generation.
        if self._external_trigger and hasattr(self.main_window, "tab_model"):
            # NOTE: Notify Model tab on async error to restore UI state.
            try:
                self.main_window.tab_model._on_toolpath_generation_done(False)
            except Exception:
                logger.exception("Model sekmesi hata bildirimi başarısız")
        self._external_trigger = False  # NOTE: Reset external trigger on error.
        logger.error("Tak?m yolu ?retimi hatas?: %s", exc_text)
        if "cancelled" in exc_text.lower() or "iptal" in user_message.lower():
            QMessageBox.information(self, TITLE_TOOLPATH, MSG_OPERATION_CANCELLED)
        else:
            QMessageBox.critical(self, TITLE_TOOLPATH, MSG_TOOLPATH_ERROR)
    def _on_toolpath_finished(self):
        was_external = self._external_trigger
        self._external_trigger = False  # NOTE: Reset external trigger on finish.
        self._toolpath_worker = None
        self._is_generating = False
        self._set_generate_busy(False)
        if self.btn_generate:
            self.btn_generate.setText("STL'den Z-Takipli Yol Olu?tur")
        if was_external and hasattr(self.main_window, "tab_model"):
            # NOTE: Notify Model tab only after async completion.
            try:
                self.main_window.tab_model._on_toolpath_generation_done(self._last_toolpath_ok)
            except Exception:
                logger.exception("Model sekmesi tamamlama bildirimi ba?ar?s?z")
    def _cancel_generation(self):
        if self._toolpath_worker:
            try:
                self._toolpath_worker.cancel()
                self.set_toolpath_info("??lem iptal ediliyor...")
            except Exception:
                logger.exception("?ptal iste?i g?nderilemedi")
    def _sync_viewer_from_model(self):
        """Model sekmesindeki viewer ayarlarını (tabla, renk, rotasyon, offset) kopyala."""
        main = self.main_window
        if main is None or not hasattr(main, "tab_model"):
            return
        mtab = main.tab_model
        src = mtab.viewer
        self.viewer.set_table_size(src.table_width, src.table_height)
        self.viewer.set_origin_mode(src.origin_mode)
        self.viewer.set_table_fill_enabled(src.table_fill_enabled)
        if hasattr(src, "bg_color_hex"):
            self.viewer.set_colors(src.bg_color_hex, src.table_color_hex, src.stl_color_hex)
        self.viewer.set_model_rotation(src.model_rot_x, src.model_rot_y, src.model_rot_z)
        self.viewer.set_model_offset(src.model_offset_x, src.model_offset_y, src.model_offset_z)
        self._refresh_visibility_buttons()

    def _toggle_stl_visibility(self):
        """STL görünürlüğünü aç/kapa."""
        main = self.main_window
        model_tab = getattr(main, "tab_model", None)
        model_path = getattr(model_tab, "model_path", None)

        if not model_path:
            self.set_toolpath_info("Önce Model sekmesinden bir STL yükleyin.")
            return

        if self.viewer.mesh_vertices is None:
            try:
                self.viewer.load_stl(model_path)
            except Exception as e:
                self.set_toolpath_info(f"STL yüklenemedi: {e}")
                return
        self._sync_viewer_from_model()

        self.stl_shown = not self.stl_shown
        self.viewer.set_mesh_visible(self.stl_shown)
        self.btn_toggle_stl.setText("STL Gizle" if self.stl_shown else "STL Göster")
        self.viewer.update()

    def _toggle_table_visibility(self):
        """Tabla (zemin) görüntülerini aç/kapa."""
        current = getattr(self.viewer, "table_visible", True)
        self.viewer.table_visible = not current
        self.viewer.axes_visible = self.viewer.table_visible
        self.btn_toggle_table.setText("Zemini Gizle" if self.viewer.table_visible else "Zemini Göster")
        self.viewer.update()

    def on_prepare_toolpath_clicked(self):
        """
        Alt paneldeki 'Takım yolu hazırla' butonu.
        Gerçek ofset değerine göre yeni bir takım yolu üretir ve onu aktif yol yapar.
        """
        if not self.toolpath_points:
            self.set_toolpath_info("Önce STL'den takım yolu oluşturmalısınız.")
            return

        # Geri alma için mevcut yolu yığına kaydet
        self._push_toolpath_history()

        real_offset = 0.0
        if hasattr(self, "real_offset_spin") and self.real_offset_spin is not None:
            try:
                real_offset = float(self.real_offset_spin.value())
            except Exception:
                real_offset = 0.0

        new_points = self._build_real_offset_toolpath(real_offset)
        if not new_points:
            self.set_toolpath_info("Gerçek ofset uygulanamadı; mevcut yol kullanılacak.")
            return

        self.prepared_toolpath_points = self._clone_points(new_points)
        self.toolpath_points = self._clone_points(new_points)

        # A açılarını yeniden hesapla (bıçak offset'i varsa ekle)
        offset_a = float(getattr(self, "knife_a_offset_deg", 0.0))
        self._recompute_a_for_points(self.toolpath_points, knife_offset_deg=offset_a)

        try:
            pts_arr = np.array([[p.x, p.y, p.z] for p in self.toolpath_points], dtype=np.float32)
            if self.viewer is not None and hasattr(self.viewer, "set_toolpath_polyline"):
                self.viewer.set_toolpath_polyline(pts_arr)
        except Exception:
            logger.exception("TabToolpath beklenmeyen hata")

        self._update_points_table()
        self._update_summary_info()
        if getattr(self, "chk_show_original", None) and self.chk_show_original.isChecked():
            self._update_original_toolpath_in_viewer()

        info_txt = (
            f"Gerçek ofset ile takım yolu hazırlandı: "
            f"{len(self.toolpath_points)} nokta, ofset = {real_offset:.3f} mm."
        )
        self.set_toolpath_info(info_txt)

    def on_undo_toolpath(self):
        """
        CTRL+Z geri alma.
        Edit modundaysa nokta düzenleme geri alınıyor; değilse son takım yolu durumu geri yükleniyor.
        """
        if getattr(self, "edit_mode", False):
            self.on_edit_undo_clicked()
            return

        if not self.toolpath_history:
            self.set_toolpath_info("Geri alınacak bir işlem yok.")
            return

        last_state = self.toolpath_history.pop()
        self.toolpath_points = self._clone_points(last_state)
        self.prepared_toolpath_points = self._clone_points(last_state)

        if self.viewer is not None and hasattr(self.viewer, "set_toolpath_polyline"):
            try:
                arr = np.array([[p.x, p.y, p.z] for p in self.toolpath_points], dtype=np.float32)
                self.viewer.set_toolpath_polyline(arr)
            except Exception:
                logger.exception("TabToolpath beklenmeyen hata")

        self._update_points_table()
        self._update_summary_info()
        self.set_toolpath_info("Son takım yolu işlemi geri alındı (CTRL+Z).")

    def _refresh_visibility_buttons(self):
        """Viewer görünürlük durumlarına göre buton metinlerini senkronize eder."""
        stl_loaded = getattr(self.viewer, "mesh_vertices", None) is not None
        viewer_mesh_visible = bool(getattr(self.viewer, "mesh_visible", False))
        self.stl_shown = stl_loaded and viewer_mesh_visible
        if getattr(self, "btn_toggle_stl", None):
            self.btn_toggle_stl.setText("STL Gizle" if self.stl_shown else "STL Göster")

        table_visible = bool(getattr(self.viewer, "table_visible", True))
        if getattr(self, "btn_toggle_table", None):
            self.btn_toggle_table.setText("Zemini Gizle" if table_visible else "Zemini Göster")

    def _set_generate_busy(self, busy: bool):
        """Hesaplama s?ras?nda butona bekleme g?stergesi ekler."""
        try:
            if busy:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                self.btn_generate.setEnabled(False)
                self.btn_generate.setText("Hesaplan?yor...")
                if hasattr(self, "btn_cancel_generate"):
                    self.btn_cancel_generate.setEnabled(True)
            else:
                QApplication.restoreOverrideCursor()
                self.btn_generate.setEnabled(True)
                self.btn_generate.setText("STL'den Z-Takipli Yol Olu?tur")
                if hasattr(self, "btn_cancel_generate"):
                    self.btn_cancel_generate.setEnabled(False)
        except Exception:
            logger.exception("TabToolpath beklenmeyen hata")
    def show_z_plot(self):
        """Toolpath noktalarından Z eğrisini gösterir."""
        if not self.toolpath_points:
            QMessageBox.warning(self, "Z Eğrisi", "Önce bir takım yolu oluşturun.")
            return
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            QMessageBox.critical(self, "Z Eğrisi", "Matplotlib kütüphanesi yüklü değil. Grafik için: pip install matplotlib")
            return
        indices = list(range(1, len(self.toolpath_points) + 1))
        z_vals = [p.z for p in self.toolpath_points]
        plt.figure("Z Eğrisi (Z Takibi)")
        plt.plot(indices, z_vals, label="Z (mm)")
        plt.grid(True)
        plt.xlabel("Nokta #")
        plt.ylabel("Z (mm)")
        plt.title("Z Eğrisi (Z Takibi)")
        plt.legend()
        plt.show()

    def show_a_plot(self):
        """Toolpath noktalarından A açısının eğrisini gösterir."""
        if not self.toolpath_points:
            QMessageBox.warning(self, "A Açısı Eğrisi", "Önce bir takım yolu oluşturun.")
            return
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            QMessageBox.critical(self, "A Açısı Eğrisi", "Matplotlib kütüphanesi yüklü değil. Grafik için: pip install matplotlib")
            return
        indices = list(range(1, len(self.toolpath_points) + 1))
        a_vals = [p.a for p in self.toolpath_points]
        plt.figure("A Açısının Değişimi")
        plt.plot(indices, a_vals, label="A (deg)", color="orange")
        plt.grid(True)
        plt.xlabel("Nokta #")
        plt.ylabel("Açı (deg)")
        plt.title("A Açısının Değişimi")
        plt.legend()
        plt.show()

    def _compute_path_length(self, points):
        """Verilen ToolpathPoint listesinden yaklasik 3B yol uzunlugunu hesaplar (mm)."""
        if not points or len(points) < 2:
            return 0.0

        total = 0.0
        prev = points[0]
        for p in points[1:]:
            dx = p.x - prev.x
            dy = p.y - prev.y
            dz = p.z - prev.z
            total += (dx * dx + dy * dy + dz * dz) ** 0.5
            prev = p
        return total

    def _get_selected_range_indices(self):
        """
        Nokta Listesi'nden secili satir araligini dondurur (start, end).
        - Hic secim yoksa (None, None)
        - Birden fazla blok seciliyse, Qt'nin verdigi minimum/maksimum satiri kullanir.
        """
        sel = self.points_table.selectionModel()
        if sel is None:
            return None, None

        indexes = sel.selectedRows()
        if not indexes:
            return None, None

        rows = sorted(idx.row() for idx in indexes)
        start = rows[0]
        end = rows[-1]
        if start > end:
            start, end = end, start
        return start, end

    # --------------------------------------------------
    # Nokta tablosu
    # --------------------------------------------------
    def _update_points_table(self):
        """toolpath_points listesini tabloya yazar."""
        pts = self.toolpath_points or []
        self._points_table_updating = True
        try:
            self.points_table.setRowCount(len(pts))
            for i, pt in enumerate(pts):
                values = [
                    str(i + 1),
                    f"{pt.x:.3f}",
                    f"{pt.y:.3f}",
                    f"{pt.z:.3f}",
                    f"{pt.a:.3f}",
                ]
                for col, val in enumerate(values):
                    item = QTableWidgetItem(val)
                    item.setTextAlignment(Qt.AlignCenter)
                    self.points_table.setItem(i, col, item)
            self.points_table.resizeColumnsToContents()
        finally:
            self._points_table_updating = False
        if pts:
            self.points_table.selectRow(0)
            self.viewer.set_selected_index(0)
        self._update_summary_info()
        self._update_generate_gcode_button_state()
        if self.state is not None:
            self.state.toolpath_points = self._clone_points(pts)  # NOTE: Keep state in sync for G-code.

    def _update_generate_gcode_button_state(self):
        """G-code oluşturma butonunu nokta varlığına göre enable/disable eder."""
        btn = getattr(self, "btn_generate_gcode", None)
        if btn is None:
            return
        has_points = bool(self._get_points_for_gcode())
        btn.setEnabled(has_points)

    def _get_points_for_gcode(self) -> List[ToolpathPoint]:
        """G-code üretimi için kullanılacak nokta listesi (öncelik: aktif yol)."""
        if getattr(self, "toolpath_points", None):
            return list(self.toolpath_points)
        if getattr(self, "prepared_toolpath_points", None):
            return list(self.prepared_toolpath_points)
        if getattr(self, "original_toolpath_points", None):
            return list(self.original_toolpath_points)
        return []

    def _on_generate_gcode_clicked(self):
        """G-code ??retimi Tak?m Yolu Olu?turma sekmesinde yap?l?r."""
        pts = self._get_points_for_gcode()
        if not pts:
            self.set_toolpath_info("?nce bir tak?m yolu olu?turun.")
            return
        self.set_toolpath_info("G-code olu?turma Tak?m Yolu Olu?turma sekmesinde yap?l?r.")
        try:
            builder = getattr(self.main_window, "tab_toolpath_builder", None)
            if builder is not None and hasattr(self.main_window, "tabs_3d"):
                self.main_window.tabs_3d.setCurrentWidget(builder)
        except Exception:
            logger.exception("G-code sekmesine ge?i? ba?ar?s?z")

    def _build_real_offset_toolpath(self, real_offset_mm: float) -> List[ToolpathPoint]:
        """
        Mevcut toolpath_points listesinden, XY düzleminde real_offset_mm kadar kaydırılmış yeni bir
        takım yolu üretir. Ardından min mesafe + min açı kriteri ile noktaları seyrekleştirir. Z ve A
        değerleri korunur.
        """
        base = self.toolpath_points
        if not base:
            return []

        if abs(real_offset_mm) < 1e-4:
            return self._clone_points(base)

        pts = self._clone_points(base)
        n = len(pts)
        offset_pts: List[ToolpathPoint] = []

        for i, p in enumerate(pts):
            if n == 1:
                dx, dy = 1.0, 0.0
            elif i == 0:
                dx = pts[1].x - pts[0].x
                dy = pts[1].y - pts[0].y
            elif i == n - 1:
                dx = pts[-1].x - pts[-2].x
                dy = pts[-1].y - pts[-2].y
            else:
                dx = pts[i + 1].x - pts[i - 1].x
                dy = pts[i + 1].y - pts[i - 1].y

            length = math.hypot(dx, dy)
            if length < 1e-9:
                nx, ny = 0.0, 0.0
            else:
                vx = dx / length
                vy = dy / length
                nx = -vy
                ny = vx

            o = real_offset_mm
            offset_pts.append(ToolpathPoint(p.x + nx * o, p.y + ny * o, p.z, p.a))

        if len(offset_pts) < 3:
            return offset_pts

        try:
            base_step = float(self.step_spin.value())
        except Exception:
            base_step = 0.5
        min_step = max(0.25 * base_step, 0.02)
        min_angle_deg = 5.0

        simplified: List[ToolpathPoint] = []
        last_p: ToolpathPoint = None  # type: ignore
        last_dir = None

        for p in offset_pts:
            if last_p is None:
                simplified.append(p)
                last_p = p
                last_dir = None
                continue

            dx = p.x - last_p.x
            dy = p.y - last_p.y
            dist = math.hypot(dx, dy)
            if dist < 1e-9:
                continue

            dir_vec = (dx / dist, dy / dist)
            if last_dir is None:
                angle = 0.0
            else:
                dot = last_dir[0] * dir_vec[0] + last_dir[1] * dir_vec[1]
                dot = max(-1.0, min(1.0, dot))
                angle = math.degrees(math.acos(dot))

            if dist < min_step and angle < min_angle_deg:
                continue

            simplified.append(p)
            last_p = p
            last_dir = dir_vec

        if simplified and simplified[-1] is not offset_pts[-1]:
            simplified.append(offset_pts[-1])

        return simplified

    def _push_toolpath_history(self):
        """
        Mevcut toolpath_points listesini geri alma yığınına kopyalar.
        """
        if not self.toolpath_points:
            return
        snapshot = self._clone_points(self.toolpath_points)
        self.toolpath_history.append(snapshot)

    def _update_original_toolpath_in_viewer(self):
        """
        Orijinal takım yolunu viewer'a gönderir.
        """
        if self.viewer is None:
            return
        if not self.original_toolpath_points:
            return
        if not hasattr(self.viewer, "set_original_toolpath_polyline"):
            return
        try:
            arr = np.array(
                [[p.x, p.y, p.z] for p in self.original_toolpath_points],
                dtype=np.float32,
            )
            self.viewer.set_original_toolpath_polyline(arr)
        except Exception:
            logger.exception("TabToolpath beklenmeyen hata")

    def on_show_original_toggled(self, checked: bool):
        """
        'Eski yolu göster' checkbox'ı.
        """
        if self.viewer is None:
            return
        if hasattr(self.viewer, "set_show_original_toolpath"):
            self.viewer.set_show_original_toolpath(bool(checked))
        if checked:
            self._update_original_toolpath_in_viewer()

    def _clone_points(self, points: List[ToolpathPoint]) -> List[ToolpathPoint]:
        return [ToolpathPoint(p.x, p.y, p.z, p.a) for p in points]

    def _push_history(self, reason: str = ""):
        """
        Mevcut toolpath_points listesinin kopyasını history'e ekler.
        Maksimum _history_limit kadar eleman tutulur.
        """
        if not self.toolpath_points:
            return
        snapshot = self._clone_points(self.toolpath_points)
        self._history.append(snapshot)
        if len(self._history) > self._history_limit:
            self._history.pop(0)
        self._has_edit_changes = True

    def _restore_from_snapshot(self, snapshot: List[ToolpathPoint]):
        self.toolpath_points = self._clone_points(snapshot)
        self._apply_points_to_viewer_and_table()
        self._has_edit_changes = True

    def _apply_points_to_viewer_and_table(self):
        """
        toolpath_points listesini kullanarak:
        - viewer.toolpath_polyline'ı günceller
        - tabloyu yeniden doldurur
        - özet bilgileri yeniler
        """
        pts = self.toolpath_points or []
        if self.viewer is not None:
            if pts:
                arr = np.array([[p.x, p.y, p.z] for p in pts], dtype=np.float32)
                self.viewer.set_toolpath_polyline(arr)
            else:
                self.viewer.set_toolpath_polyline(None)
            self.viewer.primary_index = -1
            self.viewer.secondary_index = -1
            self.viewer.update()

        if self.points_table is not None:
            self._points_table_updating = True
            self.points_table.blockSignals(True)
            try:
                self.points_table.setRowCount(len(pts))
                for i, p in enumerate(pts):
                    values = [
                        str(i + 1),
                        f"{p.x:.3f}",
                        f"{p.y:.3f}",
                        f"{p.z:.3f}",
                        f"{p.a:.3f}",
                    ]
                    for col, val in enumerate(values):
                        item = QTableWidgetItem(val)
                        item.setTextAlignment(Qt.AlignCenter)
                        self.points_table.setItem(i, col, item)
            finally:
                self.points_table.blockSignals(False)
                self._points_table_updating = False
            self.points_table.resizeColumnsToContents()

        self._update_summary_info()

    def _on_viewer_selection_changed(self, primary: int, secondary: int):
        """
        Viewer'da bir nokta (veya iki nokta) seçildiğinde tabloyu ve bilgi satırını günceller.
        Ctrl + sol tık ile iki nokta seçimi için primary/secondary tutulur.
        """
        self._selected_primary = primary
        self._selected_secondary = secondary

        table = self.points_table
        if (
            table is None
            or primary is None
            or primary < 0
            or primary >= len(self.toolpath_points)
        ):
            return

        table.blockSignals(True)
        self._points_table_updating = True
        try:
            table.clearSelection()
            item = None
            if secondary is None or secondary < 0:
                row = primary
                table.selectRow(row)
                item = table.item(row, 0)
            else:
                start, end = sorted((primary, secondary))
                for row in range(start, end + 1):
                    table.selectRow(row)
                mid = (start + end) // 2
                item = table.item(mid, 0)
            if item is not None:
                table.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        finally:
            table.blockSignals(False)
            self._points_table_updating = False

        pt = self.toolpath_points[primary]
        self.set_toolpath_info(
            f"Seçim: #{primary+1} | X={pt.x:.3f}, Y={pt.y:.3f}, Z={pt.z:.3f}, A={pt.a:.3f}"
        )

    def _on_table_cell_clicked(self, row: int, _col: int):
        """Tabloda satır seçildiğinde viewer'da ilgili noktayı vurgular."""
        if row is None or row < 0 or row >= len(self.toolpath_points):
            return
        # Tablo üzerinden seçim yapıldığında secondary temizlenir
        self._selected_primary = int(row)
        self._selected_secondary = -1
        self.points_table.selectRow(row)
        if self.viewer is not None:
            self.viewer.set_selected_index(int(row))
        pt = self.toolpath_points[row]
        self.set_toolpath_info(
            f"Seçim: #{row+1} | X={pt.x:.3f}, Y={pt.y:.3f}, Z={pt.z:.3f}, A={pt.a:.3f}"
        )

    def _on_viewer_point_selected(self, index: int, _pt):
        """Viewer'da bir nokta seçildiğinde tablo seçimini günceller."""
        if index is None or index < 0 or index >= len(self.toolpath_points):
            return
        try:
            self.points_table.blockSignals(True)
            self.points_table.selectRow(int(index))
            item = self.points_table.item(int(index), 0)
            if item is not None:
                self.points_table.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        finally:
            self.points_table.blockSignals(False)

    def _update_summary_info(self):
        """
        toolpath_points listesinden özet bilgileri hesaplar ve HUD'u günceller.
        """
        if (
            self.toolpath_points is None
            or len(self.toolpath_points) == 0
            or getattr(self.main_window, "tab_general_info", None) is None
        ):
            gen_tab = getattr(self.main_window, "tab_general_info", None)
            if gen_tab is not None and hasattr(gen_tab, "reset_summary"):
                gen_tab.reset_summary()
            return

        pts = self.toolpath_points
        gen_tab = getattr(self.main_window, "tab_general_info", None)
        if gen_tab is None:
            return

        count = len(pts)
        length = 0.0
        for i in range(1, count):
            dx = pts[i].x - pts[i - 1].x
            dy = pts[i].y - pts[i - 1].y
            dz = pts[i].z - pts[i - 1].z
            length += (dx * dx + dy * dy + dz * dz) ** 0.5

        z_vals = [p.z for p in pts]
        a_vals = [p.a for p in pts]
        z_min, z_max = (min(z_vals), max(z_vals)) if z_vals else (0.0, 0.0)
        a_min, a_max = (min(a_vals), max(a_vals)) if a_vals else (0.0, 0.0)

        feed_xy = None
        settings_tab = getattr(self.main_window, "tab_settings", None)
        if settings_tab is not None:
            feed_xy = getattr(settings_tab, "feed_xy", None)
        try:
            feed_xy = float(feed_xy)
        except Exception:
            feed_xy = None

        est_text = "Tahmini süre: -"
        if feed_xy and feed_xy > 1e-6:
            time_min = length / feed_xy  # dakika
            time_sec = time_min * 60.0
            if time_sec >= 120:
                est_text = f"Tahmini süre: {time_min:.2f} dk"
            else:
                est_text = f"Tahmini süre: {time_sec:.1f} sn"

        if hasattr(gen_tab, "update_summary"):
            gen_tab.update_summary(
                count=count,
                length_mm=length,
                z_min=z_min,
                z_max=z_max,
                a_min=a_min,
                a_max=a_max,
                est_text=est_text,
            )

    # --------------------------------------------------
    # Dışa aktarma
    # --------------------------------------------------
    def update_gcode_text(self):
        """Varsa G-kod metin alanını günceller."""
        widget = getattr(self, "gcode_text_edit", None)
        if widget is None:
            return
        try:
            text = self.gcode_lines
            if isinstance(self.gcode_lines, list):
                text = "\n".join(self.gcode_lines)
            widget.setPlainText(text or "")
        except Exception:
            return

    def on_save_points_clicked(self):
        if not self.toolpath_points:
            QMessageBox.warning(self, "Noktaları Kaydet", "Önce bir takım yolu oluşturun.")
            return

        filters = "CSV dosyası (*.csv);;JSON dosyası (*.json)"
        filename, selected_filter = QFileDialog.getSaveFileName(self, "Noktaları Kaydet", "", filters)
        if not filename:
            return

        selected_filter = (selected_filter or "").lower()
        lower_name = filename.lower()
        ext = None
        if lower_name.endswith(".csv"):
            ext = "csv"
        elif lower_name.endswith(".json"):
            ext = "json"
        else:
            if "csv" in selected_filter:
                filename += ".csv"
                ext = "csv"
            elif "json" in selected_filter:
                filename += ".json"
                ext = "json"

        if ext == "csv":
            self._save_points_to_csv(filename)
        elif ext == "json":
            self._save_points_to_json(filename)
        else:
            QMessageBox.warning(self, "Noktaları Kaydet", "Desteklenmeyen dosya uzantısı.")

    def _save_points_to_csv(self, filename):
        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["x", "y", "z", "a"])
                for pt in self.toolpath_points:
                    writer.writerow([pt.x, pt.y, pt.z, pt.a])
            self.set_toolpath_info(f"CSV kaydedildi: {filename}")
        except Exception as exc:
            QMessageBox.critical(self, "Noktaları Kaydet", f"CSV kaydedilemedi: {exc}")

    def _save_points_to_json(self, filename):
        data = [{"x": p.x, "y": p.y, "z": p.z, "a": p.a} for p in self.toolpath_points]
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.set_toolpath_info(f"JSON kaydedildi: {filename}")
        except Exception as exc:
            QMessageBox.critical(self, "Noktaları Kaydet", f"JSON kaydedilemedi: {exc}")


    def _write_params_to_settings_tab(self, offset_mm: float, step_mm: float, mode_idx: int):
        tab_settings = getattr(self.main_window, "tab_settings", None)
        if tab_settings is None:
            return
        tab_settings.contour_offset_mm = offset_mm
        tab_settings.z_step_mm = step_mm
        tab_settings.z_mode_index = mode_idx
        # Ayarlar sekmesindeki spinbox'ı da güncel tut
        if hasattr(tab_settings, "spin_contour_offset"):
            try:
                tab_settings.spin_contour_offset.blockSignals(True)
                tab_settings.spin_contour_offset.setValue(offset_mm)
            finally:
                tab_settings.spin_contour_offset.blockSignals(False)
        if hasattr(tab_settings, "spin_z_step"):
            try:
                tab_settings.spin_z_step.blockSignals(True)
                tab_settings.spin_z_step.setValue(step_mm)
            finally:
                tab_settings.spin_z_step.blockSignals(False)
        if hasattr(tab_settings, "combo_z_mode"):
            try:
                tab_settings.combo_z_mode.blockSignals(True)
                tab_settings.combo_z_mode.setCurrentIndex(int(mode_idx))
            finally:
                tab_settings.combo_z_mode.blockSignals(False)

    def _on_params_changed(self, _value=None):
        """Spinbox/combobox değişince değerleri Ayarlar sekmesine yazar."""
        self._write_params_to_settings_tab(
            float(self.offset_spin.value()),
            float(self.step_spin.value()),
            int(self.z_mode_combo.currentIndex()),
        )
        if hasattr(self, "offset_spin") and hasattr(self, "real_offset_spin"):
            try:
                val = float(self.offset_spin.value())
            except Exception:
                val = 0.0
            self.real_offset_spin.blockSignals(True)
            self.real_offset_spin.setValue(-val)
            self.real_offset_spin.blockSignals(False)
        tab_model = getattr(self.main_window, "tab_model", None)
        if tab_model is not None and hasattr(tab_model, "spin_model_offset"):
            tab_model.spin_model_offset.blockSignals(True)
            tab_model.spin_model_offset.setValue(self.offset_spin.value())
            tab_model.spin_model_offset.blockSignals(False)

    def set_contour_offset(self, value: float):
        """Dışarıdan kontur ofsetini ayarlar ve senkron tutar."""
        try:
            self.offset_spin.blockSignals(True)
            self.offset_spin.setValue(float(value))
        finally:
            self.offset_spin.blockSignals(False)
        # Diğer sekmelerle paylaş
        self._on_params_changed()

    def set_step_value(self, value: float):
        """Dışarıdan nokta adımını ayarlar ve sekmeler arası senkron tutar."""
        try:
            self.step_spin.blockSignals(True)
            self.step_spin.setValue(float(value))
        finally:
            self.step_spin.blockSignals(False)
        self._on_params_changed()

    def set_z_mode_index(self, idx: int):
        """Z takip modu indeksini dışarıdan ayarlar ve senkron tutar."""
        try:
            self.z_mode_combo.blockSignals(True)
            self.z_mode_combo.setCurrentIndex(int(idx))
        finally:
            self.z_mode_combo.blockSignals(False)
        self._on_params_changed()

    def _filter_and_compress_issues(self, issues: List[PathIssue]) -> List[PathIssue]:
        """
        analyze_toolpath sonucundaki hataları sadeleştirir:
        - Küçük şiddetli A/Z/Yön değişimlerini filtreler.
        - Birbirine çok yakın ardışık hataları tek bir hata olarak birleştirir.
        """
        if not issues:
            return []

        min_severity = {
            "A_JUMP": 20.0,    # derece
            "Z_SPIKE": 1.0,    # mm
            "DIR_SHARP": 15.0, # derece
        }

        strong: List[PathIssue] = []
        for iss in issues:
            thr = min_severity.get(getattr(iss, "type", None))
            if thr is None:
                strong.append(iss)
            else:
                try:
                    if float(getattr(iss, "severity", 0.0)) >= thr:
                        strong.append(iss)
                except Exception:
                    strong.append(iss)

        if not strong:
            return []

        strong.sort(key=lambda i: i.index)
        compressed: List[PathIssue] = []
        window = 3  # aynı tipte ve index farkı <= 3 ise tek hata kabul et

        for iss in strong:
            if not compressed:
                compressed.append(iss)
                continue

            last = compressed[-1]
            if iss.type == last.type and (iss.index - last.index) <= window:
                if iss.severity > last.severity:
                    compressed[-1] = iss
            else:
                compressed.append(iss)

        return compressed

    def _on_raw_issue_toggle(self):
        """Ham hata gösterimi checkbox'ı değiştiğinde bellekteki ayarı günceller."""
        self.analysis_options["show_raw"] = bool(self.chk_show_raw_issues.isChecked())
        self._refresh_issue_table_from_last()

    def _refresh_issue_table_from_last(self):
        """
        Son issues listesini aktif filtre durumuna göre süzer ve tabloyu yeniler.
        """
        issues = list(self._last_issues) if self._last_issues else []

        # Sadece A hataları filtreliyse
        if self.filter_a_only:
            filtered = []
            for iss in issues:
                issue_type = None
                if hasattr(iss, "type"):
                    issue_type = getattr(iss, "type", None)
                elif isinstance(iss, dict):
                    issue_type = iss.get("issue_type") or iss.get("type")
                if issue_type in ("A_JUMP", "A_ANGLE", "A_ANGLE_JUMP"):
                    filtered.append(iss)
            issues = filtered

        # Mevcut tablo güncelleme fonksiyonunu issues ile besle
        self._issues = issues
        try:
            self._fill_issues_table()
        except Exception:
            logger.exception("TabToolpath beklenmeyen hata")

        # Sayaç güncelle
        if getattr(self, "lbl_issue_count", None) is not None:
            self.lbl_issue_count.setText(f"Toplam hata sayısı: {len(issues)}")

    def on_filter_a_only_toggled(self, checked: bool):
        """
        'Sadece A hataları' butonu tıklandığında çağrılır.
        """
        self.filter_a_only = bool(checked)
        self._refresh_issue_table_from_last()

    def on_show_advanced_analysis_dialog(self):
        """
        Analiz eşiklerini ve Z üst limit kontrolünü kullanıcıya açan küçük bir modal.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle("Gelişmiş Analiz Ayarları")
        form = QFormLayout(dlg)
        form.setSpacing(6)

        spin_a = QDoubleSpinBox()
        spin_a.setDecimals(1)
        spin_a.setRange(0.0, 360.0)
        spin_a.setValue(float(self.analysis_options.get("angle_threshold", 30.0)))
        spin_a.setSuffix(" °")
        form.addRow("A eşiği (ΔA)", spin_a)

        spin_z = QDoubleSpinBox()
        spin_z.setDecimals(3)
        spin_z.setRange(0.0, 50.0)
        spin_z.setValue(float(self.analysis_options.get("z_threshold", 2.0)))
        spin_z.setSuffix(" mm")
        form.addRow("Z eşiği (ΔZ)", spin_z)

        spin_dir = QDoubleSpinBox()
        spin_dir.setDecimals(1)
        spin_dir.setRange(0.0, 180.0)
        spin_dir.setValue(float(self.analysis_options.get("dir_threshold", 30.0)))
        spin_dir.setSuffix(" °")
        form.addRow("Yön değişimi eşiği", spin_dir)

        spin_xy = QDoubleSpinBox()
        spin_xy.setDecimals(3)
        spin_xy.setRange(0.0, 20.0)
        spin_xy.setValue(float(self.analysis_options.get("xy_spike_threshold", 0.3)))
        spin_xy.setSuffix(" mm")
        form.addRow("XY spike eşiği", spin_xy)

        chk_zmax = QCheckBox("Z üst limitini kontrol et (Z_TOO_HIGH)")
        chk_zmax.setChecked(bool(self.analysis_options.get("enable_z_max", False)))
        form.addRow("", chk_zmax)

        chk_raw = QCheckBox("Ham hataları göster (filtreleme kapalı)")
        chk_raw.setChecked(bool(self.analysis_options.get("show_raw", False)))
        form.addRow("", chk_raw)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        form.addRow(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec_() == QDialog.Accepted:
            self.analysis_options["angle_threshold"] = float(spin_a.value())
            self.analysis_options["z_threshold"] = float(spin_z.value())
            self.analysis_options["dir_threshold"] = float(spin_dir.value())
            self.analysis_options["xy_spike_threshold"] = float(spin_xy.value())
            self.analysis_options["enable_z_max"] = bool(chk_zmax.isChecked())
            self.analysis_options["show_raw"] = bool(chk_raw.isChecked())
            try:
                self.chk_show_raw_issues.blockSignals(True)
                self.chk_show_raw_issues.setChecked(self.analysis_options["show_raw"])
            finally:
                self.chk_show_raw_issues.blockSignals(False)

    def on_analyze_path_clicked(self):
        """
        Toolpath üzerindeki olası problemleri analiz eder ve tabloya yazar.
        """
        if not self.toolpath_points:
            self.set_toolpath_info("Analiz için önce takım yolu oluşturmalısınız.")
            if getattr(self, "tbl_issues", None) is not None:
                self.tbl_issues.setRowCount(0)
            self._issues = []
            return

        tab_settings = getattr(self.main_window, "tab_settings", None)
        table_w = getattr(tab_settings, "table_width_mm", None)
        table_h = getattr(tab_settings, "table_height_mm", None)
        z_max = getattr(tab_settings, "safe_z_mm", None)
        if z_max is None:
            z_max = getattr(tab_settings, "safe_z", None)
        z_min = getattr(tab_settings, "z_min_mm", None)
        a_min = getattr(tab_settings, "knife_a_min_deg", None)
        a_max = getattr(tab_settings, "knife_a_max_deg", None)
        opts = self.analysis_options or {}
        show_raw = bool(getattr(self.chk_show_raw_issues, "isChecked", lambda: False)())
        self.analysis_options["show_raw"] = show_raw

        issues: List[PathIssue] = []

        try:
            issues.extend(
                self.pipeline.validate(
                    self.toolpath_points,
                    table_width_mm=table_w,
                    table_height_mm=table_h,
                    z_min_mm=z_min,
                    z_max_mm=z_max,
                    enable_z_max_check=bool(opts.get("enable_z_max", False)),
                    a_min_deg=a_min,
                    a_max_deg=a_max,
                )
            )
        except Exception:
            logger.exception("TabToolpath beklenmeyen hata")

        try:
            angle_threshold = float(opts.get("angle_threshold", 30.0))
            z_threshold = float(opts.get("z_threshold", 2.0))
            dir_threshold = float(opts.get("dir_threshold", 30.0))
            xy_spike_threshold = float(opts.get("xy_spike_threshold", 0.3))

            raw_issues = self.pipeline.analyze(
                self.toolpath_points,
                angle_threshold_deg=angle_threshold,
                z_threshold_mm=z_threshold,
                dir_threshold_deg=dir_threshold,
                xy_spike_threshold_mm=xy_spike_threshold,
            )
            if show_raw:
                issues.extend(raw_issues)
            else:
                issues.extend(self._filter_and_compress_issues(raw_issues))
        except Exception:
            logger.exception("TabToolpath beklenmeyen hata")

        # Son analiz sonucunu sakla (filtrelenmiş ya da ham, kullanıcının seçimine göre)
        self._issues = issues
        self._last_issues = list(issues) if issues else []
        if self.state is not None and self.state.toolpath_result is not None:
            self.state.toolpath_result.issues = list(issues)  # NOTE: Store analysis in result.
        if self.viewer is not None and hasattr(self.viewer, "set_issue_indices"):
            indices = [iss.index for iss in self._issues]
            self.viewer.set_issue_indices(indices)
        # Tabloyu aktif filtre durumuna göre yenile
        self._refresh_issue_table_from_last()

        if not self._issues:
            self.set_toolpath_info("Herhangi bir problem tespit edilmedi.")
            return

        self.set_toolpath_info(f"{len(self._issues)} adet olası problem tespit edildi.")
        if getattr(self, "tbl_issues", None) is not None and self.tbl_issues.rowCount() > 0:
            self.tbl_issues.blockSignals(True)
            try:
                self.tbl_issues.selectRow(0)
            finally:
                self.tbl_issues.blockSignals(False)
        try:
            self.on_issue_row_clicked(0, 0)
        except Exception:
            logger.exception("TabToolpath beklenmeyen hata")

    def _fill_issues_table(self):
        """
        self._issues listesini self.tbl_issues tablosuna yazar.
        Sütunlar:
          0: # (nokta index + 1)
          1: Tip (A açısı / Z dalgalanması / Keskin yön)
          2: Açıklama (PathIssue.description)
        """
        if self.tbl_issues is None:
            return

        self.tbl_issues.blockSignals(True)
        try:
            self.tbl_issues.clearContents()
            self.tbl_issues.setRowCount(0)
            # Son tablo verisini sakla (filtre öncesi liste)
            self._last_issues = list(self._issues) if self._issues else []

            if getattr(self, "lbl_issue_count", None) is not None:
                self.lbl_issue_count.setText(f"Toplam hata sayısı: {len(self._issues) if self._issues else 0}")

            if not self._issues:
                return

            self.tbl_issues.setColumnCount(3)
            self.tbl_issues.setHorizontalHeaderLabels(["#", "Tip", "Açıklama"])
            self.tbl_issues.setRowCount(len(self._issues))

            for row, issue in enumerate(self._issues):
                idx_value = issue.index + 1
                item_idx = QTableWidgetItem(str(idx_value))
                item_idx.setFlags(item_idx.flags() & ~Qt.ItemIsEditable)
                self.tbl_issues.setItem(row, 0, item_idx)

                if issue.type == "A_JUMP":
                    tip_text = "A açısı"
                elif issue.type == "Z_SPIKE":
                    tip_text = "Z dalgalanması"
                elif issue.type == "DIR_SHARP":
                    tip_text = "Keskin yön"
                else:
                    tip_text = issue.type
                item_type = QTableWidgetItem(tip_text)
                item_type.setFlags(item_type.flags() & ~Qt.ItemIsEditable)
                self.tbl_issues.setItem(row, 1, item_type)

                desc = issue.description or ""
                if not desc:
                    if issue.type == "A_JUMP":
                        desc = "A ekseninde ani açı değişimi"
                    elif issue.type == "Z_SPIKE":
                        desc = "Z ekseninde ani yükseklik değişimi"
                    elif issue.type == "DIR_SHARP":
                        desc = "XY düzleminde keskin yön değişimi"
                    else:
                        desc = "Tanımsız problem"

                item_desc = QTableWidgetItem(desc)
                item_desc.setFlags(item_desc.flags() & ~Qt.ItemIsEditable)
                item_desc.setToolTip(desc)
                self.tbl_issues.setItem(row, 2, item_desc)

            self.tbl_issues.resizeColumnsToContents()
            if self.tbl_issues.columnWidth(2) < 250:
                self.tbl_issues.setColumnWidth(2, 250)
        finally:
            self.tbl_issues.blockSignals(False)

    def on_issue_row_clicked(self, row: int, column: int):
        """
        Sorunlar tablosunda bir satıra tıklanınca ilgili noktayı seçer.
        """
        if row is None or row < 0 or row >= len(self._issues):
            return

        issue = self._issues[row]
        idx = issue.index
        if idx < 0 or idx >= len(self.toolpath_points):
            return

        try:
            self.set_toolpath_info(issue.description)
        except Exception:
            logger.exception("TabToolpath beklenmeyen hata")

        if self.points_table is not None:
            self.points_table.blockSignals(True)
            try:
                self.points_table.clearSelection()
                self.points_table.selectRow(idx)
            finally:
                self.points_table.blockSignals(False)

        if self.viewer is not None:
            try:
                self.viewer.set_selected_index(idx)
            except Exception:
                logger.exception("TabToolpath beklenmeyen hata")
            try:
                p = self.toolpath_points[idx]
                if hasattr(self.viewer, "set_focus_point"):
                    # Merkeze getirirken zoom'u koru
                    self.viewer.set_focus_point(float(p.x), float(p.y), float(p.z), auto_zoom=False)
            except Exception:
                logger.exception("TabToolpath beklenmeyen hata")

    def _recompute_a_for_points(self, points, knife_offset_deg: float = 0.0):
        """
        Verilen ToolpathPoint listesindeki X/Y/Z'e göre A açılarını yeniden hesaplar.
        Tangente göre açı bulur, wrap/unwrap ile sürekliliği korur, isteğe bağlı offset ekler.
        """
        if not points or len(points) < 2:
            return
        # NOTE: A offset/reverse settings are applied in addition to knife offset.
        settings_tab = getattr(self.main_window, "tab_settings", None)
        try:
            extra_offset = float(
                getattr(
                    settings_tab,
                    "A_OFFSET_DEG",
                    getattr(settings_tab, "a_offset_deg", getattr(settings_tab, "a_deg_offset", 0.0)),
                )
            )
        except Exception:
            extra_offset = 0.0
        a_reverse = bool(getattr(settings_tab, "A_REVERSE", getattr(settings_tab, "a_reverse", 0)))
        total_offset = float(knife_offset_deg) + float(extra_offset)
        contact_enabled = bool(getattr(settings_tab, "knife_contact_offset_enabled", 0)) if settings_tab is not None else False
        contact_side = int(getattr(settings_tab, "knife_contact_side", getattr(settings_tab, "kerf_side", 1))) if settings_tab is not None else 1
        try:
            contact_d_min = float(getattr(settings_tab, "knife_contact_d_min_mm", 0.3))
        except Exception:
            contact_d_min = 0.3
        radius = _get_blade_radius_mm(settings_tab)
        contact_enabled = contact_enabled and radius > 0.0

        prev_angle = None
        n = len(points)

        for i, p in enumerate(points):
            if n == 1:
                dx, dy = 1.0, 0.0
            elif i == 0:
                dx = points[1].x - points[0].x
                dy = points[1].y - points[0].y
            elif i == n - 1:
                dx = points[-1].x - points[-2].x
                dy = points[-1].y - points[-2].y
            else:
                dx = points[i + 1].x - points[i - 1].x
                dy = points[i + 1].y - points[i - 1].y

            if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                if prev_angle is not None:
                    p.a = prev_angle
                continue

            base_angle = math.degrees(math.atan2(dy, dx))
            if contact_enabled:
                sign = 1.0 if contact_side >= 0 else -1.0
                z_val = float(getattr(p, "z", 0.0))
                depth = max(0.0, min(-z_val, radius)) if radius > 0 else 0.0
                d_sq = max(0.0, radius * radius - (radius - depth) ** 2) if radius > 0 else 0.0
                d = math.sqrt(d_sq) if radius > 0 else 0.0
                normal_angle = base_angle + (90.0 * sign)
                if d < contact_d_min and prev_angle is not None:
                    normal_angle = prev_angle
                base_angle = normal_angle

            if prev_angle is None:
                angle = base_angle
            else:
                diff = base_angle - prev_angle
                while diff > 180.0:
                    diff -= 360.0
                while diff < -180.0:
                    diff += 360.0
                angle = prev_angle + diff

            p.a = angle
            prev_angle = angle

        try:
            angles = np.array([p.a for p in points], dtype=np.float64)
            angles_rad = np.deg2rad(angles)
            angles_unwrapped = np.unwrap(angles_rad)
            angles_deg = np.rad2deg(angles_unwrapped)

            if A_SMOOTH_WINDOW and A_SMOOTH_WINDOW > 1:
                window = int(max(1, A_SMOOTH_WINDOW))
                kernel = np.ones(window, dtype=np.float64) / float(window)
                angles_deg = np.convolve(angles_deg, kernel, mode="same")

            if A_MAX_STEP_DEG is not None:
                max_step = float(A_MAX_STEP_DEG)
                for i in range(1, len(angles_deg)):
                    delta = angles_deg[i] - angles_deg[i - 1]
                    if delta > max_step:
                        angles_deg[i] = angles_deg[i - 1] + max_step
                    elif delta < -max_step:
                        angles_deg[i] = angles_deg[i - 1] - max_step

            for p, ang in zip(points, angles_deg):
                adj = float(ang) + total_offset
                if a_reverse:
                    adj += 180.0
                p.a = adj
        except Exception:
            logger.exception("A açısı stabilizasyonu uygulanamadı")

    def apply_toolpath_style_from_settings(
        self,
        color_hex: str,
        width_px: float,
        point_color_hex: Optional[str] = None,
        point_size_px: Optional[float] = None,
        first_point_hex: Optional[str] = None,
        second_point_hex: Optional[str] = None,
    ):
        """Ayarlar sekmesinden gelen yol / nokta stilini uygular."""
        if self.viewer is not None:
            self.viewer.set_toolpath_style(
                color_hex,
                width_px,
                point_color_hex=point_color_hex,
                point_size_px=point_size_px,
                first_point_hex=first_point_hex,
                second_point_hex=second_point_hex,
            )

    def _on_points_item_changed(self, item: QTableWidgetItem):
        """
        Nokta Listesi'nde X/Y/Z/A hücresi değiştiğinde veriyi ve viewer'ı günceller.
        """
        if self._points_table_updating:
            return
        if item is None or self.toolpath_points is None:
            return

        row = item.row()
        col = item.column()
        if row < 0 or row >= len(self.toolpath_points):
            return

        if col == 0:
            self._points_table_updating = True
            try:
                item.setText(str(row + 1))
            finally:
                self._points_table_updating = False
            return

        if col not in (1, 2, 3, 4):
            return

        text = (item.text() or "").strip().replace(",", ".")
        try:
            val = float(text)
        except ValueError:
            p = self.toolpath_points[row]
            old = [p.x, p.y, p.z, p.a][col - 1]
            self._points_table_updating = True
            try:
                item.setText(f"{old:.3f}")
            finally:
                self._points_table_updating = False
            self.set_toolpath_info("Geçersiz sayı girdiniz.")
            return

        if getattr(self, "edit_mode", False) and hasattr(self, "_push_history"):
            self._push_history("table_edit")

        p = self.toolpath_points[row]
        if col == 1:
            p.x = val
        elif col == 2:
            p.y = val
        elif col == 3:
            p.z = val
        elif col == 4:
            p.a = val

        if self.viewer is not None and self.toolpath_points:
            pts_arr = np.array([[tp.x, tp.y, tp.z] for tp in self.toolpath_points], dtype=np.float32)
            self.viewer.set_toolpath_polyline(pts_arr)

        if hasattr(self, "_update_summary_info"):
            self._update_summary_info()

        self.set_toolpath_info(f"Satır {row + 1} güncellendi (sütun {col}).")

    def focus_selected_point(self):
        """Se?ili noktan?n merkezine kameray? odaklar."""
        idx = self.points_table.currentRow() if self.points_table is not None else -1
        if idx is None or idx < 0 or self.toolpath_points is None or idx >= len(self.toolpath_points):
            QMessageBox.information(self, TITLE_TOOLPATH, MSG_SELECT_POINT_FIRST)
            return
        p = self.toolpath_points[idx]
        try:
            if hasattr(self.viewer, "focus_point"):
                self.viewer.focus_point(float(p.x), float(p.y), float(p.z), keep_distance=True)
            elif hasattr(self.viewer, "set_focus_point"):
                self.viewer.set_focus_point(float(p.x), float(p.y), float(p.z), auto_zoom=False)
        except Exception:
            logger.exception("Kamera odaklama ba?ar?s?z")

    def zoom_selected_point(self):
        """Se?ili noktaya do?ru yak?nla??r."""
        idx = self.points_table.currentRow() if self.points_table is not None else -1
        if idx is None or idx < 0 or self.toolpath_points is None or idx >= len(self.toolpath_points):
            QMessageBox.information(self, TITLE_TOOLPATH, MSG_SELECT_POINT_FIRST)
            return
        try:
            if hasattr(self.viewer, "zoom_towards_point"):
                self.viewer.zoom_towards_point()
            elif hasattr(self.viewer, "set_zoom"):
                self.viewer.set_zoom(max(10.0, getattr(self.viewer, "dist", 100.0) * 0.85))
        except Exception:
            logger.exception("Kamera zoom ba?ar?s?z")

    def fit_all_camera(self):
        """Kameray? varsay?lan konuma getirir."""
        try:
            if hasattr(self.viewer, "fit_all"):
                self.viewer.fit_all()
            elif hasattr(self.viewer, "reset_camera"):
                self.viewer.reset_camera()
        except Exception:
            logger.exception("Kamera reset ba?ar?s?z")
