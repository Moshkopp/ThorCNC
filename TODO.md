# ThorCNC TODO

---

## 🔲 Offene Punkte

### Versionierung
- [ ] Automatische Versionierung (Bump-Script oder hatch-vcs) — noch offen



### Probe Result Panel
- [ ] Toleranz für Δ-Anzeige konfigurierbar machen (initial fix ±0.05mm)
- [ ] CSV-Export aus History
- [ ] Optional: Banner-Warnung "MEASURE ONLY MODE" bei Auto-Zero OFF

### Surface Map
- [x] NGC-Subroutine: Snake-Pattern Grid-Probing, Z-Werte in nummerierten Parametern ✅
- [x] Heatmap-Widget: bilineare Interpolation, Messpunkt-Dots mit Z-Labels, Farbskala ✅
- [x] Scan-Steuerung: Start/Abort, Progressbar, Polling via mtime + INTERP-Idle ✅
- [ ] Workflow: Werkstückgröße + Kantenversatz + aktuelle Position als Referenzpunkt
- [ ] Radiobutton-Auswahl des Startpunkts direkt in der Heatmap
- [ ] Mesh-Kompensation: Z-Map als Korrektur-Offset auf G-Code anwenden
- [ ] Export: Surface Map als CSV

---

## 🛠️ Laufende Arbeiten

### Probing Script Robustheit (G-Code) — abgeschlossen ✅
- [x] Pattern auf alle 28 Subs übertragen und an Maschine validiert (2026-04-25)
- [x] `ProbeResultPanel` + `ProbeHistoryDialog` implementiert
- [x] Polling über `.var`-Datei (mtime-basiert)
- [x] SIM Probe Trigger Button eingebaut
- [x] Probe Result Panel: Layout & Style überarbeitet

---

## ✅ Abgeschlossene Modularisierung

### Struktur-Status (MainWindow)
- **Original:** ~5.027 Zeilen
- **Aktuell:** **564 Zeilen** ✅ Ziel erreicht (Ziel: ~600 Zeilen)
- **Gesamt-Einsparung:** 4463 Zeilen (88%)
- **Module:** 17 Spezialisierte + 1 Base = 18 insgesamt

### Schritt 1–10: Fundament & Kern-Module ✅
FileManager, ToolTable, Offsets, Motion, ProbingTab, Settings, DRO, Spindle, SimpleView, GCodeView, MDI

### Schritt 11–15: Erweiterung ✅
HAL, ControlPanel, Backplot, ProgramControl, Status, HighlightSettings

### Schritt 16: Final Cleanup ✅
- [x] Nav-Wiring, `_sync_nav_buttons`, `_on_digital_out_changed`, `_on_language_changed` in Module verschoben
- [x] `setup_widget()`, `setup_flyouts()`, `replace_vtk_placeholder()` aus MainWindow extrahiert
- [x] Unused imports bereinigt

### Schritt 17: Debug-Cleanup & Kleinfixes ✅
- [x] Alle `[ProbeDBG]`, `[DIAGNOSTIC]`, `[DEBUG]` und Verbose-Startup-Prints entfernt
- [x] `en.json`: falsche deutsche Übersetzung für `"- Delete Selected"` korrigiert
- [x] `spindle.py`: doppelten `import linuxcnc` entfernt
- [x] `navigation.py`: `QTimer` korrekt aus `QtCore` importiert

---

## 📊 Modul-Übersicht

| Modul | Zeilen | Datei |
|---|---|---|
| FileManagerModule | ~270 | modules/file_manager.py |
| ToolTableModule | ~362 | modules/tool_table.py |
| OffsetsModule | ~172 | modules/offsets.py |
| MotionModule | ~343 | modules/motion.py |
| ProbingTabModule | ~801 | modules/probing_tab.py |
| NavigationModule | ~400 | modules/navigation.py |
| SettingsTabModule | ~500 | modules/settings_tab.py |
| DROModule | ~310 | modules/dro.py |
| SpindleModule | ~150 | modules/spindle.py |
| SimpleViewModule | ~120 | modules/simple_view.py |
| GCodeViewModule | ~320 | modules/gcode_view.py |
| MDIModule | ~120 | modules/mdi.py |
| HALModule | ~100 | modules/hal.py |
| ControlPanelModule | ~130 | modules/control_panel.py |
| BackplotModule | ~105 | modules/backplot.py |
| ProgramControlModule | ~298 | modules/program_control.py |
| StatusModule | ~85 | modules/status.py |
| SurfaceMapModule | ~426 | modules/surface_map.py |
| SurfaceMapWidget | ~283 | widgets/surface_map_widget.py |

---

---

## ✅ Heute abgeschlossen (01.05.2026)

- [x] About-Button unter Settings → Advanced, zeigt Version aus `thorcnc.__version__` ✅
- [x] Toolsetter Spindle Zero: Minimum = 0, Tooltip erklärt Vorzeichen-Konvention ✅
- [x] Manual Tool Selection Dialog: Diameter zentriert, Spalten optimiert ✅
- [x] HAL-Pins: `thorcnc.simple-view` (Schalter) + `thorcnc.simple-view-toggle` (Taster) ✅
- [x] Programm-Icon: SVG erstellt (`thorcnc/images/icon.svg`), in App + install.sh eingebunden ✅

*Letztes Update: 01.05.2026*
