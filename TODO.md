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
  - Alle File-Tab Funktionen (Browse, Load, Save, Edit)

### Schritt 2: ToolTableModule ✅
- [x] `thorcnc/modules/tool_table.py` - Werkzeugtabellen-Management
  - 10 Methoden extrahiert
  - `NumericTableWidgetItem` Klasse verschoben
  - ~333 Zeilen aus MainWindow gespart
  - Tool-Tabelle UI + Datei I/O + Tool-Change HAL + M6 MDI
  - **UX Features:**
    - Auto-Toolnummer (nächste freie Nummer)
    - Auto-Description aus Diameter (Ø{dia}mm)
    - Fokus direkt auf Diameter-Feld
    - Saubere Sortierung (disabled während Edit, enabled beim Save)

---

## 🚀 Nächste Schritte (Roadmap)

### Schritt 3: OffsetsModule ✅
- [x] `thorcnc/modules/offsets.py` - Offsets/WCS Management
  - ~172 Zeilen
  - 6 Methoden extrahiert + `_WCS_LIST` Klassenattribut
  - ~163 Zeilen aus MainWindow gespart

### Schritt 4: MotionModule ✅
- [x] `thorcnc/modules/motion.py` - Bewegungs-Management
  - 21 Methoden extrahiert
  - ~343 Zeilen
  - ~333 Zeilen aus MainWindow gespart
  - Jogging (alle Richtungen, Inkremente)
  - Home / Limit-Handling
  - Override-Slider (Feed, Spindle, Rapid)
  - Soft-Limits Visualisierung

### Schritt 5: ProbingTabModule ✅
- [x] `thorcnc/modules/probing_tab.py` - Probing-Management
  - 26 Methoden extrahiert
  - ~801 Zeilen
  - ~790 Zeilen aus MainWindow gespart
  - Komplette UI-Initialisierung (SVG-Icons, StackedWidget)
  - Alle Probe-Sequenzen (Edge, Hole, Pocket, etc.)
  - Probe-Marker Positionierung
  - Preference-Management (before/after probe NGCs)
  - DRO-Synchronisierung (compact probe DRO)
  - **Konsolidierung:** ProbingManager integriert (Probe-Warning State)

**Aktueller Stand:** MainWindow 3004 Zeilen (von 5027 → **2023 Zeilen gespart!**)

---

### Schritt 6: SettingsTabModule (TODO)
**Geschätzter Aufwand:** ~450 Zeilen

Umfasst:
- `_setup_settings_tab` - alle Settings-Widgets
- Preferenzen speichern/laden
- Theme-Anwendung
- Sprache-Wechsel

---

### Schritt 7: DROModule + SpindleModule (TODO)
**Geschätzter Aufwand:** ~150 Zeilen kombiniert

**DROModule:**
- Position Display aktualisierung
- Work vs. Machine Koordinaten

**SpindleModule:**
- Spindle Speed Display + Control
- Direction Buttons (CW/CCW)

---

### Schritt 8: MainWindow Cleanup (TODO)
**Nach allen Module-Extraktion**

Upgrade der bestehenden Manager auf neues ThorModule Interface:
- `NavigationManager` → **Gelöscht** (Integriert in NavigationModule)
- `ProbingManager` → **Gelöscht** (Integriert in ProbingTabModule)

---

## 📊 Extraction Progress

| Modul | Status | Zeilen | Methoden | Quelle |
|---|---|---|---|---|
| FileManagerModule | ✅ | ~270 | 13 | thorcnc/modules/file_manager.py |
| ToolTableModule | ✅ | ~362 | 10 | thorcnc/modules/tool_table.py |
| OffsetsModule | ✅ | ~172 | 6 | thorcnc/modules/offsets.py |
| MotionModule | ✅ | ~343 | 21 | thorcnc/modules/motion.py |
| ProbingTabModule | ✅ | ~801 | 26 | thorcnc/modules/probing_tab.py |
| NavigationModule | ✅ | ~281 | 15+ | thorcnc/modules/navigation.py |
| SettingsTabModule | ✅ | ~500 | 20+ | thorcnc/modules/settings_tab.py |
| DROModule | 📋 | ~80 | 3-4 | todo |
| SpindleModule | 📋 | ~70 | 3-4 | todo |
| **Gesamt (geplant)** | - | **~2,800** | **~75+** | - |

**Einsparung in MainWindow:** ~2,500 Zeilen
**Zielgröße:** 500-600 Zeilen (nur Infrastruktur)

---

## 🏗️ Architektur-Pattern

### ThorModule Base Class
```python
class ThorModule:
    def __init__(self, thorc):
        self._t = thorc  # Backref zu MainWindow/ThorCNC
    
    def setup(self):
        """UI bauen, lokale State init"""
        pass
    
    def connect_signals(self):
        """Qt Signals wiren nach allen setups"""
        pass
    
    def teardown(self):
        """Cleanup vor Shutdown"""
        pass
```

### Initialisierungsreihenfolge in `__init__`
```python
# 1. Managers + Module instanziieren
self.file_manager = FileManagerModule(self)
self.tool_table = ToolTableModule(self)
# ... weitere ...

# 2. _load_ui() aufrufen (UI-Layout laden)

# 3. Alle setup() Methoden aufrufen
self.file_manager.setup()
self.tool_table.setup()
# ... weitere ...

# 4. Alle connect_signals() aufrufen
self.file_manager.connect_signals()
self.tool_table.connect_signals()
# ... weitere ...

# 5. Event Filter zum Schluss (nach poller ist vollständig init!)
QApplication.instance().installEventFilter(self)
```

---

## ⚠️ Wichtige Richtlinien

### Bevor ihr ein Modul extrahiert:

1. **Umfang klären** - Welche Methoden gehören dazu?
2. **Abhängigkeiten mappen** - Was braucht das Modul von MainWindow?
3. **Signal-Flow verstehen** - Welche Qt-Signals kommen von Poller/HAL?
4. **Externe Zugriffe dokumentieren** - Wer else aus MainWindow auf das Modul zugreift

### Red Flags:
- ❌ Modul hat zu viele externe Abhängigkeiten → logisch nicht gut abgegrenzt
- ❌ Zirkuläre Abhängigkeiten zwischen Modulen → Refactoring nötig
- ❌ Methode passt in 3+ Module → falsche Granularität

### Best Practice:
- ✅ Ein Modul = ein Tab/Bereich der UI
- ✅ Modul besitzt seine Widgets und State vollständig
- ✅ Zugriff von außen nur über öffentliche Methoden
- ✅ Signals über `self._t.poller` oder `self._t.cmd`

---

## 🔍 Nächste konkrete Aktion

**Wer:** Moshy  
**Was:** Schritt 6 - SettingsTabModule extrahieren  
**Wie:** 
1. Plan-Mode für SettingsTabModule
2. `thorcnc/modules/settings_tab.py` erstellen
3. ~10+ Methoden extrahieren (Preferences, Theme, Language)
4. MainWindow aktualisieren
5. ~450 Zeilen Einsparung = MainWindow auf ~2500 Zeilen

**Begründung:** Nächster logischer Schritt, um den UI-Setup-Teil von MainWindow zu entlasten.

---

## 📝 Notizen

- **Mixins waren problematisch:** Memory-Access-Fehler in LinuxCNC wegen Event Filter Installation vor poller-init
- **Lösung:** Komposition statt Vererbung → Manager/Module mit Backref `self._t`
- **Performance:** Keine Overhead durch diesen Ansatz, ähnlich zu normalen Klassen
- **Git:** User macht commits selbst, Claude nur Code-Changes

---

*Letztes Update: 23.04.2026 nach ProbingTabModule Extraktion*  
*Status: Schritt 5 ✅ abgeschlossen (MainWindow 3017 Zeilen, -2010 Zeilen gesamt)*  
*Nächster Start: SettingsTabModule (Schritt 6)*
