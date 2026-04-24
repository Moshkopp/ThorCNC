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

**Aktueller Stand:** MainWindow **1393** Zeilen (von 5027 → **3634 Zeilen gespart!**)

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

### Schritt 12: Backplot / 3D View Module (TODO)
**Geschätzter Aufwand:** ~250 Zeilen

Umfasst:
- Backplot Initialization & View Management
- Camera/Perspective Handling
- Toolpath Display & Updates
- View State Restoration (zoom, rotation)

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
| **Gesamt (Modularisiert)** | - | **~3.858** | - |

---

## 🏗️ Struktur-Status (MainWindow)
*   **Original:** ~5.027 Zeilen
*   **Aktuell:** **1.393 Zeilen** (↓ 169 Zeilen seit Schritt 10)
*   **Status:** HAL & Control Panel Module abgeschlossen. MainWindow ist jetzt ~73% kleiner. Nächste Kandidaten: Backplot/3D View, oder kleinere Utility-Module.

---

## 📝 Notizen
- **Modulare Architektur:** Business Logic wird in Module extrahiert, UI-Setup bleibt in MainWindow (pragmatischer Ansatz)
- **Timing:** HAL.setup() wird vor UI-Initialisierung aufgerufen (Timing-Fix für Hardware Init)
- **Control Panel:** Synchronisiert regelmäßig mit Poller für Button-States und Z-Safety Checks
- **Z-Safety:** G53 Shortcuts (Home X/Y) deaktiviert wenn Z nicht bei Machine-Zero ist (Sicherheitsfeature)
- **Module.setup():** Wird nach MainWindow.__init__() aufgerufen, damit alle UI-Refs verfügbar sind
- **Module.connect_signals():** Wird erst nach allen setup()-Calls aufgerufen (Signal-Verbindungen)

---

*Letztes Update: 24.04.2026 nach HAL & Control Panel Modul-Extraktion*  
*Status: Schritt 11 ✅ abgeschlossen (MainWindow 1393 Zeilen, ↓ 169 Zeilen seit Schritt 10)*  
*Gesamt-Einsparung: 3634 Zeilen (72% der Original-MainWindow)*  
*Nächster Start: Backplot/3D View Module (Schritt 12) oder weitere Refactoring*
