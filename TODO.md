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

**Aktueller Stand:** MainWindow 4298 Zeilen (von 5027 → **729 Zeilen gespart!**)

---

## 🚀 Nächste Schritte (Roadmap)

### Schritt 3: OffsetsModule (NÄCHST)
**Geschätzter Aufwand:** ~165 Zeilen  
**Priorität:** 🟢 HIGH (kleine Sache, dann großen Brocken zum Schluss)

Umfasst:
- `_setup_offsets_tab` - UI-Aufbau
- `_refresh_offsets_table` - Tabelle aktualisieren
- `_on_offset_wcs_changed` - WCS-Wechsel
- `_clear_wcs` - WCS zurücksetzen

**Strategie:** Kleine Module zuerst → MainWindow schrumpft kontinuierlich → große Brocken (Probing, Settings) am Ende

---

### Schritt 4: MotionModule (TODO)
**Geschätzter Aufwand:** ~250 Zeilen

Umfasst:
- Jogging (alle Richtungen, Inkremente)
- Home / Limit-Handling
- Override-Slider (Feed, Spindle, Rapid)
- Soft-Limits Visualisierung

**Abhängigkeiten:** Base classes, Status Poller

---

### Schritt 5: ProbingTabModule (TODO - der große)
**Geschätzter Aufwand:** ~850 Zeilen (größter einzelner Modul)

Umfasst:
- `_setup_probing_tab` - komplexes UI mit vielen Widgets
- Alle Probe-Sequenzen (Edge, Hole, Pocket, etc.)
- Probe-Marker Positionierung
- Tool-Sensor Integration

**Notiz:** `ProbingManager` existiert bereits als Helper (Probe-Warning State). 
`ProbingTabModule` würde den UI-Teil + Sequenzen enthalten.

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
- `NavigationManager` → `ThorModule` mit `connect_signals()`
- `ProbingManager` → Aufteilen in ProbingManager (state) + ProbingTabModule (UI)

---

## 📊 Extraction Progress

| Modul | Status | Zeilen | Methoden | Quelle |
|---|---|---|---|---|
| FileManagerModule | ✅ | ~270 | 13 | thorcnc/modules/file_manager.py |
| ToolTableModule | ✅ | ~362 | 10 | thorcnc/modules/tool_table.py |
| OffsetsModule | 📋 | ~165 | 4 | todo |
| MotionModule | 📋 | ~250 | 8-10 | todo |
| ProbingTabModule | 📋 | ~850 | 20+ | todo |
| SettingsTabModule | 📋 | ~450 | 10+ | todo |
| DROModule | 📋 | ~80 | 3-4 | todo |
| SpindleModule | 📋 | ~70 | 3-4 | todo |
| **Gesamt (geplant)** | - | **~2,500** | **~60+** | - |

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
**Was:** Schritt 3 - OffsetsModule extrahieren  
**Wie:** 
1. Plan-Mode für OffsetsModule
2. `thorcnc/modules/offsets.py` erstellen
3. 4 Methoden extrahieren
4. MainWindow aktualisieren
5. ~165 Zeilen Einsparung = MainWindow auf ~4133 Zeilen

**Begründung:** Kleine, klare Aufgabe → großen Brocken (Probing ~850 Zeilen) zum Schluss für Momentum

---

## 📝 Notizen

- **Mixins waren problematisch:** Memory-Access-Fehler in LinuxCNC wegen Event Filter Installation vor poller-init
- **Lösung:** Komposition statt Vererbung → Manager/Module mit Backref `self._t`
- **Performance:** Keine Overhead durch diesen Ansatz, ähnlich zu normalen Klassen
- **Git:** User macht commits selbst, Claude nur Code-Changes

---

*Letztes Update: 23.04.2026 nach ToolTableModule + UX Features*  
*Nächster Start: OffsetsModule (Schritt 3)*
