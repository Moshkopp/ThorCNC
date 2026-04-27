#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# ThorCNC Updater
# Zieht die neuesten Änderungen aus dem Repository und reinstalliert das Paket.
#
# Verwendung:
#   ./update.sh            # normales Update
#   ./update.sh --dev      # Update im Entwicklungsmodus (editable)
# -----------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEV_MODE=false
FORCE_MODE=false

for arg in "$@"; do
    case "$arg" in
        --dev)   DEV_MODE=true ;;
        --force) FORCE_MODE=true ;;
        -h|--help)
            sed -n '2,8p' "$0" | sed 's/^# //; s/^#//'
            exit 0
            ;;
    esac
done

# --- PIP Flags (Debian 12+ / PEP 668) ----------------------------------------
PIP_BREAK_FLAG=""
if pip install --help | grep -q 'break-system-packages'; then
    PIP_BREAK_FLAG="--break-system-packages"
fi

# --- Farben ------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'

info() { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[FEHLER]${NC} $*" >&2; exit 1; }
confirm() {
    local msg="$1"
    read -rp "$(echo -e "  ${YELLOW}?${NC} $msg [j/N]: ")" answer
    case "${answer,,}" in
        j|y|ja|yes) return 0 ;;
        *) return 1 ;;
    esac
}

echo -e "${BOLD}ThorCNC Updater${NC}"
echo "---------------------------------------"

cd "$SCRIPT_DIR"

# --- Git-Status prüfen -------------------------------------------------------
if ! git rev-parse --git-dir &>/dev/null; then
    err "Kein Git-Repository gefunden in: $SCRIPT_DIR"
fi

# Lokale Änderungen anzeigen (kein Abbruch)
if ! git diff --quiet || ! git diff --cached --quiet; then
    warn "Lokale Änderungen vorhanden - werden beim Pull beibehalten (kein Überschreiben)."
fi

# Aktuelle Version merken
OLD_REV=$(git rev-parse --short HEAD)
info "Aktuelle Version: $OLD_REV"

# --- Stash & Pull ------------------------------------------------------------
if $FORCE_MODE; then
    warn "FORCE MODE: Verwerfe lokale Änderungen und setze auf origin zurück..."
    git fetch origin &>/dev/null
    git reset --hard "origin/$(git rev-parse --abbrev-ref HEAD)"
else
    info "Bereite Repository vor (Index-Reparatur)..."
    # Fallback-Strategie für beschädigte Indizes auf VMs
    if ! git update-index --refresh &>/dev/null; then
        warn "Index ist beschädigt. Starte Deep-Repair..."
        rm -f .git/index.lock &>/dev/null || true
        rm -f .git/index &>/dev/null || true
        git reset HEAD -- . &>/dev/null || true
        git update-index --refresh &>/dev/null || true
    fi

    info "Sichere lokale Änderungen (Stash)..."
    git stash push -m "update.sh auto-stash" || {
        err "Stash fehlgeschlagen. Nutze './update.sh --force' um lokale Änderungen zu verwerfen."
    }
fi

info "Lade neueste Änderungen von origin..."
git pull --ff-only origin "$(git rev-parse --abbrev-ref HEAD)" || {
    warn "Fast-forward nicht möglich (lokale Änderungen?)."
    warn "Versuche 'git pull --rebase'..."
    git pull --rebase origin "$(git rev-parse --abbrev-ref HEAD)" || {
        warn "Konnte nicht automatisch mergen."
        warn "Versuche lokale Änderungen wiederherzustellen..."
    }
}

if ! $FORCE_MODE; then
    info "Stelle lokale Änderungen wieder her (Stash pop)..."
    git stash pop || warn "Keine Änderungen zum Wiederherstellen oder Konflikt beim Pop."
fi

NEW_REV=$(git rev-parse --short HEAD)

if [ "$OLD_REV" = "$NEW_REV" ]; then
    ok "Bereits auf dem neuesten Stand ($NEW_REV) - kein Commit-Update."
else
    ok "Aktualisiert: $OLD_REV -> $NEW_REV"
    echo ""
    git log --oneline "${OLD_REV}..HEAD"
    echo ""
fi

# --- Paket neu installieren --------------------------------------------------
EXTRAS="[backplot]"

# python3-pyqtgraph vom apt entfernen falls vorhanden (inkompatibel mit PySide6)
if dpkg -l python3-pyqtgraph &>/dev/null 2>&1; then
    warn "python3-pyqtgraph (apt) gefunden – wird entfernt (inkompatibel mit PySide6)..."
    sudo apt-get remove -y python3-pyqtgraph || true
fi

# pyqtgraph + PyOpenGL explizit force-reinstall damit nicht die apt-Version aktiv bleibt
info "Aktualisiere pyqtgraph + PyOpenGL via pip..."
pip install $PIP_BREAK_FLAG --force-reinstall "pyqtgraph>=0.13" "PyOpenGL>=3.1" || \
    warn "pip force-reinstall fehlgeschlagen – Backplot funktioniert evtl. nicht."

if $DEV_MODE; then
    info "Editable Reinstall (--dev) mit Extras $EXTRAS..."
    pip install $PIP_BREAK_FLAG --upgrade -e ".$EXTRAS"
    ok "thorcnc (dev) aktualisiert."
else
    info "Reinstalliere thorcnc mit Extras $EXTRAS..."
    pip install $PIP_BREAK_FLAG --upgrade ".$EXTRAS"
    ok "thorcnc aktualisiert."
fi

# --- Subroutines synchronisieren ---------------------------------------------
# Hinweis: Probe-Parameter (1000-1042) werden beim ThorCNC-Start automatisch
# in die eigene var-Datei eingetragen - kein manueller Schritt nötig.

install_subroutines() {
    SRC="$SCRIPT_DIR/configs/sim/subroutines"
    DEST="$HOME/linuxcnc/nc_files/subroutines"
    
    if [ -d "$SRC" ]; then
        info "Synchronisiere Subroutines nach $DEST..."
        mkdir -p "$DEST"
        cp -r "$SRC/"* "$DEST/" || true
        ok "Subroutines synchronisiert."
    else
        warn "Subroutines-Quellordner nicht gefunden: $SRC"
    fi
}

if confirm "nc_files/subroutines nach ~/linuxcnc/nc_files/ synchronisieren?"; then
    install_subroutines
else
    info "nc_files übersprungen."
fi

# --- Probe-Parameter in var-Datei vorinitialisieren --------------------------
seed_probe_params() {
    # Sucht alle INI-Dateien im linuxcnc/configs-Verzeichnis und ergänzt
    # fehlende Probe-Parameter (1000-1042) ohne bestehende Werte zu überschreiben.
    PROBE_PARAMS="1000 1001 1010 1011 1012 1013 1014 1020 1021 1030 1031 1040"
    CONFIGS_DIR="$HOME/linuxcnc/configs"

    find "$CONFIGS_DIR" -name "*.ini" 2>/dev/null | while read -r ini_file; do
        var_name=$(grep -i "^PARAMETER_FILE" "$ini_file" 2>/dev/null | head -1 | awk -F'=' '{print $2}' | tr -d ' \r')
        [ -z "$var_name" ] && continue
        var_file="$(dirname "$ini_file")/$var_name"
        [ -f "$var_file" ] || continue

        added=0
        for p in $PROBE_PARAMS; do
            if ! grep -q "^${p}[[:space:]]" "$var_file"; then
                echo -e "${p}\t0.000000" >> "$var_file"
                added=$((added + 1))
            fi
        done

        if [ "$added" -gt 0 ]; then
            ok "Probe-Parameter ($added neu) in: $var_file"
        fi
    done
}

echo ""
echo -e "${BOLD}Update abgeschlossen.${NC}"
echo ""

# --- Desktop Shortcut --------------------------------------------------------
DESKTOP_PATH="$HOME/Desktop"
if [ ! -d "$DESKTOP_PATH" ] && [ -d "$HOME/Schreibtisch" ]; then
    DESKTOP_PATH="$HOME/Schreibtisch"
fi

if [ -d "$DESKTOP_PATH" ] && confirm "Desktop-Verknüpfungen erstellen/aktualisieren (Update, Sim)?"; then
    SHORTCUT="$DESKTOP_PATH/ThorCNC-Update.desktop"

    cat > "$SHORTCUT" <<EOD
[Desktop Entry]
Type=Application
Name=ThorCNC Update
Comment=Zieht neueste Version und installiert thorcnc neu
Exec=bash -c "cd '$SCRIPT_DIR' && ./update.sh; echo; echo 'Fertig.'; read -p 'Drücke Enter zum Schließen...' -n 1 -s"
Icon=system-software-update
Terminal=true
Categories=Utility;
EOD

    chmod +x "$SHORTCUT"
    ok "Verknüpfung erstellt: ThorCNC-Update.desktop"

    SIM_SHORTCUT="$DESKTOP_PATH/ThorCNC-Sim.desktop"

    cat > "$SIM_SHORTCUT" <<EOD
[Desktop Entry]
Type=Application
Name=ThorCNC Sim
Comment=Startet ThorCNC in der Simulation
Exec=bash -c "cd '$SCRIPT_DIR' && ./start.sh"
Icon=applications-engineering
Terminal=false
Categories=Engineering;
EOD

    chmod +x "$SIM_SHORTCUT"
    ok "Verknüpfung erstellt: ThorCNC-Sim.desktop"
else
    info "Desktop-Verknüpfungen übersprungen."
fi

echo ""
