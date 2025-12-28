# main.py
# ----------------------------------------------------------
# XYZA Toolpath - Ana Pencere
# Sekmeler:
#   - Model Yükleme
#   - Takım Yolu
#   - Simülasyon (STL bıçak modeli)
#   - Ayarlar (bıçak: açı / ölçek / yön)
#   - Genel Bilgiler
# ----------------------------------------------------------

import sys
import os
import logging
import configparser

from project_state import ProjectState
from core.path_utils import find_or_create_config, resource_path
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QTabWidget,
    QWidget,
    QVBoxLayout,
    QSplashScreen,
    QScrollArea,
    QSizePolicy,
    QFrame,
)
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtCore import Qt, QElapsedTimer, QThread
from tabs.tab_toolpath_prepare import TabToolpath
from tabs.tab_toolpath_builder import TabToolpathBuilder
from tabs.tab_model import TabModel
from tabs.tab_settings import TabSettings
from tabs.tab_simulation import GLKnifeViewer
from tabs.tab_general_info import TabGeneralInfo
from tabs.tab_2d import Tab2DWidget

SETTINGS_FILE, TOOL_FILE = [str(p) for p in find_or_create_config()]
logger = logging.getLogger(__name__)


# ----------------------------------------------------------
# Settings.ini -> WINDOW yükleme
# ----------------------------------------------------------
def load_window_settings():
    cfg = configparser.ConfigParser()

    if os.path.exists(SETTINGS_FILE):
        cfg.read(SETTINGS_FILE, encoding="utf-8")
    if "WINDOW" not in cfg:
        cfg["WINDOW"] = {
            "width": "1100",
            "height": "700",
            "left": "100",
            "top": "100",
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception:
            logger.exception("WINDOW defaults could not be written")

    win = cfg["WINDOW"]
    return (
        int(win.get("width", "1100")),
        int(win.get("height", "700")),
        int(win.get("left", "100")),
        int(win.get("top", "100")),
    )


# ----------------------------------------------------------
# Settings.ini -> WINDOW kaydetme
# ----------------------------------------------------------
def save_window_settings(width, height, left, top):
    cfg = configparser.ConfigParser()

    if os.path.exists(SETTINGS_FILE):
        cfg.read(SETTINGS_FILE, encoding="utf-8")

    if "WINDOW" not in cfg:
        cfg["WINDOW"] = {}

    cfg["WINDOW"]["width"] = str(width)
    cfg["WINDOW"]["height"] = str(height)
    cfg["WINDOW"]["left"] = str(left)
    cfg["WINDOW"]["top"] = str(top)

    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        cfg.write(f)


# ----------------------------------------------------------
# Main Window
# ----------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, progress_callback=None):
        super().__init__()
        self._progress_callback = progress_callback or (lambda msg, pct=None: None)

        w, h, left, top = load_window_settings()

        self.setWindowTitle("XYZA Toolpath")
        self.setWindowIcon(QIcon(str(resource_path("icons/app_icon.png"))))

        self.resize(w, h)
        self.move(left, top)

        # Üst seviye sekmeler
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.tabBar().setCursor(Qt.PointingHandCursor)

        # 2D sayfası (şimdilik boş placeholder)
        self.page_2d = Tab2DWidget(self)

        # 3D sayfası: içinde Yol Hazırlama / Takım Yolu Oluşturma sekmeleri
        self.page_3d = QWidget()
        layout_3d = QVBoxLayout(self.page_3d)
        layout_3d.setContentsMargins(0, 0, 0, 0)
        self.tabs_3d = QTabWidget()
        self.tabs_3d.tabBar().setCursor(Qt.PointingHandCursor)
        layout_3d.addWidget(self.tabs_3d)

        self.state = ProjectState()
        self._emit_progress("Sekmeler hazırlanıyor...", 5)
        self._add_tabs()

    def _wrap_tab_scroll(self, widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        scroll.setMinimumSize(0, 0)
        scroll.setWidget(widget)
        return scroll


    # ------------------------------------------------------
    # Sekmeler
    # ------------------------------------------------------
    def _add_tabs(self):

        # 1) Model Yükleme
        self.tab_model = TabModel(self, self.state)
        # NOTE: Top-level Model tab is added once below to avoid duplicate addTab.
        self._emit_progress("Model sekmesi", 20)

        # 2) Yol Hazırlama
        self.tab_toolpath = TabToolpath(self, self.state)
        self._emit_progress("Yol Hazırlama sekmesi", 40)

        # 3) Takım Yolu Oluşturma
        self.tab_toolpath_builder = TabToolpathBuilder(self, self.state)
        self._emit_progress("Takım Yolu Oluşturma sekmesi", 50)

        # İç 3D sekmelerini ekle
        self.tabs_3d.addTab(
            self.tab_toolpath,
            QIcon(str(resource_path("icons/toolpath.png"))),
            "Yol Hazırlama",
        )
        self.tabs_3d.addTab(
            self.tab_toolpath_builder,
            QIcon(str(resource_path("icons/toolpath.png"))),
            "Takım Yolu Oluşturma",
        )

        # 4) Simülasyon (Bıçak STL Viewer)
        self.tab_simulation = GLKnifeViewer(self, state=self.state)
        self._emit_progress("Simülasyon sekmesi", 60)

        # 5) Ayarlar
        self.tab_settings = TabSettings(self, self.state)
        self._emit_progress("Ayarlar sekmesi", 80)

        # 6) Genel Bilgiler
        self.tab_general_info = TabGeneralInfo(self)
        self._emit_progress("Genel Bilgiler sekmesi", 90)

        # Üst seviye sekmeler: yeni sıra
        self.tabs.addTab(
            self._wrap_tab_scroll(self.tab_model),
            QIcon(str(resource_path("icons/model.png"))),
            "Model Yükleme",
        )
        self.tabs.addTab(
            self._wrap_tab_scroll(self.page_3d),
            QIcon(str(resource_path("icons/toolpath.png"))),
            "3D",
        )
        self.tabs.addTab(
            self._wrap_tab_scroll(self.page_2d),
            QIcon(str(resource_path("icons/toolpath.png"))),
            "2D",
        )
        self.tabs.addTab(
            self._wrap_tab_scroll(self.tab_simulation),
            QIcon(str(resource_path("icons/simulation.png"))),
            "Simülasyon",
        )
        self.tabs.addTab(
            self._wrap_tab_scroll(self.tab_settings),
            QIcon(str(resource_path("icons/settings.png"))),
            "Ayarlar",
        )
        self.tabs.addTab(
            self._wrap_tab_scroll(self.tab_general_info),
            QIcon(str(resource_path("icons/toolpath.png"))),
            "Bilgi",
        )

        # Ayarlar & Simülasyon canlı güncelleme
        # TabSettings içinden GLKnifeViewer'a erişmek için referans veriyoruz
        self.tab_model.knife_viewer = self.tab_simulation
        # Kontur ofsetini ini'den hem Model hem Takım Yolu sekmesine uygula
        try:
            offset_val = float(getattr(self.tab_settings, "contour_offset_mm", 0.0))
            if hasattr(self.tab_model, "set_contour_offset_from_settings"):
                self.tab_model.set_contour_offset_from_settings(offset_val)
            if hasattr(self.tab_toolpath, "set_contour_offset"):
                self.tab_toolpath.set_contour_offset(offset_val)
            step_val = float(getattr(self.tab_settings, "z_step_mm", 0.5))
            mode_idx = int(getattr(self.tab_settings, "z_mode_index", 0))
            if hasattr(self.tab_toolpath, "set_step_value"):
                self.tab_toolpath.set_step_value(step_val)
            if hasattr(self.tab_toolpath, "set_z_mode_index"):
                self.tab_toolpath.set_z_mode_index(mode_idx)
        except Exception:
            logger.exception("Sekme başlangıç ayarları uygulanamadı")
        self._emit_progress("Hazır", 100)

    # ------------------------------------------------------
    # Kapatırken pencere boyutunu kaydet
    # ------------------------------------------------------
    def closeEvent(self, event):
        size = self.size()
        pos = self.pos()
        save_window_settings(size.width(), size.height(), pos.x(), pos.y())
        event.accept()

    def _emit_progress(self, message, percent=None):
        try:
            self._progress_callback(message, percent)
        except Exception:
            logger.exception("İlerleme iletimi başarısız")


# ----------------------------------------------------------
# Program Giriş Noktası
# ----------------------------------------------------------
if __name__ == "__main__":
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[
            logging.FileHandler(os.path.join("logs", "app.log"), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    app = QApplication(sys.argv)
    # Splash ekranı (QSplashScreen + progress mesajı)
    splash = None
    splash_path = resource_path(os.path.join("images", "splash.png"))
    if splash_path.exists():
        pix = QPixmap(str(splash_path))
        if not pix.isNull():
            pix = pix.scaled(
                int(pix.width() / 2),
                int(pix.height() / 2),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        splash = QSplashScreen(pix)
        splash.show()
        splash.showMessage("", Qt.AlignBottom | Qt.AlignHCenter, Qt.white)
        app.processEvents()

    timer = QElapsedTimer()
    timer.start()

    def _update_splash(msg, pct=None):
        if splash is None:
            return
        if pct is not None:
            text = f"{pct}%"
        else:
            text = ""
        splash.showMessage(text, Qt.AlignBottom | Qt.AlignHCenter, Qt.white)
        app.processEvents()

    win = MainWindow(progress_callback=_update_splash)
    win.show()
    # En az 3 saniye splash göster
    remaining = 3000 - timer.elapsed()
    if remaining > 0:
        QThread.msleep(int(remaining))
    if splash is not None:
        splash.finish(win)
    sys.exit(app.exec_())
