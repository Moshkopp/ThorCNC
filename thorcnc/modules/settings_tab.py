"""Settings tab module for ThorCNC — UI settings, machine safety, abort handler, toolsetter config."""

import os
import linuxcnc
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QPushButton, QComboBox, QCheckBox, QGroupBox, QVBoxLayout,
    QWidget, QLineEdit, QHBoxLayout, QLabel, QTextEdit, QFrame,
    QDoubleSpinBox, QMessageBox, QTabWidget, QColorDialog, QGridLayout
)
from PySide6.QtGui import QColor

_BACKPLOT_COLOR_KEYS = [
    ("tool",       "Cutter"),
    ("trail",      "Trail"),
    ("background", "Background"),
    ("rapid",      "Rapid (G0)"),
    ("feed",       "Feed (G1)"),
    ("arc",        "Arc (G2/G3)"),
]
_BACKPLOT_COLOR_DEFAULTS = {
    "rapid":      "#ff3333",
    "feed":       "#e5e5e5",
    "arc":        "#33e5e5",
    "tool":       "#e5cc33",
    "trail":      "#ff9900",
    "background": "#0d1117",
    "wcs_size":   28.0,
}

from .base import ThorModule
from ..i18n import _t

class SettingsTabModule(ThorModule):
    """Manages the Settings tab: UI preferences, Machine safety, Abort handler, Toolsetter."""

    _TOOLSENSOR_FIELDS = [
        ("dsb_ts_x",            "ts_x",            0.0),
        ("dsb_ts_y",            "ts_y",            0.0),
        ("dsb_ts_z",            "ts_z",            0.0),
        ("dsb_ts_wechsel_x",    "ts_wechsel_x",    0.0),
        ("dsb_ts_wechsel_y",    "ts_wechsel_y",    0.0),
        ("dsb_ts_wechsel_z",    "ts_wechsel_z",    0.0),
        ("dsb_ts_search_vel",   "ts_search_vel",   100.0),
        ("dsb_ts_probe_vel",    "ts_probe_vel",    10.0),
        ("dsb_ts_max_probe",    "ts_max_probe",    10.0),
        ("dsb_ts_retract",      "ts_retract",      1.0),
        ("dsb_ts_spindle_zero", "ts_spindle_zero", 100.0),
    ]

    def __init__(self, thorc):
        super().__init__(thorc)

    def setup(self):
        self._setup_settings_tab()

    def connect_signals(self):
        pass # All signals connected in _setup_settings_tab

    def _setup_settings_tab(self):
        """Verbindet alle Settings-Sub-Tabs."""
        
        # ── UI Tab: Theme & Language ───────────────────────────────────────────
        if cb_theme := self._t._w(QComboBox, "combo_theme"):
            # Set internal keys as userData before translation
            for i in range(cb_theme.count()):
                cb_theme.setItemData(i, cb_theme.itemText(i))
            
            valid_themes = ["dark", "light"]
            saved = self._t.settings.get("theme", "dark")
            if saved not in valid_themes:
                saved = "dark"
                
            idx = cb_theme.findData(saved)
            if idx >= 0:
                cb_theme.setCurrentIndex(idx)
            
            cb_theme.currentTextChanged.connect(
                lambda t, c=cb_theme: self._t.navigation.apply_theme(c.currentData() or t)
            )
            # navigation module already applied theme in its setup if needed, 
            # but we ensure consistency here.

        if cb_lang := self._t._w(QComboBox, "combo_language"):
            # Set internal keys as userData before translation
            for i in range(cb_lang.count()):
                cb_lang.setItemData(i, cb_lang.itemText(i))
                
            saved_lang = self._t.settings.get("language", "Deutsch")
            idx = cb_lang.findData(saved_lang)
            if idx >= 0:
                cb_lang.setCurrentIndex(idx)
            cb_lang.currentIndexChanged.connect(lambda i, c=cb_lang: self._on_language_changed(c.itemData(i)))

        # ── UI Tab: 2-Spalten-Layout ──────────────────────────────────────────
        if ui_tab := self._t._w(QWidget, "settings_tab_ui"):
            old_layout = ui_tab.layout()

            # Vorhandene Widgets aus dem .ui-Layout einsammeln (Theme, GCode, Language)
            left_widgets = []
            while old_layout.count():
                item = old_layout.takeAt(0)
                if w := item.widget():
                    w.setParent(None)
                    left_widgets.append(w)

            # Wrapper mit 2-Spalten-HBox in das leere Layout einhängen
            wrapper = QWidget()
            hbox = QHBoxLayout(wrapper)
            hbox.setSpacing(16)
            hbox.setContentsMargins(0, 0, 0, 0)

            left_vbox = QVBoxLayout()
            left_vbox.setSpacing(8)
            right_vbox = QVBoxLayout()
            right_vbox.setSpacing(8)

            # Linke Spalte: Theme, G-Code Highlighting, Language
            for w in left_widgets:
                left_vbox.addWidget(w)
            left_vbox.addStretch()

            hbox.addLayout(left_vbox, 1)
            hbox.addLayout(right_vbox, 1)
            old_layout.addWidget(wrapper)

            # ── Rechte Spalte: Grafik / Performance ──
            gb_gfx = QGroupBox(_t("Graphics / Performance"))
            gl_gfx = QVBoxLayout(gb_gfx)
            self._cb_aa = QCheckBox(_t("Backplot Antialiasing (Smoothing)"))
            self._cb_aa.setToolTip(_t("Improves line quality (MSAA). Requires restart for full effect."))
            active = self._t.settings.get("backplot_antialiasing", True)
            self._cb_aa.setChecked(active)
            self._cb_aa.toggled.connect(self._on_aa_toggled)
            gl_gfx.addWidget(self._cb_aa)

            lay_msaa = QHBoxLayout()
            lay_msaa.addWidget(QLabel(_t("MSAA Samples:")))
            self._cb_msaa = QComboBox()
            for x in [2, 4, 8, 16]:
                self._cb_msaa.addItem(f"{x}x", userData=x)
            saved_msaa = self._t.settings.get("backplot_msaa_samples", 4)
            idx = self._cb_msaa.findData(saved_msaa)
            if idx >= 0:
                self._cb_msaa.setCurrentIndex(idx)
            self._cb_msaa.setEnabled(active)
            self._cb_msaa.currentIndexChanged.connect(self._on_msaa_changed)
            lay_msaa.addWidget(self._cb_msaa)
            gl_gfx.addLayout(lay_msaa)

            self._cb_resource_monitor = QCheckBox(_t("Show CPU/RAM usage (bottom bar)"))
            self._cb_resource_monitor.setToolTip(_t("Shows CPU and RAM usage of the process in the bottom bar."))
            self._cb_resource_monitor.setChecked(self._t.settings.get("show_resource_monitor", False))
            self._cb_resource_monitor.toggled.connect(self._on_resource_monitor_toggled)
            gl_gfx.addWidget(self._cb_resource_monitor)
            right_vbox.addWidget(gb_gfx)

            # ── Rechte Spalte: Werkzeugliste ──
            gb_tools = QGroupBox(_t("Tool List"))
            gl_tools = QVBoxLayout(gb_tools)
            self._cb_show_pocket = QCheckBox(_t("Show Pocket Column"))
            self._cb_show_pocket.setToolTip(_t("Shows or hides the Pocket column (P) in the tool list."))
            show_pocket = self._t.settings.get("show_pocket_column", True)
            self._cb_show_pocket.setChecked(show_pocket)
            self._cb_show_pocket.toggled.connect(self._on_show_pocket_column_changed)
            gl_tools.addWidget(self._cb_show_pocket)
            right_vbox.addWidget(gb_tools)

            # ── Rechte Spalte: Backplot Farben ──
            self._setup_backplot_colors(right_vbox)
            right_vbox.addStretch()

            # Initiale Sichtbarkeit anwenden
            self._on_show_pocket_column_changed(show_pocket)



        # ── Machine Tab Cleanup & Probe Warning Settings ──────────────────────
        if mach_tab := self._t._w(QWidget, "settings_tab_machine"):
            # Clear existing
            if old_layout := mach_tab.layout():
                while old_layout.count():
                    item = old_layout.takeAt(0)
                    if w := item.widget():
                        w.setParent(None)
                        w.deleteLater()
                QWidget().setLayout(old_layout)
            
            main_layout = QHBoxLayout(mach_tab)
            main_layout.setContentsMargins(10, 10, 10, 10)
            main_layout.setSpacing(15)
            
            if gb_old_ts := self._t._w(QGroupBox, "groupBoxTsBeforeAfter"):
                gb_old_ts.hide()
            
            # --- Column 1: Machine Safety / Warnings (Left) ---
            col_safety = QVBoxLayout()
            f_safety = QFrame()
            f_safety.setFrameShape(QFrame.Shape.StyledPanel)
            f_safety.setObjectName("safetyFrame")
            fl_safety = QVBoxLayout(f_safety)
            gb_safety = QGroupBox(_t("Machine Safety / Warnings"))
            gl_safety = QVBoxLayout(gb_safety)
            
            lbl_desc = QLabel(_t("<b>Visual Probe Warning:</b><br>"
                              "Colors the status bar when digital outputs (M64) are active (e.g. for 3D probes)."))
            lbl_desc.setWordWrap(True)
            lbl_desc.setObjectName("settings_desc_label")
            gl_safety.addWidget(lbl_desc)
            
            self._cb_probe_warn = QCheckBox(_t("Enable Visual Warning"))
            gl_safety.addWidget(self._cb_probe_warn)

            lay_pins = QHBoxLayout()
            lay_pins.addWidget(QLabel(_t("M64 P... (Index):")))
            self._le_probe_pins = QLineEdit()
            self._le_probe_pins.setPlaceholderText(_t("e.g. 0, 2"))
            lay_pins.addWidget(self._le_probe_pins)
            gl_safety.addLayout(lay_pins)

            lay_color = QHBoxLayout()
            lay_color.addWidget(QLabel(_t("Warning Color:")))
            self._btn_probe_color = QPushButton(_t("SELECT"))
            self._btn_probe_color.setFixedWidth(120)
            lay_color.addWidget(self._btn_probe_color)
            lay_color.addStretch()
            gl_safety.addLayout(lay_color)

            # Connect to ProbingTabModule (which now handles warning state)
            if hasattr(self._t, "probing_tab"):
                self._t.probing_tab.connect_settings_widgets(
                    self._cb_probe_warn,
                    self._le_probe_pins,
                    self._btn_probe_color
                )
            
            gl_safety.addSpacing(10)
            sep2 = QFrame()
            sep2.setFrameShape(QFrame.Shape.HLine)
            sep2.setObjectName("settings_separator")
            gl_safety.addWidget(sep2)
            gl_safety.addSpacing(5)

            fl_safety.addWidget(gb_safety)
            fl_safety.addStretch()
            col_safety.addWidget(f_safety)
            main_layout.addLayout(col_safety, 1)
            
            # --- Column 2: Abort Handler (Middle) ---
            col_abort = QVBoxLayout()
            gb_abort = QGroupBox(_t("Abort Handler (STOP/Error)"))
            gl_abort = QVBoxLayout(gb_abort)
            
            lbl_abort_desc = QLabel(_t("<b>Abort G-Code:</b><br>"
                                     "This code is executed when the program is stopped.<br>"
                                     "<font color='#aaa'>INI [RS274NGC] ON_ABORT_COMMAND = O&lt;on_abort&gt; call</font>"))
            lbl_abort_desc.setWordWrap(True)
            gl_abort.addWidget(lbl_abort_desc)
            
            self._te_abort_gcode = QTextEdit()
            self._te_abort_gcode.setPlaceholderText(_t("e.g. M5 M9\nG54\nG90\nG40"))
            self._te_abort_gcode.setMinimumHeight(200)
            
            saved_abort = self._t.settings.get("abort_gcode", "M5 M9\nG54\nG90\nG40")
            self._te_abort_gcode.setPlainText(saved_abort)
            gl_abort.addWidget(self._te_abort_gcode)
            
            btn_save_abort = QPushButton(_t("SAVE & APPLY"))
            btn_save_abort.setMinimumHeight(45)
            btn_save_abort.clicked.connect(self._save_abort_handler)
            gl_abort.addWidget(btn_save_abort)
            
            col_abort.addWidget(gb_abort)
            main_layout.addLayout(col_abort, 2)
            
            # --- Column 3: Macros (Right) ---
            col_macros = QVBoxLayout()
            
            # --- Toolsetter Macros ---
            gb_ts = QGroupBox(_t("Toolsetter Macros (Before/After)"))
            gb_ts.setMinimumHeight(220)
            gl_ts = QVBoxLayout(gb_ts)

            self._te_ts_before = QTextEdit()
            self._te_ts_after = QTextEdit()

            gl_ts.addWidget(QLabel(_t("BEFORE TOOLSETTER (e.g. air blast on):")))
            gl_ts.addWidget(self._te_ts_before)
            gl_ts.addWidget(QLabel(_t("AFTER TOOLSETTER (e.g. air blast off):")))
            gl_ts.addWidget(self._te_ts_after)
            
            self._te_ts_before.setMaximumHeight(60)
            self._te_ts_after.setMaximumHeight(60)
            
            # Connect saving for Toolsetter
            for key, widget in (("ts_before", self._te_ts_before), ("ts_after", self._te_ts_after)):
                val = self._t.settings.get(key, "")
                widget.blockSignals(True)
                widget.setPlainText(str(val) if val else "")
                widget.blockSignals(False)
                widget.textChanged.connect(
                    lambda k=key, w=widget: self._on_ts_text_save(k, w)
                )
            col_macros.addWidget(gb_ts)
            
            # --- 3D Probe Macros ---
            gb_probe = QGroupBox(_t("3D Probe Macros (Before/After)"))
            gb_probe.setMinimumHeight(220)
            gl_probe = QVBoxLayout(gb_probe)

            self._te_probe_before = QTextEdit()
            self._te_probe_after = QTextEdit()

            gl_probe.addWidget(QLabel(_t("BEFORE PROBING (e.g. M64 P2):")))
            gl_probe.addWidget(self._te_probe_before)
            gl_probe.addWidget(QLabel(_t("AFTER PROBING (e.g. M65 P2):")))
            gl_probe.addWidget(self._te_probe_after)
            
            self._te_probe_before.setMaximumHeight(60)
            self._te_probe_after.setMaximumHeight(60)
            
            # Connect saving for Probe
            for key, widget in (("probe_before", self._te_probe_before), ("probe_after", self._te_probe_after)):
                val = self._t.settings.get(key, "")
                widget.blockSignals(True)
                widget.setPlainText(str(val) if val else "")
                widget.blockSignals(False)
                widget.textChanged.connect(
                    lambda k=key, w=widget: self._on_probe_text_save(k, w)
                )
            col_macros.addWidget(gb_probe)
            
            col_macros.addStretch()
            main_layout.addLayout(col_macros, 1)

        # ── Advanced Tab ──────────────────────────────────────────────────────
        if adv_tab := self._t._w(QWidget, "settings_tab_advanced"):
            # Clear existing
            if old_layout := adv_tab.layout():
                while old_layout.count():
                    item = old_layout.takeAt(0)
                    if w := item.widget():
                        w.setParent(None)
                        w.deleteLater()
                QWidget().setLayout(old_layout)
            
            adv_layout = QHBoxLayout(adv_tab)
            adv_layout.setContentsMargins(10, 10, 10, 10)
            adv_layout.setSpacing(15)

            # Col 1: Diagnostics
            col_diag_adv = QVBoxLayout()
            gb_diag_adv = QGroupBox(_t("Diagnostics & Components"))
            gl_diag_adv = QVBoxLayout(gb_diag_adv)

            for text, func in [
                (_t("HAL Show (Pins & Signals)"), self.run_halshow),
                (_t("HAL Scope (Oscilloscope)"), self.run_halscope),
                (_t("LinuxCNC Status (Detail Info)"), self.run_linuxcnc_status)
            ]:
                b = QPushButton(text)
                b.setMinimumHeight(45)
                b.clicked.connect(func)
                gl_diag_adv.addWidget(b)
            
            if b_sim := self._t._w(QPushButton, "btn_probe_sim"):
                gl_diag_adv.addWidget(b_sim)
                
            gl_diag_adv.addStretch()
            col_diag_adv.addWidget(gb_diag_adv)
            adv_layout.addLayout(col_diag_adv, 1)

            # Col 2: Machine Behavior
            col_behavior = QVBoxLayout()
            gb_behavior = QGroupBox(_t("Machine Behavior"))
            gl_behavior = QVBoxLayout(gb_behavior)
            
            # Repurpose Homing Buttons
            self._cb_homing_g53 = QCheckBox(_t("Repurpose homing buttons (Ref -> G53 X0)"))
            self._cb_homing_g53.setToolTip(_t("Replaces the REF button with G53 X0 once the axis is homed."))
            self._cb_homing_g53.setChecked(self._t.settings.get("homing_g53_conversion", False))
            self._cb_homing_g53.toggled.connect(
                lambda checked: (self._t.settings.set("homing_g53_conversion", checked),
                                 self._t.settings.save(),
                                 self._t.motion._on_homed(getattr(self._t.poller, "_homed", [])))
            )
            gl_behavior.addWidget(self._cb_homing_g53)

            # Arrow-key jogging
            self._cb_arrow_jog = QCheckBox(_t("Arrow key jogging (←→ X, ↑↓ Y, PgUp/Dn Z)"))
            self._cb_arrow_jog.setToolTip(_t("Enables keyboard jogging: arrow keys for X/Y, PgUp/Dn for Z."))
            self._cb_arrow_jog.setChecked(self._t.settings.get("arrow_key_jog", False))
            self._cb_arrow_jog.toggled.connect(
                lambda checked: (self._t.settings.set("arrow_key_jog", checked),
                                 self._t.settings.save())
            )
            gl_behavior.addWidget(self._cb_arrow_jog)
            gl_behavior.addStretch()
            col_behavior.addWidget(gb_behavior)
            adv_layout.addLayout(col_behavior, 1)

            # Col 3: About
            col_about = QVBoxLayout()
            gb_about = QGroupBox(_t("About"))
            gl_about = QVBoxLayout(gb_about)
            btn_about = QPushButton(_t("About ThorCNC"))
            btn_about.setMinimumHeight(45)
            btn_about.clicked.connect(self._show_about_dialog)
            gl_about.addWidget(btn_about)
            gl_about.addStretch()
            col_about.addWidget(gb_about)
            adv_layout.addLayout(col_about, 1)

            adv_layout.addStretch()

        # ── Abort Handler & Toolsetter Initialization ────────────────────────
        self._write_on_abort_ngc()
        
        # Spinboxen laden & verbinden
        for widget_name, prefs_key, default in self._TOOLSENSOR_FIELDS:
            dsb = self._t._w(QDoubleSpinBox, widget_name)
            if not dsb:
                continue

            val = self._t.settings.get(prefs_key, default)
            dsb.blockSignals(True)
            dsb.setValue(float(val))
            dsb.blockSignals(False)

            self._hal_set(prefs_key, float(val))

            dsb.valueChanged.connect(
                lambda v, k=prefs_key: self._on_toolsensor_changed(k, v)
            )

        if dsb := self._t._w(QDoubleSpinBox, "dsb_ts_spindle_zero"):
            dsb.setToolTip(_t("The probe reads a negative Z value — enter the absolute value (positive) here."))

        if b := self._t._w(QPushButton, "btn_set_wechsel_pos"):
            b.clicked.connect(self._set_wechsel_pos_from_machine)
        if b := self._t._w(QPushButton, "btn_set_taster_pos"):
            b.clicked.connect(self._set_taster_pos_from_machine)

        self._setup_large_tool_offset()
        self._write_ts_before_after()
        self._write_probe_before_after()

    # ── Backplot Farben ───────────────────────────────────────────────────────

    def _setup_backplot_colors(self, parent_layout):
        """Erzeugt die Farbauswahl-Gruppe für den Backplot im UI-Tab."""
        gb = QGroupBox(_t("Backplot Colors / Sizes"))
        outer = QVBoxLayout(gb)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        saved = self._t.settings.get("backplot_colors", {})

        # Zwei gleichbreite Spalten nebeneinander
        cols_lay = QHBoxLayout()
        cols_lay.setSpacing(20)

        left_keys  = _BACKPLOT_COLOR_KEYS[:3]   # Fräser, Hintergrund, Vorschub
        right_keys = _BACKPLOT_COLOR_KEYS[3:]   # Trail, Eilgang, Bogen

        for group in (left_keys, right_keys):
            col_grid = QGridLayout()
            col_grid.setHorizontalSpacing(8)
            col_grid.setVerticalSpacing(5)
            col_grid.setColumnStretch(1, 1)   # Button-Spalte dehnt sich aus
            for row_i, (key, label) in enumerate(group):
                hex_color = saved.get(key, _BACKPLOT_COLOR_DEFAULTS[key])
                lbl = QLabel(_t(label) + ":")
                lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                btn = QPushButton()
                btn.setFixedHeight(28)
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                self._set_color_btn_style(btn, hex_color)
                btn.clicked.connect(lambda _=False, k=key, b=btn: self._pick_backplot_color(k, b))
                col_grid.addWidget(lbl, row_i, 0)
                col_grid.addWidget(btn, row_i, 1)

            wrapper = QWidget()
            wrapper.setLayout(col_grid)
            cols_lay.addWidget(wrapper, 1)   # gleicher Stretch für beide Hälften

        outer.addLayout(cols_lay)

        # ── Trennlinie + WCS-Kreuz Größe ──────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        outer.addWidget(sep)

        wcs_lay = QHBoxLayout()
        wcs_lay.setSpacing(8)
        wcs_lay.addWidget(QLabel(_t("WCS Cross Size (mm):")))
        self._dsb_wcs_size = QDoubleSpinBox()
        self._dsb_wcs_size.setRange(5.0, 200.0)
        self._dsb_wcs_size.setSingleStep(5.0)
        self._dsb_wcs_size.setDecimals(1)
        self._dsb_wcs_size.setFixedWidth(100)
        self._dsb_wcs_size.setValue(float(saved.get("wcs_size", _BACKPLOT_COLOR_DEFAULTS["wcs_size"])))
        self._dsb_wcs_size.valueChanged.connect(self._on_wcs_size_changed)
        wcs_lay.addWidget(self._dsb_wcs_size)
        wcs_lay.addStretch()
        outer.addLayout(wcs_lay)

        parent_layout.addWidget(gb)

    @staticmethod
    def _set_color_btn_style(btn: QPushButton, hex_color: str):
        c = QColor(hex_color)
        brightness = c.red() * 0.299 + c.green() * 0.587 + c.blue() * 0.114
        text = "#000000" if brightness > 128 else "#ffffff"
        btn.setStyleSheet(
            f"background-color:{hex_color}; color:{text}; border:1px solid #555; border-radius:3px;"
        )
        btn.setText(hex_color)

    def _pick_backplot_color(self, key: str, btn: QPushButton):
        saved = self._t.settings.get("backplot_colors", {})
        current_hex = saved.get(key, _BACKPLOT_COLOR_DEFAULTS[key])
        color = QColorDialog.getColor(QColor(current_hex), None, _t("Choose Color"))
        if not color.isValid():
            return
        hex_color = color.name()

        # In Settings speichern
        saved[key] = hex_color
        self._t.settings.set("backplot_colors", saved)
        self._t.settings.save()

        # Button aktualisieren
        self._set_color_btn_style(btn, hex_color)

        # Auf beide Backplots anwenden (Haupt + SimpleView)
        self._t.backplot.set_colors({key: hex_color})
        try:
            sv = self._t.simple_view_mod.simple_view
            if sv and getattr(sv, "backplot", None):
                sv.backplot.set_colors({key: hex_color})
        except AttributeError:
            pass

    # ── Großwerkzeug-Versatz ─────────────────────────────────────────────────

    _OFFSET_DIRS = {
        "X+": ( 1.0,  0.0),
        "X-": (-1.0,  0.0),
        "Y+": ( 0.0,  1.0),
        "Y-": ( 0.0, -1.0),
    }

    def _setup_large_tool_offset(self):
        """Neue GroupBox im Toolsetter-Tab für den Großwerkzeug-Versatz."""
        ts_tab = self._t._w(QWidget, "settings_tab_toolsetter")
        if not ts_tab:
            return
        layout = ts_tab.layout()
        if not layout:
            return

        gb = QGroupBox(_t("Large Tools (> Probe Contact Surface)"))
        vbox = QVBoxLayout(gb)
        vbox.setSpacing(6)
        vbox.setContentsMargins(10, 10, 10, 10)

        # Beschreibung
        lbl_desc = QLabel(_t(
            "If the tool diameter is larger than the probe contact surface,\n"
            "the position is offset by the tool radius before measurement,\n"
            "so the cutting edge is centered over the probe."
        ))
        lbl_desc.setObjectName("settings_desc_label")
        lbl_desc.setWordWrap(True)
        vbox.addWidget(lbl_desc)

        # Checkbox: Feature aktiv
        self._cb_large_tool = QCheckBox(_t("Enable offset when tool > contact surface"))
        enabled = self._t.settings.get("ts_large_tool_enable", False)
        self._cb_large_tool.setChecked(bool(enabled))
        self._cb_large_tool.toggled.connect(self._on_large_tool_toggled)
        vbox.addWidget(self._cb_large_tool)

        # Kontaktfläche Ø + Richtung nebeneinander
        row_lay = QHBoxLayout()
        row_lay.setSpacing(16)

        row_lay.addWidget(QLabel(_t("Contact surface diameter (mm):")))
        self._dsb_contact_dia = QDoubleSpinBox()
        self._dsb_contact_dia.setRange(1.0, 200.0)
        self._dsb_contact_dia.setSingleStep(0.5)
        self._dsb_contact_dia.setDecimals(1)
        self._dsb_contact_dia.setFixedWidth(80)
        self._dsb_contact_dia.setValue(float(self._t.settings.get("ts_contact_diameter", 16.0)))
        self._dsb_contact_dia.valueChanged.connect(self._on_contact_dia_changed)
        row_lay.addWidget(self._dsb_contact_dia)

        row_lay.addSpacing(20)
        row_lay.addWidget(QLabel(_t("Offset direction:")))
        self._cb_offset_dir = QComboBox()
        for d in self._OFFSET_DIRS:
            self._cb_offset_dir.addItem(d)
        saved_dir = self._t.settings.get("ts_offset_direction", "X+")
        idx = self._cb_offset_dir.findText(saved_dir)
        if idx >= 0:
            self._cb_offset_dir.setCurrentIndex(idx)
        self._cb_offset_dir.currentTextChanged.connect(self._on_offset_dir_changed)
        self._cb_offset_dir.setFixedWidth(70)
        row_lay.addWidget(self._cb_offset_dir)
        row_lay.addStretch()
        vbox.addLayout(row_lay)

        layout.addWidget(gb)

        # HAL-Pins beim Start setzen
        self._sync_large_tool_hal()

    def _sync_large_tool_hal(self):
        """Alle Großwerkzeug-HAL-Pins aus den gespeicherten Werten setzen."""
        if not self._t._hal_comp:
            return
        try:
            enabled = bool(self._t.settings.get("ts_large_tool_enable", False))
            dia     = float(self._t.settings.get("ts_contact_diameter", 16.0))
            dirkey  = self._t.settings.get("ts_offset_direction", "X+")
            dx, dy  = self._OFFSET_DIRS.get(dirkey, (1.0, 0.0))
            self._t._hal_comp["ts-large-tool-enable"] = enabled
            self._t._hal_comp["ts-contact-diameter"]  = dia
            self._t._hal_comp["ts-offset-dir-x"]      = dx
            self._t._hal_comp["ts-offset-dir-y"]      = dy
        except Exception:
            pass

    def _on_large_tool_toggled(self, enabled: bool):
        self._t.settings.set("ts_large_tool_enable", enabled)
        self._t.settings.save()
        self._sync_large_tool_hal()

    def _on_contact_dia_changed(self, value: float):
        self._t.settings.set("ts_contact_diameter", value)
        self._t.settings.save()
        self._sync_large_tool_hal()

    def _on_offset_dir_changed(self, text: str):
        self._t.settings.set("ts_offset_direction", text)
        self._t.settings.save()
        self._sync_large_tool_hal()

    def _on_wcs_size_changed(self, value: float):
        saved = self._t.settings.get("backplot_colors", {})
        saved["wcs_size"] = value
        self._t.settings.set("backplot_colors", saved)
        self._t.settings.save()
        self._t.backplot.set_colors({"wcs_size": value})
        try:
            sv = self._t.simple_view_mod.simple_view
            if sv and getattr(sv, "backplot", None):
                sv.backplot.set_colors({"wcs_size": value})
        except AttributeError:
            pass

    def _save_abort_handler(self):
        """Speichert den G-Code für den Abort-Handler und aktualisiert die .ngc Datei."""
        gcode = self._te_abort_gcode.toPlainText()
        self._t.settings.set("abort_gcode", gcode)
        self._t.settings.save()
        self._write_on_abort_ngc()

    def _write_on_abort_ngc(self):
        """Aktualisiert die on_abort.ngc Datei basierend auf dem aktuellen UI-Inhalt."""
        if not hasattr(self, "_te_abort_gcode"):
            return
            
        gcode = self._te_abort_gcode.toPlainText()
        ini_dir = os.path.dirname(self._t.ini_path) if self._t.ini_path else os.getcwd()
        ngc_filename = "on_abort.ngc"
        target_path = None
        
        local_sub = os.path.join(ini_dir, "subroutines", ngc_filename)
        if os.path.exists(local_sub):
            target_path = local_sub
        
        if not target_path and self._t.ini:
            sub_paths = self._t.ini.find("RS274NGC", "SUBROUTINE_PATH")
            if sub_paths:
                for p in sub_paths.split(":"):
                    p = p.strip()
                    if not p: continue
                    full_p = os.path.expanduser(p)
                    if not os.path.isabs(full_p):
                        full_p = os.path.join(ini_dir, full_p)
                    
                    test_path = os.path.join(full_p, ngc_filename)
                    if os.path.exists(test_path):
                        target_path = test_path
                        break
        
        if not target_path:
            target_path = local_sub
            
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write("(--- Dynamically generated by ThorCNC ---)\n")
                f.write("(--- Settings -> Machine -> Abort Handler ---)\n\n")
                f.write("o<on_abort> sub\n")
                for line in gcode.splitlines():
                    f.write(f"  {line}\n")
                f.write("o<on_abort> endsub\n")
                f.write("M2\n")
            
            self._t._status(f"Abort-Handler synchronisiert: {target_path}")
        except Exception as e:
            self._t._status(f"Fehler beim Schreiben des Abort-Handlers: {e}", error=True)

    def _hal_set(self, prefs_key: str, value: float):
        if not self._t._hal_comp:
            return
        try:
            pin_name = prefs_key.replace("_", "-")
            self._t._hal_comp[pin_name] = value
        except Exception:
            pass

    def _on_toolsensor_changed(self, key: str, value: float):
        self._t.settings.set(key, value)
        self._t.settings.save()
        self._hal_set(key, value)

    def _on_ts_text_save(self, key: str, widget):
        self._t.settings.set(key, widget.toPlainText())
        self._t.settings.save()
        self._write_ts_before_after()
        before = self._t.settings.get("ts_before", "") or ""
        after  = self._t.settings.get("ts_after",  "") or ""
        self._t._status(f"Toolsetter  BEFORE: [{before.strip() or '—'}]  |  AFTER: [{after.strip() or '—'}]")

    def _ts_ngc_dir(self) -> str:
        search_dirs = []
        if self._t.ini_path:
            search_dirs.append(os.path.dirname(os.path.abspath(self._t.ini_path)))
        if self._t.ini:
            prefix = self._t.ini.find("DISPLAY", "PROGRAM_PREFIX")
            if prefix:
                prefix = os.path.expanduser(prefix)
                if not os.path.isabs(prefix) and self._t.ini_path:
                    prefix = os.path.abspath(os.path.join(os.path.dirname(self._t.ini_path), prefix))
                search_dirs.append(prefix)
        search_dirs.append(os.path.expanduser("~/linuxcnc/nc_files"))
        
        for base in search_dirs:
            sub = os.path.join(base, "subroutines")
            if os.path.isdir(sub): return sub
        return search_dirs[1] if len(search_dirs) > 1 else search_dirs[0]

    def _write_ts_before_after(self):
        ngc_dir = self._ts_ngc_dir()
        before_code = self._t.settings.get("ts_before", "").strip()
        after_code  = self._t.settings.get("ts_after", "").strip()
        try:
            os.makedirs(ngc_dir, exist_ok=True)
            with open(os.path.join(ngc_dir, "before_toolsetter.ngc"), "w") as f:
                f.write("O<before_toolsetter> sub\n")
                if before_code: f.write(f"  {before_code}\n")
                f.write("O<before_toolsetter> endsub\nM2\n")
            with open(os.path.join(ngc_dir, "after_toolsetter.ngc"), "w") as f:
                f.write("O<after_toolsetter> sub\n")
                if after_code: f.write(f"  {after_code}\n")
                f.write("O<after_toolsetter> endsub\nM2\n")
        except Exception as e:
            self._t._status(f"Could not write toolsetter NGC files: {e}", error=True)

    def _on_probe_text_save(self, key: str, widget):
        self._t.settings.set(key, widget.toPlainText())
        self._t.settings.save()
        self._write_probe_before_after()
        before = self._t.settings.get("probe_before", "") or ""
        after  = self._t.settings.get("probe_after", "") or ""
        self._t._status(f"3D Probe  BEFORE: [{before.strip() or '—'}]  |  AFTER: [{after.strip() or '—'}]")

    def _write_probe_before_after(self):
        # We reuse the ts_ngc_dir as it resolves to `subroutines`
        ngc_dir = self._ts_ngc_dir()
        before_code = self._t.settings.get("probe_before", "").strip()
        after_code  = self._t.settings.get("probe_after", "").strip()
        try:
            os.makedirs(ngc_dir, exist_ok=True)
            with open(os.path.join(ngc_dir, "before_probe.ngc"), "w") as f:
                f.write("O<before_probe> sub\n")
                if before_code: f.write(f"  {before_code}\n")
                f.write("O<before_probe> endsub\n")
            with open(os.path.join(ngc_dir, "after_probe.ngc"), "w") as f:
                f.write("O<after_probe> sub\n")
                if after_code: f.write(f"  {after_code}\n")
                f.write("O<after_probe> endsub\n")
        except Exception as e:
            self._t._status(f"Could not write probe NGC files: {e}", error=True)

    def _on_aa_toggled(self, enabled: bool):
        self._t.settings.set("backplot_antialiasing", enabled)
        self._t.settings.save()
        self._t.backplot.set_antialiasing(enabled)
        if hasattr(self, "_cb_msaa"):
            self._cb_msaa.setEnabled(enabled)
        self._t._status(_t("Antialiasing master switch changed. (MSAA level requires restart)"))

    def _on_msaa_changed(self, index: int):
        val = self._cb_msaa.itemData(index)
        self._t.settings.set("backplot_msaa_samples", val)
        self._t.settings.save()
        self._t._status(_t("MSAA set to {}x. A restart is required.").format(val))

    def _on_resource_monitor_toggled(self, enabled: bool):
        self._t.settings.set("show_resource_monitor", enabled)
        self._t.settings.save()
        if lbl := getattr(self._t, "_lbl_resource_monitor", None):
            lbl.setVisible(enabled)
        if timer := getattr(self._t, "_res_timer", None):
            if enabled:
                self._t._update_resource_monitor()
                timer.start()
            else:
                timer.stop()

    def _on_show_pocket_column_changed(self, visible: bool):
        from PySide6.QtWidgets import QTableWidget
        if w := self._t._w(QTableWidget, "toolTable"):
            w.setColumnHidden(1, not visible)
        self._t.settings.set("show_pocket_column", visible)
        self._t.settings.save()

    def _html_tab_index(self) -> int:
        tab = self._t._w(QTabWidget, "tabWidget")
        if not tab: return 5
        for i in range(tab.count()):
            if tab.widget(i) and tab.widget(i).objectName() == "tab_html":
                return i
        return 5

    def _on_language_changed(self, lang_key):
        """Sprache wechseln und UI neu laden."""
        if not lang_key: return
        self._t.settings.set("language", lang_key)
        self._t.settings.save()
        self._t._status(_t("Language set to {}. Restart recommended.").format(lang_key))
        # Translation in ThorCNC handles the rest via i18n manager if fully implemented

    def _set_wechsel_pos_from_machine(self):
        res = QMessageBox.question(self._t.ui, _t("Capture Position"),
                                  _t("Do you really want to set the current machine position as the new CHANGE POSITION?"),
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res != QMessageBox.StandardButton.Yes: return
        pos = getattr(self._t, "_last_pos", None)
        if pos is None: return self._t._status(_t("No position data available!"), error=True)
        mapping = [("dsb_ts_wechsel_x", "ts_wechsel_x", 0), ("dsb_ts_wechsel_y", "ts_wechsel_y", 1), ("dsb_ts_wechsel_z", "ts_wechsel_z", 2)]
        for wname, pkey, idx in mapping:
            if dsb := self._t._w(QDoubleSpinBox, wname): dsb.setValue(pos[idx])
        self._t._status(_t("Change position set from current machine position."))

    def _set_taster_pos_from_machine(self):
        res = QMessageBox.question(self._t.ui, _t("Capture Position"),
                                  _t("Do you really want to set the current machine position as the new PROBE POSITION?"),
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res != QMessageBox.StandardButton.Yes: return
        pos = getattr(self._t, "_last_pos", None)
        if pos is None: return self._t._status(_t("No position data available!"), error=True)
        mapping = [("dsb_ts_x", "ts_x", 0), ("dsb_ts_y", "ts_y", 1), ("dsb_ts_z", "ts_z", 2)]
        for wname, pkey, idx in mapping:
            if dsb := self._t._w(QDoubleSpinBox, wname): dsb.setValue(pos[idx])
        self._t._status(_t("Probe position set from current machine position."))

    def run_halshow(self):
        import subprocess
        subprocess.Popen(["halshow"])

    def run_halscope(self):
        import subprocess
        subprocess.Popen(["halscope"])

    def run_linuxcnc_status(self):
        import subprocess
        subprocess.Popen(["linuxcnc_status"])

    def _show_about_dialog(self):
        from .. import __version__
        dlg = QMessageBox()
        dlg.setWindowTitle(_t("About ThorCNC"))
        dlg.setText(
            f"<h2>ThorCNC</h2>"
            f"<p>{_t('Version')}: <b>{__version__}</b></p>"
            f"<p>LinuxCNC VCP — Mill (mm), PySide6</p>"
            f"<p>GPL-2.0-or-later</p>"
        )
        dlg.setStandardButtons(QMessageBox.StandardButton.Ok)
        dlg.exec()
