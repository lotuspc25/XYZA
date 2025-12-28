# tabs/tab_general_info.py
# ----------------------------------------------------------
# "Genel Bilgiler" sekmesi
# - Z eğrisi ve A açısı eğrisi butonları
# - İyileştirme bilgisi butonu
# - Gerekirse ileride ek özet bilgiler için alan
# ----------------------------------------------------------

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGroupBox,
    QPushButton,
    QLabel,
    QSizePolicy,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


class TabGeneralInfo(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        font_group = QFont("Segoe UI", 9, QFont.Bold)
        font_btn = QFont("Segoe UI", 9)
        font_label = QFont("Segoe UI", 9)

        grp_charts = QGroupBox("Eğriler / Grafikler")
        grp_charts.setFont(font_group)
        charts_layout = QVBoxLayout(grp_charts)
        charts_layout.setSpacing(6)

        self.btn_show_z_curve = QPushButton("Z Eğrisini Göster")
        self.btn_show_z_curve.setFont(font_btn)
        self.btn_show_z_curve.setCursor(Qt.PointingHandCursor)
        self.btn_show_z_curve.clicked.connect(self._on_show_z_curve_clicked)
        charts_layout.addWidget(self.btn_show_z_curve)

        self.btn_show_a_curve = QPushButton("A Açısı Eğrisini Göster")
        self.btn_show_a_curve.setFont(font_btn)
        self.btn_show_a_curve.setCursor(Qt.PointingHandCursor)
        self.btn_show_a_curve.clicked.connect(self._on_show_a_curve_clicked)
        charts_layout.addWidget(self.btn_show_a_curve)

        grp_opt = QGroupBox("İyileştirme / Optimizasyon")
        grp_opt.setFont(font_group)
        opt_layout = QVBoxLayout(grp_opt)
        opt_layout.setSpacing(6)

        self.btn_show_opt_info = QPushButton("İyileştirme Bilgisi")
        self.btn_show_opt_info.setFont(font_btn)
        self.btn_show_opt_info.setCursor(Qt.PointingHandCursor)
        self.btn_show_opt_info.clicked.connect(self._on_show_opt_info_clicked)
        opt_layout.addWidget(self.btn_show_opt_info)

        self.lbl_info = QLabel(
            "Takım yolu, analiz ve optimizasyonla ilgili özet bilgiler burada gösterilebilir."
        )
        self.lbl_info.setWordWrap(True)
        opt_layout.addWidget(self.lbl_info)

        # --- Özet Bilgiler grubu
        self.grp_summary = QGroupBox("Özet Bilgiler")
        self.grp_summary.setFont(font_group)
        sum_layout = QVBoxLayout(self.grp_summary)
        sum_layout.setSpacing(4)

        self.lbl_points_count = QLabel("Nokta sayısı: 0")
        self.lbl_path_length = QLabel("Yol uzunluğu: 0.0 mm")
        self.lbl_z_minmax = QLabel("Z min / Z max: - / -")
        self.lbl_a_minmax = QLabel("A min / A max: - / -")
        self.lbl_est_time = QLabel("Tahmini süre: -")

        for lbl in [
            self.lbl_points_count,
            self.lbl_path_length,
            self.lbl_z_minmax,
            self.lbl_a_minmax,
            self.lbl_est_time,
        ]:
            lbl.setFont(font_label)
            sum_layout.addWidget(lbl)

        layout.addWidget(grp_charts)
        layout.addWidget(grp_opt)
        layout.addWidget(self.grp_summary)
        layout.addStretch(1)

    # --------------------------------------------------
    # Buton işlemleri: TabToolpath üzerindeki fonksiyonlara delege et
    # --------------------------------------------------
    def _get_toolpath_tab(self):
        return getattr(self.main_window, "tab_toolpath", None)

    def _on_show_z_curve_clicked(self):
        tp = self._get_toolpath_tab()
        if tp is not None and hasattr(tp, "show_z_plot"):
            tp.show_z_plot()

    def _on_show_a_curve_clicked(self):
        tp = self._get_toolpath_tab()
        if tp is not None and hasattr(tp, "show_a_plot"):
            tp.show_a_plot()

    def _on_show_opt_info_clicked(self):
        tp = self._get_toolpath_tab()
        if tp is not None and hasattr(tp, "on_show_opt_info_clicked"):
            tp.on_show_opt_info_clicked()

    def update_summary(
        self,
        count: int,
        length_mm: float,
        z_min: float,
        z_max: float,
        a_min: float,
        a_max: float,
        est_text: str,
    ):
        """TabToolpath'tan gelen özet istatistikleri UI'a uygular."""
        if getattr(self, "lbl_points_count", None) is None:
            return

        self.lbl_points_count.setText(f"Nokta sayısı: {count}")
        self.lbl_path_length.setText(f"Yol uzunluğu: {length_mm:.1f} mm")
        self.lbl_z_minmax.setText(f"Z min / Z max: {z_min:.2f} / {z_max:.2f} mm")
        if a_min is None or a_max is None:
            self.lbl_a_minmax.setText("A min / A max: - / -")
        else:
            self.lbl_a_minmax.setText(f"A min / A max: {a_min:.1f} deg / {a_max:.1f} deg")
        self.lbl_est_time.setText(est_text)

    def reset_summary(self):
        """Takım yolu yokken özet metinlerini sıfırlar."""
        if getattr(self, "lbl_points_count", None) is None:
            return

        self.lbl_points_count.setText("Nokta sayısı: 0")
        self.lbl_path_length.setText("Yol uzunluğu: 0.0 mm")
        self.lbl_z_minmax.setText("Z min / Z max: - / -")
        self.lbl_a_minmax.setText("A min / A max: - / -")
        self.lbl_est_time.setText("Tahmini süre: -")
