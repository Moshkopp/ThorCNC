"""Surface Map Module.

Handles:
- Grid probing UI (extents, cols/rows, probe params)
- NGC subroutine call and progress tracking
- Heatmap visualization of scanned Z data
"""

import os
import linuxcnc
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame,
    QLabel, QDoubleSpinBox, QSpinBox, QPushButton, QProgressBar, QSizePolicy,
)

from .base import ThorModule
from ..i18n import _t
from ..widgets.surface_map_widget import SurfaceMapWidget


class SurfaceMapModule(ThorModule):
    """Manages surface map scanning and heatmap visualization."""

    def __init__(self, thorc):
        super().__init__(thorc)
        self._scanning = False
        self._scan_interp_was_idle = False
        self._total_points = 0
        self._poll_timer = None
        self._var_mtime = 0.0

    def setup(self):
        pass

    def connect_signals(self):
        pass

    def setup_widget(self):
        """Create nav button and populate the tab_html placeholder (index 5)."""
        from PySide6.QtWidgets import QTabWidget
        ui = self._t.ui
        tab = ui.findChild(QTabWidget, "tabWidget")
        if not tab:
            return

        # Create the nav button and insert it after nav_probing in the sidebar
        self._create_nav_button(ui)

        # Populate tab_html (index 5) — it has no layout yet
        page = tab.widget(5)
        if not page:
            return

        lay = QHBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # Left Column
        vl_left = QVBoxLayout()
        vl_left.setSpacing(6)
        vl_left.addWidget(self._build_params_panel())
        vl_left.addStretch()
        lay.addLayout(vl_left)

        # Right Column
        vl_right = QVBoxLayout()
        vl_right.setSpacing(6)
        vl_right.addWidget(self._build_controls_panel())

        self._heatmap = SurfaceMapWidget()
        self._heatmap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vl_right.addWidget(self._heatmap)

        self._lbl_stats = QLabel("—")
        self._lbl_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_stats.setObjectName("surfaceMapStats")
        vl_right.addWidget(self._lbl_stats)

        lay.addLayout(vl_right)

        # Apply stretched column widths
        lay.setStretch(0, 0)
        lay.setStretch(1, 1)

        self._load_prefs()

    def _create_nav_button(self, ui):
        """Insert nav_surface_map button into the sidebar after nav_probing."""
        from PySide6.QtWidgets import QFrame
        left_panel = ui.findChild(QFrame, "leftPanel")
        if not left_panel or not left_panel.layout():
            return

        lay = left_panel.layout()

        # Find position of nav_probing in the layout
        nav_probe = ui.findChild(QPushButton, "nav_probing")
        insert_pos = 5  # fallback position
        if nav_probe:
            for i in range(lay.count()):
                item = lay.itemAt(i)
                if item and item.widget() is nav_probe:
                    insert_pos = i + 1
                    break

        btn = QPushButton(_t("SURFACE MAP"))
        btn.setObjectName("nav_surface_map")
        btn.setMinimumHeight(38)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCheckable(True)
        lay.insertWidget(insert_pos, btn)

    # ── Config Panel ──────────────────────────────────────────────────────────

    def _build_params_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("surfaceMapParams")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setMaximumWidth(360)

        grid = QGridLayout(frame)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setVerticalSpacing(12)
        grid.setHorizontalSpacing(8)

        def dsb(val, mn, mx, decimals=2, step=1.0):
            w = QDoubleSpinBox()
            w.setRange(mn, mx)
            w.setDecimals(decimals)
            w.setSingleStep(step)
            w.setValue(val)
            w.setMinimumHeight(55)
            w.setStyleSheet("font-size: 14pt; font-weight: bold;")
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            w.valueChanged.connect(self._save_prefs)
            return w

        def spb(val, mn, mx):
            w = QSpinBox()
            w.setRange(mn, mx)
            w.setValue(val)
            w.setMinimumHeight(55)
            w.setStyleSheet("font-size: 14pt; font-weight: bold;")
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            w.valueChanged.connect(self._save_prefs)
            return w
            
        def lbl(text):
            l = QLabel(text)
            l.setStyleSheet("font-size: 11pt; color: #eee; font-weight: bold;")
            return l

        # --- Probing Parameters ---
        lbl_title_params = QLabel(_t("PROBING PARAMETERS"))
        lbl_title_params.setStyleSheet("font-size: 13pt; font-weight: bold; color: #4db8ff;")
        grid.addWidget(lbl_title_params, 0, 0, 1, 2)

        grid.addWidget(lbl(_t("PROBE TOOL")), 1, 0)
        self._spb_probe_tool = spb(99, 1, 999)
        grid.addWidget(self._spb_probe_tool, 1, 1)

        grid.addWidget(lbl(_t("PROBE FEED")), 2, 0)
        self._dsb_feed = dsb(60.0, 1, 1000, step=10)
        grid.addWidget(self._dsb_feed, 2, 1)

        grid.addWidget(lbl(_t("Z CLEARANCE")), 3, 0)
        self._dsb_clearance = dsb(5.0, -999, 999)
        grid.addWidget(self._dsb_clearance, 3, 1)

        grid.addWidget(lbl(_t("PROBE DEPTH")), 4, 0)
        self._dsb_depth = dsb(-5.0, -999, 0)
        grid.addWidget(self._dsb_depth, 4, 1)

        # --- Scan Coordinates ---
        lbl_title_coords = QLabel(_t("SCAN COORDINATES"))
        lbl_title_coords.setStyleSheet("font-size: 13pt; font-weight: bold; color: #4db8ff; margin-top: 15px;")
        grid.addWidget(lbl_title_coords, 5, 0, 1, 2)

        grid.addWidget(lbl(_t("X Start")), 6, 0)
        self._dsb_x_start = dsb(-50.0, -9999, 9999)
        grid.addWidget(self._dsb_x_start, 6, 1)

        grid.addWidget(lbl(_t("X End")), 7, 0)
        self._dsb_x_end = dsb(50.0, -9999, 9999)
        grid.addWidget(self._dsb_x_end, 7, 1)

        grid.addWidget(lbl(_t("Y Start")), 8, 0)
        self._dsb_y_start = dsb(-50.0, -9999, 9999)
        grid.addWidget(self._dsb_y_start, 8, 1)

        grid.addWidget(lbl(_t("Y End")), 9, 0)
        self._dsb_y_end = dsb(50.0, -9999, 9999)
        grid.addWidget(self._dsb_y_end, 9, 1)

        grid.addWidget(lbl(_t("Spalten")), 10, 0)
        self._spb_cols = spb(5, 2, 30)
        grid.addWidget(self._spb_cols, 10, 1)

        grid.addWidget(lbl(_t("Zeilen")), 11, 0)
        self._spb_rows = spb(5, 2, 30)
        grid.addWidget(self._spb_rows, 11, 1)

        grid.setRowStretch(12, 1)

        return frame

    def _build_controls_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("surfaceMapControls")
        frame.setFrameShape(QFrame.Shape.StyledPanel)

        hl = QHBoxLayout(frame)
        hl.setContentsMargins(8, 6, 8, 6)
        hl.setSpacing(6)

        self._btn_start = QPushButton(_t("▶  START SCAN"))
        self._btn_start.setMinimumHeight(45)
        self._btn_start.setMinimumWidth(160)
        self._btn_start.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_start.clicked.connect(self._start_scan)
        hl.addWidget(self._btn_start)

        self._btn_abort = QPushButton(_t("✕  ABBRUCH"))
        self._btn_abort.setMinimumHeight(45)
        self._btn_abort.setMinimumWidth(120)
        self._btn_abort.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_abort.setEnabled(False)
        self._btn_abort.clicked.connect(self._abort_scan)
        hl.addWidget(self._btn_abort)

        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setFormat("%v / %m Punkte")
        self._progress.setMinimumHeight(45)
        self._progress.setMinimumWidth(200)
        hl.addWidget(self._progress)

        hl.addStretch()

        return frame

    def _load_prefs(self):
        self._loading_prefs = True
        try:
            val = self._t.settings.get("surface_map_tool")
            if val is not None: self._spb_probe_tool.setValue(int(val))
            val = self._t.settings.get("surface_map_feed")
            if val is not None: self._dsb_feed.setValue(float(val))
            val = self._t.settings.get("surface_map_clearance")
            if val is not None: self._dsb_clearance.setValue(float(val))
            val = self._t.settings.get("surface_map_depth")
            if val is not None: self._dsb_depth.setValue(float(val))
            
            val = self._t.settings.get("surface_map_x_start")
            if val is not None: self._dsb_x_start.setValue(float(val))
            val = self._t.settings.get("surface_map_x_end")
            if val is not None: self._dsb_x_end.setValue(float(val))
            val = self._t.settings.get("surface_map_y_start")
            if val is not None: self._dsb_y_start.setValue(float(val))
            val = self._t.settings.get("surface_map_y_end")
            if val is not None: self._dsb_y_end.setValue(float(val))
            
            val = self._t.settings.get("surface_map_cols")
            if val is not None: self._spb_cols.setValue(int(val))
            val = self._t.settings.get("surface_map_rows")
            if val is not None: self._spb_rows.setValue(int(val))
        except Exception:
            pass
        finally:
            self._loading_prefs = False

    def _save_prefs(self, *args):
        if getattr(self, "_loading_prefs", False): return
        if not hasattr(self, "_spb_rows"): return
        self._t.settings.set("surface_map_tool", self._spb_probe_tool.value())
        self._t.settings.set("surface_map_feed", self._dsb_feed.value())
        self._t.settings.set("surface_map_clearance", self._dsb_clearance.value())
        self._t.settings.set("surface_map_depth", self._dsb_depth.value())
        self._t.settings.set("surface_map_x_start", self._dsb_x_start.value())
        self._t.settings.set("surface_map_x_end", self._dsb_x_end.value())
        self._t.settings.set("surface_map_y_start", self._dsb_y_start.value())
        self._t.settings.set("surface_map_y_end", self._dsb_y_end.value())
        self._t.settings.set("surface_map_cols", self._spb_cols.value())
        self._t.settings.set("surface_map_rows", self._spb_rows.value())
        self._t.settings.save()

    # ── Scan Control ──────────────────────────────────────────────────────────

    @Slot()
    def _start_scan(self):
        if self._scanning:
            return

        # Safety check: Is a tool loaded and is it the correct probe tool?
        current_tool = self._t.poller.stat.tool_in_spindle
        target_probe_tool = self._spb_probe_tool.value()

        if current_tool == 0:
            self._t._status(_t("Surface Map: Abgebrochen – Kein Werkzeug geladen (T0)"), error=True)
            return

        if current_tool != target_probe_tool:
            self._t._status(_t(f"Surface Map: Abgebrochen – T{current_tool} ist nicht das konfigurierte Taster-Werkzeug (T{target_probe_tool})"), error=True)
            return

        x0 = self._dsb_x_start.value()
        x1 = self._dsb_x_end.value()
        y0 = self._dsb_y_start.value()
        y1 = self._dsb_y_end.value()
        cols = self._spb_cols.value()
        rows = self._spb_rows.value()
        feed = self._dsb_feed.value()
        clearance = self._dsb_clearance.value()
        depth = self._dsb_depth.value()

        if x1 <= x0:
            self._t._status(_t("Surface Map: X End muss größer als X Start sein"), error=True)
            return
        if y1 <= y0:
            self._t._status(_t("Surface Map: Y End muss größer als Y Start sein"), error=True)
            return

        self._total_points = cols * rows
        self._progress.setRange(0, self._total_points)
        self._progress.setValue(0)
        self._btn_start.setEnabled(False)
        self._btn_abort.setEnabled(True)
        self._scanning = True
        self._scan_interp_was_idle = False

        # Pre-seed var file so LinuxCNC writes these params back at M2
        self._seed_var_params(cols * rows)

        # Capture mtime AFTER seeding so we only react to changes from the scan
        path = self._var_file_path()
        try:
            self._var_mtime = os.path.getmtime(path) if path else 0.0
        except OSError:
            self._var_mtime = 0.0

        # Write a small wrapper program so M2 flushes params to the var file.
        # MDI-only calls never write to the var file (no M2 executed).
        wrapper = (
            f"O<before_probe> call\n"
            f"O<surface_map_probe> call "
            f"[{x0}] [{x1}] [{y0}] [{y1}] "
            f"[{cols}] [{rows}] [{feed}] [{clearance}] [{depth}]\n"
            f"O<after_probe> call\n"
            f"M2\n"
        )
        cfg_dir = os.path.dirname(self._t.ini_path) if self._t.ini_path else "/tmp"
        sub_dir = None
        if self._t.ini:
            raw = self._t.ini.find("RS274NGC", "SUBROUTINE_PATH") or ""
            for candidate in raw.split(":"):
                candidate = os.path.expanduser(candidate.strip())
                if candidate and os.path.isdir(candidate):
                    sub_dir = candidate
                    break
        if sub_dir is None:
            fallback = os.path.join(cfg_dir, "subroutines")
            sub_dir = fallback if os.path.isdir(fallback) else cfg_dir
        wrapper_path = os.path.join(sub_dir, "_surface_map_run.ngc")
        try:
            with open(wrapper_path, "w") as fh:
                fh.write(wrapper)
        except OSError as e:
            self._t._status(f"Surface Map: Konnte Wrapper nicht schreiben: {e}", error=True)
            self._reset_scan_state()
            return

        try:
            # Clear internal state before opening program to prevent old flags from flushing
            self._t.cmd.mode(linuxcnc.MODE_MDI)
            self._t.cmd.wait_complete()
            self._t.cmd.mdi("#1998=0")
            self._t.cmd.wait_complete()
            self._t.cmd.mdi("#1999=0")
            self._t.cmd.wait_complete()

            self._t.cmd.mode(linuxcnc.MODE_AUTO)
            self._t.cmd.wait_complete()
            self._t.cmd.program_open(wrapper_path)
            self._t.cmd.auto(linuxcnc.AUTO_RUN, 0)
        except Exception as e:
            self._t._status(f"Surface Map: Startfehler: {e}", error=True)
            self._reset_scan_state()
            return

        self._t._status(_t(f"Surface Map: Scan gestartet ({cols}×{rows} = {self._total_points} Punkte)"))

        self._poll_timer = QTimer(self._t)
        self._poll_timer.timeout.connect(self._poll_progress)
        self._poll_timer.start(800)

    @Slot()
    def _abort_scan(self):
        if self._poll_timer:
            self._poll_timer.stop()
        try:
            self._t.cmd.abort()
        except Exception:
            pass
        self._t._status(_t("Surface Map: Scan abgebrochen"), error=True)
        self._reset_scan_state()

    def _reset_scan_state(self):
        self._scanning = False
        self._btn_start.setEnabled(True)
        self._btn_abort.setEnabled(False)
        if self._poll_timer:
            self._poll_timer.stop()
            self._poll_timer = None

    # ── Polling ───────────────────────────────────────────────────────────────

    @Slot()
    def _poll_progress(self):
        if not self._scanning:
            return

        path = self._var_file_path()

        # Track INTERP state transition: idle → running → idle
        try:
            interp = self._t.poller.stat.interp_state
            if not self._scan_interp_was_idle:
                if interp != linuxcnc.INTERP_IDLE:
                    self._scan_interp_was_idle = True
            elif interp == linuxcnc.INTERP_IDLE:
                # Machine returned to idle — give OS 400ms to flush var file,
                # then read once and complete regardless of done flag.
                self._poll_timer.stop()
                QTimer.singleShot(400, self._finish_from_var_file)
                return
        except Exception:
            pass

        # Primary: mtime-based detection (done flag = 1)
        if path:
            try:
                mtime = os.path.getmtime(path)
                if mtime != self._var_mtime:
                    self._var_mtime = mtime
                    params = self._read_var_file(path)
                    progress = int(params.get(1998, 0))
                    self._progress.setValue(progress)
                    if int(params.get(1999, 0)) == 1:
                        self._poll_timer.stop()
                        self._on_scan_complete(params)
            except OSError:
                pass

    @Slot()
    def _finish_from_var_file(self):
        """Called after a short delay once INTERP went idle — reads final var file."""
        if not self._scanning:
            return
        path = self._var_file_path()
        if path:
            params = self._read_var_file(path)
            self._on_scan_complete(params)

    def _on_scan_complete(self, params: dict):
        cols = self._spb_cols.value()
        rows = self._spb_rows.value()
        x0   = self._dsb_x_start.value()
        x1   = self._dsb_x_end.value()
        y0   = self._dsb_y_start.value()
        y1   = self._dsb_y_end.value()

        # Build grid [row][col] from flat params
        grid = []
        for row in range(rows):
            grid_row = []
            for col in range(cols):
                z = params.get(2000 + row * cols + col, 0.0)
                grid_row.append(z)
            grid.append(grid_row)

        x_step = (x1 - x0) / max(cols - 1, 1)
        y_step = (y1 - y0) / max(rows - 1, 1)
        x_coords = [x0 + col * x_step for col in range(cols)]
        y_coords = [y0 + row * y_step for row in range(rows)]

        self._heatmap.set_data(grid, x_coords, y_coords)

        flat = [z for row in grid for z in row]
        z_min = min(flat)
        z_max = max(flat)
        z_delta = z_max - z_min
        self._lbl_stats.setText(
            f"Min Z: {z_min:.3f} mm    Max Z: {z_max:.3f} mm    Δ: {z_delta:.3f} mm"
        )
        self._progress.setValue(self._total_points)
        self._t._status(_t(f"Surface Map: Scan abgeschlossen — Δ Z = {z_delta:.3f} mm"))
        self._reset_scan_state()

    # ── Var File ──────────────────────────────────────────────────────────────

    def _seed_var_params(self, n_points: int):
        """Pre-seed surface map parameters in the var file.

        LinuxCNC only writes back parameters that already exist in the var file.
        We seed 1990-1999 (metadata/flags) and 2000..2000+n_points-1 (Z values).
        """
        path = self._var_file_path()
        if not path:
            return
        needed = list(range(1990, 2000)) + list(range(2000, 2000 + n_points))
        try:
            with open(path, "r") as f:
                lines = f.readlines()
            params: dict[int, str] = {}
            for line in lines:
                parts = line.split()
                if len(parts) >= 2 and parts[0].lstrip("-").isdigit():
                    params[int(parts[0])] = line
            for p in needed:
                if p not in params:
                    params[p] = f"{p}\t0.000000\n"
                    
            # Crucial: Always clear progress and done flags before a new scan!
            # Otherwise, leftover flags from a previous scan will prematurely stop the new scan
            params[1998] = "1998\t0.000000\n"
            params[1999] = "1999\t0.000000\n"

            with open(path, "w") as f:
                for key in sorted(params):
                    f.write(params[key])
        except OSError:
            pass

    def _var_file_path(self) -> str | None:
        if not self._t.ini or not self._t.ini_path:
            return None
        var_file = self._t.ini.find("RS274NGC", "PARAMETER_FILE")
        if not var_file:
            return None
        if not os.path.isabs(var_file):
            var_file = os.path.join(os.path.dirname(self._t.ini_path), var_file)
        return var_file if os.path.exists(var_file) else None

    @staticmethod
    def _read_var_file(path: str) -> dict:
        params = {}
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith(";"):
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            params[int(parts[0])] = float(parts[1])
                        except (ValueError, IndexError):
                            pass
        except OSError:
            pass
        return params
