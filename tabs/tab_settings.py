# tabs/tab_settings.py
# ----------------------------------------------------------
# "Ayarlar" sekmesi
# - Tabla (makine yatağı) ayarları
# - G54 orjin seçimi
# - Renkler (zemin, arka plan, STL)
# - Zemin (Tabla) için "Dolu" checkbox'ı (sadece grid modu)
# - Takım / İlerleme ayarları (SAFE_Z, Feed XY, Feed Z)
# - Bıçak Seçimi (liste + boy / uç çapı / gövde çapı / açı) + 3B önizleme
# ----------------------------------------------------------

import os
import re
import configparser
import logging

from core.config_reader import get_cfg_value
from core.knife_catalog import KnifeDef, load_catalog
from core.knife_spec import build_knife_spec, normalize_profile
from core.path_utils import find_or_create_config
from core.result import Result, WarningItem
from core.tool_library import load_active_tool_no, load_tool, save_active_tool_no, save_tool
from core.warnings import warnings_summary, warnings_to_multiline_text

from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QFormLayout,
    QDoubleSpinBox,
    QSpinBox,
    QComboBox,
    QLabel,
    QPushButton,
    QLineEdit,
    QColorDialog,
    QCheckBox,
    QSizePolicy,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QMessageBox,
    QToolTip,
)
from PyQt5.QtCore import Qt, QEvent, QSize, QUrl, QRect, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QCursor, QFontMetrics, QIcon, QPainter, QPalette, QPixmap

from widgets.knife_preview_3d import KnifePreview3DWidget

INI_PATH, TOOL_INI_PATH = [str(p) for p in find_or_create_config()]
logger = logging.getLogger(__name__)


class ColorLineEdit(QLineEdit):
    def __init__(self, default_hex="#ffffff", parent=None):
        super().__init__(parent)
        self.setText(default_hex)
        self.set_max_visual()
        self.setFont(QFont("Consolas", 9))
        self.setReadOnly(False)

    def mousePressEvent(self, event):
        current_hex = self.text().strip()
        col = QColor(current_hex) if QColor(current_hex).isValid() else QColor("#ffffff")
        new_col = QColorDialog.getColor(col, self, "Renk Seç")
        if new_col.isValid():
            hex_str = new_col.name().lower()
            self.setText(hex_str)
            self.set_max_visual()

    def set_max_visual(self):
        hex_str = self.text().strip()
        col = QColor(hex_str) if QColor(hex_str).isValid() else QColor("#ffffff")
        r, g, b = col.red(), col.green(), col.blue()
        luminance = (0.299 * r + 0.587 * g + 0.114 * b)
        text_color = "#000000" if luminance > 160 else "#ffffff"
        self.setStyleSheet(
            "QLineEdit { "
            f"background-color: {col.name()}; "
            f"color: {text_color}; "
            "border: 1px solid #808080; "
            "}"
        )


class KnifeCatalogDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)

        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        opt.text = ""
        opt.icon = QIcon()
        bg_role = QPalette.Highlight if (opt.state & QStyle.State_Selected) else QPalette.Base
        bg = QColor(opt.palette.color(bg_role))
        if bg.alpha() < 255:
            bg.setAlpha(255)
        painter.save()
        painter.fillRect(opt.rect, bg)
        painter.restore()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        rect = opt.rect
        icon = index.data(Qt.DecorationRole)
        icon_size = opt.decorationSize if opt.decorationSize.isValid() else QSize(32, 32)
        icon_rect = rect.adjusted(4, 2, -4, -2)
        icon_rect.setWidth(icon_size.width())
        icon_rect.setHeight(icon_size.height())
        icon_rect.moveTop(rect.top() + (rect.height() - icon_size.height()) // 2)
        if isinstance(icon, QIcon):
            icon.paint(painter, icon_rect, Qt.AlignCenter)

        text_left = icon_rect.right() + 8
        text_rect = rect.adjusted(text_left - rect.left(), 2, -6, -2)

        title = index.data(Qt.DisplayRole) or ""
        meta = index.data(Qt.UserRole + 1) or ""
        title_font = QFont(opt.font)
        title_font.setBold(True)
        meta_font = QFont(opt.font)
        meta_font.setPointSize(max(7, meta_font.pointSize() - 1))

        title_metrics = QFontMetrics(title_font)
        meta_metrics = QFontMetrics(meta_font)
        title_rect = QRect(text_rect)
        title_rect.setHeight(title_metrics.height())
        meta_rect = QRect(text_rect)
        meta_rect.setTop(title_rect.bottom() + 2)
        meta_rect.setHeight(meta_metrics.height())

        if opt.state & QStyle.State_Selected:
            title_color = QColor(opt.palette.color(QPalette.Active, QPalette.HighlightedText))
            meta_color = QColor(title_color)
        else:
            title_color = QColor(opt.palette.color(QPalette.Active, QPalette.Text))
            meta_color = QColor(title_color)
            meta_color = meta_color.darker(130)
        title_color.setAlpha(255)
        meta_color.setAlpha(255)

        painter.save()
        painter.setFont(title_font)
        painter.setPen(title_color)
        painter.drawText(
            title_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            title_metrics.elidedText(title, Qt.ElideRight, title_rect.width()),
        )
        painter.setFont(meta_font)
        painter.setPen(meta_color)
        painter.drawText(
            meta_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            meta_metrics.elidedText(meta, Qt.ElideRight, meta_rect.width()),
        )
        painter.restore()

    def sizeHint(self, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        title_font = QFont(opt.font)
        title_font.setBold(True)
        meta_font = QFont(opt.font)
        meta_font.setPointSize(max(7, meta_font.pointSize() - 1))
        title_metrics = QFontMetrics(title_font)
        meta_metrics = QFontMetrics(meta_font)
        height = title_metrics.height() + meta_metrics.height() + 8
        icon_height = opt.decorationSize.height() if opt.decorationSize.isValid() else 32
        return QSize(opt.rect.width(), max(height, icon_height + 6))


class TabSettings(QWidget):
    settings_changed = pyqtSignal(float, float, str, str, str, str, bool)

    def __init__(self, main_window, state):
        super().__init__(main_window)
        self.main_window = main_window
        self.state = state

        # Tabla
        self.table_width_mm = 800.0
        self.table_height_mm = 400.0
        self.origin_mode = "center"
        self.show_table_fill = True

        # Toolpath
        self.safe_z = 10.0
        self.feed_xy = 2000.0
        self.feed_z = 500.0
        self.toolpath_color_hex = "#ff0000"
        self.toolpath_width_px = 2.0
        # Makine park (G53)
        self.use_g53_park = True
        self.g53_park_x = 0.0
        self.g53_park_y = 0.0
        self.g53_park_z = 0.0
        self.g53_park_a = None
        # Spindle
        self.spindle_enabled = False
        self.spindle_use_s = False
        self.spindle_rpm = 10000.0
        self.spindle_on_mcode = "M3"
        self.spindle_off_mcode = "M5"
        self.spindle_emit_off_at_end = False
        # Nokta stil ayarları
        self.point_color_hex = "#ffff00"      # genel nokta rengi
        self.point_size_px = self.toolpath_width_px * 2.0
        self.point_primary_hex = "#ff0000"    # 1. nokta + hatalı noktalar
        self.point_secondary_hex = "#00ff00"  # 2. nokta
        # Kamera
        self.orbit_sensitivity = 0.3
        self.pan_sensitivity = 0.005
        self.zoom_sensitivity = 1.1
        self.camera_dist = 1452.0
        self.camera_rot_x = 0.0
        self.camera_rot_y = 0.0
        self.feed_xy_mm_min = self.feed_xy
        self.feed_z_mm_min = self.feed_z
        self.feed_travel_mm_min = 4000.0
        self.safe_z_mm = self.safe_z
        self.spindle_on_cmd = "M3"
        self.spindle_off_cmd = "M5"

        # Z-takipli takım yolu
        self.contour_offset_mm = 0.0
        self.z_step_mm = 0.5
        self.z_mode_index = 0
        # A ekseni ayarları (UI yok, sadece ini)
        self.a_offset_deg = 0.0
        self.a_reverse = 0
        self.a_source_mode = "2d_tangent"
        self.a_pivot_enable = 1
        self.a_pivot_r_mm = 2.0
        self.a_pivot_steps = 12
        self.a_corner_threshold_deg = 25.0
        # Bıçak temas ofseti (UI yok, sadece ini)
        self.knife_contact_offset_enabled = 0
        self.knife_contact_side = 1
        self.knife_contact_d_min_mm = 0.3

        # Bıçak
        self.knife_names = []
        self.current_knife_name = ""
        self.knife_length = 30.0
        self.knife_tip_diam = 0.30
        self.knife_body_diam = 3.00
        self.knife_angle_deg = 0.0
        self.knife_profile = "scalpel_pointed"
        self.knife_direction_axis = "x"
        self.knife_thickness_mm = 1.0
        self.knife_cut_length_mm = 10.0
        self.knife_disk_thickness_mm = 2.0
        self.active_tool_no = 1
        self.knife_catalog = []
        self.knife_defs_by_id = {}
        self._knife_tooltip_index = -1
        self._loading_tool = False
        self._knife_ground_visible = True

        self.blade_preview = None

        self._build_ui()
        self.settings_result = self._load_from_ini()
        self.settings_warnings = self.settings_result.warnings
        self._update_settings_warnings_ui()
        if self.settings_warnings:
            logger.warning("Settings loaded with warnings: %s", warnings_summary(self.settings_warnings))
        else:
            logger.info("Settings loaded without warnings")
        if not self.settings_result.ok and self.settings_result.error:
            self.label_status.setText(str(self.settings_result.error))

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(6, 6, 6, 6)
        root_layout.setSpacing(6)

        title = QLabel("Genel Ayarlar")
        title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        root_layout.addWidget(title)

        # --- Makine & Koordinat ---
        grp_table = QGroupBox("Makine & Koordinat")
        grp_table.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        form = QFormLayout(grp_table)
        form.setContentsMargins(6, 6, 6, 6)
        form.setLabelAlignment(Qt.AlignLeft)
        form.setVerticalSpacing(4)

        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(10.0, 5000.0)
        self.spin_width.setDecimals(1)
        self.spin_width.setSingleStep(10.0)

        self.spin_height = QDoubleSpinBox()
        self.spin_height.setRange(10.0, 5000.0)
        self.spin_height.setDecimals(1)
        self.spin_height.setSingleStep(10.0)

        self.combo_origin = QComboBox()
        self.origin_options = [
            ("Orta (G54 merkez)", "center"),
            ("Sol Alt (X min, Y min)", "front_left"),
            ("Sağ Alt (X max, Y min)", "front_right"),
            ("Sol Üst (X min, Y max)", "back_left"),
            ("Sağ Üst (X max, Y max)", "back_right"),
        ]
        for text, _code in self.origin_options:
            self.combo_origin.addItem(text)

        form.addRow("Tabla Genişliği X (mm):", self.spin_width)
        form.addRow("Tabla Derinliği Y (mm):", self.spin_height)
        form.addRow("G54 Orjini:", self.combo_origin)

        self.spin_safe_z = QDoubleSpinBox()
        self.spin_safe_z.setRange(0.0, 200.0)
        self.spin_safe_z.setDecimals(2)
        self.spin_safe_z.setSingleStep(1.0)
        self.spin_safe_z.setValue(self.safe_z)
        form.addRow("SAFE_Z (mm):", self.spin_safe_z)

        self.combo_z_mode = QComboBox()
        self.combo_z_mode.addItems(
            ["A - Üst yüzey (max Z)", "B - Orta (min+max)/2", "C - Alt yüzey (min Z)"]
        )
        form.addRow("Z Takip Yöntemi:", self.combo_z_mode)

        # --- Toolpath ---
        grp_tool = QGroupBox("Takım & İlerleme")
        grp_tool.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        tool_form = QFormLayout(grp_tool)
        tool_form.setContentsMargins(6, 6, 6, 6)
        tool_form.setLabelAlignment(Qt.AlignLeft)
        tool_form.setVerticalSpacing(4)

        self.spin_feed_xy = QDoubleSpinBox()
        self.spin_feed_xy.setRange(1.0, 50000.0)
        self.spin_feed_xy.setDecimals(2)
        self.spin_feed_xy.setSingleStep(100.0)
        self.spin_feed_xy.setValue(self.feed_xy)
        tool_form.addRow("Feed XY (mm/dk):", self.spin_feed_xy)

        self.spin_feed_z = QDoubleSpinBox()
        self.spin_feed_z.setRange(1.0, 50000.0)
        self.spin_feed_z.setDecimals(2)
        self.spin_feed_z.setSingleStep(50.0)
        self.spin_feed_z.setValue(self.feed_z)
        tool_form.addRow("Feed Z (mm/dk):", self.spin_feed_z)

        # Spindle ayarları
        self.chk_spindle_enabled = QCheckBox("Spindle (M3) aktif")
        self.chk_spindle_use_s = QCheckBox("S (RPM) yaz")
        self.chk_spindle_emit_off = QCheckBox("Bitişte M5 yaz")
        spindle_row = QHBoxLayout()
        spindle_row.setContentsMargins(0, 0, 0, 0)
        spindle_row.setSpacing(6)
        spindle_row.addWidget(self.chk_spindle_enabled)
        spindle_row.addWidget(self.chk_spindle_use_s)
        spindle_row.addWidget(self.chk_spindle_emit_off)
        spindle_row.addStretch(1)
        tool_form.addRow("Spindle:", spindle_row)

        self.spin_spindle_rpm = QDoubleSpinBox()
        self.spin_spindle_rpm.setRange(0.0, 100000.0)
        self.spin_spindle_rpm.setDecimals(0)
        self.spin_spindle_rpm.setSingleStep(100.0)
        tool_form.addRow("Spindle RPM:", self.spin_spindle_rpm)

        self.edit_spindle_on = QLineEdit(self.spindle_on_mcode)
        self.edit_spindle_off = QLineEdit(self.spindle_off_mcode)
        tool_form.addRow("M3 Kodu:", self.edit_spindle_on)
        tool_form.addRow("M5 Kodu:", self.edit_spindle_off)

        # Z-takipli takım yolu ayarları
        self.spin_contour_offset = QDoubleSpinBox()
        self.spin_contour_offset.setRange(-5.0, 5.0)
        self.spin_contour_offset.setDecimals(2)
        self.spin_contour_offset.setSingleStep(0.1)
        tool_form.addRow("Kontur Ofseti (mm):", self.spin_contour_offset)

        self.spin_z_step = QDoubleSpinBox()
        self.spin_z_step.setRange(0.01, 10.0)
        self.spin_z_step.setDecimals(3)
        self.spin_z_step.setSingleStep(0.01)
        tool_form.addRow("Nokta Adımı (mm):", self.spin_z_step)

        # --- Renkler ---
        grp_colors = QGroupBox("Görsel & Kamera")
        colors_layout = QFormLayout(grp_colors)
        colors_layout.setContentsMargins(6, 6, 6, 6)
        colors_layout.setLabelAlignment(Qt.AlignLeft)
        colors_layout.setVerticalSpacing(4)

        self.edit_table_color = ColorLineEdit("#ffff7f")
        self.chk_table_fill = QCheckBox("Dolu")
        self.chk_table_fill.setChecked(True)

        row_table = QHBoxLayout()
        row_table.addWidget(self.edit_table_color, 1)
        row_table.addWidget(self.chk_table_fill)

        colors_layout.addRow("Zemin (Tabla) rengi:", row_table)

        self.edit_bg_color = ColorLineEdit("#e6e6eb")
        colors_layout.addRow("Arka plan rengi:", self.edit_bg_color)

        self.edit_stl_color = ColorLineEdit("#ff6699")
        colors_layout.addRow("STL rengi:", self.edit_stl_color)

        self.spin_cam_orbit = QDoubleSpinBox()
        self.spin_cam_orbit.setRange(0.01, 5.0)
        self.spin_cam_orbit.setDecimals(3)
        self.spin_cam_orbit.setSingleStep(0.01)
        colors_layout.addRow("Orbit hassasiyeti:", self.spin_cam_orbit)

        self.spin_cam_pan = QDoubleSpinBox()
        self.spin_cam_pan.setRange(0.0001, 0.5)
        self.spin_cam_pan.setDecimals(4)
        self.spin_cam_pan.setSingleStep(0.0005)
        colors_layout.addRow("Pan hassasiyeti:", self.spin_cam_pan)

        self.spin_cam_zoom = QDoubleSpinBox()
        self.spin_cam_zoom.setRange(1.01, 3.0)
        self.spin_cam_zoom.setDecimals(3)
        self.spin_cam_zoom.setSingleStep(0.01)
        colors_layout.addRow("Zoom oranı:", self.spin_cam_zoom)

        self.spin_cam_dist = QDoubleSpinBox()
        self.spin_cam_dist.setRange(10.0, 10000.0)
        self.spin_cam_dist.setDecimals(1)
        self.spin_cam_dist.setSingleStep(10.0)
        colors_layout.addRow("Başlangıç mesafesi:", self.spin_cam_dist)

        self.spin_cam_rx = QDoubleSpinBox()
        self.spin_cam_rx.setRange(-180.0, 180.0)
        self.spin_cam_rx.setDecimals(1)
        self.spin_cam_rx.setSingleStep(1.0)
        colors_layout.addRow("Başlangıç Rx (°):", self.spin_cam_rx)

        self.spin_cam_ry = QDoubleSpinBox()
        self.spin_cam_ry.setRange(-180.0, 180.0)
        self.spin_cam_ry.setDecimals(1)
        self.spin_cam_ry.setSingleStep(1.0)
        colors_layout.addRow("Başlangıç Ry (°):", self.spin_cam_ry)

        grp_colors.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        self.grp_general_settings = grp_table
        self.grp_color_settings = grp_colors

        # --- Bıçak Seçimi ---
        grp_knife = QGroupBox("Bıçak Seçimi")
        grp_knife.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        grp_knife_layout = QVBoxLayout(grp_knife)
        grp_knife_layout.setContentsMargins(6, 6, 6, 6)
        grp_knife_layout.setSpacing(4)

        knife_form = QFormLayout()
        knife_form.setContentsMargins(0, 0, 0, 0)
        knife_form.setLabelAlignment(Qt.AlignLeft)
        knife_form.setVerticalSpacing(4)

        self.spin_tool_no = QSpinBox()
        self.spin_tool_no.setRange(1, 99)
        self.spin_tool_no.setSingleStep(1)
        self.spin_tool_no.setValue(self.active_tool_no)
        knife_form.addRow("Tak?m Numaras?:", self.spin_tool_no)

        self.combo_knife = QComboBox()
        self.combo_knife.setIconSize(QSize(32, 32))
        self.combo_knife.setItemDelegate(KnifeCatalogDelegate(self.combo_knife))
        self.combo_knife.view().setMouseTracking(True)
        self.combo_knife.view().viewport().installEventFilter(self)

        self.combo_knife_profile = QComboBox()
        self.combo_knife_profile.addItem("Scalpel (Sivri)", "scalpel_pointed")
        self.combo_knife_profile.addItem("Scalpel (Yuvarlak)", "scalpel_rounded")
        self.combo_knife_profile.addItem("Döner Disk", "rotary_disk")
        knife_form.addRow("Profil:", self.combo_knife_profile)

        self.combo_knife_direction = QComboBox()
        self.combo_knife_direction.addItem("X'e paralel", "x")
        self.combo_knife_direction.addItem("Y'ye paralel", "y")
        knife_form.addRow("Bıçak Yönü:", self.combo_knife_direction)

        self.spin_knife_thickness = QDoubleSpinBox()
        self.spin_knife_thickness.setRange(0.1, 10.0)
        self.spin_knife_thickness.setDecimals(2)
        self.spin_knife_thickness.setSingleStep(0.1)
        knife_form.addRow("Bıçak Kalınlığı (mm):", self.spin_knife_thickness)

        self.spin_knife_cut_length = QDoubleSpinBox()
        self.spin_knife_cut_length.setRange(0.1, 500.0)
        self.spin_knife_cut_length.setDecimals(2)
        self.spin_knife_cut_length.setSingleStep(0.5)
        knife_form.addRow("Kesme Boyu (mm):", self.spin_knife_cut_length)

        self.spin_disk_thickness = QDoubleSpinBox()
        self.spin_disk_thickness.setRange(0.1, 20.0)
        self.spin_disk_thickness.setDecimals(2)
        self.spin_disk_thickness.setSingleStep(0.1)
        knife_form.addRow("Disk Kalınlığı (mm):", self.spin_disk_thickness)

        self.spin_knife_length = QDoubleSpinBox()
        self.spin_knife_length.setRange(1.0, 500.0)
        self.spin_knife_length.setDecimals(2)
        self.spin_knife_length.setSingleStep(1.0)
        knife_form.addRow("Bıçak Boyu (mm):", self.spin_knife_length)

        self.spin_knife_tip = QDoubleSpinBox()
        self.spin_knife_tip.setRange(0.01, 20.0)
        self.spin_knife_tip.setDecimals(3)
        self.spin_knife_tip.setSingleStep(0.05)
        knife_form.addRow("Kesici Ağız Çapı (mm):", self.spin_knife_tip)

        self.spin_knife_body = QDoubleSpinBox()
        self.spin_knife_body.setRange(0.5, 50.0)
        self.spin_knife_body.setDecimals(3)
        self.spin_knife_body.setSingleStep(0.1)
        knife_form.addRow("Bıçak Gövde Çapı (mm):", self.spin_knife_body)

        # Yeni: Açı
        self.spin_knife_angle = QDoubleSpinBox()
        self.spin_knife_angle.setRange(-180.0, 180.0)
        self.spin_knife_angle.setDecimals(1)
        self.spin_knife_angle.setSingleStep(5.0)
        knife_form.addRow("Bıçak Açısı (° / A0):", self.spin_knife_angle)

        grp_knife_layout.addLayout(knife_form)

        self.blade_preview = KnifePreview3DWidget(self)
        self.blade_preview.setMinimumSize(480, 480)
        self.blade_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.btn_toggle_knife_ground = QPushButton("Zemin Gizle")
        self.btn_toggle_knife_ground.setCheckable(True)
        self.btn_toggle_knife_ground.setChecked(True)
        self.btn_toggle_knife_ground.clicked.connect(self._toggle_knife_ground)

        grp_knife_preview = QGroupBox("Bıçak Görünümü")
        grp_knife_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        knife_preview_layout = QVBoxLayout(grp_knife_preview)
        knife_preview_layout.setContentsMargins(6, 6, 6, 6)
        knife_preview_layout.setSpacing(4)
        knife_selector = QFormLayout()
        knife_selector.setContentsMargins(0, 0, 0, 0)
        knife_selector.setLabelAlignment(Qt.AlignLeft)
        knife_selector.setVerticalSpacing(2)
        knife_selector.addRow("Bıçak:", self.combo_knife)
        knife_preview_layout.addLayout(knife_selector)
        knife_preview_layout.addWidget(self.blade_preview, 1)
        knife_preview_layout.addWidget(self.btn_toggle_knife_ground)
        self.grp_knife_preview = grp_knife_preview

        self.spin_tool_no.valueChanged.connect(self._on_tool_no_changed)
        self.combo_knife.currentIndexChanged.connect(self._on_knife_changed)
        self.combo_knife_profile.currentIndexChanged.connect(self._update_knife_viewer)
        self.combo_knife_direction.currentIndexChanged.connect(self._on_knife_direction_changed)
        self.spin_knife_angle.valueChanged.connect(self._on_angle_changed)
        self.spin_knife_thickness.valueChanged.connect(self._on_knife_params_changed)
        self.spin_knife_cut_length.valueChanged.connect(self._on_knife_params_changed)
        self.spin_disk_thickness.valueChanged.connect(self._on_knife_params_changed)
        self.spin_knife_length.valueChanged.connect(self._on_knife_params_changed)
        self.spin_knife_tip.valueChanged.connect(self._on_knife_params_changed)
        self.spin_knife_body.valueChanged.connect(self._on_knife_params_changed)
        self._toggle_knife_ground(self.btn_toggle_knife_ground.isChecked())

        self.grp_feed_settings = grp_tool
        self.grp_tool_settings = grp_knife
        self.grp_camera_settings = grp_colors

        # --- Yol Görünümü ---
        grp_style = QGroupBox("Yol & Nokta Görünümü")
        style_form = QFormLayout(grp_style)
        style_form.setContentsMargins(6, 6, 6, 6)
        style_form.setLabelAlignment(Qt.AlignLeft)
        style_form.setVerticalSpacing(4)

        self.edit_toolpath_color = ColorLineEdit("#ff0000")
        self.edit_toolpath_color.editingFinished.connect(self._on_style_changed)
        style_form.addRow("Yol Rengi:", self.edit_toolpath_color)

        self.spin_toolpath_width = QDoubleSpinBox()
        self.spin_toolpath_width.setRange(0.5, 10.0)
        self.spin_toolpath_width.setDecimals(1)
        self.spin_toolpath_width.setSingleStep(0.5)
        self.spin_toolpath_width.setValue(self.toolpath_width_px)
        self.spin_toolpath_width.valueChanged.connect(self._on_style_changed)
        style_form.addRow("Yol Kalınlığı (px):", self.spin_toolpath_width)

        # Nokta stili
        self.edit_point_color = ColorLineEdit(self.point_color_hex)
        self.edit_point_color.editingFinished.connect(self._on_style_changed)
        style_form.addRow("Nokta rengi:", self.edit_point_color)

        self.spin_point_size = QDoubleSpinBox()
        self.spin_point_size.setRange(0.5, 20.0)
        self.spin_point_size.setDecimals(1)
        self.spin_point_size.setSingleStep(0.5)
        self.spin_point_size.setValue(self.point_size_px)
        self.spin_point_size.valueChanged.connect(self._on_style_changed)
        style_form.addRow("Nokta kalınlığı (px):", self.spin_point_size)

        self.edit_first_point_color = ColorLineEdit(self.point_primary_hex)
        self.edit_first_point_color.editingFinished.connect(self._on_style_changed)
        style_form.addRow("1. nokta / Hata rengi:", self.edit_first_point_color)

        self.edit_second_point_color = ColorLineEdit(self.point_secondary_hex)
        self.edit_second_point_color.editingFinished.connect(self._on_style_changed)
        style_form.addRow("2. nokta rengi:", self.edit_second_point_color)

        grp_style.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.grp_path_view_settings = grp_style

        left_col = QWidget(self)
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.addWidget(self.grp_general_settings)
        left_layout.addWidget(self.grp_feed_settings)
        left_layout.addWidget(self.grp_path_view_settings)
        left_layout.addWidget(self.grp_camera_settings)
        left_layout.addStretch(1)

        mid_col = QWidget(self)
        mid_layout = QVBoxLayout(mid_col)
        mid_layout.setContentsMargins(0, 0, 0, 0)
        mid_layout.setSpacing(4)
        mid_layout.addWidget(self.grp_knife_preview, 1)

        # Grid yerleşimi (3 sütun)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)

        grid.addWidget(left_col, 0, 0)
        grid.addWidget(mid_col, 0, 1)
        grid.addWidget(self.grp_tool_settings, 0, 2)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        grid_row = QHBoxLayout()
        grid_row.setContentsMargins(0, 0, 0, 0)
        grid_row.setSpacing(0)
        grid_row.addLayout(grid)
        grid_row.addStretch(1)
        root_layout.addLayout(grid_row)

        # --- Status + Kaydet ---
        self.label_status = QLabel("")
        self.label_status.setFont(QFont("Segoe UI", 8))
        root_layout.addWidget(self.label_status)
        self.label_warnings = QLabel("")
        self.label_warnings.setFont(QFont("Segoe UI", 8))
        self.btn_show_warnings = QPushButton("Uyarilari Goster")
        self.btn_show_warnings.setCursor(Qt.PointingHandCursor)
        self.btn_show_warnings.clicked.connect(self._show_settings_warnings)
        self.btn_show_warnings.setVisible(False)
        warnings_row = QHBoxLayout()
        warnings_row.addWidget(self.label_warnings, 1)
        warnings_row.addWidget(self.btn_show_warnings)
        root_layout.addLayout(warnings_row)

        self.btn_save_settings = QPushButton("Ayarları Kaydet")
        self.btn_save_settings.setCursor(Qt.PointingHandCursor)
        self.btn_save_settings.clicked.connect(self._on_save_clicked)
        button_row = QHBoxLayout()
        button_row.addWidget(self.btn_save_settings)
        root_layout.addLayout(button_row)

        root_layout.addStretch(1)
        self.setLayout(root_layout)

    # ------------------------------------------------------
    # INI okuma
    # ------------------------------------------------------
    def _load_from_ini(self):
        warnings = []
        missing_sections = set()
        cfg = configparser.ConfigParser()
        file_exists = os.path.exists(INI_PATH)
        read_ok = []
        read_error = None
        if file_exists:
            try:
                read_ok = cfg.read(INI_PATH, encoding="utf-8")
            except configparser.Error as exc:
                read_error = exc
        if not file_exists or not read_ok:
            if not file_exists:
                warnings.append(
                    WarningItem(
                        code="settings.file_missing",
                        message="Settings file not found; using defaults.",
                        context={"path": INI_PATH},
                    )
                )
                error = FileNotFoundError(f"Settings file not found: {INI_PATH}. Using defaults.")
            else:
                context = {"path": INI_PATH}
                if read_error is not None:
                    context["error"] = str(read_error)
                warnings.append(
                    WarningItem(
                        code="settings.read_error",
                        message="Settings file could not be read; using defaults.",
                        context=context,
                    )
                )
                error = ValueError(f"Settings file could not be read: {INI_PATH}. Using defaults.")
            self.spin_width.setValue(self.table_width_mm)
            self.spin_height.setValue(self.table_height_mm)
            self._set_origin_combo_from_code(self.origin_mode)

            self.edit_bg_color.setText("#e6e6eb")
            self.edit_bg_color.set_max_visual()
            self.edit_table_color.setText("#d5e4f0")
            self.edit_table_color.set_max_visual()
            self.edit_stl_color.setText("#ff6699")
            self.edit_stl_color.set_max_visual()

            self.chk_table_fill.setChecked(True)

            self.spin_safe_z.setValue(self.safe_z)
            self.spin_feed_xy.setValue(self.feed_xy)
            self.spin_feed_z.setValue(self.feed_z)
            self.spin_contour_offset.setValue(self.contour_offset_mm)
            self.spin_z_step.setValue(self.z_step_mm)
            self.combo_z_mode.setCurrentIndex(self.z_mode_index)

            # Kamera varsayılanları
            self.spin_cam_orbit.setValue(self.orbit_sensitivity)
            self.spin_cam_pan.setValue(self.pan_sensitivity)
            self.spin_cam_zoom.setValue(self.zoom_sensitivity)
            self.spin_cam_dist.setValue(self.camera_dist)
            self.spin_cam_rx.setValue(self.camera_rot_x)
            self.spin_cam_ry.setValue(self.camera_rot_y)

            self.toolpath_color_hex = "#ff0000"
            self.toolpath_width_px = 2.0
            try:
                self.edit_toolpath_color.blockSignals(True)
                self.spin_toolpath_width.blockSignals(True)
                self.edit_toolpath_color.setText(self.toolpath_color_hex)
                self.edit_toolpath_color.set_max_visual()
                self.spin_toolpath_width.setValue(self.toolpath_width_px)
                if hasattr(self, "edit_point_color"):
                    self.edit_point_color.blockSignals(True)
                    self.spin_point_size.blockSignals(True)
                    self.edit_first_point_color.blockSignals(True)
                    self.edit_second_point_color.blockSignals(True)
                    self.point_color_hex = "#ffff00"
                    self.point_primary_hex = "#ff0000"
                    self.point_secondary_hex = "#00ff00"
                    self.point_size_px = self.toolpath_width_px * 2.0
                    self.edit_point_color.setText(self.point_color_hex)
                    self.edit_point_color.set_max_visual()
                    self.spin_point_size.setValue(self.point_size_px)
                    self.edit_first_point_color.setText(self.point_primary_hex)
                    self.edit_first_point_color.set_max_visual()
                    self.edit_second_point_color.setText(self.point_secondary_hex)
                    self.edit_second_point_color.set_max_visual()
            finally:
                self.edit_toolpath_color.blockSignals(False)
                self.spin_toolpath_width.blockSignals(False)
                if hasattr(self, "edit_point_color"):
                    self.edit_point_color.blockSignals(False)
                if hasattr(self, "spin_point_size"):
                    self.spin_point_size.blockSignals(False)
                if hasattr(self, "edit_first_point_color"):
                    self.edit_first_point_color.blockSignals(False)
                if hasattr(self, "edit_second_point_color"):
                    self.edit_second_point_color.blockSignals(False)
            self._apply_style_to_toolpath_tab()

            self._load_tool_selection()
            self._apply_camera_settings()
            return Result.fail(error, warnings)

        def get_value(section, option, getter, fallback):
            return get_cfg_value(cfg, section, option, getter, fallback, warnings, missing_sections)

        self.table_width_mm = get_value("TABLE", "width_mm", cfg.getfloat, self.table_width_mm)
        self.table_height_mm = get_value("TABLE", "height_mm", cfg.getfloat, self.table_height_mm)
        self.origin_mode = get_value("TABLE", "origin_mode", cfg.get, self.origin_mode)
        self.show_table_fill = get_value("TABLE", "show_table_fill", cfg.getboolean, self.show_table_fill)

        self.spin_width.setValue(self.table_width_mm)
        self.spin_height.setValue(self.table_height_mm)
        self._set_origin_combo_from_code(self.origin_mode)
        self.chk_table_fill.setChecked(self.show_table_fill)

        bg = get_value("COLORS", "background", cfg.get, "#e6e6eb")
        table_c = get_value("COLORS", "table", cfg.get, "#d5e4f0")
        stl_c = get_value("COLORS", "stl", cfg.get, "#ff6699")

        self.edit_bg_color.setText(bg)
        self.edit_bg_color.set_max_visual()
        self.edit_table_color.setText(table_c)
        self.edit_table_color.set_max_visual()
        self.edit_stl_color.setText(stl_c)
        self.edit_stl_color.set_max_visual()

        # TabToolpath viewer'ına da tabla / renk ayarlarını uygula
        if hasattr(self.main_window, "tab_toolpath") and self.main_window.tab_toolpath:
            tp = self.main_window.tab_toolpath
            viewer = getattr(tp, "viewer", None)
            if viewer is not None:
                try:
                    viewer.set_table_size(self.table_width_mm, self.table_height_mm)
                    viewer.set_origin_mode(self.origin_mode)
                    viewer.set_table_fill_enabled(self.show_table_fill)
                    viewer.set_colors(bg, table_c, stl_c)
                except Exception:
                    logger.exception("TabToolpath viewer renk/tabla güncellemesi başarısız")

        # Takım Yolu Oluşturma sekmesindeki viewer'ı da tabla ve renk ayarlarıyla güncelle
        if hasattr(self.main_window, "tab_toolpath_builder") and self.main_window.tab_toolpath_builder:
            builder = self.main_window.tab_toolpath_builder
            viewer = getattr(builder, "viewer", None)
            if viewer is not None:
                try:
                    viewer.set_table_size(self.table_width_mm, self.table_height_mm)
                    viewer.set_origin_mode(self.origin_mode)
                    viewer.set_table_fill_enabled(self.show_table_fill)
                    viewer.set_colors(bg, table_c, stl_c)
                except Exception:
                    logger.exception("TabToolpathBuilder viewer renk/tabla güncellemesi başarısız")

        self.safe_z = get_value("TOOLPATH", "safe_z", cfg.getfloat, self.safe_z)
        self.feed_xy = get_value("TOOLPATH", "feed_xy", cfg.getfloat, self.feed_xy)
        self.feed_z = get_value("TOOLPATH", "feed_z", cfg.getfloat, self.feed_z)
        self.toolpath_color_hex = get_value("TOOLPATH", "color", cfg.get, self.toolpath_color_hex)
        self.toolpath_width_px = get_value("TOOLPATH", "width", cfg.getfloat, self.toolpath_width_px)
        # Makine park (ini-only)
        self.use_g53_park = get_value("MACHINE", "use_g53_park", cfg.getboolean, self.use_g53_park)
        self.g53_park_x = get_value("MACHINE", "g53_park_x", cfg.getfloat, self.g53_park_x)
        self.g53_park_y = get_value("MACHINE", "g53_park_y", cfg.getfloat, self.g53_park_y)
        self.g53_park_z = get_value("MACHINE", "g53_park_z", cfg.getfloat, self.g53_park_z)
        # Opsiyonel A park degeri; okunamazsa None kalir
        try:
            self.g53_park_a = get_value("MACHINE", "g53_park_a", cfg.getfloat, self.g53_park_a)
        except Exception:
            pass
        self.point_size_px = self.toolpath_width_px * 2.0
        # Nokta stilini VIEW bölümünden oku
        self.point_color_hex = get_value("VIEW", "point_color", cfg.get, self.point_color_hex)
        self.point_size_px = get_value("VIEW", "point_size_px", cfg.getfloat, self.point_size_px)
        self.point_primary_hex = get_value("VIEW", "first_point_color", cfg.get, self.point_primary_hex)
        self.point_secondary_hex = get_value("VIEW", "second_point_color", cfg.get, self.point_secondary_hex)
        self.contour_offset_mm = get_value("APP", "contour_offset_mm", cfg.getfloat, self.contour_offset_mm)
        self.z_step_mm = get_value("APP", "z_step_mm", cfg.getfloat, self.z_step_mm)
        self.z_mode_index = get_value("APP", "z_mode", cfg.getint, self.z_mode_index)
        self.feed_xy_mm_min = get_value("APP", "feed_xy_mm_min", cfg.getfloat, self.feed_xy_mm_min)
        self.feed_z_mm_min = get_value("APP", "feed_z_mm_min", cfg.getfloat, self.feed_z_mm_min)
        self.feed_travel_mm_min = get_value("APP", "feed_travel_mm_min", cfg.getfloat, self.feed_travel_mm_min)
        self.safe_z_mm = get_value("APP", "safe_z_mm", cfg.getfloat, self.safe_z_mm)
        self.spindle_enabled = get_value("GCODE", "spindle_enabled", cfg.getboolean, self.spindle_enabled)
        self.spindle_use_s = get_value("GCODE", "spindle_use_s", cfg.getboolean, self.spindle_use_s)
        self.spindle_rpm = get_value("GCODE", "spindle_rpm", cfg.getfloat, self.spindle_rpm)
        self.spindle_on_mcode = get_value("GCODE", "spindle_on_mcode", cfg.get, self.spindle_on_mcode)
        self.spindle_off_mcode = get_value("GCODE", "spindle_off_mcode", cfg.get, self.spindle_off_mcode)
        self.spindle_emit_off_at_end = get_value("GCODE", "spindle_emit_off_at_end", cfg.getboolean, self.spindle_emit_off_at_end)
        # Eski alanlar uyumlu olsun diye oku
        self.spindle_on_cmd = get_value("APP", "spindle_on_cmd", cfg.get, f"{self.spindle_on_mcode} S{int(self.spindle_rpm)}")
        self.spindle_off_cmd = get_value("APP", "spindle_off_cmd", cfg.get, self.spindle_off_mcode)
        self.a_offset_deg = get_value("APP", "A_OFFSET_DEG", cfg.getfloat, self.a_offset_deg)
        self.a_reverse = get_value("APP", "A_REVERSE", cfg.getint, self.a_reverse)
        a_mode = None
        if cfg.has_option("APP", "a_source_mode"):
            a_mode = get_value("APP", "a_source_mode", cfg.get, self.a_source_mode)
        else:
            try:
                legacy = cfg.getint("APP", "a_source", fallback=None)
            except Exception:
                legacy = None
            if legacy is not None:
                a_mode = {1: "2d_tangent", 2: "mesh_normal", 3: "hybrid"}.get(int(legacy))
        if a_mode:
            self.a_source_mode = str(a_mode).strip().lower()
        if self.a_source_mode not in ("2d_tangent", "mesh_normal", "hybrid"):
            self.a_source_mode = "2d_tangent"
        self.a_pivot_enable = get_value("APP", "A_PIVOT_ENABLE", cfg.getint, self.a_pivot_enable)
        self.a_pivot_r_mm = get_value("APP", "A_PIVOT_R_MM", cfg.getfloat, self.a_pivot_r_mm)
        self.a_pivot_steps = get_value("APP", "A_PIVOT_STEPS", cfg.getint, self.a_pivot_steps)
        self.a_corner_threshold_deg = get_value("APP", "A_CORNER_THRESHOLD_DEG", cfg.getfloat, self.a_corner_threshold_deg)
        self.knife_contact_offset_enabled = get_value("APP", "knife_contact_offset_enabled", cfg.getint, self.knife_contact_offset_enabled)
        self.knife_contact_side = get_value("APP", "knife_contact_side", cfg.getint, self.knife_contact_side)
        self.knife_contact_d_min_mm = get_value("APP", "knife_contact_d_min_mm", cfg.getfloat, self.knife_contact_d_min_mm)
        self.orbit_sensitivity = get_value("CAMERA", "orbit_sensitivity", cfg.getfloat, self.orbit_sensitivity)
        self.pan_sensitivity = get_value("CAMERA", "pan_sensitivity", cfg.getfloat, self.pan_sensitivity)
        self.zoom_sensitivity = get_value("CAMERA", "zoom_sensitivity", cfg.getfloat, self.zoom_sensitivity)
        self.camera_dist = get_value("CAMERA", "initial_distance", cfg.getfloat, self.camera_dist)
        self.camera_rot_x = get_value("CAMERA", "initial_rot_x", cfg.getfloat, self.camera_rot_x)
        self.camera_rot_y = get_value("CAMERA", "initial_rot_y", cfg.getfloat, self.camera_rot_y)

        self.spin_safe_z.setValue(self.safe_z)
        self.spin_feed_xy.setValue(self.feed_xy)
        self.spin_feed_z.setValue(self.feed_z)
        self.spin_contour_offset.setValue(self.contour_offset_mm)
        self.spin_z_step.setValue(self.z_step_mm)
        self.combo_z_mode.setCurrentIndex(self.z_mode_index)
        # Spindle UI
        try:
            self.chk_spindle_enabled.setChecked(bool(self.spindle_enabled))
            self.chk_spindle_use_s.setChecked(bool(self.spindle_use_s))
            self.chk_spindle_emit_off.setChecked(bool(self.spindle_emit_off_at_end))
            self.spin_spindle_rpm.setValue(self.spindle_rpm)
            self.edit_spindle_on.setText(self.spindle_on_mcode)
            self.edit_spindle_off.setText(self.spindle_off_mcode)
        except Exception:
            logger.exception("Spindle ayarlari UI'a uygulanamadı")

        # Kamera ayarlarını UI'a yansıt
        try:
            self.spin_cam_orbit.setValue(self.orbit_sensitivity)
            self.spin_cam_pan.setValue(self.pan_sensitivity)
            self.spin_cam_zoom.setValue(self.zoom_sensitivity)
            self.spin_cam_dist.setValue(self.camera_dist)
            self.spin_cam_rx.setValue(self.camera_rot_x)
            self.spin_cam_ry.setValue(self.camera_rot_y)
        except Exception:
            logger.exception("Kamera ayarları UI'a uygulanamadı")

        try:
            self.edit_toolpath_color.blockSignals(True)
            self.spin_toolpath_width.blockSignals(True)
            self.edit_toolpath_color.setText(self.toolpath_color_hex)
            self.edit_toolpath_color.set_max_visual()
            self.spin_toolpath_width.setValue(self.toolpath_width_px)
            self.edit_point_color.blockSignals(True)
            self.spin_point_size.blockSignals(True)
            self.edit_point_color.setText(self.point_color_hex)
            self.edit_point_color.set_max_visual()
            self.spin_point_size.setValue(self.point_size_px)
            self.edit_first_point_color.blockSignals(True)
            self.edit_second_point_color.blockSignals(True)
            self.edit_first_point_color.setText(self.point_primary_hex)
            self.edit_first_point_color.set_max_visual()
            self.edit_second_point_color.setText(self.point_secondary_hex)
            self.edit_second_point_color.set_max_visual()
        finally:
            self.edit_toolpath_color.blockSignals(False)
            self.spin_toolpath_width.blockSignals(False)
            self.edit_point_color.blockSignals(False)
            self.spin_point_size.blockSignals(False)
            self.edit_first_point_color.blockSignals(False)
            self.edit_second_point_color.blockSignals(False)

        self._apply_style_to_toolpath_tab()
        self._load_tool_selection()

        # TabToolpath spinbox'larını ini yüklemesiyle eşitle
        if hasattr(self.main_window, "tab_toolpath") and self.main_window.tab_toolpath:
            self.main_window.tab_toolpath._apply_saved_toolpath_settings()

        # Kamera ayarlarını viewer'lara uygula
        self._apply_camera_settings()
        return Result.ok(None, warnings)

    def _update_settings_warnings_ui(self):
        summary = warnings_summary(self.settings_warnings)
        if summary:
            self.label_warnings.setText(f"UYARI: {summary}")
            self.btn_show_warnings.setVisible(True)
        else:
            self.label_warnings.setText("")
            self.btn_show_warnings.setVisible(False)

    def _show_settings_warnings(self):
        QMessageBox.information(self, "Ayar Uyarilari", warnings_to_multiline_text(self.settings_warnings))

    def _ensure_knife_catalog(self):
        if self.knife_catalog:
            return
        self.knife_catalog = load_catalog()
        self.knife_defs_by_id = {k.id: k for k in self.knife_catalog}
        self.knife_names = [k.id for k in self.knife_catalog]
        self._populate_knife_combo()

    def _populate_knife_combo(self, selected_id: str = ""):
        if not hasattr(self, "combo_knife"):
            return
        self.combo_knife.blockSignals(True)
        self.combo_knife.clear()
        for knife_def in self.knife_catalog:
            icon = self._knife_icon_for(knife_def)
            text = f"{knife_def.id} - {knife_def.name}".strip()
            self.combo_knife.addItem(icon, text)
            idx = self.combo_knife.count() - 1
            self.combo_knife.setItemData(idx, knife_def, Qt.UserRole)
            self.combo_knife.setItemData(idx, knife_def.meta, Qt.UserRole + 1)
        if selected_id:
            self._select_knife_by_id(selected_id)
        self.combo_knife.blockSignals(False)

    def _select_knife_by_id(self, knife_id: str) -> bool:
        if not hasattr(self, "combo_knife"):
            return False
        for i in range(self.combo_knife.count()):
            knife_def = self.combo_knife.itemData(i, Qt.UserRole)
            if isinstance(knife_def, KnifeDef) and knife_def.id == knife_id:
                self.combo_knife.setCurrentIndex(i)
                return True
        return False

    def _current_knife_def(self):
        if not hasattr(self, "combo_knife"):
            return None
        idx = self.combo_knife.currentIndex()
        if idx < 0:
            return None
        knife_def = self.combo_knife.itemData(idx, Qt.UserRole)
        return knife_def if isinstance(knife_def, KnifeDef) else None

    def _knife_def_from_index(self, index):
        if not index or not index.isValid():
            return None
        knife_def = index.data(Qt.UserRole)
        return knife_def if isinstance(knife_def, KnifeDef) else None

    def _resolve_knife_thumbnail(self, path: str) -> str:
        if not path:
            return ""
        if os.path.isabs(path):
            return path
        return os.path.abspath(path)

    def _knife_icon_for(self, knife_def: KnifeDef) -> QIcon:
        thumb = self._resolve_knife_thumbnail(knife_def.thumbnail)
        if thumb and os.path.exists(thumb):
            return QIcon(thumb)
        label = (knife_def.id or "K")[:2].upper()
        return self._make_placeholder_icon(label)

    def _make_placeholder_icon(self, label: str, size: int = 32) -> QIcon:
        pix = QPixmap(size, size)
        pix.fill(QColor("#d9d9d9"))
        painter = QPainter(pix)
        try:
            painter.setPen(QColor("#404040"))
            painter.drawRect(0, 0, size - 1, size - 1)
            font = QFont("Segoe UI", 8)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(pix.rect(), Qt.AlignCenter, label)
        finally:
            painter.end()
        return QIcon(pix)

    def _profile_from_kind(self, kind: str) -> str:
        value = (kind or "").lower()
        if "disk" in value:
            return "rotary_disk"
        if "rounded" in value:
            return "scalpel_rounded"
        return "scalpel_pointed"

    def _axis_from_direction(self, direction: str) -> str:
        value = (direction or "").strip().lower()
        if value in ("y", "y_parallel", "y-parallel", "yparallel"):
            return "y"
        if value in ("x", "x_parallel", "x-parallel", "xparallel"):
            return "x"
        if "y" in value:
            return "y"
        return "x"

    def _direction_from_axis(self, axis: str) -> str:
        return "Y_parallel" if (axis or "").lower() == "y" else "X_parallel"

    def _block_knife_signals(self, block: bool):
        widgets = [
            self.spin_knife_length,
            self.spin_knife_tip,
            self.spin_knife_body,
            self.spin_knife_angle,
            self.spin_knife_thickness,
            self.spin_knife_cut_length,
            self.spin_disk_thickness,
            self.combo_knife_profile,
            self.combo_knife_direction,
        ]
        for widget in widgets:
            if widget is not None:
                widget.blockSignals(block)

    def _set_active_tool_no(self, tool_no: int):
        tool_no = int(tool_no) if tool_no else 1
        self.active_tool_no = tool_no if tool_no > 0 else 1
        if hasattr(self, "spin_tool_no"):
            self.spin_tool_no.blockSignals(True)
            self.spin_tool_no.setValue(self.active_tool_no)
            self.spin_tool_no.blockSignals(False)

    def _load_tool_selection(self):
        self._ensure_knife_catalog()
        tool_no = load_active_tool_no(INI_PATH)
        self._set_active_tool_no(tool_no)
        tool_data = load_tool(TOOL_INI_PATH, self.active_tool_no)
        knife_id = ""
        if tool_data:
            knife_id = str(tool_data.get("knife_id", "") or "")
        knife_def = self.knife_defs_by_id.get(knife_id) if knife_id else None
        if knife_def is None and self.knife_catalog:
            knife_def = self.knife_catalog[0]
        if knife_def is None:
            return
        self._apply_knife_def(knife_def, tool_data, select_combo=True)

    def _apply_knife_def(self, knife_def: KnifeDef, tool_data=None, select_combo: bool = True):
        if knife_def is None:
            return
        self._loading_tool = True
        try:
            self.current_knife_name = knife_def.id
            self.knife_names = [k.id for k in self.knife_catalog] if self.knife_catalog else [knife_def.id]
            if select_combo:
                self.combo_knife.blockSignals(True)
                self._select_knife_by_id(knife_def.id)
                self.combo_knife.blockSignals(False)

            values = dict(knife_def.defaults or {})
            if tool_data:
                for key in (
                    "blade_length_mm",
                    "cutting_edge_diam_mm",
                    "body_diam_mm",
                    "blade_thickness_mm",
                    "cut_length_mm",
                    "disk_thickness_mm",
                    "knife_angle_deg",
                ):
                    if key in tool_data:
                        values[key] = float(tool_data[key])

            self._block_knife_signals(True)
            try:
                if "blade_length_mm" in values:
                    self.spin_knife_length.setValue(float(values["blade_length_mm"]))
                if "cutting_edge_diam_mm" in values:
                    self.spin_knife_tip.setValue(float(values["cutting_edge_diam_mm"]))
                if "body_diam_mm" in values:
                    self.spin_knife_body.setValue(float(values["body_diam_mm"]))
                if "blade_thickness_mm" in values:
                    self.spin_knife_thickness.setValue(float(values["blade_thickness_mm"]))
                if "cut_length_mm" in values:
                    self.spin_knife_cut_length.setValue(float(values["cut_length_mm"]))
                if "disk_thickness_mm" in values:
                    self.spin_disk_thickness.setValue(float(values["disk_thickness_mm"]))
                if "knife_angle_deg" in values:
                    self.spin_knife_angle.setValue(float(values["knife_angle_deg"]))
            finally:
                self._block_knife_signals(False)

            profile = ""
            if tool_data and tool_data.get("knife_profile"):
                profile = str(tool_data.get("knife_profile") or "")
            if not profile:
                profile = self._profile_from_kind(knife_def.kind)
            self._sync_profile_from_name(knife_def.name, profile)

            direction_axis = self.knife_direction_axis
            if tool_data and tool_data.get("knife_direction"):
                direction_axis = self._axis_from_direction(tool_data.get("knife_direction"))
            self._sync_direction_axis(direction_axis)
            self._sync_knife_state_from_ui()
        finally:
            self._loading_tool = False

    def _load_knives_default(self):
        self._ensure_knife_catalog()
        if not self.knife_catalog:
            return
        self._apply_knife_def(self.knife_catalog[0], None, select_combo=True)

    def _migrate_legacy_knife(self, cfg: configparser.ConfigParser) -> bool:
        """Eski [KNIFE] yapısını KNIVES/KNIFE_<name> şemasına taşır."""
        if "KNIFE" not in cfg:
            return False

        legacy = cfg["KNIFE"]
        legacy_name = self._sanitize_knife_name(legacy.get("name", "Legacy Knife"))
        length = legacy.get("length_mm", legacy.get("length", "30.0"))
        tip = legacy.get("tip_mm", legacy.get("tip_diameter_mm", "1.0"))
        body = legacy.get("body_mm", legacy.get("body_diameter_mm", "3.0"))
        angle = legacy.get("angle_deg", "0.0")

        knives_sec = cfg["KNIVES"] if "KNIVES" in cfg else {}
        names = [
            self._sanitize_knife_name(n)
            for n in (knives_sec.get("list", "") or "").split(";")
            if n.strip()
        ]
        current = self._sanitize_knife_name(knives_sec.get("current", legacy_name)) or legacy_name
        if legacy_name not in names:
            names.append(legacy_name)
        if current not in names:
            current = legacy_name

        cfg["KNIVES"] = {"current": current, "list": ";".join(names)}
        cfg[f"KNIFE_{legacy_name}"] = {
            "length_mm": length,
            "tip_diameter_mm": tip,
            "body_diameter_mm": body,
            "angle_deg": angle,
        }
        try:
            cfg.remove_section("KNIFE")
        except Exception:
            logger.exception("Legacy KNIFE bölümü silinemedi")
        return True

    def _sanitize_knife_name(self, name: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9 _-]+", "", name or "")
        cleaned = cleaned.strip()
        return cleaned or "Knife"

    def _normalize_knife_sections(self, cfg: configparser.ConfigParser) -> bool:
        """KNIFE_* bölümlerinde bozuk isimleri temizler ve KNIVES listesini günceller."""
        changed = False
        knife_sections = [s for s in cfg.sections() if s.startswith("KNIFE_")]
        names = []
        for sec in knife_sections:
            raw_name = sec[len("KNIFE_") :]
            safe_name = self._sanitize_knife_name(raw_name)
            names.append(safe_name)
            if safe_name != raw_name:
                new_sec = f"KNIFE_{safe_name}"
                if new_sec not in cfg:
                    cfg[new_sec] = {}
                cfg[new_sec].update(cfg[sec])
                try:
                    cfg.remove_section(sec)
                except Exception:
                    logger.exception("Legacy KNIFE_* bölümü silinemedi: %s", sec)
                changed = True

        if names:
            knives_sec = cfg["KNIVES"] if "KNIVES" in cfg else {}
            existing = [
                self._sanitize_knife_name(n)
                for n in (knives_sec.get("list", "") or "").split(";")
                if n.strip()
            ]
            merged = []
            for n in existing + names:
                if n and n not in merged:
                    merged.append(n)
            current = knives_sec.get("current", merged[0] if merged else "Knife")
            current = self._sanitize_knife_name(current)
            if current not in merged and merged:
                current = merged[0]
            cfg["KNIVES"] = {"current": current, "list": ";".join(merged)}
            changed = True
        return changed

    def _load_knives_from_cfg(self, cfg: configparser.ConfigParser, warnings_out=None, missing_sections=None):
        if "KNIVES" not in cfg:
            if warnings_out is not None:
                warnings_out.append(
                    WarningItem(
                        code="settings.missing_section",
                        message="Missing section [KNIVES]; using defaults.",
                        context={"section": "KNIVES"},
                    )
                )
            self._load_knives_default()
            return

        def get_value(section, option, getter, fallback):
            return get_cfg_value(cfg, section, option, getter, fallback, warnings_out, missing_sections)

        names_str = (get_value("KNIVES", "list", cfg.get, "") or "").strip()
        names = [self._sanitize_knife_name(n) for n in names_str.split(";") if n.strip()] if names_str else []

        if not names:
            self._load_knives_default()
            return

        self.knife_names = names
        current = self._sanitize_knife_name(get_value("KNIVES", "current", cfg.get, names[0]))
        self.current_knife_name = current if current in names else names[0]

        self.combo_knife.blockSignals(True)
        self.combo_knife.clear()
        self.combo_knife.addItems(self.knife_names)
        self.combo_knife.setCurrentText(self.current_knife_name)
        self.combo_knife.blockSignals(False)

        sect_name = f"KNIFE_{self.current_knife_name}"
        dirty = False
        self.knife_length, d = self._get_knife_float(cfg, sect_name, "length_mm", 30.0)
        dirty |= d
        self.knife_tip_diam, d = self._get_knife_float(cfg, sect_name, "tip_diameter_mm", 2.0)
        dirty |= d
        self.knife_body_diam, d = self._get_knife_float(cfg, sect_name, "body_diameter_mm", 6.0)
        dirty |= d
        self.knife_angle_deg, d = self._get_knife_float(cfg, sect_name, "angle_deg", 0.0)
        dirty |= d
        self.knife_thickness_mm, d = self._get_knife_float(cfg, sect_name, "blade_thickness_mm", 1.0)
        dirty |= d
        self.knife_cut_length_mm, d = self._get_knife_float(cfg, sect_name, "cut_length_mm", 10.0)
        dirty |= d
        self.knife_disk_thickness_mm, d = self._get_knife_float(cfg, sect_name, "disk_thickness_mm", 2.0)
        dirty |= d
        default_profile = self._get_default_profile()
        self.knife_profile, profile_dirty = self._get_profile_from_cfg(cfg, sect_name, default_profile)
        default_axis = self._get_default_direction_axis()
        self.knife_direction_axis, direction_dirty = self._get_direction_axis_from_cfg(cfg, sect_name, default_axis)
        dirty = dirty or profile_dirty or direction_dirty

        if self.knife_cut_length_mm > self.knife_length:
            self.knife_cut_length_mm = self.knife_length
            cfg.set(sect_name, "cut_length_mm", f"{self.knife_cut_length_mm}")
            dirty = True

        self.spin_knife_length.setValue(self.knife_length)
        self.spin_knife_tip.setValue(self.knife_tip_diam)
        self.spin_knife_body.setValue(self.knife_body_diam)
        self.spin_knife_angle.setValue(self.knife_angle_deg)
        self.spin_knife_thickness.setValue(self.knife_thickness_mm)
        self.spin_knife_cut_length.setValue(self.knife_cut_length_mm)
        self.spin_disk_thickness.setValue(self.knife_disk_thickness_mm)

        self._sync_profile_from_name(self.current_knife_name, self.knife_profile)
        self._sync_direction_axis(self.knife_direction_axis)
        self._update_knife_viewer()
        if dirty:
            try:
                with open(INI_PATH, "w", encoding="utf-8") as f:
                    cfg.write(f)
            except Exception:
                logger.exception("Profile ayari yazilamadi")

    def _set_origin_combo_from_code(self, code: str):
        for idx, (_text, c) in enumerate(self.origin_options):
            if c == code:
                self.combo_origin.setCurrentIndex(idx)
                return
        self.combo_origin.setCurrentIndex(0)

    def _get_origin_code_from_combo(self) -> str:
        idx = self.combo_origin.currentIndex()
        if 0 <= idx < len(self.origin_options):
            return self.origin_options[idx][1]
        return "center"

    # ------------------------------------------------------
    # Bıçak olayları
    # ------------------------------------------------------
    def _on_tool_no_changed(self, value: int):
        if self._loading_tool:
            return
        self._set_active_tool_no(int(value))
        tool_data = load_tool(TOOL_INI_PATH, self.active_tool_no)
        knife_id = ""
        if tool_data:
            knife_id = str(tool_data.get("knife_id", "") or "")
        knife_def = self.knife_defs_by_id.get(knife_id) if knife_id else None
        if knife_def is None and self.knife_catalog:
            knife_def = self.knife_catalog[0]
        if knife_def is None:
            return
        self._apply_knife_def(knife_def, tool_data, select_combo=True)

    def _on_knife_changed(self, index: int):
        if self._loading_tool:
            return
        if index < 0:
            return
        view = self.combo_knife.view() if hasattr(self, "combo_knife") else None
        idx = view.model().index(index, 0) if view is not None else None
        knife_def = self._knife_def_from_index(idx) if idx is not None else None
        if knife_def is None:
            return
        self.current_knife_name = knife_def.id
        self._apply_knife_def(knife_def, None, select_combo=False)

    def _on_angle_changed(self, value: float):
        self.knife_angle_deg = float(value)
        self._sync_knife_state_from_ui()

    def _on_knife_direction_changed(self, _value=None):
        axis = "x"
        if hasattr(self, "combo_knife_direction"):
            axis = self.combo_knife_direction.currentData() or "x"
        self.knife_direction_axis = axis if axis in ("x", "y") else "x"
        self._update_knife_viewer()

    def _sync_knife_state_from_ui(self):
        self.knife_length = float(self.spin_knife_length.value())
        self.knife_tip_diam = float(self.spin_knife_tip.value())
        self.knife_body_diam = float(self.spin_knife_body.value())
        self.knife_thickness_mm = float(self.spin_knife_thickness.value())
        self.knife_cut_length_mm = float(self.spin_knife_cut_length.value())
        self.knife_disk_thickness_mm = float(self.spin_disk_thickness.value())
        self.knife_angle_deg = float(self.spin_knife_angle.value())
        if self.knife_cut_length_mm > self.knife_length:
            self.knife_cut_length_mm = self.knife_length
            self.spin_knife_cut_length.blockSignals(True)
            self.spin_knife_cut_length.setValue(self.knife_cut_length_mm)
            self.spin_knife_cut_length.blockSignals(False)
        self._update_knife_viewer()

    def _on_knife_params_changed(self, _value=None):
        self._sync_knife_state_from_ui()

    def _detect_profile_from_name(self, name: str) -> str:
        return normalize_profile("", name)

    def _get_default_profile(self) -> str:
        if hasattr(self, "combo_knife_profile") and self.combo_knife_profile.count() > 0:
            data = self.combo_knife_profile.itemData(0)
            if data:
                return str(data)
        return "scalpel_pointed"

    def _get_profile_from_cfg(self, cfg: configparser.ConfigParser, section: str, default_profile: str):
        raw = ""
        if cfg.has_section(section) and cfg.has_option(section, "profile"):
            try:
                raw = cfg.get(section, "profile")
            except configparser.Error:
                raw = ""
        norm = normalize_profile(raw, self.current_knife_name)
        if not raw or norm != raw:
            if not cfg.has_section(section):
                cfg[section] = {}
            norm = normalize_profile(default_profile, self.current_knife_name)
            cfg.set(section, "profile", norm)
            return norm, True
        return norm, False

    def _get_knife_float(self, cfg: configparser.ConfigParser, section: str, option: str, default: float):
        if not cfg.has_section(section):
            cfg[section] = {}
        if not cfg.has_option(section, option):
            cfg.set(section, option, f"{default}")
            return float(default), True
        try:
            return float(cfg.get(section, option)), False
        except (ValueError, configparser.Error):
            cfg.set(section, option, f"{default}")
            return float(default), True

    def _get_default_direction_axis(self) -> str:
        if hasattr(self, "combo_knife_direction") and self.combo_knife_direction.count() > 0:
            data = self.combo_knife_direction.itemData(0)
            if data in ("x", "y"):
                return data
        return "x"

    def _get_direction_axis_from_cfg(self, cfg: configparser.ConfigParser, section: str, default_axis: str):
        raw = ""
        if cfg.has_section(section) and cfg.has_option(section, "direction_axis"):
            try:
                raw = cfg.get(section, "direction_axis")
            except configparser.Error:
                raw = ""
        value = (raw or "").strip().lower()
        if value not in ("x", "y"):
            if not cfg.has_section(section):
                cfg[section] = {}
            value = default_axis if default_axis in ("x", "y") else "x"
            cfg.set(section, "direction_axis", value)
            return value, True
        if raw != value:
            cfg.set(section, "direction_axis", value)
            return value, True
        return value, False

    def _sync_profile_from_name(self, name: str, profile: str = ""):
        if not hasattr(self, "combo_knife_profile"):
            return
        profile = normalize_profile(profile, name)
        self.knife_profile = profile
        for i in range(self.combo_knife_profile.count()):
            if self.combo_knife_profile.itemData(i) == profile:
                self.combo_knife_profile.setCurrentIndex(i)
                return

    def _sync_direction_axis(self, axis: str):
        if not hasattr(self, "combo_knife_direction"):
            return
        axis = axis if axis in ("x", "y") else "x"
        self.knife_direction_axis = axis
        for i in range(self.combo_knife_direction.count()):
            if self.combo_knife_direction.itemData(i) == axis:
                self.combo_knife_direction.setCurrentIndex(i)
                return

    def eventFilter(self, obj, event):
        if hasattr(self, "combo_knife") and obj is self.combo_knife.view().viewport():
            if event.type() == QEvent.ToolTip:
                index = self.combo_knife.view().indexAt(event.pos())
                if not index.isValid():
                    self._hide_knife_tooltip()
                    return True
                if index.row() != self._knife_tooltip_index:
                    self._knife_tooltip_index = index.row()
                    self._show_knife_tooltip(index)
                return True
            if event.type() == QEvent.Leave:
                self._hide_knife_tooltip()
        return super().eventFilter(obj, event)

    def _show_knife_tooltip(self, index):
        knife_def = self._knife_def_from_index(index)
        if knife_def is None:
            return
        title = f"{knife_def.id} - {knife_def.name}".strip()
        thumb = self._resolve_knife_thumbnail(knife_def.thumbnail)
        lines = []
        if thumb and os.path.exists(thumb):
            url = QUrl.fromLocalFile(thumb).toString()
            lines.append(f'<img src="{url}" width="260" />')
        if title:
            lines.append(f"<b>{title}</b>")
        if knife_def.meta:
            lines.append(knife_def.meta)
        if not lines:
            return
        QToolTip.showText(QCursor.pos(), "<br>".join(lines), self.combo_knife)

    def _hide_knife_tooltip(self):
        if self._knife_tooltip_index != -1:
            QToolTip.hideText()
            self._knife_tooltip_index = -1

    def _toggle_knife_ground(self, checked: bool):
        self._knife_ground_visible = bool(checked)
        if self.blade_preview is not None and hasattr(self.blade_preview, "set_ground_visible"):
            self.blade_preview.set_ground_visible(self._knife_ground_visible)
        if hasattr(self, "btn_toggle_knife_ground"):
            self.btn_toggle_knife_ground.setText(
                "Zemin Gizle" if self._knife_ground_visible else "Zemin Goster"
            )

    def _update_knife_viewer(self):
        if self.blade_preview is None:
            return

        profile = ""
        if hasattr(self, "combo_knife_profile"):
            profile = self.combo_knife_profile.currentData() or ""
        direction_axis = self.knife_direction_axis
        if hasattr(self, "combo_knife_direction"):
            direction_axis = self.combo_knife_direction.currentData() or direction_axis
        direction_axis = direction_axis if direction_axis in ("x", "y") else "x"
        spec = build_knife_spec(
            self.current_knife_name,
            float(self.spin_knife_length.value()),
            float(self.spin_knife_tip.value()),
            float(self.spin_knife_body.value()),
            float(self.spin_knife_angle.value()),
            profile=profile,
        )
        self.knife_profile = spec["profile"]
        self.knife_direction_axis = direction_axis

        params = {
            "blade_length_mm": spec["length_mm"],
            "tip_diameter_mm": spec["tip_diameter_mm"],
            "shank_diameter_mm": spec["body_diameter_mm"],
            "body_diameter_mm": spec["body_diameter_mm"],
            "body_diam_mm": spec["body_diameter_mm"],
            "cutting_edge_diam_mm": spec["tip_diameter_mm"],
            "a0_deg": spec["a0_deg"],
            "bevel_angle_deg": 30.0,
            "shoulder_length_mm": None,
            "tip_round_radius_mm": None,
            "disk_diameter_mm": spec["tip_diameter_mm"],
            "hub_diameter_mm": spec["body_diameter_mm"],
            "kerf_mm": 0.3,
            "direction_axis": self.knife_direction_axis,
            "blade_thickness_mm": float(self.spin_knife_thickness.value()),
            "cut_length_mm": float(self.spin_knife_cut_length.value()),
            "disk_thickness_mm": float(self.spin_disk_thickness.value()),
        }
        self.blade_preview.set_blade(spec["profile"], params)
        self.blade_preview.update()

    def _apply_style_to_toolpath_tab(self):
        if hasattr(self.main_window, "tab_toolpath") and self.main_window.tab_toolpath:
            try:
                self.main_window.tab_toolpath.apply_toolpath_style_from_settings(
                    self.toolpath_color_hex,
                    self.toolpath_width_px,
                    self.point_color_hex,
                    self.point_size_px,
                    self.point_primary_hex,
                    self.point_secondary_hex,
                )
                viewer = getattr(self.main_window.tab_toolpath, "viewer", None)
                if viewer is not None and hasattr(viewer, "set_pivot_preview_settings"):
                    viewer.set_pivot_preview_settings(
                        bool(self.a_pivot_enable),
                        float(self.a_pivot_r_mm),
                        int(self.a_pivot_steps),
                        float(self.a_corner_threshold_deg),
                    )
            except Exception:
                logger.exception("TabToolpath stil ayarları uygulanamadı")
        if hasattr(self.main_window, "tab_toolpath_builder") and self.main_window.tab_toolpath_builder:
            viewer = getattr(self.main_window.tab_toolpath_builder, "viewer", None)
            if viewer is not None and hasattr(viewer, "set_pivot_settings"):
                try:
                    viewer.set_pivot_settings(
                        bool(self.a_pivot_enable),
                        float(self.a_pivot_r_mm),
                        int(self.a_pivot_steps),
                        float(self.a_corner_threshold_deg),
                    )
                except Exception:
                    logger.exception("TabToolpathBuilder pivot ayarları uygulanamadı")

    def _apply_camera_settings(self):
        viewers = []
        if hasattr(self.main_window, "tab_model") and self.main_window.tab_model:
            viewers.append(getattr(self.main_window.tab_model, "viewer", None))
        if hasattr(self.main_window, "tab_toolpath") and self.main_window.tab_toolpath:
            viewers.append(getattr(self.main_window.tab_toolpath, "viewer", None))
        if hasattr(self.main_window, "tab_toolpath_builder") and self.main_window.tab_toolpath_builder:
            viewers.append(getattr(self.main_window.tab_toolpath_builder, "viewer", None))

        for v in viewers:
            if v is None:
                continue
            try:
                if hasattr(v, "orbit_sensitivity"):
                    v.orbit_sensitivity = float(self.orbit_sensitivity)
                if hasattr(v, "pan_sensitivity"):
                    v.pan_sensitivity = float(self.pan_sensitivity)
                if hasattr(v, "zoom_sensitivity"):
                    v.zoom_sensitivity = float(self.zoom_sensitivity)
                if hasattr(v, "dist"):
                    v.dist = float(self.camera_dist)
                if hasattr(v, "rot_x"):
                    v.rot_x = float(self.camera_rot_x)
                if hasattr(v, "rot_y"):
                    v.rot_y = float(self.camera_rot_y)
                if hasattr(v, "update"):
                    v.update()
            except Exception:
                logger.exception("Camera settings apply failed")
                continue

    def _on_style_changed(self):
        def _normalize(text_value: str, fallback: str) -> str:
            txt = (text_value or "").strip()
            if txt and not txt.startswith("#"):
                txt = "#" + txt
            if len(txt) != 7 or not QColor(txt).isValid():
                txt = fallback
            return txt.lower()

        self.toolpath_color_hex = _normalize(self.edit_toolpath_color.text(), self.toolpath_color_hex)
        self.point_color_hex = _normalize(self.edit_point_color.text(), self.point_color_hex)
        self.point_primary_hex = _normalize(self.edit_first_point_color.text(), self.point_primary_hex)
        self.point_secondary_hex = _normalize(self.edit_second_point_color.text(), self.point_secondary_hex)

        try:
            self.edit_toolpath_color.blockSignals(True)
            self.edit_point_color.blockSignals(True)
            self.edit_first_point_color.blockSignals(True)
            self.edit_second_point_color.blockSignals(True)
            self.edit_toolpath_color.setText(self.toolpath_color_hex)
            self.edit_toolpath_color.set_max_visual()
            self.edit_point_color.setText(self.point_color_hex)
            self.edit_point_color.set_max_visual()
            self.edit_first_point_color.setText(self.point_primary_hex)
            self.edit_first_point_color.set_max_visual()
            self.edit_second_point_color.setText(self.point_secondary_hex)
            self.edit_second_point_color.set_max_visual()
        finally:
            self.edit_toolpath_color.blockSignals(False)
            self.edit_point_color.blockSignals(False)
            self.edit_first_point_color.blockSignals(False)
            self.edit_second_point_color.blockSignals(False)

        self.toolpath_width_px = float(self.spin_toolpath_width.value())
        self.point_size_px = float(self.spin_point_size.value())
        self._apply_style_to_toolpath_tab()

    # ------------------------------------------------------
    # Kaydet
    # ------------------------------------------------------
    def _on_save_clicked(self):
        self.table_width_mm = float(self.spin_width.value())
        self.table_height_mm = float(self.spin_height.value())
        self.origin_mode = self._get_origin_code_from_combo()
        self.show_table_fill = self.chk_table_fill.isChecked()

        bg_color = self.edit_bg_color.text().strip()
        table_color = self.edit_table_color.text().strip()
        stl_color = self.edit_stl_color.text().strip()

        self.safe_z = float(self.spin_safe_z.value())
        self.feed_xy = float(self.spin_feed_xy.value())
        self.feed_z = float(self.spin_feed_z.value())
        self.contour_offset_mm = float(self.spin_contour_offset.value())
        self.z_step_mm = float(self.spin_z_step.value())
        self.z_mode_index = int(self.combo_z_mode.currentIndex())
        self.safe_z_mm = float(getattr(self, "safe_z_mm", self.safe_z))
        self.feed_xy_mm_min = float(getattr(self, "feed_xy_mm_min", self.feed_xy))
        self.feed_z_mm_min = float(getattr(self, "feed_z_mm_min", self.feed_z))
        self.feed_travel_mm_min = float(getattr(self, "feed_travel_mm_min", 4000.0))
        self.spindle_enabled = bool(self.chk_spindle_enabled.isChecked()) if hasattr(self, "chk_spindle_enabled") else False
        self.spindle_use_s = bool(self.chk_spindle_use_s.isChecked()) if hasattr(self, "chk_spindle_use_s") else False
        self.spindle_emit_off_at_end = bool(self.chk_spindle_emit_off.isChecked()) if hasattr(self, "chk_spindle_emit_off") else False
        self.spindle_rpm = float(self.spin_spindle_rpm.value()) if hasattr(self, "spin_spindle_rpm") else self.spindle_rpm
        self.spindle_on_mcode = (self.edit_spindle_on.text().strip() if hasattr(self, "edit_spindle_on") else self.spindle_on_mcode) or "M3"
        self.spindle_off_mcode = (self.edit_spindle_off.text().strip() if hasattr(self, "edit_spindle_off") else self.spindle_off_mcode) or "M5"
        # Uyumlu eski alanlar
        self.spindle_on_cmd = f"{self.spindle_on_mcode} S{int(round(self.spindle_rpm))}" if self.spindle_use_s else self.spindle_on_mcode
        self.spindle_off_cmd = self.spindle_off_mcode
        self.orbit_sensitivity = float(self.spin_cam_orbit.value())
        self.pan_sensitivity = float(self.spin_cam_pan.value())
        self.zoom_sensitivity = float(self.spin_cam_zoom.value())
        self.camera_dist = float(self.spin_cam_dist.value())
        self.camera_rot_x = float(self.spin_cam_rx.value())
        self.camera_rot_y = float(self.spin_cam_ry.value())

        self._on_style_changed()

        knife_def = self._current_knife_def()
        current_knife = knife_def.id if knife_def else (self.combo_knife.currentText().strip() or "Varsay?lan B??ak")
        self.current_knife_name = current_knife
        self.knife_names = [k.id for k in self.knife_catalog] if self.knife_catalog else [current_knife]
        self.active_tool_no = int(self.spin_tool_no.value())

        self.knife_length = float(self.spin_knife_length.value())
        self.knife_tip_diam = float(self.spin_knife_tip.value())
        self.knife_body_diam = float(self.spin_knife_body.value())
        self.knife_angle_deg = float(self.spin_knife_angle.value())
        self.knife_thickness_mm = float(self.spin_knife_thickness.value())
        self.knife_cut_length_mm = float(self.spin_knife_cut_length.value())
        self.knife_disk_thickness_mm = float(self.spin_disk_thickness.value())
        self.knife_profile = ""
        if hasattr(self, "combo_knife_profile"):
            self.knife_profile = self.combo_knife_profile.currentData() or ""
        self.knife_profile = normalize_profile(self.knife_profile, self.current_knife_name)
        self.knife_direction_axis = "x"
        if hasattr(self, "combo_knife_direction"):
            self.knife_direction_axis = self.combo_knife_direction.currentData() or "x"
        if self.knife_direction_axis not in ("x", "y"):
            self.knife_direction_axis = "x"

        cfg = configparser.ConfigParser()
        if os.path.exists(INI_PATH):
            cfg.read(INI_PATH, encoding="utf-8")

        if "TABLE" not in cfg:
            cfg["TABLE"] = {}
        if "COLORS" not in cfg:
            cfg["COLORS"] = {}
        if "TOOLPATH" not in cfg:
            cfg["TOOLPATH"] = {}
        if "VIEW" not in cfg:
            cfg["VIEW"] = {}
        if "APP" not in cfg:
            cfg["APP"] = {}
        if "KNIVES" not in cfg:
            cfg["KNIVES"] = {}
        if "CAMERA" not in cfg:
            cfg["CAMERA"] = {}
        if "MACHINE" not in cfg:
            cfg["MACHINE"] = {}
        if "GCODE" not in cfg:
            cfg["GCODE"] = {}

        cfg["TABLE"]["width_mm"] = f"{self.table_width_mm:.1f}"
        cfg["TABLE"]["height_mm"] = f"{self.table_height_mm:.1f}"
        cfg["TABLE"]["origin_mode"] = self.origin_mode
        cfg["TABLE"]["show_table_fill"] = "1" if self.show_table_fill else "0"

        cfg["COLORS"]["background"] = bg_color
        cfg["COLORS"]["table"] = table_color
        cfg["COLORS"]["stl"] = stl_color

        cfg["TOOLPATH"]["safe_z"] = f"{self.safe_z:.2f}"
        cfg["TOOLPATH"]["feed_xy"] = f"{self.feed_xy:.2f}"
        cfg["TOOLPATH"]["feed_z"] = f"{self.feed_z:.2f}"
        cfg.set("TOOLPATH", "color", self.toolpath_color_hex)
        cfg.set("TOOLPATH", "width", f"{self.toolpath_width_px:.2f}")
        cfg["VIEW"]["point_color"] = self.point_color_hex
        cfg["VIEW"]["point_size_px"] = f"{self.point_size_px:.2f}"
        cfg["VIEW"]["first_point_color"] = self.point_primary_hex
        cfg["VIEW"]["second_point_color"] = self.point_secondary_hex
        cfg["APP"]["contour_offset_mm"] = f"{self.contour_offset_mm:.3f}"
        cfg["APP"]["z_step_mm"] = f"{self.z_step_mm:.3f}"
        cfg["APP"]["z_mode"] = str(self.z_mode_index)
        cfg["APP"]["feed_xy_mm_min"] = f"{self.feed_xy_mm_min:.3f}"
        cfg["APP"]["feed_z_mm_min"] = f"{self.feed_z_mm_min:.3f}"
        cfg["APP"]["feed_travel_mm_min"] = f"{self.feed_travel_mm_min:.3f}"
        cfg["APP"]["safe_z_mm"] = f"{self.safe_z_mm:.3f}"
        cfg["APP"]["spindle_on_cmd"] = self.spindle_on_cmd
        cfg["APP"]["spindle_off_cmd"] = self.spindle_off_cmd
        cfg["APP"]["A_OFFSET_DEG"] = f"{self.a_offset_deg:.3f}"
        cfg["APP"]["A_REVERSE"] = str(int(self.a_reverse))
        cfg["APP"]["a_source_mode"] = str(self.a_source_mode or "2d_tangent")
        cfg["APP"]["A_PIVOT_ENABLE"] = str(int(self.a_pivot_enable))
        cfg["APP"]["A_PIVOT_R_MM"] = f"{self.a_pivot_r_mm:.3f}"
        cfg["APP"]["A_PIVOT_STEPS"] = str(int(self.a_pivot_steps))
        cfg["APP"]["A_CORNER_THRESHOLD_DEG"] = f"{self.a_corner_threshold_deg:.2f}"
        cfg["APP"]["knife_contact_offset_enabled"] = str(int(self.knife_contact_offset_enabled))
        cfg["APP"]["knife_contact_side"] = str(int(self.knife_contact_side))
        cfg["APP"]["knife_contact_d_min_mm"] = f"{self.knife_contact_d_min_mm:.3f}"
        cfg["MACHINE"]["use_g53_park"] = "1" if bool(self.use_g53_park) else "0"
        cfg["MACHINE"]["g53_park_x"] = f"{float(self.g53_park_x):.3f}"
        cfg["MACHINE"]["g53_park_y"] = f"{float(self.g53_park_y):.3f}"
        cfg["MACHINE"]["g53_park_z"] = f"{float(self.g53_park_z):.3f}"
        if self.g53_park_a is not None:
            cfg["MACHINE"]["g53_park_a"] = f"{float(self.g53_park_a):.3f}"
        cfg["GCODE"]["spindle_enabled"] = "1" if self.spindle_enabled else "0"
        cfg["GCODE"]["spindle_use_s"] = "1" if self.spindle_use_s else "0"
        cfg["GCODE"]["spindle_rpm"] = f"{float(self.spindle_rpm):.0f}"
        cfg["GCODE"]["spindle_on_mcode"] = self.spindle_on_mcode
        cfg["GCODE"]["spindle_off_mcode"] = self.spindle_off_mcode
        cfg["GCODE"]["spindle_emit_off_at_end"] = "1" if self.spindle_emit_off_at_end else "0"
        cfg["CAMERA"]["orbit_sensitivity"] = f"{self.orbit_sensitivity:.4f}"
        cfg["CAMERA"]["pan_sensitivity"] = f"{self.pan_sensitivity:.4f}"
        cfg["CAMERA"]["zoom_sensitivity"] = f"{self.zoom_sensitivity:.4f}"
        cfg["CAMERA"]["initial_distance"] = f"{self.camera_dist:.3f}"
        cfg["CAMERA"]["initial_rot_x"] = f"{self.camera_rot_x:.3f}"
        cfg["CAMERA"]["initial_rot_y"] = f"{self.camera_rot_y:.3f}"

        knives_sec = cfg["KNIVES"]
        knives_sec["current"] = self.current_knife_name
        knives_sec["list"] = ";".join(self.knife_names)

        sect_name = f"KNIFE_{self.current_knife_name}"
        if sect_name not in cfg:
            cfg[sect_name] = {}
        ksec = cfg[sect_name]
        ksec["length_mm"] = f"{self.knife_length:.3f}"
        ksec["tip_diameter_mm"] = f"{self.knife_tip_diam:.3f}"
        ksec["body_diameter_mm"] = f"{self.knife_body_diam:.3f}"
        ksec["angle_deg"] = f"{self.knife_angle_deg:.3f}"
        ksec["blade_thickness_mm"] = f"{self.knife_thickness_mm:.3f}"
        ksec["cut_length_mm"] = f"{self.knife_cut_length_mm:.3f}"
        ksec["disk_thickness_mm"] = f"{self.knife_disk_thickness_mm:.3f}"
        ksec["profile"] = self.knife_profile
        ksec["direction_axis"] = self.knife_direction_axis

        with open(INI_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)

        tool_profile = {
            "knife_id": self.current_knife_name,
            "knife_direction": self._direction_from_axis(self.knife_direction_axis),
            "knife_angle_deg": self.knife_angle_deg,
            "blade_thickness_mm": self.knife_thickness_mm,
            "cut_length_mm": self.knife_cut_length_mm,
            "disk_thickness_mm": self.knife_disk_thickness_mm,
            "blade_length_mm": self.knife_length,
            "cutting_edge_diam_mm": self.knife_tip_diam,
            "body_diam_mm": self.knife_body_diam,
            "knife_profile": self.knife_profile,
        }
        try:
            save_tool(TOOL_INI_PATH, self.active_tool_no, tool_profile)
            save_active_tool_no(INI_PATH, self.active_tool_no)
        except Exception:
            logger.exception("Tool library save failed")

        self._update_knife_viewer()
        self._apply_camera_settings()
        sim_viewer = getattr(self.main_window, "tab_simulation", None)
        if sim_viewer is not None and hasattr(sim_viewer, "reload_knife_from_settings"):
            try:
                sim_viewer.reload_knife_from_settings()
            except Exception:
                logger.exception("Simulasyon bicak guncellemesi basarisiz")

        if hasattr(self.main_window, "tab_model") and self.main_window.tab_model:
            self.main_window.tab_model.apply_table_settings(
                self.table_width_mm,
                self.table_height_mm,
                self.origin_mode,
                bg_color,
                table_color,
                stl_color,
                table_fill_enabled=self.show_table_fill,
            )

        # Also update TabToolpath viewer with the same table and color settings
        if hasattr(self.main_window, "tab_toolpath") and self.main_window.tab_toolpath:
            tp = self.main_window.tab_toolpath
            viewer = getattr(tp, "viewer", None)
            if viewer is not None:
                try:
                    viewer.set_table_size(self.table_width_mm, self.table_height_mm)
                    viewer.set_origin_mode(self.origin_mode)
                    viewer.set_table_fill_enabled(self.show_table_fill)
                    viewer.set_colors(bg_color, table_color, stl_color)
                except Exception:
                    logger.exception("TabToolpath viewer tablo/renk güncellenemedi")
        # Takım Yolu Oluşturma sekmesindeki viewer'ı da aynı ayarlarla güncelle
        if hasattr(self.main_window, "tab_toolpath_builder") and self.main_window.tab_toolpath_builder:
            builder = self.main_window.tab_toolpath_builder
            viewer = getattr(builder, "viewer", None)
            if viewer is not None:
                try:
                    viewer.set_table_size(self.table_width_mm, self.table_height_mm)
                    viewer.set_origin_mode(self.origin_mode)
                    viewer.set_table_fill_enabled(self.show_table_fill)
                    viewer.set_colors(bg_color, table_color, stl_color)
                except Exception:
                    logger.exception("TabToolpathBuilder viewer tablo/renk güncellenemedi")
        # Takım Yolu sekmesindeki viewer'ı da aynı tabla ve renklerle güncelle
        if hasattr(self.main_window, "tab_toolpath") and self.main_window.tab_toolpath:
            tp = self.main_window.tab_toolpath
            if hasattr(tp, "viewer") and tp.viewer is not None:
                tp.viewer.set_table_size(self.table_width_mm, self.table_height_mm)
                tp.viewer.set_origin_mode(self.origin_mode)
                tp.viewer.set_table_fill_enabled(self.show_table_fill)
                tp.viewer.set_colors(bg_color, table_color, stl_color)

        self.label_status.setText(
            f"Kaydedildi: Tabla {self.table_width_mm:.1f} x "
            f"{self.table_height_mm:.1f} mm, G54 = {self.origin_mode}, "
            f"SAFE_Z = {self.safe_z:.2f}, "
            f"FeedXY = {self.feed_xy:.2f}, "
            f"FeedZ = {self.feed_z:.2f}, "
            f"Kontur Ofseti = {self.contour_offset_mm:.2f} mm, "
            f"Adim = {self.z_step_mm:.2f} mm, "
            f"Bicak = {self.current_knife_name}, "
            f"Boy = {self.knife_length:.2f} mm, "
            f"Uc = {self.knife_tip_diam:.3f} mm, "
            f"Govde = {self.knife_body_diam:.3f} mm, "
            f"Aci = {self.knife_angle_deg:.1f} derece"
        )

        self.settings_changed.emit(
            self.table_width_mm,
            self.table_height_mm,
            self.origin_mode,
            bg_color,
            table_color,
            stl_color,
            self.show_table_fill,
        )

        # Kaydet sonrası Takım Yolu sekmesinin step/z modunu güncelle
        if hasattr(self.main_window, "tab_toolpath") and self.main_window.tab_toolpath:
            try:
                self.main_window.tab_toolpath.set_contour_offset(self.contour_offset_mm)
                self.main_window.tab_toolpath.set_step_value(self.z_step_mm)
                self.main_window.tab_toolpath.set_z_mode_index(self.z_mode_index)
            except Exception:
                logger.exception("TabToolpath step/z modu guncellenemedi")
