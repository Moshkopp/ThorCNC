"""
ThorCNC Main Window
Lädt die aus probe_basic.ui konvertierte UI und verbindet alle Widgets
direkt mit LinuxCNC über eigene Implementierungen (kein qtpyvcp).
"""
import os
import linuxcnc
from PySide6.QtWidgets import QMainWindow, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, QObject, Slot
from PySide6.QtUiTools import QUiLoader

from .status_poller import StatusPoller
from .gcode_parser import parse_file
from .widgets.gcode_view import GCodeView
from .widgets.backplot import BackplotWidget

_DIR = os.path.dirname(__file__)


class ThorCNC(QObject):
    """
    Controller-Klasse. Das geladene QMainWindow aus probe_basic.ui IS das Fenster.
    """

    def __init__(self, ini_path: str = "", parent=None):
        super().__init__(parent)

        self.ini_path = ini_path or os.environ.get("INI_FILE_NAME", "")
        self.ini = linuxcnc.ini(self.ini_path) if self.ini_path else None
        self.cmd = linuxcnc.command()
        
        self._jog_velocity = 100.0  # mm/min or inch/min default
        self._jog_increment = 0.0   # 0.0 means continuous
        
        # State tracking for dynamic run buttons
        self._is_machine_on = False
        self._has_file = False
        self._interp_state = linuxcnc.INTERP_IDLE
        self._is_spindle_running = False
        self._user_program = ""   # Vom User explizit geladenes Hauptprogramm
        self._load_settings()
        self._load_ui()
        self._replace_custom_widgets()
        self._restore_window_state()
        self._setup_dro()
        self._hal_comp = None
        self._setup_hal()
        self._setup_poller()
        self._setup_file_manager()
        self._setup_tool_table()
        self._setup_offsets_tab()
        self._setup_settings_tab()
        self._connect_signals()
        self._apply_ini_settings()
    # ── Settings & State ──────────────────────────────────────────────────────
    
    def _load_settings(self):
        from .settings import SettingsManager
        prefs_file = "thorcnc.prefs"
        ini_dir = os.path.dirname(self.ini_path) if self.ini_path else os.path.expanduser("~")
        if self.ini:
            p = self.ini.find("DISPLAY", "PREFS_FILE")
            if p:
                prefs_file = p
        
        prefs_path = os.path.expanduser(prefs_file)
        if not os.path.isabs(prefs_path):
            prefs_path = os.path.abspath(os.path.join(ini_dir, prefs_path))
            
        self.settings = SettingsManager(prefs_path)
        
        if self.settings.is_new:
            self._warn_missing_prefs = True
        else:
            self._warn_missing_prefs = False

    def _restore_window_state(self):
        from PySide6.QtCore import QByteArray
        geom = self.settings.get("window_geometry")
        state = self.settings.get("window_state")
        
        if geom:
            self.ui.restoreGeometry(QByteArray.fromHex(geom.encode()))
        if state:
            self.ui.restoreState(QByteArray.fromHex(state.encode()))
            
        # Splitter main
        ms_state = self.settings.get("main_splitter")
        if ms_state:
            from PySide6.QtWidgets import QSplitter
            sp = self._w(QSplitter, "mainSplitter")
            if sp: sp.restoreState(QByteArray.fromHex(ms_state.encode()))
            
        fs_state = self.settings.get("file_splitter")
        if fs_state:
            from PySide6.QtWidgets import QSplitter
            sp = self._w(QSplitter, "fileSplitter")
            if sp: sp.restoreState(QByteArray.fromHex(fs_state.encode()))
            
        if not geom and not state:
            self.ui.showMaximized()

    # ── UI laden ──────────────────────────────────────────────────────────────

    def _load_ui(self):
        loader = QUiLoader()
        ui_file = os.path.join(_DIR, "thorcnc.ui")
        # Kein Parent → QMainWindow bleibt eigenständig, kein Doppel-Wrap
        self.ui = loader.load(ui_file)

    def _replace_custom_widgets(self):
        """GCodeEditor und VTKBackPlot durch eigene Impl. ersetzen."""
        from PySide6.QtWidgets import (QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
                                       QPushButton, QStackedWidget, QLineEdit,
                                       QListWidget, QSizePolicy)

        # ── GCode-Panel: Buttons sind fix in der UI (gcodeToggleBar)
        #    Hier nur den gcodeEditor-Placeholder durch QStackedWidget ersetzen
        old_gcode = self.ui.findChild(QWidget, "gcodeEditor")
        parent_gc = old_gcode.parent() if old_gcode else None

        # Stack: Seite 0 = GCodeView, Seite 1 = MDI-Page
        self._gcode_mdi_stack = QStackedWidget()
        self._gcode_mdi_stack.setObjectName("gcodeEditor")

        # Seite 0: GCodeView
        self.gcode_view = GCodeView()
        self._gcode_mdi_stack.addWidget(self.gcode_view)

        # Seite 1: MDI-Page
        mdi_page = QWidget()
        mdi_page_lay = QVBoxLayout(mdi_page)
        mdi_page_lay.setContentsMargins(4, 4, 4, 4)
        mdi_page_lay.setSpacing(6)

        self._mdi_input = QLineEdit()
        self._mdi_input.setObjectName("mdiEntry")
        self._mdi_input.setPlaceholderText("MDI COMMAND...")
        self._mdi_input.setMinimumHeight(40)
        self._mdi_input.setStyleSheet(
            "QLineEdit { background:#1e1e1e; color:#eee; border:1px solid #555;"
            " border-radius:4px; font-size:13pt; padding:2px 8px; }")
        self._mdi_input.returnPressed.connect(
            lambda: self._send_mdi(self._mdi_input.text(), self._mdi_input))

        self._mdi_history_widget = QListWidget()
        self._mdi_history_widget.setObjectName("mdiHistory")
        self._mdi_history_widget.setStyleSheet(
            "QListWidget { background:#1a1a1a; color:#ccc; border:1px solid #444;"
            " font-size:12pt; }"
            "QListWidget::item:hover { background:#2a2a2a; }"
            "QListWidget::item:selected { background:#2d5fa8; color:white; }")
        self._mdi_history_widget.itemDoubleClicked.connect(
            lambda item: self._mdi_input.setText(item.text()))

        mdi_page_lay.addWidget(self._mdi_input)
        mdi_page_lay.addWidget(self._mdi_history_widget)
        self._gcode_mdi_stack.addWidget(mdi_page)

        # UI-Buttons verdrahten (aus der UI-Datei)
        self._btn_show_gcode = self.ui.findChild(QPushButton, "btn_gcode_view")
        self._btn_show_mdi   = self.ui.findChild(QPushButton, "btn_mdi_view")
        if self._btn_show_gcode:
            self._btn_show_gcode.clicked.connect(lambda: self._switch_gcode_panel(0))
        if self._btn_show_mdi:
            self._btn_show_mdi.clicked.connect(lambda: self._switch_gcode_panel(1))

        # Placeholder durch Stack ersetzen (Stack liegt in einem QVBoxLayout)
        if parent_gc and parent_gc.layout():
            lay = parent_gc.layout()
            idx = lay.indexOf(old_gcode)
            lay.removeWidget(old_gcode)
            old_gcode.deleteLater()
            lay.insertWidget(idx, self._gcode_mdi_stack)

        # MDI-History aus Settings laden
        for entry in self.settings.get("mdi_history", []):
            self._mdi_history_widget.addItem(entry)

        self._switch_gcode_panel(0)

        # ── Backplot mit View-Toolbar ─────────────────────────────────────────
        old_vtk = self.ui.findChild(QWidget, "vtk")
        parent_vtk = old_vtk.parent() if old_vtk else None

        _aa_on = self.settings.get("backplot_antialiasing", True)
        _msaa  = self.settings.get("backplot_msaa_samples", 4) if _aa_on else 0
        self.backplot = BackplotWidget(msaa_samples=_msaa)
        self.backplot.setObjectName("vtk")

        # Buttons direkt in BackplotWidget's eingebaute Toolbar einfügen
        # (kein Wrapper-Widget → kein GLViewWidget-Reparenting-Problem)
        tb_lay = self.backplot.toolbar_layout()
        _view_style = ("QPushButton { background:#333; color:#ccc; border-radius:4px;"
                       " font-weight:bold; padding:1px 10px; }"
                       "QPushButton:hover { background:#555; }")
        # View-Buttons links (vor dem Stretch)
        tb_lay.takeAt(0)   # den initialen Stretch kurz rausnehmen (wird unten neu eingefügt)
        for label, fn in (("ISO",        self.backplot.set_view_iso),
                          ("TOP",        self.backplot.set_view_z),
                          ("FRONT",      self.backplot.set_view_y),
                          ("SIDE",       self.backplot.set_view_x),
                          ("CLR TRAIL",  self.backplot.clear_trail)):
            b = QPushButton(label)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet(_view_style)
            b.clicked.connect(fn)
            tb_lay.addWidget(b)
        tb_lay.addStretch()   # Stretch wieder einfügen (trennt links von rechts)

        self._btn_go_to_home = QPushButton("GO TO HOME")
        self._btn_go_to_home.setObjectName("btn_go_to_home")
        self._btn_go_to_home.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_go_to_home.clicked.connect(self._go_to_home)
        self._update_goto_home_style(all_homed=False)
        tb_lay.addWidget(self._btn_go_to_home)

        if parent_vtk:
            if isinstance(parent_vtk, QSplitter):
                idx = parent_vtk.indexOf(old_vtk)
                parent_vtk.replaceWidget(idx, self.backplot)
            elif parent_vtk.layout():
                lay = parent_vtk.layout()
                idx = lay.indexOf(old_vtk)
                lay.removeWidget(old_vtk)
                lay.insertWidget(idx, self.backplot)
            old_vtk.deleteLater()

        bpm = self.settings.get("backplot_view")
        if bpm:
            self.backplot.set_view_opts(bpm)

    def _switch_gcode_panel(self, idx: int):
        self._gcode_mdi_stack.setCurrentIndex(idx)
        active   = "background:#2d5fa8; color:white;"
        inactive = "background:#2a2a2a; color:#aaa;"
        for b, active_idx in ((self._btn_show_gcode, 0), (self._btn_show_mdi, 1)):
            if b is None:
                continue
            b.setChecked(idx == active_idx)
            b.setStyleSheet(
                f"QPushButton {{ {active if idx == active_idx else inactive} border-radius:4px;"
                " font-weight:bold; font-size:11pt; padding:2px 12px; }")

    def _update_goto_home_style(self, all_homed: bool):
        if not hasattr(self, "_btn_go_to_home"):
            return
        in_auto = getattr(self, "_current_mode", None) == linuxcnc.MODE_AUTO
        if in_auto:
            self._btn_go_to_home.setEnabled(False)
            self._btn_go_to_home.setStyleSheet(
                "QPushButton { background:#444; color:#888; border-radius:4px;"
                " font-weight:bold; padding:1px 10px; }")
        elif all_homed:
            self._btn_go_to_home.setEnabled(True)
            self._btn_go_to_home.setStyleSheet(
                "QPushButton { background:#2d862d; color:white; border-radius:4px;"
                " font-weight:bold; padding:1px 10px; }"
                "QPushButton:hover { background:#3aa63a; }")
        else:
            self._btn_go_to_home.setEnabled(True)
            self._btn_go_to_home.setStyleSheet(
                "QPushButton { background:#c0392b; color:white; border-radius:4px;"
                " font-weight:bold; padding:1px 10px; }"
                "QPushButton:hover { background:#e74c3c; }")

    def _setup_dro(self):
        """DRO-Panel im probe_basic-Stil: Achsname | WORK | MACHINE | REF-Button."""
        from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QWidget,
                                       QFrame, QPushButton, QSizePolicy, QComboBox)

        container = self.ui.findChild(QHBoxLayout, "dro_display_layout")
        if not container:
            return

        self._dro_work    = {}   # axis → QLabel (relative/work)
        self._dro_machine = {}   # axis → QLabel (absolute/machine)
        self._dro_ref_btn = {}   # axis → QPushButton

        # Rahmen-Widget, füllt den ganzen DRO-Frame
        wrapper = QWidget()
        wrapper.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        vbox = QVBoxLayout(wrapper)
        vbox.setContentsMargins(8, 4, 8, 4)
        vbox.setSpacing(4)

        zero_btn_style = (
            "QPushButton { font: bold 11pt 'Bebas Kai'; border-radius:4px;"
            " background: rgb(52, 101, 164); color: white; min-width:54px; }"
            "QPushButton:hover { background: rgb(70, 130, 200); }"
            "QPushButton:pressed { background: rgb(32, 74, 135); }")
        ref_btn_style = (
            "QPushButton { font: bold 10pt 'Bebas Kai'; border-radius:4px;"
            " background: rgb(60,60,60); color: rgb(186,189,182); min-width:54px; }"
            "QPushButton:hover { background: rgb(80,80,80); }")

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QWidget()
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        hdr_style = "color: rgb(238,238,236); font: bold 13pt 'Bebas Kai'; padding: 0 4px;"

        # ZERO ALL button (links)
        btn_zero_all = QPushButton("ZERO\nALL")
        btn_zero_all.setFixedWidth(54)
        btn_zero_all.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        btn_zero_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_zero_all.setStyleSheet(zero_btn_style)
        btn_zero_all.clicked.connect(lambda: self._zero_axis("ALL"))
        hl.addWidget(btn_zero_all)

        # AXIS header
        lbl_axis_hdr = QLabel("AXIS")
        lbl_axis_hdr.setFixedWidth(48)
        lbl_axis_hdr.setStyleSheet(hdr_style)
        lbl_axis_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(lbl_axis_hdr)

        # WCS ComboBox
        self._wcs_combo = QComboBox()
        self._wcs_combo.setFixedWidth(120)
        self._wcs_combo.setFixedHeight(30)
        self._wcs_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for label, index in [("G54", 1), ("G55", 2), ("G56", 3), ("G57", 4),
                              ("G58", 5), ("G59", 6), ("G59.1", 7), ("G59.2", 8), ("G59.3", 9)]:
            self._wcs_combo.addItem(label, userData=index)
        self._wcs_combo.setStyleSheet(
            "QComboBox { font: bold 13pt 'Bebas Kai'; color: rgb(238,238,236);"
            " background: rgb(60,68,70); border:1px solid rgb(186,189,182);"
            " border-radius:4px; padding: 0 6px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background: rgb(46,52,54);"
            " color: rgb(238,238,236); selection-background-color: rgb(78,154,6); }")
        self._wcs_combo.currentIndexChanged.connect(self._on_wcs_combo_changed)
        hl.addWidget(self._wcs_combo)

        # MACHINE header
        lbl_mach_hdr = QLabel("MACHINE")
        lbl_mach_hdr.setFixedWidth(120)
        lbl_mach_hdr.setStyleSheet(hdr_style)
        lbl_mach_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(lbl_mach_hdr)

        hl.addStretch()

        # REF ALL button (rechts)
        btn_ref_all = QPushButton("REF ALL")
        btn_ref_all.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        btn_ref_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_ref_all.setStyleSheet(
            "QPushButton { font: bold 11pt 'Bebas Kai'; border-radius:4px;"
            " background: rgb(78,154,6); color: white; }"
            "QPushButton:hover { background: rgb(100,180,20); }")
        btn_ref_all.clicked.connect(self._home_all)
        hl.addWidget(btn_ref_all)
        vbox.addWidget(hdr)

        # ── Separator ─────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: rgb(186,189,182);")
        vbox.addWidget(sep)

        # ── Achsen-Zeilen ─────────────────────────────────────────────────────
        dro_style_work    = ("font: 16pt 'Bebas Kai'; color: #00dd55;"
                             " background: rgb(30,34,36); border-radius:3px;"
                             " padding: 0 6px;")
        dro_style_machine = ("font: 14pt 'Bebas Kai'; color: #aaaaaa;"
                             " background: rgb(30,34,36); border-radius:3px;"
                             " padding: 0 6px;")

        for axis, joint in (("X", 0), ("Y", 1), ("Z", 2)):
            row = QWidget()
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)

            # ZERO button (links)
            btn_zero = QPushButton(f"ZERO\n{axis}")
            btn_zero.setFixedWidth(54)
            btn_zero.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            btn_zero.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn_zero.setStyleSheet(zero_btn_style)
            btn_zero.clicked.connect(lambda _=False, a=axis: self._zero_axis(a))
            hl.addWidget(btn_zero)

            # Achsbuchstabe
            lbl_axis = QLabel(axis)
            lbl_axis.setFixedWidth(48)
            lbl_axis.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_axis.setStyleSheet("font: bold 18pt 'Bebas Kai'; color: rgb(238,238,236);")
            hl.addWidget(lbl_axis)

            # WORK position
            lbl_work = QLabel("+0.000")
            lbl_work.setFixedWidth(120)
            lbl_work.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            lbl_work.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl_work.setStyleSheet(dro_style_work)
            hl.addWidget(lbl_work)

            # MACHINE position
            lbl_mach = QLabel("+0.000")
            lbl_mach.setFixedWidth(120)
            lbl_mach.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            lbl_mach.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl_mach.setStyleSheet(dro_style_machine)
            hl.addWidget(lbl_mach)

            hl.addStretch()

            # REF button
            btn_ref = QPushButton(f"REF {axis}")
            btn_ref.setFixedWidth(54)
            btn_ref.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            btn_ref.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn_ref.setStyleSheet(
                "QPushButton { font: bold 10pt 'Bebas Kai'; border-radius:4px;"
                " background: rgb(60,60,60); color: rgb(186,189,182); }"
                "QPushButton:hover { background: rgb(80,80,80); }"
                "QPushButton[homed=true] { background: rgb(78,154,6); color: white; }")
            btn_ref.clicked.connect(lambda _=False, j=joint: self._home_joint(j))
            hl.addWidget(btn_ref)

            vbox.addWidget(row)
            self._dro_work[axis]    = lbl_work
            self._dro_machine[axis] = lbl_mach
            self._dro_ref_btn[axis] = btn_ref

        container.addWidget(wrapper)

    @Slot(list)
    def _on_g5x_offset(self, g5x: list):
        """WCS-Offset geändert → DRO neu berechnen + Backplot-Kreuz verschieben.
        G59.3 (Index 9) wird im Backplot ignoriert – wird nur für Messroutinen
        verwendet und soll den Backplot des Hauptprogramms nicht verschieben."""
        self._refresh_dro()
        if self.poller.stat.g5x_index != 9:
            self.backplot.set_wcs_origin(g5x[0], g5x[1], g5x[2])

    @Slot(int)
    def _on_g5x_index(self, g5x_index: int):
        """LinuxCNC WCS geändert → Combo synchronisieren (ohne Signal-Loop)."""
        combo = getattr(self, "_wcs_combo", None)
        if combo is None:
            return
        for i in range(combo.count()):
            if combo.itemData(i) == g5x_index:
                combo.blockSignals(True)
                combo.setCurrentIndex(i)
                combo.blockSignals(False)
                break

    def _zero_axis(self, axis: str):
        """Setzt den WCS-Nullpunkt für die Achse(n) anhand der ComboBox-Auswahl."""
        g5x_index = self._wcs_combo.currentData()  # 1=G54, 2=G55, …
        axis_map = {"X": "X0", "Y": "Y0", "Z": "Z0", "ALL": "X0 Y0 Z0"}
        coords = axis_map.get(axis, "X0 Y0 Z0")
        wcs_name = self._wcs_combo.currentText()
        try:
            self.cmd.mode(linuxcnc.MODE_MDI)
            self.cmd.wait_complete()
            self.cmd.mdi(f"G10 L20 P{g5x_index} {coords}")
            self.cmd.wait_complete()
            self.cmd.mode(linuxcnc.MODE_MANUAL)
            self._status(f"ZERO {axis} → {wcs_name}")
        except Exception:
            pass

    def _on_wcs_combo_changed(self, index):
        """WCS-Auswahl → G54..G59.3 per MDI senden."""
        wcs = self._wcs_combo.itemText(index)
        try:
            self.cmd.mode(linuxcnc.MODE_MDI)
            self.cmd.wait_complete()
            self.cmd.mdi(wcs)
            self.cmd.wait_complete()
            self.cmd.mode(linuxcnc.MODE_MANUAL)
        except Exception:
            pass

    def _apply_ini_settings(self):
        name = "ThorCNC"
        if self.ini:
            name = self.ini.find("EMC", "MACHINE") or name
        self.ui.setWindowTitle(name)
        self._setup_jog_display()
        self._apply_machine_envelope()

    def _apply_machine_envelope(self):
        if not self.ini:
            return
        def lim(axis, key, default):
            v = self.ini.find(f"AXIS_{axis}", key)
            return float(v) if v else default

        # Envelope zeigt nutzbaren Arbeitsbereich (0 bis MAX bzw. MIN bis 0)
        # nicht die technischen Soft-Limits mit Homing-Überfahrt
        self.backplot.set_machine_envelope(
            x_min=lim("X", "MIN_LIMIT", 0), x_max=lim("X", "MAX_LIMIT", 600),
            y_min=lim("Y", "MIN_LIMIT", 0), y_max=lim("Y", "MAX_LIMIT", 500),
            z_min=lim("Z", "MIN_LIMIT", -200), z_max=lim("Z", "MAX_LIMIT", 0),
        )

    def _setup_jog_display(self):
        """Jog-Display-Page aus INI setzen, Icons auf Buttons legen."""
        from PySide6.QtWidgets import QStackedWidget, QPushButton

        # ── Richtige Seite im jogDisplay ──────────────────────────────────────
        coords = ""
        if self.ini:
            coords = (self.ini.find("TRAJ", "COORDINATES") or
                      self.ini.find("DISPLAY", "GEOMETRY") or "XYZ").upper().replace(" ", "")

        page_map = {"XYZ": 0, "XYZA": 1, "XYZAB": 2, "XYZAC": 3, "XYZBC": 4, "XYZABC": 5}
        page = page_map.get(coords, 0)

        jog_stack = self.ui.findChild(QStackedWidget, "jogDisplay")
        if jog_stack:
            jog_stack.setCurrentIndex(page)

        # ── Icons auf XYZ-Buttons (_3 Suffix = jog_xyz Seite) ─────────────────
        btn_icons = {
            "z_plus_jogbutton_3":  ("Z", "up"),
            "z_minus_jogbutton_3": ("Z", "down"),
            "y_plus_jogbutton_3":  ("Y", "up"),
            "y_minus_jogbutton_3": ("Y", "down"),
            "x_plus_jogbutton_3":  ("X", "right"),
            "x_minus_jogbutton_3": ("X", "left"),
        }
        for btn_name, (axis, direction) in btn_icons.items():
            b = self.ui.findChild(QPushButton, btn_name)
            if b:
                b.setIcon(self._make_jog_icon(axis, direction))
                b.setIconSize(b.minimumSize())
                b.setText("")

    @staticmethod
    def _make_jog_icon(axis: str, direction: str, size: int = 42):
        """Zeichnet ein Jog-Button-Icon: farbiger Ring + Chevron-Pfeil + Achsbeschriftung."""
        from PySide6.QtGui import (QPixmap, QPainter, QColor, QPolygonF,
                                   QFont, QPen, QBrush, QRadialGradient,
                                   QConicalGradient, QPainterPath)
        from PySide6.QtCore import QPointF, QRectF

        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy = size / 2.0, size / 2.0
        r = size / 2.0 - 1.5

        # Achsfarben (passend zum Backplot-Koordinatensystem)
        axis_colors = {
            "X": QColor(210, 55,  55),   # rot
            "Y": QColor(45,  190, 75),   # grün
            "Z": QColor(55,  120, 215),  # blau
        }
        ac = axis_colors.get(axis, QColor(160, 160, 160))

        # ── Hintergrund: subtiler Radial-Gradient ─────────────────────────
        bg = QRadialGradient(cx, cy, r)
        bg.setColorAt(0.0, QColor(52, 57, 62))
        bg.setColorAt(1.0, QColor(28, 31, 34))
        p.setBrush(QBrush(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # ── Farbiger Ring (Achsfarbe, halb-transparent) ───────────────────
        ring_pen = QPen(ac, 2.2)
        ring_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(ring_pen)
        p.drawEllipse(QPointF(cx, cy), r, r)

        # ── Chevron-Pfeil ─────────────────────────────────────────────────
        # Zwei dicke Linien bilden einen ">"-Pfeil (kein Filled-Polygon)
        sign = "+" if direction in ("up", "right") else "−"
        arm  = size * 0.20   # halbe Schenkel-Länge
        tip_offset = size * 0.10   # wie weit die Spitze von der Mitte entfernt ist

        # Chevron-Spitze und zwei Schenkel-Endpunkte
        if direction == "up":
            tip = QPointF(cx,         cy - size * 0.18)
            p1  = QPointF(cx - arm,   cy + tip_offset)
            p2  = QPointF(cx + arm,   cy + tip_offset)
        elif direction == "down":
            tip = QPointF(cx,         cy + size * 0.18)
            p1  = QPointF(cx - arm,   cy - tip_offset)
            p2  = QPointF(cx + arm,   cy - tip_offset)
        elif direction == "right":
            tip = QPointF(cx + size * 0.18, cy)
            p1  = QPointF(cx - tip_offset,  cy - arm)
            p2  = QPointF(cx - tip_offset,  cy + arm)
        else:  # left
            tip = QPointF(cx - size * 0.18, cy)
            p1  = QPointF(cx + tip_offset,  cy - arm)
            p2  = QPointF(cx + tip_offset,  cy + arm)

        arrow_pen = QPen(ac.lighter(140), size * 0.11)
        arrow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        arrow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(arrow_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        path = QPainterPath()
        path.moveTo(p1)
        path.lineTo(tip)
        path.lineTo(p2)
        p.drawPath(path)

        # ── Achsbeschriftung (Achse + Vorzeichen, Gegenseite des Pfeils) ──
        font = QFont("Monospace", max(6, size // 8))
        font.setBold(True)
        p.setFont(font)
        label_color = ac.lighter(160)
        label_color.setAlpha(220)
        p.setPen(QPen(label_color))

        if direction == "up":
            label_rect = QRectF(0, size * 0.68, size, size * 0.28)
        elif direction == "down":
            label_rect = QRectF(0, size * 0.04, size, size * 0.28)
        elif direction == "right":
            label_rect = QRectF(0, size * 0.04, size * 0.52, size)
        else:  # left
            label_rect = QRectF(size * 0.48, size * 0.04, size * 0.52, size)

        p.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, f"{axis}{sign}")

        p.end()
        from PySide6.QtGui import QIcon
        return QIcon(pix)

    # ── StatusPoller ──────────────────────────────────────────────────────────

    def _setup_poller(self):
        self.poller = StatusPoller(interval_ms=100, parent=self)

    def _setup_file_manager(self):
        from PySide6.QtWidgets import QTreeView, QTextBrowser, QPushButton, QFileSystemModel, QLabel
        from PySide6.QtCore import QDir
        import os

        tree = self._w(QTreeView, "fileManagerView")
        self._file_preview = self._w(QTextBrowser, "filePreviewArea")
        self._btn_load = self._w(QPushButton, "load_gcode_button")
        
        self._btn_nav_up = self._w(QPushButton, "btn_nav_up")
        self._btn_nav_home = self._w(QPushButton, "btn_nav_home")
        self._lbl_current_path = self._w(QLabel, "lbl_current_path")

        if not tree or not self._file_preview or not self._btn_load:
            return

        # Start directory from INI or default fallback
        start_dir = os.path.expanduser("~/linuxcnc/nc_files")
        if self.ini and self.ini_path:
            cfg_dir = self.ini.find("DISPLAY", "PROGRAM_PREFIX")
            if cfg_dir:
                cfg_dir = os.path.expanduser(cfg_dir)
                if not os.path.isabs(cfg_dir):
                    ini_dir = os.path.dirname(self.ini_path)
                    cfg_dir = os.path.abspath(os.path.join(ini_dir, cfg_dir))
                start_dir = cfg_dir
        
        if not os.path.exists(start_dir):
            try:
                os.makedirs(start_dir, exist_ok=True)
            except Exception:
                start_dir = os.path.expanduser("~/linuxcnc/nc_files")

        self._file_home_dir = start_dir

        self._fs_model = QFileSystemModel()
        self._fs_model.setRootPath(start_dir)
        self._fs_model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)

        tree.setModel(self._fs_model)
        
        # Hide unneeded columns for cleaner look
        tree.setColumnWidth(0, 300)
        tree.hideColumn(1) # size
        tree.hideColumn(2) # type
        tree.hideColumn(3) # date

        tree.selectionModel().selectionChanged.connect(self._on_file_selected)
        tree.doubleClicked.connect(self._on_file_double_clicked)
        
        if self._btn_nav_up:
            self._btn_nav_up.clicked.connect(self._nav_up)
        if self._btn_nav_home:
            self._btn_nav_home.clicked.connect(self._nav_home)
        
        self._selected_filepath = None
        self._btn_load.clicked.connect(self._load_selected_file)
        self._btn_load.setEnabled(False)
        
        last_dir = self.settings.get("last_file_dir")
        if last_dir and os.path.exists(last_dir):
            self._nav_set_dir(last_dir)
        else:
            self._nav_set_dir(start_dir)

    def _nav_set_dir(self, path: str):
        import os
        from PySide6.QtWidgets import QTreeView
        tree = self._w(QTreeView, "fileManagerView")
        if tree and os.path.isdir(path):
            tree.setRootIndex(self._fs_model.index(path))
            self._current_dir = path
            if self._lbl_current_path:
                self._lbl_current_path.setText(path)

    def _nav_up(self):
        import os
        if hasattr(self, "_current_dir"):
            parent_dir = os.path.dirname(self._current_dir)
            if parent_dir and parent_dir != self._current_dir:
                self._nav_set_dir(parent_dir)

    def _nav_home(self):
        if hasattr(self, "_file_home_dir"):
            self._nav_set_dir(self._file_home_dir)
            
    def _on_file_double_clicked(self, idx):
        import os
        path = self._fs_model.filePath(idx)
        if os.path.isdir(path):
            self._nav_set_dir(path)

    def _on_file_selected(self):
        from PySide6.QtWidgets import QTreeView
        import os
        tree = self._w(QTreeView, "fileManagerView")
        idx = tree.currentIndex()
        if not idx.isValid():
            return
            
        path = self._fs_model.filePath(idx)
        if os.path.isdir(path):
            self.settings.set("last_file_dir", path)
            self._selected_filepath = None
            self._btn_load.setEnabled(False)
            self._file_preview.setText("[ORDNER AUSGEWÄHLT]")
        else:
            self.settings.set("last_file_dir", os.path.dirname(path))
            self._selected_filepath = path
            self._btn_load.setEnabled(True)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    head = [next(f) for _ in range(50)]
                self._file_preview.setText("".join(head))
            except StopIteration:
                pass # EOF reached before 50 lines
            except Exception as e:
                self._file_preview.setText(f"Fehler beim Laden:\n{e}")

    def _load_selected_file(self):
        if self._selected_filepath:
            self._user_program = self._selected_filepath
            # Tell linuxcnc to open the program
            self.cmd.mode(linuxcnc.MODE_AUTO)
            self.cmd.wait_complete()
            self.cmd.program_open(self._selected_filepath)
            
            # Switch view back to MAIN
            from PySide6.QtWidgets import QTabWidget
            if tab := self._w(QTabWidget, "tabWidget"):
                tab.setCurrentIndex(0)

    def _setup_tool_table(self):
        from PySide6.QtWidgets import QTableWidget, QPushButton
        
        self.tool_table = self._w(QTableWidget, "toolTable")
        self.btn_add_tool = self._w(QPushButton, "btn_add_tool")
        self.btn_reload_tools = self._w(QPushButton, "btn_reload_tools")
        self.btn_save_tools = self._w(QPushButton, "btn_save_tools")

        if not self.tool_table:
            return

        # Path resolvieren
        self._tool_tbl_path = None
        if self.ini and self.ini_path:
            tbl_name = self.ini.find("EMCIO", "TOOL_TABLE")
            if tbl_name:
                import os
                if not os.path.isabs(tbl_name):
                    self._tool_tbl_path = os.path.abspath(os.path.join(os.path.dirname(self.ini_path), tbl_name))
                else:
                    self._tool_tbl_path = tbl_name

        if self.btn_add_tool:
            self.btn_add_tool.clicked.connect(self._add_tool)
        if self.btn_reload_tools:
            self.btn_reload_tools.clicked.connect(self._load_tool_table)
        if self.btn_save_tools:
            self.btn_save_tools.clicked.connect(self._save_tool_table)

        self._load_tool_table()
        
        # Restore tool table column widths
        tt_state = self.settings.get("tool_table_state")
        if tt_state:
            from PySide6.QtCore import QByteArray
            self.tool_table.horizontalHeader().restoreState(QByteArray.fromHex(tt_state.encode()))

    def _load_tool_table(self):
        import os, re
        from PySide6.QtWidgets import QTableWidgetItem
        if not self._tool_tbl_path or not os.path.exists(self._tool_tbl_path):
            return

        self.tool_table.setRowCount(0)
        try:
            with open(self._tool_tbl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith(";"): 
                        continue
                    
                    parts = line.split(";", 1)
                    data = parts[0].strip()
                    comment = parts[1].strip() if len(parts) > 1 else ""
                    
                    t = re.search(r'T(\d+)', data)
                    p = re.search(r'P(\d+)', data)
                    d = re.search(r'D([+-]?\d*\.\d+|\d+)', data)
                    z = re.search(r'Z([+-]?\d*\.\d+|\d+)', data)
                    
                    row = self.tool_table.rowCount()
                    self.tool_table.insertRow(row)
                    
                    self.tool_table.setItem(row, 0, QTableWidgetItem(t.group(1) if t else ""))
                    self.tool_table.setItem(row, 1, QTableWidgetItem(p.group(1) if p else ""))
                    self.tool_table.setItem(row, 2, QTableWidgetItem(d.group(1) if d else ""))
                    self.tool_table.setItem(row, 3, QTableWidgetItem(z.group(1) if z else ""))
                    self.tool_table.setItem(row, 4, QTableWidgetItem(comment))
        except Exception as e:
            self._status(f"Error loading tool table: {e}", error=True)

    def _add_tool(self):
        from PySide6.QtWidgets import QTableWidgetItem
        if not self.tool_table: return
        row = self.tool_table.rowCount()
        self.tool_table.insertRow(row)
        for c in range(5):
            self.tool_table.setItem(row, c, QTableWidgetItem(""))

    def _save_tool_table(self):
        if not self._tool_tbl_path or not self.tool_table:
            return
            
        lines = []
        for row in range(self.tool_table.rowCount()):
            t = self.tool_table.item(row, 0)
            p = self.tool_table.item(row, 1)
            d = self.tool_table.item(row, 2)
            z = self.tool_table.item(row, 3)
            c = self.tool_table.item(row, 4)
            
            ts = t.text().strip() if t and t.text().strip() else ""
            ps = p.text().strip() if p and p.text().strip() else ""
            ds = d.text().strip() if d and d.text().strip() else ""
            zs = z.text().strip() if z and z.text().strip() else ""
            cs = c.text().strip() if c and c.text().strip() else ""
            
            if not ts: continue # T is required
            
            # Format nicely
            parts = [f"T{ts}"]
            if ps: parts.append(f"P{ps}")
            if ds: parts.append(f"D{ds}")
            if zs: parts.append(f"Z{zs}")
            
            line = " ".join(parts)
            if cs:
                line += f" ;{cs}"
            lines.append(line)
            
        try:
            with open(self._tool_tbl_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
                
            # Reload tool table in LinuxCNC
            self.cmd.load_tool_table()
            self._status("Werkzeugtabelle gespeichert und neu geladen!")
        except Exception as e:
            self._status(f"Error saving tool table: {e}", error=True)

    # ── Settings Tab ──────────────────────────────────────────────────────────

    # Mapping: (spinbox_name, prefs_key, default_value)
    _TOOLSENSOR_FIELDS = [
        ("dsb_ts_wechsel_x",    "ts_wechsel_x",    0.0),
        ("dsb_ts_wechsel_y",    "ts_wechsel_y",    0.0),
        ("dsb_ts_wechsel_z",    "ts_wechsel_z",    0.0),
        ("dsb_ts_x",            "ts_x",            0.0),
        ("dsb_ts_y",            "ts_y",            0.0),
        ("dsb_ts_z",            "ts_z",            0.0),
        ("dsb_ts_spindle_zero", "ts_spindle_zero", 0.0),
        ("dsb_ts_max_probe",    "ts_max_probe",   50.0),
        ("dsb_ts_retract",      "ts_retract",      2.0),
        ("dsb_ts_search_vel",   "ts_search_vel", 100.0),
        ("dsb_ts_probe_vel",    "ts_probe_vel",   10.0),
    ]

    def _setup_hal(self):
        """Initialisiert die HAL-Komponente so früh wie möglich (Timing-Fix)."""
        try:
            import hal
            self._hal_comp = hal.component("thorcnc")
            
            # Pins für Tool-Sensor (aus Settings/VCP-Style)
            for _, key, _ in self._TOOLSENSOR_FIELDS:
                pin_name = key.replace("_", "-")
                self._hal_comp.newpin(pin_name, hal.HAL_FLOAT, hal.HAL_OUT)
            
            # Standard-Pins für Status & Kontrolle
            self._hal_comp.newpin("probe-sim",          hal.HAL_BIT,   hal.HAL_OUT)
            self._hal_comp.newpin("spindle-atspeed",    hal.HAL_BIT,   hal.HAL_IN)
            self._hal_comp.newpin("spindle-speed-actual", hal.HAL_FLOAT, hal.HAL_IN)
            self._hal_comp.newpin("spindle-load",       hal.HAL_FLOAT, hal.HAL_IN)
            
            # Pins für TsHW / Handrad Integration (falls gewünscht)
            self._hal_comp.newpin("jog-vel-final",      hal.HAL_FLOAT, hal.HAL_OUT)
            
            self._hal_comp.ready()
            self._status("HAL-Komponente 'thorcnc' bereit.")
            
            # Sim-Parameter + Net-Verbindung per halcmd (nur Simulation)
            if "sim" in self.ini_path.lower():
                import subprocess
                _hc = lambda *args: subprocess.run(["halcmd"] + list(args), capture_output=True)
                _hc("setp", "limit_speed.maxv", "600.0")
                _hc("setp", "spindle_mass.gain", "0.002")
                _hc("net", "spindle-at-speed",    "thorcnc.spindle-atspeed")
                _hc("net", "spindle-rpm-filtered", "thorcnc.spindle-speed-actual")
                
        except Exception as e:
            print(f"[ThorCNC] HAL-Initialisierung übersprungen: {e}")
            self._hal_comp = None

    # ── WCS-Offset-Tabelle ────────────────────────────────────────────────────

    # Parameter-Nummern: G54=5221, G55=5241 ... (je +20, X/Y/Z = +0/+1/+2)
    _WCS_LIST = [
        ("G54", 1, 5221), ("G55", 2, 5241), ("G56", 3, 5261),
        ("G57", 4, 5281), ("G58", 5, 5301), ("G59", 6, 5321),
        ("G59.1", 7, 5341), ("G59.2", 8, 5361), ("G59.3", 9, 5381),
    ]

    def _var_file_path(self) -> str | None:
        if not self.ini:
            return None
        name = self.ini.find("RS274NGC", "PARAMETER_FILE")
        if not name:
            return None
        p = os.path.join(os.path.dirname(self.ini_path), name)
        return p if os.path.exists(p) else None

    def _read_var_file(self) -> dict[int, float]:
        """Liest die LinuxCNC .var-Datei und gibt {param_nr: wert} zurück."""
        path = self._var_file_path()
        if not path:
            return {}
        params: dict[int, float] = {}
        try:
            with open(path, "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            params[int(parts[0])] = float(parts[1])
                        except ValueError:
                            pass
        except OSError:
            pass
        return params

    def _setup_offsets_tab(self):
        from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                                       QTableWidget, QTableWidgetItem,
                                       QPushButton, QHeaderView, QLabel,
                                       QAbstractItemView)
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtGui import QColor, QFont

        tab = self._w(QWidget, "tab_offsets")
        if not tab:
            return

        outer = QVBoxLayout(tab)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        # Titel
        title = QLabel("Work Coordinate Offsets (G54 – G59.3)")
        title.setStyleSheet("font-size:14pt; font-weight:bold; color:#eee;")
        outer.addWidget(title)

        # Tabelle
        cols = ["WCS", "X", "Y", "Z", ""]
        tbl = QTableWidget(len(self._WCS_LIST), len(cols))
        tbl.setObjectName("offsetTable")
        tbl.setHorizontalHeaderLabels(cols)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tbl.setFocusPolicy(_Qt.FocusPolicy.NoFocus)
        tbl.setStyleSheet("""
            QTableWidget {
                background: #1e1e1e; color: #eee;
                gridline-color: #3a3a3a;
                font-size: 12pt;
                border: 1px solid #444;
            }
            QHeaderView::section {
                background: #2a2a2a; color: #aaa;
                font-size: 11pt; font-weight: bold;
                border: none; border-bottom: 2px solid #555;
                padding: 6px;
            }
            QTableWidget::item { padding: 4px 10px; }
        """)

        hdr = tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        tbl.setColumnWidth(0, 80)
        tbl.setColumnWidth(4, 90)
        tbl.verticalHeader().setDefaultSectionSize(47)

        _bold = QFont()
        _bold.setBold(True)
        _bold.setPointSize(12)

        for row, (label, p_idx, base_param) in enumerate(self._WCS_LIST):
            # WCS-Name
            name_item = QTableWidgetItem(label)
            name_item.setTextAlignment(_Qt.AlignmentFlag.AlignCenter)
            name_item.setFont(_bold)
            tbl.setItem(row, 0, name_item)
            # X / Y / Z (Platzhalter – werden per _refresh_offsets_table befüllt)
            for col in range(1, 4):
                it = QTableWidgetItem("–")
                it.setTextAlignment(_Qt.AlignmentFlag.AlignRight | _Qt.AlignmentFlag.AlignVCenter)
                tbl.setItem(row, col, it)
            # Clear-Button
            btn = QPushButton("CLEAR")
            btn.setFocusPolicy(_Qt.FocusPolicy.NoFocus)
            btn.setFixedSize(74, 35)
            btn.setStyleSheet(
                "QPushButton { background:#7b241c; color:white; border-radius:4px;"
                " font-weight:bold; }"
                "QPushButton:hover { background:#a93226; }")
            btn.clicked.connect(lambda _=False, n=p_idx: self._clear_wcs(n))
            tbl.setCellWidget(row, 4, btn)

        outer.addWidget(tbl)
        outer.addStretch()

        self._offset_table = tbl
        self._offset_active_row = 0
        self._offset_var_mtime = 0.0

        # Erste Befüllung + Signal-Verbindung
        self._refresh_offsets_table()
        self.poller.periodic.connect(self._refresh_offsets_table)
        self.poller.g5x_index_changed.connect(self._on_offset_wcs_changed)

    def _refresh_offsets_table(self):
        """Liest die .var-Datei (nur wenn mtime geändert) und aktualisiert die Tabelle."""
        path = self._var_file_path()
        if not hasattr(self, "_offset_table"):
            return
        mtime = os.path.getmtime(path) if path else 0.0
        if mtime == self._offset_var_mtime:
            return
        self._offset_var_mtime = mtime

        from PySide6.QtGui import QColor
        params = self._read_var_file()
        tbl = self._offset_table

        for row, (_, _, base) in enumerate(self._WCS_LIST):
            for col, offset in enumerate((0, 1, 2)):
                val = params.get(base + offset, 0.0)
                it = tbl.item(row, col + 1)
                if it:
                    it.setText(f"{val:+.4f}")
                    it.setForeground(QColor("#e74c3c" if val != 0.0 else "#555"))

    def _on_offset_wcs_changed(self, index: int):
        """Hebt die aktive WCS-Zeile hervor."""
        if not hasattr(self, "_offset_table"):
            return
        from PySide6.QtGui import QColor
        tbl = self._offset_table
        for row, (_, p_idx, _) in enumerate(self._WCS_LIST):
            active = p_idx == index
            bg = QColor("#1a3a5c") if active else QColor("#1e1e1e")
            for col in range(4):
                it = tbl.item(row, col)
                if it:
                    it.setBackground(bg)

    def _clear_wcs(self, p_idx: int):
        """Setzt alle Offsets des angegebenen WCS auf 0 via G10 L2."""
        try:
            self.cmd.mode(linuxcnc.MODE_MDI)
            self.cmd.wait_complete()
            self.cmd.mdi(f"G10 L2 P{p_idx} X0 Y0 Z0")
            self.cmd.wait_complete()
            self.cmd.mode(linuxcnc.MODE_MANUAL)
            self._status(f"WCS G{53 + p_idx if p_idx <= 6 else '59.' + str(p_idx - 6)} → X0 Y0 Z0")
            self._offset_var_mtime = 0.0   # mtime invalidieren → sofortiger Refresh
        except Exception as e:
            self._status(f"Offset-Clear Fehler: {e}")

    def _setup_settings_tab(self):
        """Verbindet alle Settings-Sub-Tabs."""
        from PySide6.QtWidgets import QDoubleSpinBox, QPushButton, QComboBox, QCheckBox, QGroupBox, QVBoxLayout, QWidget

        # ── UI-Tab: Theme & Sprache ───────────────────────────────────────────
        if cb := self._w(QComboBox, "combo_theme"):
            # Gespeichertes Theme vorauswählen
            saved = self.settings.get("theme", "dark")
            idx = cb.findText(saved)
            if idx >= 0:
                cb.setCurrentIndex(idx)
            cb.currentTextChanged.connect(self._apply_theme)

        if cb := self._w(QComboBox, "combo_language"):
            saved_lang = self.settings.get("language", "Deutsch")
            idx = cb.findText(saved_lang)
            if idx >= 0:
                cb.setCurrentIndex(idx)
            cb.currentTextChanged.connect(
                lambda lang: self.settings.set("language", lang))

        # ── Backplot Antialiasing ──
        if ui_tab := self._w(QWidget, "settings_tab_ui"):
            layout = ui_tab.layout()
            gb_gfx = QGroupBox("Grafik / Performance")
            # Wir suchen uns einen Platz vor dem vertikalen Spacer
            gl_gfx = QVBoxLayout(gb_gfx)
            self._cb_aa = QCheckBox("Backplot Antialiasing (Glättung)")
            self._cb_aa.setToolTip("Verbessert die Linienqualität (MSAA). Erfordert Neustart für volle Wirkung.")
            
            active = self.settings.get("backplot_antialiasing", True)
            self._cb_aa.setChecked(active)
            self._cb_aa.toggled.connect(self._on_aa_toggled)
            
            # --- MSAA Samples ---
            lay_msaa = QHBoxLayout()
            lay_msaa.addWidget(QLabel("MSAA Samples:"))
            self._cb_msaa = QComboBox()
            for x in [2, 4, 8, 16]:
                self._cb_msaa.addItem(f"{x}x", userData=x)
            
            saved_msaa = self.settings.get("backplot_msaa_samples", 4)
            idx = self._cb_msaa.findData(saved_msaa)
            if idx >= 0: self._cb_msaa.setCurrentIndex(idx)
            
            self._cb_msaa.setEnabled(active)
            self._cb_msaa.currentIndexChanged.connect(self._on_msaa_changed)
            
            lay_msaa.addWidget(self._cb_msaa)
            gl_gfx.addLayout(lay_msaa)

            gl_gfx.addWidget(self._cb_aa)
            # Vor dem vertikalen Spacer am Ende einfügen (layout hat Theme, Language, Spacer -> count=3)
            layout.insertWidget(layout.count() - 1, gb_gfx)


        # Spinboxen laden & verbinden
        for widget_name, prefs_key, default in self._TOOLSENSOR_FIELDS:
            dsb = self._w(QDoubleSpinBox, widget_name)
            if not dsb:
                continue

            # Wert aus Prefs laden (oder Default)
            val = self.settings.get(prefs_key, default)
            dsb.blockSignals(True)
            dsb.setValue(float(val))
            dsb.blockSignals(False)

            # HAL-Pin initial setzen
            self._hal_set(prefs_key, float(val))

            # Jede Änderung → Prefs speichern + HAL aktualisieren
            dsb.valueChanged.connect(
                lambda v, k=prefs_key: self._on_toolsensor_changed(k, v)
            )

        # "Aktuelle Position" Buttons
        if b := self._w(QPushButton, "btn_set_wechsel_pos"):
            b.clicked.connect(self._set_wechsel_pos_from_machine)
        if b := self._w(QPushButton, "btn_set_taster_pos"):
            b.clicked.connect(self._set_taster_pos_from_machine)

        # Probe Sim Button (Sim only)
        if b := self._w(QPushButton, "btn_probe_sim"):
            b.pressed.connect(lambda: self._set_sim_probe(True))
            b.released.connect(lambda: self._set_sim_probe(False))

    def _set_sim_probe(self, state: bool):
        """Setzt den simulierten Probe-Pin direkt auf motion.probe-input."""
        try:
            import hal as _hal
            _hal.set_p("motion.probe-input", "TRUE" if state else "FALSE")
            self._status(f"PROBE SIM: {'[ AKTIV ]' if state else '[ INAKTIV ]'}")
        except Exception as e:
            self._status(f"PROBE SIM Fehler: {e}")

    def _hal_set(self, prefs_key: str, value: float):
        """Setzt einen HAL-Pin, wenn der HAL-Comp verfügbar ist."""
        if not self._hal_comp:
            return
        try:
            pin_name = prefs_key.replace("_", "-")
            self._hal_comp[pin_name] = value
        except Exception:
            pass

    def _on_toolsensor_changed(self, key: str, value: float):
        """Callback: Spinbox geändert → Prefs speichern + HAL-Pin setzen."""
        self.settings.set(key, value)
        self.settings.save()
        self._hal_set(key, value)

    def _on_aa_toggled(self, enabled: bool):
        """Callback: Antialiasing Checkbox geändert."""
        self.settings.set("backplot_antialiasing", enabled)
        self.settings.save()
        self.backplot.set_antialiasing(enabled)
        if hasattr(self, "_cb_msaa"):
            self._cb_msaa.setEnabled(enabled)
        self._status("Antialiasing-Master-Schalter geändert. (MSAA-Level braucht Neustart)")

    def _on_msaa_changed(self, index: int):
        """MSAA Samples (2x, 4x, etc) geändert."""
        val = self._cb_msaa.itemData(index)
        self.settings.set("backplot_msaa_samples", val)
        self.settings.save()
        self._status(f"MSAA auf {val}x gesetzt. Ein Neustart ist nötig.")

    def _set_wechsel_pos_from_machine(self):
        """Übernimmt die aktuelle Maschinenposition als Wechselposition X/Y/Z."""
        from PySide6.QtWidgets import QDoubleSpinBox
        pos = getattr(self, "_last_pos", None)
        if pos is None:
            self._status("Keine Positionsdaten verfügbar!", error=True)
            return
        mapping = [
            ("dsb_ts_wechsel_x", "ts_wechsel_x", 0),
            ("dsb_ts_wechsel_y", "ts_wechsel_y", 1),
            ("dsb_ts_wechsel_z", "ts_wechsel_z", 2),
        ]
        for widget_name, prefs_key, axis_idx in mapping:
            dsb = self._w(QDoubleSpinBox, widget_name)
            if dsb:
                dsb.setValue(pos[axis_idx])
        self._status("Wechselposition aus aktueller Maschinenposition übernommen.")

    def _set_taster_pos_from_machine(self):
        """Übernimmt die aktuelle Maschinenposition als Taster-Position X/Y/Z."""
        from PySide6.QtWidgets import QDoubleSpinBox
        pos = getattr(self, "_last_pos", None)
        if pos is None:
            self._status("Keine Positionsdaten verfügbar!", error=True)
            return
        mapping = [
            ("dsb_ts_x", "ts_x", 0),
            ("dsb_ts_y", "ts_y", 1),
            ("dsb_ts_z", "ts_z", 2),
        ]
        for widget_name, prefs_key, axis_idx in mapping:
            dsb = self._w(QDoubleSpinBox, widget_name)
            if dsb:
                dsb.setValue(pos[axis_idx])
        self._status("Taster-Position aus aktueller Maschinenposition übernommen.")

    def _connect_signals(self):
        p = self.poller
        ui = self.ui

        p.estop_changed.connect(self._on_estop)
        p.machine_on_changed.connect(self._on_machine_on)
        p.mode_changed.connect(self._on_mode)
        p.interp_changed.connect(self._on_interp)
        p.position_changed.connect(self._on_position)
        p.tool_in_spindle.connect(self._on_tool)
        p.tool_offset_changed.connect(self._on_tool_offset_changed)
        p.spindle_at_speed.connect(self._on_spindle_at_speed)
        p.spindle_speed_actual.connect(self._on_spindle_actual)
        p.spindle_load.connect(self._on_spindle_load)
        p.feed_override.connect(self._on_feed_override)
        p.spindle_override.connect(self._on_spindle_override)
        if hasattr(p, 'rapid_override'):
            p.rapid_override.connect(self._on_rapid_override)
        p.spindle_speed.connect(self._on_spindle_speed)
        p.homed_changed.connect(self._on_homed)
        p.g5x_index_changed.connect(self._on_g5x_index)
        p.g5x_offset_changed.connect(self._on_g5x_offset)
        p.gcodes_changed.connect(self._on_gcodes)
        p.file_loaded.connect(self._on_file_loaded)
        p.program_line.connect(self._on_program_line)
        p.error_message.connect(self._on_error)
        p.info_message.connect(self._on_info)

        # ── Maschinen-Buttons (probe_basic Widget-Namen) ──────────────────────
        from PySide6.QtWidgets import QPushButton, QSlider
        def btn(name):
            return ui.findChild(QPushButton, name)
        def sld(name):
            return ui.findChild(QSlider, name)

        if b := btn("power_button"):
            b.clicked.connect(self._toggle_power)
        if b := btn("stop_button"):
            b.clicked.connect(self._stop_program)
        if b := btn("btn_run"):
            b.clicked.connect(self._run_program)
        if b := btn("manual_mode_button"):
            b.clicked.connect(lambda: self.cmd.mode(linuxcnc.MODE_MANUAL))
        if b := btn("mdi_mode_button"):
            b.clicked.connect(lambda: self.cmd.mode(linuxcnc.MODE_MDI))
        if b := btn("auto_mode_button"):
            b.clicked.connect(lambda: self.cmd.mode(linuxcnc.MODE_AUTO))
        if b := btn("go_to_home_button"):
            b.clicked.connect(self._home_all)
        if b := btn("btn_run"):
            b.clicked.connect(self._run_program)
        if b := btn("estop_button"):
            b.clicked.connect(self._toggle_estop)

        # Spindle Controls
        if b := btn("btn_spindle_fwd"):
            b.clicked.connect(lambda: self.cmd.spindle(linuxcnc.SPINDLE_FORWARD, 1000))  # Default 1000 RPM unless specified
        if b := btn("btn_spindle_rev"):
            b.clicked.connect(lambda: self.cmd.spindle(linuxcnc.SPINDLE_REVERSE, 1000))
        if b := btn("btn_spindle_stop"):
            b.clicked.connect(lambda: self.cmd.spindle(linuxcnc.SPINDLE_OFF))
            
        # M6 Tool Change
        if b := btn("btn_m6_change"):
            b.clicked.connect(self._send_m6)
        if b := btn("ref_all_button"):
            b.clicked.connect(self._home_all)
        if b := btn("ref_x_button"):
            b.clicked.connect(lambda: self._home_joint(0))
        if b := btn("ref_y_button"):
            b.clicked.connect(lambda: self._home_joint(1))
        if b := btn("ref_z_button"):
            b.clicked.connect(lambda: self._home_joint(2))
        if b := btn("btn_pause_mdi"):
            b.clicked.connect(self._pause_program)
        if b := btn("feed_override_to_100_button"):
            b.clicked.connect(lambda: self.cmd.feedrate(1.0))
        if b := btn("spindle_override_to_100_button"):
            b.clicked.connect(lambda: self.cmd.spindleoverride(1.0))
        if b := btn("rapid_override_to_100_button"):
            b.clicked.connect(lambda: self.cmd.rapidrate(1.0))
        if b := btn("v_override_to_100_button"):
            b.clicked.connect(self._on_v_override_to_100)
        
        # HAL Show
        if b := btn("btn_halshow"):
            b.clicked.connect(self._run_halshow)

        # Go to Home
        if b := btn("btn_go_to_home"):
            b.clicked.connect(self._go_to_home)

        # Jog-Buttons (Suffix _3 = jog_xyz Seite, 3-Achsen)
        for axis, joint in (("x", 0), ("y", 1), ("z", 2)):
            for dirn, sign in (("plus", 1), ("minus", -1)):
                if b := btn(f"{axis}_{dirn}_jogbutton_3"):
                    b.pressed.connect(
                        lambda a=joint, s=sign: self._jog_start(a, s))
                    b.released.connect(
                        lambda a=joint: self._jog_stop(a))

        # Maschinen-Modus Combobox (MANUAL / AUTO / MDI)
        _MODE_MAP = [linuxcnc.MODE_MANUAL, linuxcnc.MODE_AUTO, linuxcnc.MODE_MDI]
        from PySide6.QtWidgets import QComboBox
        if cb := ui.findChild(QComboBox, "combo_machine_mode"):
            cb.activated.connect(lambda idx: self.cmd.mode(_MODE_MAP[idx]))

        # Overrides & Jog Slider
        if s := sld("feed_override_slider"):
            s.valueChanged.connect(lambda v: self.cmd.feedrate(v / 100.0))
        if s := sld("spindle_override_slider"):
            s.valueChanged.connect(lambda v: self.cmd.spindleoverride(v / 100.0))
        if s := sld("rapid_override_slider"):
            s.valueChanged.connect(lambda v: self.cmd.rapidrate(v / 100.0))
        if s := sld("v_override_slider"):
            s.valueChanged.connect(self._on_v_override_changed)
        if s := sld("jog_vel_slider"):
            s.valueChanged.connect(self._on_jog_vel_changed)

        # Jog Increment Buttons (Exclusive)
        if b := btn("btn_jog_cont"):
            b.clicked.connect(lambda: self._set_jog_increment(0.0))
        if b := btn("btn_jog_1_0"):
            b.clicked.connect(lambda: self._set_jog_increment(1.0))
        if b := btn("btn_jog_0_1"):
            b.clicked.connect(lambda: self._set_jog_increment(0.1))
        if b := btn("btn_jog_0_01"):
            b.clicked.connect(lambda: self._set_jog_increment(0.01))

        # Nav-Buttons → tabWidget
        from PySide6.QtWidgets import QTabWidget, QButtonGroup
        tab = ui.findChild(QTabWidget, "tabWidget")
        if tab:
            self.nav_group = QButtonGroup(self)
            self.nav_group.setExclusive(True)
            for idx, name in enumerate(
                    ("nav_main", "nav_file", "nav_tool", "nav_offsets",
                     "nav_probing", "nav_settings", "nav_status")):
                if b := btn(name):
                    b.setCheckable(True)
                    b.setMinimumHeight(60)  # Force height in code to be sure
                    self.nav_group.addButton(b, idx)
                    b.clicked.connect(lambda _, i=idx, t=tab: t.setCurrentIndex(i))
            
            tab.currentChanged.connect(self._sync_nav_buttons)
            # Initial sync (Wait a bit for machine state)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(500, lambda: self._sync_nav_buttons(tab.currentIndex()))

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _w(self, cls, name):
        return self.ui.findChild(cls, name)

    @Slot(bool)
    def _on_estop(self, active: bool):
        self._status(f"ESTOP {'AKTIV' if active else 'ZURÜCKGESETZT'}")
        from PySide6.QtWidgets import QPushButton
        if b := self._w(QPushButton, "estop_button"):
            if active:
                # E-Stop gedrückt (aus): roter Rahmen
                b.setStyleSheet("QPushButton { border: 2px solid #ff4444; border-radius: 4px; background-color: #2a2a2a; color: white; font-weight: bold; font-size: 14pt; }")
            else:
                # E-Stop bereit (an): vollflächig rot
                b.setStyleSheet("QPushButton { background-color: #cc0000; color: white; border-radius: 4px; font-weight: bold; font-size: 14pt; }")

    @Slot(bool)
    def _on_machine_on(self, on: bool):
        from PySide6.QtWidgets import QPushButton
        self._is_machine_on = on
        if b := self._w(QPushButton, "power_button"):
            if on:
                # Power an: vollflächig grün
                b.setStyleSheet("QPushButton { background-color: #27ae60; color: white; border-radius: 4px; font-weight: bold; font-size: 14pt; }")
            else:
                # Power aus: grüner Rahmen
                b.setStyleSheet("QPushButton { border: 2px solid #27ae60; border-radius: 4px; background-color: #2a2a2a; color: white; font-weight: bold; font-size: 14pt; }")
        self._update_run_buttons()
        # GO TO HOME: nur grün wenn Maschine an UND alle Joints gehomt
        self._update_goto_home_style(on and getattr(self, "_all_joints_homed", False))

    @Slot(int)
    def _on_mode(self, mode: int):
        from PySide6.QtWidgets import QPushButton, QComboBox
        self._current_mode = mode
        for name, m in (("manual_mode_button", linuxcnc.MODE_MANUAL),
                        ("mdi_mode_button",    linuxcnc.MODE_MDI),
                        ("auto_mode_button",   linuxcnc.MODE_AUTO)):
            if b := self._w(QPushButton, name):
                b.setChecked(mode == m)
        _IDX = {linuxcnc.MODE_MANUAL: 0, linuxcnc.MODE_AUTO: 1, linuxcnc.MODE_MDI: 2}
        if cb := self._w(QComboBox, "combo_machine_mode"):
            cb.blockSignals(True)
            cb.setCurrentIndex(_IDX.get(mode, 0))
            cb.blockSignals(False)
        # MDI-Modus → automatisch MDI-Seite zeigen
        if hasattr(self, "_gcode_mdi_stack"):
            if mode == linuxcnc.MODE_MDI:
                self._switch_gcode_panel(1)
            else:
                self._switch_gcode_panel(0)
        # GO TO HOME im AUTO-Modus deaktivieren
        self._update_goto_home_style(self._is_machine_on and getattr(self, "_all_joints_homed", False))

    @Slot(int)
    def _on_interp(self, state: int):
        from PySide6.QtWidgets import QPushButton
        self._interp_state = state
        running = state in (linuxcnc.INTERP_READING, linuxcnc.INTERP_WAITING)
        paused  = state == linuxcnc.INTERP_PAUSED
        if b := self._w(QPushButton, "stop_button"):
            b.setEnabled(running or paused)
        if b := self._w(QPushButton, "btn_pause_mdi"):
            b.setEnabled(running)
            
        self._update_run_buttons()

    def _update_run_buttons(self):
        from PySide6.QtWidgets import QPushButton
        btn_run = self._w(QPushButton, "btn_run")
        btn_pause = self._w(QPushButton, "btn_pause_mdi")
        btn_stop = self._w(QPushButton, "stop_button")
        
        if not (btn_run and btn_pause and btn_stop): return
        
        style_base = "border-radius: 4px; font-weight: bold; font-size: 12pt; "
        
        if not self._is_machine_on:
            btn_run.setStyleSheet(style_base + "background-color: #444; color: #888;")
            btn_pause.setStyleSheet(style_base + "background-color: #444; color: #888;")
            btn_stop.setStyleSheet(style_base + "background-color: #444; color: #888;")
            return
            
        is_running = self._interp_state in (linuxcnc.INTERP_READING, linuxcnc.INTERP_WAITING)
        is_paused = self._interp_state == linuxcnc.INTERP_PAUSED
        is_idle = self._interp_state == linuxcnc.INTERP_IDLE
        
        # Cycle Start (btn_run)
        if is_running:
            btn_run.setStyleSheet(style_base + "background-color: #27ae60; color: white;")
        elif (is_idle or is_paused) and self._has_file:
            btn_run.setStyleSheet(style_base + "border: 2px solid #27ae60; background-color: #222; color: #27ae60;")
        else:
            btn_run.setStyleSheet(style_base + "background-color: #444; color: #888;")
            
        # Feedhold (btn_pause_mdi)
        if is_paused:
            btn_pause.setStyleSheet(style_base + "background-color: #f39c12; color: white;")
        elif is_running:
            btn_pause.setStyleSheet(style_base + "border: 2px solid #f39c12; background-color: #222; color: #f39c12;")
        else:
            btn_pause.setStyleSheet(style_base + "background-color: #444; color: #888;")
            
        # Stop (stop_button)
        if is_running or is_paused:
            btn_stop.setStyleSheet(style_base + "background-color: #c0392b; color: white;")
        else:
            btn_stop.setStyleSheet(style_base + "background-color: #444; color: #888;")

    @Slot(list)
    def _on_position(self, pos: list):
        self._last_pos = pos
        self._refresh_dro()

    def _refresh_dro(self, _=None):
        pos = getattr(self, "_last_pos", None)
        if pos is None:
            return
        g5x   = getattr(self.poller, "_g5x_offset", None) or [0.0, 0.0, 0.0]
        try:
            t_off = self.poller.stat.tool_offset or [0.0, 0.0, 0.0]
        except AttributeError:
            t_off = [0.0, 0.0, 0.0]
            
        homed = getattr(self.poller, "_homed", []) or []

        all_homed = True
        for i, axis in enumerate(("X", "Y", "Z")):
            is_homed = i < len(homed) and homed[i]
            if not is_homed:
                all_homed = False
            work = pos[i] - g5x[i] - t_off[i]
            mach = pos[i]
            if axis in self._dro_work:
                self._dro_work[axis].setText(f"{work:+.3f}")
            if axis in self._dro_machine:
                self._dro_machine[axis].setText(f"{mach:+.3f}")

        # Tool-Marker nur zeigen wenn alle Achsen gereferenciert
        if all_homed:
            self.backplot.set_tool_position(pos[0] - t_off[0], pos[1] - t_off[1], pos[2] - t_off[2])
        else:
            self.backplot.set_tool_position(float('nan'), float('nan'), float('nan'))

    @Slot(int)
    def _on_tool(self, tool: int):
        from PySide6.QtWidgets import QLabel, QTableWidget
        if tool == 0:
            return  # Tool 0 = kein/unbekanntes Werkzeug, Anzeige nicht überschreiben
        if lbl := self._w(QLabel, "tool_number_entry_main_panel"):
            lbl.setText(str(tool))

        # Tool-Tabelle neu einlesen (Messung kann .tbl Datei geändert haben)
        self._load_tool_table()

        # Geometrie aus dem gerade neu geladenen Widget lesen
        from PySide6.QtWidgets import QTableWidget
        table = self._w(QTableWidget, "toolTable")
        dia, length, comment = "0.000", "0.000", "-"
        if table:
            for r in range(table.rowCount()):
                t_item = table.item(r, 0)
                if t_item and t_item.text().strip() == str(tool):
                    d_item = table.item(r, 2)
                    len_item = table.item(r, 3)
                    c_item = table.item(r, 4)
                    if d_item: dia = d_item.text()
                    if len_item: length = len_item.text()
                    if c_item: comment = c_item.text()
                    break

        if dia_lbl := self._w(QLabel, "tool_dia_label"):
            dia_lbl.setText(dia)
        if len_lbl := self._w(QLabel, "tool_len_label"):
            len_lbl.setText(length)
        if c_lbl := self._w(QLabel, "tool_comment_label"):
            c_lbl.setText(comment)
            
        try:
            fdia = float(dia) if dia.strip() else 0.0
        except ValueError:
            fdia = 0.0
        try:
            flen = float(length) if length.strip() else 0.0
        except ValueError:
            flen = 0.0
        self.backplot.set_tool_geometry(fdia, flen)

    @Slot(list)
    def _on_tool_offset_changed(self, _):
        """Werkzeugoffset hat sich geändert (z.B. nach Messung) → Tool-Anzeige aktualisieren."""
        tool = self.poller.stat.tool_in_spindle
        if tool > 0:
            self._on_tool(tool)

    @Slot(tuple)
    def _on_gcodes(self, gcodes: tuple):
        from PySide6.QtWidgets import QLabel
        if lbl := self._w(QLabel, "active_gcodes_label"):
            active = []
            important = {"G54", "G55", "G56", "G57", "G58", "G59", "G59.1", "G59.2", "G59.3", "G43", "G49", "G20", "G21", "G90", "G91"}
            for g in gcodes[1:]:
                if g == -1: continue
                val = g / 10.0
                g_str = f"G{val:g}"
                if g_str in important:
                    active.append(f'<span style="color: #FFC13B; font-weight: bold;">{g_str}</span>')
                else:
                    active.append(f'{g_str}')
            
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setText("<br>".join(active))

    @Slot(list)
    def _on_homed(self, homed: list):
        self._all_joints_homed = all(i < len(homed) and homed[i] for i in range(3))
        self._update_goto_home_style(self._is_machine_on and self._all_joints_homed)
        for i, axis in enumerate(("X", "Y", "Z")):
            is_homed = i < len(homed) and homed[i]
            # DRO work label: grün wenn gehomed, rot wenn nicht
            if axis in self._dro_work:
                color = "#00dd55" if is_homed else "#e74c3c"
                self._dro_work[axis].setStyleSheet(
                    f"font: 16pt 'Bebas Kai'; color: {color};"
                    " background: rgb(30,34,36); border-radius:3px; padding: 0 6px;")
            # REF button: grün wenn gehomed
            if axis in self._dro_ref_btn:
                btn = self._dro_ref_btn[axis]
                if is_homed:
                    btn.setStyleSheet(
                        "QPushButton { font: bold 10pt 'Bebas Kai'; border-radius:4px;"
                        " background: rgb(78,154,6); color: white; }"
                        "QPushButton:hover { background: rgb(100,180,20); }")
                else:
                    btn.setStyleSheet(
                        "QPushButton { font: bold 10pt 'Bebas Kai'; border-radius:4px;"
                        " background: rgb(60,60,60); color: rgb(186,189,182); }"
                        "QPushButton:hover { background: rgb(80,80,80); }")

    @Slot(float)
    def _on_feed_override(self, val: float):
        from PySide6.QtWidgets import QLabel, QSlider
        if lbl := self._w(QLabel, "feed_override_status"):
            lbl.setText(f"F {val*100:.0f}%")
        if s := self._w(QSlider, "feed_override_slider"):
            s.blockSignals(True)
            s.setValue(int(val * 100))
            s.blockSignals(False)

    @Slot(float)
    def _on_spindle_override(self, val: float):
        from PySide6.QtWidgets import QLabel, QSlider
        if lbl := self._w(QLabel, "spindle_override_status"):
            lbl.setText(f"S {val*100:.0f}%")
        if s := self._w(QSlider, "spindle_override_slider"):
            s.blockSignals(True)
            s.setValue(int(val * 100))
            s.blockSignals(False)

    @Slot(float)
    def _on_rapid_override(self, val: float):
        from PySide6.QtWidgets import QLabel, QSlider
        if lbl := self._w(QLabel, "rapid_override_status"):
            lbl.setText(f"R {val*100:.0f}%")
        if s := self._w(QSlider, "rapid_override_slider"):
            s.blockSignals(True)
            s.setValue(int(val * 100))
            s.blockSignals(False)

    def _on_v_override_changed(self, val: int):
        from PySide6.QtWidgets import QLabel
        if lbl := self._w(QLabel, "v_override_status"):
            lbl.setText(f"V {val}%")
        self.cmd.feedrate(val / 100.0)
        self.cmd.spindleoverride(val / 100.0)
        
    def _on_v_override_to_100(self):
        from PySide6.QtWidgets import QSlider, QLabel
        if s := self._w(QSlider, "v_override_slider"):
            s.setValue(100)
        if lbl := self._w(QLabel, "v_override_status"):
            lbl.setText(f"V 100%")
        self.cmd.feedrate(1.0)
        self.cmd.spindleoverride(1.0)

    @Slot(float)
    def _on_spindle_speed(self, rpm: float):
        from PySide6.QtWidgets import QLabel
        self._is_spindle_running = (abs(rpm) > 0.1)
        if lbl := self._w(QLabel, "lbl_spindle_soll"):
            lbl.setText(f"{abs(rpm):.0f}")
        self._update_run_buttons()
        self._update_spindle_buttons()

    @Slot(float)
    def _on_spindle_actual(self, rpm: float):
        from PySide6.QtWidgets import QLabel
        if lbl := self._w(QLabel, "lbl_spindle_ist"):
            lbl.setText(f"{abs(rpm):.0f}")

    @Slot(float)
    def _on_spindle_load(self, load: float):
        from PySide6.QtWidgets import QProgressBar
        if bar := self._w(QProgressBar, "spindle_load_bar"):
            bar.setValue(int(max(0, min(100, load))))

    @Slot(bool)
    def _on_spindle_at_speed(self, at_speed: bool):
        self._spindle_at_speed = at_speed
        self._update_spindle_buttons()

    def _update_spindle_buttons(self):
        from PySide6.QtWidgets import QPushButton
        direction = self.poller.stat.spindle[0]['direction']  # 1=fwd, -1=rev, 0=stop
        at_speed  = getattr(self, '_spindle_at_speed', False)
        running   = direction != 0

        _base = "QPushButton { border-radius: 4px; font-weight: bold; padding: 4px 8px; "

        if running and at_speed:
            # Vollflächig grün: Solldrehzahl erreicht
            fwd_style = _base + "background-color: #27ae60; color: white; }"
            rev_style = _base + "background-color: #27ae60; color: white; }"
        elif running:
            # Grüner Rahmen: läuft, aber noch nicht auf Drehzahl
            fwd_style = _base + "border: 2px solid #27ae60; background-color: #1a1a1a; color: white; }"
            rev_style = _base + "border: 2px solid #27ae60; background-color: #1a1a1a; color: white; }"
        else:
            fwd_style = ""
            rev_style = ""

        if b := self._w(QPushButton, "btn_spindle_fwd"):
            b.setStyleSheet(fwd_style if direction == 1 else "")
        if b := self._w(QPushButton, "btn_spindle_rev"):
            b.setStyleSheet(rev_style if direction == -1 else "")

    @Slot(str)
    def _on_file_loaded(self, path: str):
        if not path or not os.path.isfile(path):
            return
        # Subroutinen (messe.ngc etc.) ignorieren – nur das User-Hauptprogramm anzeigen
        if path != self._user_program:
            return
        self._has_file = True
        self.gcode_view.load_file(path)
        self.backplot.load_toolpath(parse_file(path))
        self._update_run_buttons()

    @Slot(int)
    def _on_program_line(self, line: int):
        self.gcode_view.set_current_line(line)

    @Slot(str)
    def _on_error(self, msg: str):
        self._status(f"FEHLER: {msg}", error=True)

    @Slot(str)
    def _on_info(self, msg: str):
        self._status(msg)

    def _status(self, msg: str, error: bool = False):
        if sb := self.ui.statusBar():
            sb.showMessage(msg, 10000)
        self._append_status_log(msg, error=error)

    def _append_status_log(self, msg: str, error: bool = False):
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        from PySide6.QtGui import QColor
        from PySide6.QtCore import QDateTime
        log: QListWidget = self.ui.findChild(QListWidget, "status_log")
        if log is None:
            return
        ts = QDateTime.currentDateTime().toString("HH:mm:ss")
        item = QListWidgetItem(f"[{ts}]  {msg}")
        if error:
            item.setForeground(QColor("#ff5555"))
        else:
            item.setForeground(QColor("#aaaaaa"))
        log.addItem(item)
        log.scrollToBottom()

    def _sync_nav_buttons(self, index: int):
        """Nav-Buttons an den Tab-Zustand anpassen und LinuxCNC-Modus umschalten."""
        if hasattr(self, "nav_group"):
            if b := self.nav_group.button(index):
                b.blockSignals(True)
                b.setChecked(True)
                b.blockSignals(False)

        # Modus-Umschaltung basierend auf Tab (Auto vs Manual)
        # Tab 0: Main (Auto), Tab 1: File (Auto), Rest: Manual
        try:
            current_mode = self.poller.stat.task_mode
            target_mode = linuxcnc.MODE_MANUAL
            if index in (0, 1):
                target_mode = linuxcnc.MODE_AUTO
            
            if current_mode != target_mode:
                # Nur umschalten wenn die Maschine im IDLE ist
                if self._interp_state == linuxcnc.INTERP_IDLE:
                    self.cmd.mode(target_mode)
                    self.cmd.wait_complete()
        except Exception:
            pass

    # ── Maschinen-Aktionen ────────────────────────────────────────────────────

    def _toggle_power(self):
        s = self.poller.stat
        if s.task_state == linuxcnc.STATE_ESTOP:
            self.cmd.state(linuxcnc.STATE_ESTOP_RESET)
        elif s.task_state == linuxcnc.STATE_ON:
            self.cmd.state(linuxcnc.STATE_OFF)
        else:
            self.cmd.state(linuxcnc.STATE_ON)

    def _toggle_estop(self):
        s = self.poller.stat
        if s.task_state == linuxcnc.STATE_ESTOP:
            self.cmd.state(linuxcnc.STATE_ESTOP_RESET)
        else:
            self.cmd.state(linuxcnc.STATE_ESTOP)

    def _run_halshow(self):
        """Startet halshow als externen Prozess."""
        import subprocess
        try:
            subprocess.Popen(["halshow"], start_new_session=True)
            self._status("HAL Show gestartet.")
        except Exception as e:
            self._status(f"Fehler: halshow nicht gefunden: {e}")

    def _go_to_home(self):
        """Fahrt auf Maschinen-Nullpunkt G53 G0 X0 Y0 Z0."""
        try:
            # Merken des alten Modus
            old_mode = self.poller.stat.task_mode
            self.cmd.mode(linuxcnc.MODE_MDI)
            self.cmd.wait_complete()
            # Erst Z hoch (Sicherheit), dann XY
            self.cmd.mdi("G53 G0 Z0")
            self.cmd.wait_complete()
            self.cmd.mdi("G53 G0 X0 Y0")
            self.cmd.wait_complete()
            self.cmd.mode(old_mode)
            self._status("Fahre auf Home-Position (G53)")
        except Exception as e:
            self._status(f"Home-Fahrt Fehler: {e}")

    def _run_program(self):
        self.cmd.mode(linuxcnc.MODE_AUTO)
        self.cmd.wait_complete()
        self.cmd.auto(linuxcnc.AUTO_RUN, 0)

    def _home_all(self):
        self.cmd.mode(linuxcnc.MODE_MANUAL)
        self.cmd.wait_complete()
        self.cmd.home(-1)

    def _home_joint(self, joint: int):
        self.cmd.mode(linuxcnc.MODE_MANUAL)
        self.cmd.wait_complete()
        self.cmd.home(joint)

    def _pause_program(self):
        self.cmd.auto(linuxcnc.AUTO_PAUSE)

    def _stop_program(self):
        self.cmd.abort()

    def _send_mdi(self, text: str, widget=None):
        text = text.strip()
        if not text:
            return
        try:
            self.cmd.mode(linuxcnc.MODE_MDI)
            self.cmd.wait_complete()
            self.cmd.mdi(text)
            # Modus bleibt MDI — Poller aktualisiert Combobox automatisch.
            # Der User wechselt über die Combobox zurück zu MANUAL/AUTO.
            if widget:
                widget.clear()
            self._status(f"MDI: {text}")
            # History eintragen (kein Duplikat direkt oben)
            if hasattr(self, "_mdi_history_widget"):
                hw = self._mdi_history_widget
                if hw.count() == 0 or hw.item(0).text() != text:
                    hw.insertItem(0, text)
                    if hw.count() > 50:
                        hw.takeItem(hw.count() - 1)
        except Exception as e:
            self._status(f"MDI Fehler: {e}")
        
    def _send_m6(self):
        from PySide6.QtWidgets import QLineEdit
        entry = self._w(QLineEdit, "mdi_m6_entry")
        if not entry:
            return
        t_val = entry.text().strip()
        if not t_val:
            return
        if not t_val.upper().startswith("T"):
            t_val = "T" + t_val
        cmd_str = f"{t_val} M6 G43"
        self._send_mdi(cmd_str)
        entry.clear()

    def _set_jog_increment(self, inc: float):
        self._jog_increment = inc
        from PySide6.QtWidgets import QPushButton
        # Radio-button like behavior
        for name, val in [("btn_jog_cont", 0.0), ("btn_jog_1_0", 1.0), ("btn_jog_0_1", 0.1), ("btn_jog_0_01", 0.01)]:
            if b := self._w(QPushButton, name):
                b.setChecked(abs(inc - val) < 0.0001)

    def _on_jog_vel_changed(self, val: int):
        self._jog_velocity = float(val)
        from PySide6.QtWidgets import QLabel
        if lbl := self._w(QLabel, "jog_vel_label"):
            lbl.setText(f"Velocity: {val}")

    def _jog_start(self, joint: int, direction: int):
        self.cmd.mode(linuxcnc.MODE_MANUAL)
        self.cmd.wait_complete()
        if self._jog_increment <= 0.0:
            # Continuous
            self.cmd.jog(linuxcnc.JOG_CONTINUOUS, False, joint, direction * self._jog_velocity)
        else:
            # Incremental
            self.cmd.jog(linuxcnc.JOG_INCREMENT, False, joint, direction * self._jog_velocity, self._jog_increment)

    def _jog_stop(self, joint: int):
        if self._jog_increment <= 0.0:
            self.cmd.jog(linuxcnc.JOG_STOP, False, joint)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def show(self):
        self.ui.show()
        if hasattr(self, "_warn_missing_prefs") and self._warn_missing_prefs:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self.ui, 
                "Neue Konfigurationsdatei", 
                "Es wurde automatisch eine neue 'thorcnc.prefs' Datei im Config-Programmverzeichnis angelegt.\n"
                "In dieser speichern wir von nun an Fensterpositionen, Kameraperspektive und ausgewählte Dateipfade.\n\n"
                "Optional: Füge 'PREFS_FILE = thorcnc.prefs' im [DISPLAY] Abschnitt deiner INI hinzu, um den Ort explizit festzulegen!"
            )
            self._warn_missing_prefs = False

    def _apply_theme(self, name: str):
        from PySide6.QtWidgets import QApplication
        from .main import load_theme
        load_theme(QApplication.instance(), name)
        self.settings.set("theme", name)

    def _drain_startup_errors(self):
        """Liest den LinuxCNC Error-Channel einmalig beim Start aus und loggt alle Meldungen."""
        import linuxcnc as _lc
        self._append_status_log("── Session gestartet ──")
        try:
            ec = self.poller.error_channel
            msg = ec.poll()
            while msg:
                kind, text = msg
                is_err = kind in (_lc.NML_ERROR, _lc.OPERATOR_ERROR)
                self._append_status_log(text, error=is_err)
                msg = ec.poll()
        except Exception:
            pass

    def start(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance().aboutToQuit.connect(self._on_close)
        
        if hasattr(self, "_auto_load_file") and self._auto_load_file:
            self.load_file(self._auto_load_file)
        self._drain_startup_errors()
        if hasattr(self, "backplot"):
             s = self.backplot.get_actual_samples()
             self._status(f"Grafik-System bereit (Antialiasing: {s}x MSAA)")
        self.poller.start()

    def _on_close(self):
        self.poller.stop()
        
        # Einstellungen speichern
        geom = self.ui.saveGeometry().toHex().data().decode()
        state = self.ui.saveState().toHex().data().decode()
        self.settings.set("window_geometry", geom)
        self.settings.set("window_state", state)
        
        from PySide6.QtWidgets import QSplitter
        sp_main = self._w(QSplitter, "mainSplitter")
        if sp_main:
            self.settings.set("main_splitter", sp_main.saveState().toHex().data().decode())
            
        sp_file = self._w(QSplitter, "fileSplitter")
        if sp_file:
            self.settings.set("file_splitter", sp_file.saveState().toHex().data().decode())
            
        from PySide6.QtWidgets import QTableWidget
        tw = self._w(QTableWidget, "toolTable")
        if tw:
            self.settings.set("tool_table_state", tw.horizontalHeader().saveState().toHex().data().decode())
        
        if hasattr(self, "backplot") and hasattr(self.backplot, "get_view_opts"):
            self.settings.set("backplot_view", self.backplot.get_view_opts())

        if hasattr(self, "_mdi_history_widget"):
            hw = self._mdi_history_widget
            self.settings.set("mdi_history",
                              [hw.item(i).text() for i in range(hw.count())])

        self.settings.save()
