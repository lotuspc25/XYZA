import logging
from typing import List, Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QFileDialog,
    QPlainTextEdit,
    QPushButton,
    QMessageBox,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.warnings import warnings_summary, warnings_to_multiline_text
from core.a_axis_generator import attach_a_to_3d_points, generate_a_overlay
from project_state import ToolpathPoint  # Use shared ToolpathPoint model (single source).
from toolpath_gcode_parser import parse_gcode
from toolpath_generator import build_world_triangles
from ui_strings import TITLE_TOOLPATH, BTN_GENERATE_GCODE
from gcode_exporter import build_gcode_from_points
from sim.sim_runner import SimRunner
from tool_model import ToolVisualConfig
from widgets.gcode_viewer_3d import GCodeViewer3D
from core.path_utils import find_or_create_config

logger = logging.getLogger(__name__)


class TabToolpathBuilder(QWidget):
    """
    Takım Yolu Oluşturma sekmesi: sadece UI iskeleti (Parametreler / Viewer / Log / Noktalar).
    """

    def __init__(self, main_window, state=None):
        super().__init__(main_window)
        self.main_window = main_window
        self.state = state
        self.points: List[ToolpathPoint] = []
        self.meta: dict = {}
        self.gcode_text: str = ""
        self.segments = []
        self.gcode_warnings = []
        self.sim_runner = SimRunner()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer_tick)
        self.playing = False
        self.play_speed = 1.0
        self._build_ui()

    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Sol panel (Parametreler)
        left_box = QGroupBox("Parametreler")
        left_box.setMaximumWidth(260)
        left_layout = QVBoxLayout(left_box)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)
        lbl_params = QLabel("Parametre paneli (placeholder)")
        left_layout.addWidget(lbl_params)
        view_box = QGroupBox("Kamera")
        view_layout = QVBoxLayout(view_box)
        view_layout.setContentsMargins(6, 6, 6, 6)
        view_layout.setSpacing(4)
        self.btn_view_top = QPushButton("Üstten Görünüm")
        self.btn_view_front = QPushButton("Önden Görünüm")
        self.btn_view_side = QPushButton("Yandan Görünüm")
        self.btn_view_iso = QPushButton("İzometrik")
        self.btn_view_top.clicked.connect(lambda: self._set_sim_view("top"))
        self.btn_view_front.clicked.connect(lambda: self._set_sim_view("front"))
        self.btn_view_side.clicked.connect(lambda: self._set_sim_view("side"))
        self.btn_view_iso.clicked.connect(lambda: self._set_sim_view("iso"))
        view_layout.addWidget(self.btn_view_top)
        view_layout.addWidget(self.btn_view_front)
        view_layout.addWidget(self.btn_view_side)
        view_layout.addWidget(self.btn_view_iso)
        left_layout.addWidget(view_box)
        left_layout.addStretch(1)
        main_layout.addWidget(left_box, 0)

        # Orta panel (Viewer - 3D simülasyon)
        center_container = QWidget()
        center_layout = QVBoxLayout(center_container)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)

        sim_box = QGroupBox("G-code Simülasyon (3D)")
        sim_layout = QVBoxLayout(sim_box)
        sim_layout.setContentsMargins(8, 8, 8, 8)
        sim_layout.setSpacing(6)
        self.viewer_3d = GCodeViewer3D(self)
        sim_layout.addWidget(self.viewer_3d, 1)
        ctrl_layout = QHBoxLayout()
        self.btn_step_back = QPushButton("<<")
        self.btn_step_back.clicked.connect(lambda: self._step_sim(-1))
        self.btn_step_fwd = QPushButton(">>")
        self.btn_step_fwd.clicked.connect(lambda: self._step_sim(1))
        self.btn_reset = QPushButton("⏮")
        self.btn_reset.clicked.connect(self._reset_sim)
        self.btn_play = QPushButton("▶")
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_seek_end = QPushButton("???")
        self.btn_seek_end.clicked.connect(self._seek_end)
        self.btn_fit = QPushButton("Fit")
        self.btn_fit.clicked.connect(lambda: self.viewer_3d.fit_to_view())
        self.btn_toggle_mesh = QPushButton("STL G?ster")
        self.btn_toggle_mesh.clicked.connect(self._toggle_mesh_visibility)
        ctrl_layout.addWidget(self.btn_reset)
        ctrl_layout.addWidget(self.btn_step_back)
        ctrl_layout.addWidget(self.btn_play)
        ctrl_layout.addWidget(self.btn_step_fwd)
        ctrl_layout.addWidget(self.btn_seek_end)
        ctrl_layout.addWidget(self.btn_fit)
        ctrl_layout.addWidget(self.btn_toggle_mesh)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.valueChanged.connect(self._on_slider_changed)
        self.lbl_slider = QLabel("0 / 0")
        ctrl_layout.addWidget(self.slider, 1)
        ctrl_layout.addWidget(self.lbl_slider)

        self.lbl_pose = QLabel("X:0.000  Y:0.000  Z:0.000  A:-")
        ctrl_layout.addWidget(self.lbl_pose)

        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(25, 400)
        self.speed_slider.setValue(100)
        self.speed_slider.setFixedWidth(120)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        self.lbl_speed = QLabel("1.0x")
        ctrl_layout.addWidget(self.lbl_speed)
        ctrl_layout.addWidget(self.speed_slider)

        sim_layout.addLayout(ctrl_layout)

        center_layout.addWidget(sim_box, 1)
        main_layout.addWidget(center_container, 1)

        # Sağ panel (Noktalar / Hatalar)
        right_box = QGroupBox("Noktalar / Hatalar")
        right_box.setMaximumWidth(520)
        right_layout = QVBoxLayout(right_box)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(6)
        self.btn_generate_gcode = QPushButton(BTN_GENERATE_GCODE)
        self.btn_generate_gcode.setEnabled(False)
        self.btn_generate_gcode.clicked.connect(self._on_generate_gcode_clicked)
        right_layout.addWidget(self.btn_generate_gcode)
        self.btn_attach_a = QPushButton("A Ekseni Ekle")
        self.btn_attach_a.setEnabled(False)
        self.btn_attach_a.clicked.connect(self._on_attach_a_clicked)
        right_layout.addWidget(self.btn_attach_a)
        log_box = QGroupBox("G-code / Log")
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(8, 8, 8, 8)
        log_layout.setSpacing(4)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("G-code veya log metni burada görünecek.")
        log_layout.addWidget(self.log_edit, 1)
        self.btn_save_gcode = QPushButton("G-code Kaydet")
        self.btn_save_gcode.setEnabled(False)
        self.btn_save_gcode.clicked.connect(self._on_save_gcode_clicked)
        log_layout.addWidget(self.btn_save_gcode)
        right_layout.addWidget(log_box, 1)
        self.lbl_gcode_warnings = QLabel("")
        self.btn_show_gcode_warnings = QPushButton("Uyarilari Goster")
        self.btn_show_gcode_warnings.setCursor(Qt.PointingHandCursor)
        self.btn_show_gcode_warnings.clicked.connect(self._show_gcode_warnings)
        self.btn_show_gcode_warnings.setVisible(False)
        warnings_row = QHBoxLayout()
        warnings_row.addWidget(self.lbl_gcode_warnings, 1)
        warnings_row.addWidget(self.btn_show_gcode_warnings)
        right_layout.addLayout(warnings_row)
        main_layout.addWidget(right_box, 0)

    def _set_sim_view(self, preset: str):
        viewer = getattr(self, "viewer_3d", None)
        if viewer is None:
            return
        if preset == "top" and hasattr(viewer, "set_view_top"):
            viewer.set_view_top()
        elif preset == "front" and hasattr(viewer, "set_view_front"):
            viewer.set_view_front()
        elif preset == "side" and hasattr(viewer, "set_view_side"):
            viewer.set_view_side()
        elif preset == "iso" and hasattr(viewer, "set_view_isometric"):
            viewer.set_view_isometric()

    def _update_generate_button_state(self):
        btn = getattr(self, "btn_generate_gcode", None)
        if btn is None:
            return
        has_points = bool(getattr(self.state, "toolpath_points", None))
        btn.setEnabled(has_points)
        self._update_attach_button_state()

    def _update_attach_button_state(self):
        btn_attach = getattr(self, "btn_attach_a", None)
        if btn_attach is None:
            return
        has_points = bool(getattr(self.state, "toolpath_points", None))
        applied = bool(getattr(self.state, "a_applied_to_3d", False))
        if applied:
            btn_attach.setText("A eklendi")
            btn_attach.setEnabled(False)
        else:
            btn_attach.setText("A Ekseni Ekle")
            btn_attach.setEnabled(has_points)

    def _update_gcode_warnings_ui(self):
        summary = warnings_summary(self.gcode_warnings)
        if summary:
            self.lbl_gcode_warnings.setText(f"UYARI: {summary}")
            self.btn_show_gcode_warnings.setVisible(True)
        else:
            self.lbl_gcode_warnings.setText("")
            self.btn_show_gcode_warnings.setVisible(False)

    def _show_gcode_warnings(self):
        QMessageBox.information(self, "G-code Uyarilari", warnings_to_multiline_text(self.gcode_warnings))

    def _append_log(self, message: str) -> None:
        edit = getattr(self, "log_edit", None)
        if edit is None:
            return
        if edit.toPlainText():
            edit.appendPlainText(message)
        else:
            edit.setPlainText(message)

    def _compute_a_for_points(self, points: List[ToolpathPoint]) -> Optional[dict]:
        if not points:
            return None
        settings_tab = getattr(self.main_window, "tab_settings", None)
        knife_direction = "X_parallel"
        a_reverse = False
        a_offset = 0.0
        pivot_enable = False
        pivot_steps = 0
        corner_threshold = 25.0
        smooth_window = 5
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
                pivot_steps = 0
            try:
                corner_threshold = float(getattr(settings_tab, "A_CORNER_THRESHOLD_DEG", corner_threshold))
            except Exception:
                pass
        new_points, meta = generate_a_overlay(
            points,
            smooth_window=int(smooth_window),
            corner_threshold_deg=float(corner_threshold),
            pivot_enable=pivot_enable,
            pivot_steps=pivot_steps,
            knife_direction=knife_direction,
            a_reverse=a_reverse,
            a_offset_deg=a_offset,
        )
        return {
            "points_xy": [(p.x, p.y) for p in new_points],
            "angles_deg": meta.get("angles_deg", []),
            "corners": meta.get("corners", []),
            "meta": meta,
        }

    def _map_a_to_points(self, points: List[ToolpathPoint], a_result: dict) -> List[ToolpathPoint]:
        pts3d = list(points or [])
        angles = list(a_result.get("angles_deg") or [])
        pts2d = list(a_result.get("points_xy") or [])
        if not pts3d or not pts2d or not angles:
            return pts3d
        n = min(len(pts2d), len(angles))
        pts2d = pts2d[:n]
        angles = angles[:n]
        if len(pts3d) == len(angles):
            return [ToolpathPoint(p.x, p.y, p.z, angles[i]) for i, p in enumerate(pts3d)]

        def cumulative_s(path_xy):
            s_vals = [0.0]
            for i in range(1, len(path_xy)):
                dx = path_xy[i][0] - path_xy[i - 1][0]
                dy = path_xy[i][1] - path_xy[i - 1][1]
                s_vals.append(s_vals[-1] + (dx * dx + dy * dy) ** 0.5)
            return s_vals

        s2d = cumulative_s(pts2d)
        s3d = cumulative_s([(p.x, p.y) for p in pts3d])
        s2d_max = s2d[-1] if s2d else 0.0

        def interp_a(s_target):
            if s_target <= 0.0 or s2d_max <= 0.0:
                return angles[0]
            if s_target >= s2d_max:
                return angles[-1]
            lo = 0
            while lo < len(s2d) - 1 and s2d[lo + 1] < s_target:
                lo += 1
            hi = min(lo + 1, len(s2d) - 1)
            s0, s1 = s2d[lo], s2d[hi]
            a0, a1 = angles[lo], angles[hi]
            if s1 <= s0:
                return a0
            t = (s_target - s0) / (s1 - s0)
            return a0 + t * (a1 - a0)

        mapped = []
        for p, s_val in zip(pts3d, s3d):
            a_val = interp_a(s_val)
            mapped.append(ToolpathPoint(p.x, p.y, p.z, a_val))
        return mapped

    def load_prepared_data(
        self,
        points: Optional[List[ToolpathPoint]],
        meta: Optional[dict] = None,
        gcode_text: str = "",
    ):
        """Hazır veriyi saklar ve viewer/log alanını günceller."""
        self.points = points or []
        self.meta = meta or {}
        self.gcode_text = gcode_text or ""

        if isinstance(self.gcode_text, list):
            self.gcode_text = "\n".join(self.gcode_text)

        if hasattr(self, "btn_save_gcode"):
            self.btn_save_gcode.setEnabled(bool(self.gcode_text.strip()))
        self._update_generate_button_state()

        if self.gcode_text:
            self.log_edit.setPlainText(self.gcode_text)
            # parse for simulation
            try:
                warnings = []
                self.gcode_warnings = warnings
                self.segments = parse_gcode(self.gcode_text, warnings_out=warnings)
                self._update_gcode_warnings_ui()
                if warnings:
                    logger.warning("G-code parsed with warnings: %s", warnings_summary(warnings))
                self.sim_runner.set_segments(self.segments)
                if hasattr(self, "viewer_3d"):
                    self.viewer_3d.set_segments(self.segments)
                    # tool config from settings
                    cfg = self._load_tool_cfg()
                    self.viewer_3d.set_tool_config(cfg)
                    if hasattr(self.viewer_3d, "load_knife_tool_from_settings"):
                        self.viewer_3d.load_knife_tool_from_settings()
                    self._sync_origin_from_settings()  # NOTE: Match G54 origin in simulation.
                    # NOTE: Ensure STL mesh is visible with toolpath.
                    self._ensure_mesh_visible()
                pose = self.sim_runner.get_current_pose()
                self._update_pose_label(pose)
                self.slider.blockSignals(True)
                self.slider.setMaximum(max(0, len(self.segments) - 1))
                self.slider.setValue(0)
                self.slider.blockSignals(False)
                self._update_slider_label()
                logger.info("Sim: loaded %s segments", len(self.segments))
            except Exception:
                logger.exception("Simülasyon için G-code parse edilemedi")
        else:
            self.log_edit.clear()
            if hasattr(self, "viewer_3d"):
                self.viewer_3d.clear()
            self.segments = []
            self.gcode_warnings = []
            self._update_gcode_warnings_ui()
            self.sim_runner.set_segments([])
            self.slider.blockSignals(True)
            self.slider.setMaximum(0)
            self.slider.setValue(0)
            self.slider.blockSignals(False)
            self._update_slider_label()
        if hasattr(self, "btn_save_gcode"):
            self.btn_save_gcode.setEnabled(bool(self.gcode_text.strip()))
            self._update_pose_label(None)

    def clear_prepared_view(self):
        """Hazır veriyi ve görünümü temizler."""
        self.points = []
        self.meta = {}
        self.gcode_text = ""
        if self.state is not None:
            self.state.gcode_text = ""  # NOTE: Clear stored G-code when view is cleared.
        if hasattr(self, "log_edit"):
            self.log_edit.clear()
        if hasattr(self, "viewer_3d"):
            self.viewer_3d.clear()
        self.segments = []
        self.gcode_warnings = []
        self._update_gcode_warnings_ui()
        self.sim_runner.set_segments([])
        self.slider.blockSignals(True)
        self.slider.setMaximum(0)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self._update_slider_label()
        self._update_pose_label(None)
        self._update_generate_button_state()

    def _on_attach_a_clicked(self):
        state = getattr(self, "state", None)
        if state is not None and getattr(state, "a_applied_to_3d", False):
            self._append_log("A zaten eklendi.")
            return
        points = getattr(state, "toolpath_points", None) if state is not None else None
        if not points:
            self._append_log("3D yol bulunamadı. Önce 3D'de takım yolu oluşturun.")
            return
        a_result = getattr(state, "a_path_2d", None) if state is not None else None
        if not a_result:
            tab_2d = getattr(self.main_window, "page_2d", None)
            if tab_2d is not None and hasattr(tab_2d, "get_a_result"):
                a_result = tab_2d.get_a_result()
            if not a_result:
                a_result = self._compute_a_for_points(list(points))
                if a_result is not None and state is not None:
                    state.a_path_2d = dict(a_result)
        if not a_result:
            self._append_log("2D A yolu bulunamadı. Önce 2D'de 'A Yolu Üret' çalıştırın.")
            return
        try:
            new_points = self._map_a_to_points(list(points), a_result)
            meta = {"ok": True, "n3d": len(points), "n2d": len(a_result.get("points_xy") or [])}
        except Exception:
            logger.exception("A ekseni ekleme başarısız")
            self._append_log("A ekseni eklenemedi.")
            return
        if not meta.get("ok") or not new_points:
            self._append_log("A ekseni eklenemedi.")
            return

        if state is not None:
            try:
                state.toolpath_points = list(new_points)
                state.prepared_points = list(new_points)
                state.a_applied_to_3d = True
                if isinstance(getattr(state, "prepared_meta", None), dict):
                    state.prepared_meta["a_attach_meta"] = dict(meta)
                if state.toolpath_result is not None:
                    state.toolpath_result.points = list(new_points)
                    if isinstance(state.toolpath_result.meta, dict):
                        state.toolpath_result.meta["a_attach_meta"] = dict(meta)
            except Exception:
                logger.exception("A ekseni state'e yazılamadı")

        meta_prepared = {}
        if state is not None and isinstance(getattr(state, "prepared_meta", None), dict):
            meta_prepared = dict(state.prepared_meta)
        elif isinstance(getattr(self, "meta", None), dict):
            meta_prepared = dict(self.meta)
        meta_prepared["a_attach_meta"] = dict(meta)

        gcode_text = ""
        if state is not None and state.gcode_text:
            settings_tab = getattr(self.main_window, "tab_settings", None)
            try:
                gcode_text, _stats = build_gcode_from_points(list(new_points), settings_tab)
                state.gcode_text = gcode_text
            except Exception:
                logger.exception("G-code güncellenemedi")
                gcode_text = state.gcode_text or ""

        self.load_prepared_data(list(new_points), meta_prepared, gcode_text)
        self._update_attach_button_state()
        self._append_log("A eklendi.")

    def _on_generate_gcode_clicked(self):
        state = getattr(self, "state", None)
        points = getattr(state, "toolpath_points", None) if state is not None else None
        if not points:
            QMessageBox.warning(self, TITLE_TOOLPATH, "?nce bir tak?m yolu olu?turun.")
            return
        settings_tab = getattr(self.main_window, "tab_settings", None)
        try:
            gcode_text, stats = build_gcode_from_points(list(points), settings_tab)
        except Exception:
            logger.exception("G-code ?retimi ba?ar?s?z")
            QMessageBox.critical(self, TITLE_TOOLPATH, "G-code olu?turulamad?.")
            return
        if not gcode_text:
            QMessageBox.warning(self, TITLE_TOOLPATH, "G-code olu?turulamad?.")
            return
        if state is not None:
            state.gcode_text = gcode_text  # NOTE: Store G-code only when explicitly generated.
        self.load_prepared_data(list(points), getattr(state, "prepared_meta", None) if state is not None else None, gcode_text)

    def _on_save_gcode_clicked(self):
        text = getattr(self, "gcode_text", "") or ""
        if not text.strip():
            QMessageBox.information(self, TITLE_TOOLPATH, "Önce G-code oluşturun.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "G-code Kaydet",
            "output.nc",
            "G-code Files (*.nc *.gcode *.tap);;All Files (*)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            QMessageBox.information(self, TITLE_TOOLPATH, "G-code kaydedildi.")
        except Exception:
            logger.exception("G-code kaydedilemedi")
            QMessageBox.critical(self, TITLE_TOOLPATH, "G-code kaydedilemedi.")

    def _step_sim(self, delta: int):
        if not self.segments:
            return
        if delta < 0:
            self.sim_runner.step_back(abs(delta))
        else:
            self.sim_runner.step_forward(delta)
        done, _ = self.sim_runner.get_progress()
        if hasattr(self, "viewer_3d"):
            self.viewer_3d.set_current_index(done - 1)
        self.slider.blockSignals(True)
        self.slider.setValue(max(0, done - 1))
        self.slider.blockSignals(False)
        self._update_slider_label()
        self._update_pose_label(self.sim_runner.get_current_pose())

    def _reset_sim(self):
        self.playing = False
        self.timer.stop()
        self.btn_play.setText("▶")
        self.sim_runner.reset()
        if hasattr(self, "viewer_3d"):
            self.viewer_3d.set_progress(0)
        self.slider.blockSignals(True)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self._update_slider_label()
        self._update_pose_label(self.sim_runner.get_current_pose())

    def _seek_end(self):
        self.sim_runner.seek_end()
        done, _ = self.sim_runner.get_progress()
        if hasattr(self, "viewer_3d"):
            self.viewer_3d.set_progress(done)
        self.slider.blockSignals(True)
        self.slider.setValue(max(0, done - 1))
        self.slider.blockSignals(False)
        self._update_slider_label()
        self._update_pose_label(self.sim_runner.get_current_pose())

    def _toggle_play(self):
        if self.playing:
            self.playing = False
            self.btn_play.setText("▶")
            self.timer.stop()
        else:
            self.playing = True
            self.btn_play.setText("⏸")
            self.timer.start(50)
            logger.info("Sim: play speed=%sx step_ms=50", self.play_speed)

    def _on_timer_tick(self):
        if not self.playing or not self.segments:
            return
        steps = max(1, int(self.play_speed))
        self._step_sim(steps)
        if self.sim_runner.index >= len(self.segments) - 1:
            self._toggle_play()

    def _on_slider_changed(self, value: int):
        if not self.segments:
            return
        self.sim_runner.seek(value)
        if hasattr(self, "viewer_3d"):
            self.viewer_3d.set_current_index(value)
        self._update_slider_label()
        self._update_pose_label(self.sim_runner.get_current_pose())

    def _update_slider_label(self):
        total = len(self.segments)
        cur = max(0, min(self.slider.value(), max(0, total - 1))) if total else 0
        self.lbl_slider.setText(f"{cur+1 if total else 0} / {total}")

    def _on_speed_changed(self, val: int):
        self.play_speed = max(0.25, min(4.0, val / 100.0))
        self.lbl_speed.setText(f"{self.play_speed:.2f}x")

    def _update_pose_label(self, pose):
        if pose is None:
            self.lbl_pose.setText("X: -  Y: -  Z: -  A: -")
            return
        x, y, z, a = pose
        if a is None:
            self.lbl_pose.setText(f"X:{x:.3f}  Y:{y:.3f}  Z:{z:.3f}  A:-")
        else:
            self.lbl_pose.setText(f"X:{x:.3f}  Y:{y:.3f}  Z:{z:.3f}  A:{a:.1f} deg")

    def _toggle_mesh_visibility(self):
        viewer = getattr(self, "viewer_3d", None)
        if viewer is None:
            return
        self._sync_origin_from_settings()  # NOTE: Keep origin aligned when toggling mesh.
        loaded_now = False
        if not viewer.has_mesh():
            loaded_now = self._load_mesh_from_model()
        if loaded_now:
            new_flag = True  # NOTE: Show mesh right after load.
        else:
            new_flag = not getattr(viewer, "mesh_visible", False)
        viewer.set_mesh_visible(new_flag)
        self.btn_toggle_mesh.setText("STL Gizle" if new_flag else "STL G?ster")


    def _sync_origin_from_settings(self):
        """Sim?lasyonda G54 orijinini ayarlara g?re hizalar."""
        viewer = getattr(self, "viewer_3d", None)
        settings_tab = getattr(self.main_window, "tab_settings", None)
        if viewer is None or settings_tab is None:
            return
        try:
            w = float(getattr(settings_tab, "table_width_mm", 0.0))
            h = float(getattr(settings_tab, "table_height_mm", 0.0))
            mode = str(getattr(settings_tab, "origin_mode", "center"))
        except Exception:
            logger.exception("Origin ayarlar? okunamad?")
            return
        if mode == "front_left":
            ox, oy = 0.0, 0.0
        elif mode == "front_right":
            ox, oy = w, 0.0
        elif mode == "back_left":
            ox, oy = 0.0, h
        elif mode == "back_right":
            ox, oy = w, h
        else:
            ox, oy = w / 2.0, h / 2.0
        viewer.set_origin_offset(ox, oy, 0.0)

    def _get_mesh_settings(self):
        """settings.ini'den STL çizim ayarlarını okur."""
        import configparser

        stride = 1  # NOTE: Default full mesh for visibility; increase in settings for speed.
        mode = "solid"
        cfgp = configparser.ConfigParser()
        try:
            cfgp.read(str(find_or_create_config()[0]), encoding="utf-8")
            if "APP" in cfgp:
                stride = cfgp.getint("APP", "sim_mesh_stride", fallback=stride)
                mode = cfgp.get("APP", "sim_mesh_mode", fallback=mode)
        except Exception:
            logger.exception("Sim mesh ayarları okunamadı")
        return max(1, int(stride)), (mode or "solid").strip().lower()

    def _load_mesh_from_model(self) -> bool:
        """Model sekmesindeki STL'yi world uzayında sim viewer'a yükler."""
        viewer_3d = getattr(self, "viewer_3d", None)
        model_tab = getattr(self.main_window, "tab_model", None)
        if viewer_3d is None or model_tab is None:
            return False
        src_viewer = getattr(model_tab, "viewer", None)
        if src_viewer is None or getattr(src_viewer, "mesh_vertices", None) is None:
            return False
        try:
            tris = build_world_triangles(src_viewer)
        except Exception:
            logger.exception("STL mesh world dönüşümü başarısız")
            return False
        if tris is None or len(tris) == 0:
            return False
        verts = tris.reshape(-1, 3)
        stride, mode = self._get_mesh_settings()
        viewer_3d.set_mesh(verts.tolist(), None, stride=stride, mode=mode)
        return True

    def _ensure_mesh_visible(self):
        """Toolpath ile birlikte STL görünürlüğünü açar."""
        viewer = getattr(self, "viewer_3d", None)
        if viewer is None:
            return
        if not viewer.has_mesh():
            self._load_mesh_from_model()
        viewer.set_mesh_visible(True)
        if hasattr(self, "btn_toggle_mesh"):
            self.btn_toggle_mesh.setText("STL Gizle")

    def _load_tool_cfg(self) -> ToolVisualConfig:
        """
        Ara? g?r?n?m ayarlar?n? oku.
        ?ncelik: settings.ini [APP] (kullan?c?n?n kaydetti?i de?erler)
        Yedek: tab_settings alanlar?
        Son ?are: varsay?lan ToolVisualConfig.
        """
        import configparser

        cfg_from_ini: Optional[ToolVisualConfig] = None
        cfgp = configparser.ConfigParser()
        try:
            cfgp.read("settings.ini", encoding="utf-8")
            if "APP" in cfgp:
                class Dummy:
                    def __init__(self, d):
                        self.__dict__.update(d)

                app_dict = {k: v for k, v in cfgp["APP"].items()}
                cfg_from_ini = ToolVisualConfig.from_settings(Dummy(app_dict))
        except Exception:
            logger.exception("Tool config ini okunamad?")

        if cfg_from_ini:
            return cfg_from_ini

        settings_tab = getattr(self.main_window, "tab_settings", None)
        if settings_tab is not None:
            try:
                return ToolVisualConfig.from_settings(settings_tab)
            except Exception:
                logger.exception("Tool config settings_tab okunamad?")

        return ToolVisualConfig()

    def reload_knife_from_settings(self):
        viewer = getattr(self, "viewer_3d", None)
        if viewer is None or not hasattr(viewer, "load_knife_tool_from_settings"):
            return
        try:
            viewer.load_knife_tool_from_settings()
        except Exception:
            logger.exception("Sim tool reload failed")
