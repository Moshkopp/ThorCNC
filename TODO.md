# ThorCNC TODO - Modularisierung Roadmap

## 🎯 Vision

MainWindow.py (5000+ Zeilen) in ein modulares System umwandeln, wo jede Funktion vollständige Verantwortung für ihren Bereich übernimmt:
- **Probing** alles, was mit Probing zu tun hat
- **Motion** alles, was mit Bewegung zu tun hat (Jogging, Home, Limits)
- **MDI** alles mit MDI-Eingabe
- **ToolTable** alles mit Werkzeugtabellen
- usw.

**Zielgröße:** MainWindow ~600 Zeilen (nur Infrastruktur + Initialisierung)

---

## ✅ Abgeschlossene Schritte

### Schritt 1: Fundament + FileManagerModule ✅
- [x] `thorcnc/modules/base.py` - ThorModule Basisklasse
- [x] `thorcnc/modules/__init__.py` - Exports
- [x] `thorcnc/modules/file_manager.py` - Erstes echtes Modul
  - 13 Methoden extrahiert
  - ~270 Zeilen aus MainWindow gespart

### Schritt 2: ToolTableModule ✅
- [x] `thorcnc/modules/tool_table.py` - Werkzeugtabellen-Management
  - 10 Methoden extrahiert
  - ~333 Zeilen aus MainWindow gespart

### Schritt 3: OffsetsModule ✅
- [x] `thorcnc/modules/offsets.py` - Offsets/WCS Management
  - ~172 Zeilen extrahiert

### Schritt 4: MotionModule ✅
- [x] `thorcnc/modules/motion.py` - Bewegungs-Management
  - 21 Methoden extrahiert
  - ~343 Zeilen extrahiert

### Schritt 5: ProbingTabModule ✅
- [x] `thorcnc/modules/probing_tab.py` - Probing-Management
  - 26 Methoden extrahiert
  - ~801 Zeilen extrahiert

### Schritt 6: SettingsTabModule ✅
- [x] `thorcnc/modules/settings_tab.py` - Settings-Management
  - ~500 Zeilen extrahiert
  - Preferences, Theme, Language-Handling gekapselt

### Schritt 7: DROModule + SpindleModule ✅
- [x] `thorcnc/modules/dro.py` - DRO-Anzeige & WCS-Sync
- [x] `thorcnc/modules/spindle.py` - Spindel-Steuerung & Feed/RPM Display
  - ~460 Zeilen kombiniert extrahiert

### Schritt 8: SimpleViewModule ✅
- [x] `thorcnc/modules/simple_view.py` - Fullscreen-Overlay (Simple View)
  - Extraktion der Overlay-Logik, Geometrie-Sync und Statusleisten-Integration
  - ~120 Zeilen extrahiert

### Schritt 9: Feature-Cleanup ✅
- [x] Entfernung der HTML/PDF Dokumentations-Funktion
  - Löschung von `_setup_html_tab`, `_refresh_html_list` und zugehörigen Settings
  - ~100 Zeilen Code eingespart

### Schritt 10: GCode/MDI Module ✅
- [x] `thorcnc/modules/gcode_view.py` - GCode Viewer & Edit Management
  - Edit-Mode Toggle, Modification Tracking, Saving
  - M6 (Tool Change) Navigation
  - Active GCode/MCode Display mit Highlighting und Coolant-Status
  - ~217 Zeilen extrahiert
- [x] `thorcnc/modules/mdi.py` - MDI Input & History
  - MDI Command Execution
  - History Management (max 50 items)
  - GCode/MDI Panel Switching
  - ~98 Zeilen extrahiert

**Aktueller Stand:** MainWindow **1355** Zeilen (von 5027 → **3672 Zeilen gespart!**)

---

## 🚀 Nächste Schritte (Roadmap)

### Schritt 11: HAL & Control Panel Module ✅
- [x] `thorcnc/modules/hal.py` - Hardware Abstraction Layer
  - HAL Component Initialization & Pin Creation
  - Post-GUI HAL File Loading from INI
  - Simulation-specific HAL Setup (spindle mass, limits)
  - ~102 Zeilen extrahiert
- [x] `thorcnc/modules/control_panel.py` - Machine Control Panel (OPT Panel)
  - OPT Panel UI with Expand/Collapse Animation
  - Single Block & M1 (Optional Stop) Toggle Controls
  - Button State Synchronization with Machine Status
  - Z-Safety Checks for G53 Shortcuts
  - ~130 Zeilen extrahiert

### Schritt 12: Backplot / 3D View Module ✅
- [x] `thorcnc/modules/backplot.py` - 3D Visualization Management
  - Backplot Widget Initialization & Configuration
  - View Button Management (ISO, TOP, FRONT, SIDE)
  - Machine Envelope Setup (from INI config)
  - View State Save/Restore (zoom, rotation, perspective)
  - Program Line Tracking Integration
  - ~105 Zeilen extrahiert

### Schritt 13: ProgramControlModule ✅
- [x] `thorcnc/modules/program_control.py` - Maschinensteuerung & Programmausführung
  - Estop/Power/Mode State Handling (`_on_estop`, `_on_machine_on`, `_on_mode`)
  - Interpreter State Tracking (`_on_interp`, `_update_run_buttons`)
  - Position Updates mit Performance-Throttling
  - Program Line Tracking + Single Block Auto-Pause
  - Run/Pause/Stop/Step Logik inkl. Queued-Start und Preamble
  - ~298 Zeilen extrahiert

### Schritt 14: StatusModule ✅
- [x] `thorcnc/modules/status.py` - Status-Anzeige & Logging
  - Status Bar Label mit Auto-Clear Timer
  - Status Log (QListWidget, timestamped, theme-aware)
  - Error/Info Signal Routing
  - Startup Error Channel Drain
  - ~85 Zeilen extrahiert

### Schritt 15: HighlightSettings in GCodeViewModule ✅
- [x] `thorcnc/modules/gcode_view.py` erweitert
  - `_setup_highlight_settings`, Farb-Callbacks und `_is_light` Helfer
  - ~50 Zeilen hinzugefügt

---

## 📊 Extraction Progress

| Modul | Status | Zeilen | Quelle |
|---|---|---|---|
| FileManagerModule | ✅ | ~270 | thorcnc/modules/file_manager.py |
| ToolTableModule | ✅ | ~362 | thorcnc/modules/tool_table.py |
| OffsetsModule | ✅ | ~172 | thorcnc/modules/offsets.py |
| MotionModule | ✅ | ~343 | thorcnc/modules/motion.py |
| ProbingTabModule | ✅ | ~801 | thorcnc/modules/probing_tab.py |
| NavigationModule | ✅ | ~281 | thorcnc/modules/navigation.py |
| SettingsTabModule | ✅ | ~500 | thorcnc/modules/settings_tab.py |
| DROModule | ✅ | ~310 | thorcnc/modules/dro.py |
| SpindleModule | ✅ | ~150 | thorcnc/modules/spindle.py |
| SimpleViewModule | ✅ | ~120 | thorcnc/modules/simple_view.py |
| GCodeViewModule | ✅ | ~217 | thorcnc/modules/gcode_view.py |
| MDIModule | ✅ | ~98 | thorcnc/modules/mdi.py |
| HALModule | ✅ | ~102 | thorcnc/modules/hal.py |
| ControlPanelModule | ✅ | ~130 | thorcnc/modules/control_panel.py |
| BackplotModule | ✅ | ~105 | thorcnc/modules/backplot.py |
| ProgramControlModule | ✅ | ~298 | thorcnc/modules/program_control.py |
| StatusModule | ✅ | ~85 | thorcnc/modules/status.py |
| GCodeViewModule (Highlights) | ✅ | +~50 | thorcnc/modules/gcode_view.py |
| **Gesamt (Modularisiert)** | - | **~4.396** | - |

### Schritt 16: Final Cleanup ✅
- [x] Nav-Button-Wiring in `NavigationModule.connect_signals()` verschoben
- [x] `_sync_nav_buttons` aus MainWindow entfernt (jetzt in `NavigationModule`)
- [x] `_on_digital_out_changed` aus MainWindow entfernt (jetzt in `ProbingTabModule`)
- [x] `_on_language_changed` aus MainWindow entfernt (dead code, in `SettingsTabModule`)
- [x] `setup_widget()` für GCode/MDI Stack in `GCodeViewModule` / `MDIModule`
- [x] `setup_flyouts()` in `NavigationModule`, `replace_vtk_placeholder()` in `BackplotModule`
- [x] Unused imports bereinigt (`QStackedWidget`, `QLineEdit`, `QListWidget`, `QSpinBox`, `QTimer`, `Slot`, `GCodeView`, `QHBoxLayout`)

---

## 🏗️ Struktur-Status (MainWindow)
*   **Original:** ~5.027 Zeilen
*   **Aktuell:** **564 Zeilen** ✅ ZIEL ERREICHT (Ziel: ~600 Zeilen)
*   **Status:** Modularisierung vollständig abgeschlossen. MainWindow enthält nur noch Infrastruktur & Initialisierung. 17 spezialisierte Module + 1 Base-Modul.

---

## 📝 Notizen
- **Modulare Architektur:** Business Logic wird in Module extrahiert, UI-Setup bleibt in MainWindow (pragmatischer Ansatz)
- **Timing:** HAL.setup() wird vor UI-Initialisierung aufgerufen (Timing-Fix für Hardware Init)
- **Control Panel:** Synchronisiert regelmäßig mit Poller für Button-States und Z-Safety Checks
- **Z-Safety:** G53 Shortcuts (Home X/Y) deaktiviert wenn Z nicht bei Machine-Zero ist (Sicherheitsfeature)
- **Module.setup():** Wird nach MainWindow.__init__() aufgerufen, damit alle UI-Refs verfügbar sind
- **Module.connect_signals():** Wird erst nach allen setup()-Calls aufgerufen (Signal-Verbindungen)

---

*Letztes Update: 26.04.2026 nach Schritt 16 (Final Cleanup)*  
*Status: **Modularisierung vollständig abgeschlossen** ✅*  
*MainWindow: **564 Zeilen** (Ziel ~600 erreicht, ↓ 4463 Zeilen gegenüber Original)*  
*Gesamt-Einsparung: 4463 Zeilen (88% der Original-MainWindow)*  
*Module count: 17 Spezialisierte Module + 1 Base-Modul = **18 insgesamt***

---

## 🛠️ Laufende Aufgaben & Fixes

### Probing Script Robustheit (G-Code) — Umsetzung läuft
- [x] Pattern auf `outside_corner_bl.ngc` umgesetzt und an Maschine validiert
  - G92.1 (Geister-Offsets killen)
  - M50 P0/P1 (Feed Override aus während Probe)
  - `#<z_surface> = #5063` + absolute Z-Logik (`#<z_clearance>`, `#<z_plunge>`)
  - Auto-Zero ON/OFF beide getestet, Feed Override greift während Probe nicht ein
- [x] Pattern auf alle übrigen 27 Subs übertragen (siehe Liste unten)
- [x] **Maschinen-Test der 27 übertragenen Subs** — alle erfolgreich validiert (2026-04-25)

---

## 🆕 Probe Result Panel + History (geplant)

**Ziel:** Mess-Modus ohne WCS-Veränderung. Auto-Zero OFF = nur messen, Werte anzeigen. Z.B. Passungs-Check (Tasche/Bohrung).

### Layout-Änderungen Probing-Tab
- [ ] Kasten 1 (Pattern-Grid + Before/After Probing) **höher** machen — mehr Stretch-Factor im vertikalen Layout
- [ ] Kasten 2 (neu) **unter** dem Pattern-Grid: Probe Result Panel

### Probe Result Panel (minimal)
- [ ] QGroupBox "PROBE RESULT" mit:
  - Aktives WCS als Pill/Label oben (z.B. `[G54]`)
  - Probe-Typ + Zeitstempel
  - Result-Werte (X/Y Corner/Wall/Center, Z Surface, ggf. Diameter, Angle)
  - Auto-Zero Status-Zeile (nur sichtbar wenn OFF)
  - Δ-Anzeige bei Round/Rect mit Expected-Wert (rot/grün, Toleranz fix ±0.05mm initial)
- [ ] Buttons rechts oben: `[History]` `[Clear]`
- [ ] Polling-Mechanismus: pro Sekunde `linuxcnc.stat.parameters[1001]` checken, wenn 1 → Werte lesen, Reset via MDI `#1001=0`

### History-Dialog (separates Fenster)
- [ ] Modaler/freier QDialog mit Tabelle (Time, Type, Result-Summary, WCS, AZ)
- [ ] Klick auf Zeile → Detail-Expansion (alle Roh-Werte: Hit-Punkte, Surface, Probe-Dia)
- [ ] Buttons: `[Clear All]` `[Export CSV]` (CSV als Future)
- [ ] **Persistenz: nein** — leer bei Programmstart, in-memory deque
- [ ] Aufruf via History-Button im Result Panel (rechts oben)

### G-Code Communication Block (`#1000-#1099`)
**Reserviert in `probe_run.ngc`** mit Header-Kommentar als Dokumentation.

| Param | Bedeutung |
|---|---|
| #1000 | Probe-Type-Code (numerisch, Mapping in Python) |
| #1001 | Valid-Flag (1 = neue Daten, GUI setzt zurück auf 0) |
| #1010 | X Hit (letzter Tref) |
| #1011 | Y Hit |
| #1012 | Z Surface |
| #1020 | X Result (Wall/Corner/Center) |
| #1021 | Y Result |
| #1030 | Gemessener Durchmesser |
| #1031 | Gemessene Breite Y (für Rect) |
| #1040 | Winkel (Grad) |

- [ ] Header in `probe_run.ngc` mit Param-Tabelle einfügen
- [ ] In jeder Sub am Ende (vor `M50 P1`) Result-Publishing einfügen:
  ```ngc
  ( Publish results to GUI )
  #1000 = <type_code>
  #1010 = #<x_hit>
  ...
  #1001 = 1  ( valid flag, last )
  ```
- [ ] Type-Code-Mapping festlegen (1=outside_edge_left, 2=outside_edge_right, ...) — in beiden Seiten dokumentieren

### Implementation-Reihenfolge
1. ~~Erst Maschinen-Test der 27 Subs abwarten~~ ✅ erledigt
2. ~~Type-Code-Mapping definieren~~ ✅ erledigt
3. ~~`probe_run.ngc` Header schreiben~~ ✅ erledigt
4. ~~Result-Publishing in alle 28 Subs einfügen~~ ✅ erledigt
5. ~~Python: `ProbeResultPanel` Widget erstellen~~ ✅ erledigt
6. ~~Python: `ProbeHistoryDialog` erstellen~~ ✅ erledigt
7. ~~`probing_tab.py` Layout anpassen + Panel einfügen~~ ✅ erledigt
8. ~~Polling via var-Datei (mtime + Read)~~ ✅ erledigt (stat.parameters existiert nicht in 2.9.8)
9. Tests an Maschine — läuft

### Erledigt (2026-04-25)
- [x] `ProbeResultPanel` + `ProbeHistoryDialog` implementiert
- [x] Polling über `.var`-Datei (mtime-basiert) statt `stat.parameters` (nicht verfügbar in LinuxCNC 2.9.8)
- [x] Parameter 1000–1042 in var-Datei vorinitialisieren — `_seed_probe_var_params()` beim Start (sortiert, damit LinuxCNC nicht "Parameter-Datei nicht in Ordnung" meldet)
- [x] SIM Probe Trigger Button eingebaut (momentary, nur sichtbar wenn `probe_sim` im INI)
- [x] `update.sh`: `-n` Flag bei `cp` entfernt → Subroutines werden jetzt korrekt überschrieben

### Offene Punkte
- [x] **Probe Result Panel: Layout & Style überarbeiten** — aktuelle Darstellung unfertig, Anordnung und visuelle Gestaltung müssen angepasst werden
- [ ] Toleranz für Δ-Anzeige konfigurierbar machen (initial fix ±0.05mm)
- [ ] CSV-Export aus History
- [ ] Optional: Banner-Warnung "MEASURE ONLY MODE" bei Auto-Zero OFF
