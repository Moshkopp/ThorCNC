"""Settings tab module for ThorCNC — UI settings, machine safety, abort handler, toolsetter config."""

import os
import linuxcnc
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QPushButton, QComboBox, QCheckBox, QGroupBox, QVBoxLayout, 
    QWidget, QLineEdit, QHBoxLayout, QLabel, QTextEdit, QFrame,
    QDoubleSpinBox, QMessageBox, QTabWidget, QColorDialog
)
from PySide6.QtGui import QColor

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

        # ── UI Settings (Antialiasing, Tabs, etc) ──
        if ui_tab := self._t._w(QWidget, "settings_tab_ui"):
            layout = ui_tab.layout()
            gb_gfx = QGroupBox(_t("Grafik / Performance"))
            gl_gfx = QVBoxLayout(gb_gfx)
            self._cb_aa = QCheckBox(_t("Backplot Antialiasing (Glättung)"))
            self._cb_aa.setToolTip(_t("Verbessert die Linienqualität (MSAA). Erfordert Neustart für volle Wirkung."))
            
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
            if idx >= 0: self._cb_msaa.setCurrentIndex(idx)
            
            self._cb_msaa.setEnabled(active)
            self._cb_msaa.currentIndexChanged.connect(self._on_msaa_changed)
            
            lay_msaa.addWidget(self._cb_msaa)
            gl_gfx.addLayout(lay_msaa)

            layout.insertWidget(layout.count() - 1, gb_gfx)

            # ── Navigation / Tabs ──
            # (HTML tab removed)

            # ── Werkzeugliste ──
            gb_tools = QGroupBox(_t("Werkzeugliste"))
            gl_tools = QVBoxLayout(gb_tools)
            self._cb_show_pocket = QCheckBox(_t("Pocket-Spalte anzeigen"))
            self._cb_show_pocket.setToolTip(_t("Zeigt oder verbirgt die Pocket-Spalte (P) in der Werkzeugliste."))
            show_pocket = self._t.settings.get("show_pocket_column", True)
            self._cb_show_pocket.setChecked(show_pocket)
            self._cb_show_pocket.toggled.connect(self._on_show_pocket_column_changed)
            gl_tools.addWidget(self._cb_show_pocket)
            layout.insertWidget(layout.count() - 1, gb_tools)
            
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
            
            # --- Column 1: Machine Safety / Warnings (Left) ---
            col_safety = QVBoxLayout()
            f_safety = QFrame()
            f_safety.setFrameShape(QFrame.Shape.StyledPanel)
            f_safety.setObjectName("safetyFrame")
            fl_safety = QVBoxLayout(f_safety)
            gb_safety = QGroupBox(_t("Maschinensicherheit / Warnungen"))
            gl_safety = QVBoxLayout(gb_safety)
            
            lbl_desc = QLabel(_t("<b>Visuelle Taster-Warnung:</b><br>"
                              "Färbt die Statuszeile auffällig ein, wenn digitale "
                              "Ausgänge (M64) aktiv sind (z.B. für 3D-Taster)."))
            lbl_desc.setWordWrap(True)
            lbl_desc.setObjectName("settings_desc_label")
            gl_safety.addWidget(lbl_desc)
            
            self._cb_probe_warn = QCheckBox(_t("Visuelle Warnung aktivieren"))
            gl_safety.addWidget(self._cb_probe_warn)

            lay_pins = QHBoxLayout()
            lay_pins.addWidget(QLabel(_t("M64 P... (Index):")))
            self._le_probe_pins = QLineEdit()
            self._le_probe_pins.setPlaceholderText(_t("z.B. 0, 2"))
            lay_pins.addWidget(self._le_probe_pins)
            gl_safety.addLayout(lay_pins)

            lay_color = QHBoxLayout()
            lay_color.addWidget(QLabel(_t("Warnfarbe:")))
            self._btn_probe_color = QPushButton(_t("WÄHLEN"))
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

            self._cb_homing_g53 = QCheckBox(_t("Homing-Buttons umfunktionieren (Ref -> G53 X0)"))
            self._cb_homing_g53.setToolTip(_t("Ersetzt den REF-Button durch G53 X0, sobald die Achse homed ist."))
            self._cb_homing_g53.setChecked(self._t.settings.get("homing_g53_conversion", False))
            self._cb_homing_g53.toggled.connect(
                lambda checked: (self._t.settings.set("homing_g53_conversion", checked),
                                 self._t.settings.save(),
                                 self._t.motion._on_homed(getattr(self._t.poller, "_homed", [])))
            )
            gl_safety.addWidget(self._cb_homing_g53)
            
            fl_safety.addWidget(gb_safety)
            fl_safety.addStretch()
            col_safety.addWidget(f_safety)
            main_layout.addLayout(col_safety, 1)
            
            # --- Column 2: Abort Handler (Middle) ---
            col_abort = QVBoxLayout()
            gb_abort = QGroupBox(_t("Abort Handler (STOP/Fehler)"))
            gl_abort = QVBoxLayout(gb_abort)
            
            lbl_abort_desc = QLabel(_t("<b>G-Code bei Abbruch:</b><br>"
                                     "Dieser Code wird ausgeführt, wenn das Programm gestoppt wird.<br>"
                                     "<font color='#aaa'>INI [RS274NGC] ON_ABORT_COMMAND = O&lt;on_abort&gt; call</font>"))
            lbl_abort_desc.setWordWrap(True)
            gl_abort.addWidget(lbl_abort_desc)
            
            self._te_abort_gcode = QTextEdit()
            self._te_abort_gcode.setPlaceholderText(_t("z.B. M5 M9\nG54\nG90\nG40"))
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
            
            # --- Column 3: Diagnostics & Components (Right) ---
            col_diag = QVBoxLayout()
            gb_diag = QGroupBox(_t("Diagnose & Komponenten"))
            gl_diag = QVBoxLayout(gb_diag)
            
            diag_tools = [
                (_t("HAL Show (Pins & Signale)"), self.run_halshow),
                (_t("HAL Scope (Oszilloskop)"), self.run_halscope),
                (_t("LinuxCNC Status (Detail-Infos)"), self.run_linuxcnc_status)
            ]
            
            for text, func in diag_tools:
                b = QPushButton(text)
                b.setMinimumHeight(45)
                b.clicked.connect(func)
                gl_diag.addWidget(b)
            
            if b_sim := self._t._w(QPushButton, "btn_probe_sim"):
                gl_diag.addWidget(b_sim)
            
            gl_diag.addStretch()
            col_diag.addWidget(gb_diag)
            main_layout.addLayout(col_diag, 1)

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

        if b := self._t._w(QPushButton, "btn_set_wechsel_pos"):
            b.clicked.connect(self._set_wechsel_pos_from_machine)
        if b := self._t._w(QPushButton, "btn_set_taster_pos"):
            b.clicked.connect(self._set_taster_pos_from_machine)

        for key, wname in (("ts_before", "te_ts_before"), ("ts_after", "te_ts_after")):
            if te := self._t._w(QTextEdit, wname):
                val = self._t.settings.get(key, "")
                te.blockSignals(True)
                te.setPlainText(str(val) if val else "")
                te.blockSignals(False)
                te.textChanged.connect(
                    lambda k=key, widget=te: self._on_ts_text_save(k, widget)
                )
        self._write_ts_before_after()

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
            sub = os.path.join(base, "subroutines", "tools")
            if os.path.isdir(sub): return sub
        return search_dirs[1] if len(search_dirs) > 1 else search_dirs[0]

    def _write_ts_before_after(self):
        ngc_dir = self._ts_ngc_dir()
        before_code = ""
        after_code = ""
        if te := self._t._w(QTextEdit, "te_ts_before"):
            before_code = te.toPlainText().strip()
        if te := self._t._w(QTextEdit, "te_ts_after"):
            after_code = te.toPlainText().strip()
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

    def _on_aa_toggled(self, enabled: bool):
        self._t.settings.set("backplot_antialiasing", enabled)
        self._t.settings.save()
        self._t.backplot.set_antialiasing(enabled)
        if hasattr(self, "_cb_msaa"):
            self._cb_msaa.setEnabled(enabled)
        self._t._status(_t("Antialiasing-Master-Schalter geändert. (MSAA-Level braucht Neustart)"))

    def _on_msaa_changed(self, index: int):
        val = self._cb_msaa.itemData(index)
        self._t.settings.set("backplot_msaa_samples", val)
        self._t.settings.save()
        self._t._status(_t("MSAA auf {}x gesetzt. Ein Neustart ist nötig.").format(val))

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
        self._t._status(_t("Sprache auf {} gesetzt. Neustart empfohlen.").format(lang_key))
        # Translation in ThorCNC handles the rest via i18n manager if fully implemented

    def _set_wechsel_pos_from_machine(self):
        res = QMessageBox.question(self._t.ui, _t("Position übernehmen"), 
                                  _t("Möchtest du die aktuelle Maschinenposition wirklich als neue WECHSELPOSITION übernehmen?"),
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res != QMessageBox.StandardButton.Yes: return
        pos = getattr(self._t, "_last_pos", None)
        if pos is None: return self._t._status(_t("Keine Positionsdaten verfügbar!"), error=True)
        mapping = [("dsb_ts_wechsel_x", "ts_wechsel_x", 0), ("dsb_ts_wechsel_y", "ts_wechsel_y", 1), ("dsb_ts_wechsel_z", "ts_wechsel_z", 2)]
        for wname, pkey, idx in mapping:
            if dsb := self._t._w(QDoubleSpinBox, wname): dsb.setValue(pos[idx])
        self._t._status(_t("Change position set from current machine position."))

    def _set_taster_pos_from_machine(self):
        res = QMessageBox.question(self._t.ui, _t("Position übernehmen"), 
                                  _t("Möchtest du die aktuelle Maschinenposition wirklich als neue MESSPOSITION übernehmen?"),
                                  QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res != QMessageBox.StandardButton.Yes: return
        pos = getattr(self._t, "_last_pos", None)
        if pos is None: return self._t._status(_t("Keine Positionsdaten verfügbar!"), error=True)
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
