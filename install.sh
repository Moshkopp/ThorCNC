#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ThorCNC Installer
# Unterstützt: Debian 13 Trixie  |  Arch / CachyOS  |  dev (editable)
#
# Verwendung:
#   ./install.sh            # normale Installation
#   ./install.sh --dev      # editable install (für Entwicklung)
#   ./install.sh --uninstall
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEV_MODE=false
UNINSTALL=false

for arg in "$@"; do
    case "$arg" in
        --dev)       DEV_MODE=true ;;
        --uninstall) UNINSTALL=true ;;
        -h|--help)
            sed -n '2,8p' "$0" | sed 's/^# //; s/^#//'
            exit 0
            ;;
    esac
done

# ── PIP Flags (Debian 12+ / PEP 668) ──────────────────────────────────────────
# Wird als Funktion definiert und nach install_deps() nochmal aufgerufen,
# weil pip erst durch apt installiert werden kann und das Flag dann fehlt.
PIP_BREAK_FLAG=""
detect_pip_flags() {
    PIP_BREAK_FLAG=""
    if pip install --help 2>/dev/null | grep -q 'break-system-packages'; then
        PIP_BREAK_FLAG="--break-system-packages"
    fi
}
detect_pip_flags

# ── Farben ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[FEHLER]${NC} $*" >&2; exit 1; }
confirm() {
    local msg="$1"
    read -rp "$(echo -e "  ${YELLOW}?${NC} $msg [j/N]: ")" answer
    case "${answer,,}" in
        j|y|ja|yes) return 0 ;;
        *) return 1 ;;
    esac
}

# ── OS erkennen ───────────────────────────────────────────────────────────────
detect_os() {
    if [ -f /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        echo "${ID:-unknown}"
    else
        echo "unknown"
    fi
}

OS=$(detect_os)
info "Erkanntes System: $OS"

# ── Abhängigkeiten prüfen ─────────────────────────────────────────────────────
install_deps() {
    # Check if in a virtual environment
    if [ -n "${VIRTUAL_ENV:-}" ]; then
        info "Virtuelle Umgebung (venv) erkannt. Überspringe System-Pakete für Python."
        info "Abhängigkeiten werden direkt in die venv installiert..."
        return 0
    fi

    case "$OS" in
        debian|ubuntu)
            info "Installiere System-Pakete (apt)..."
            sudo apt-get update -qq || true

            # python3-pyqtgraph vom apt entfernen falls vorhanden:
            # Das Debian-Paket ist veraltet und defaultet zu PyQt5 – blockiert die pip-Version.
            if dpkg -l python3-pyqtgraph &>/dev/null 2>&1; then
                warn "python3-pyqtgraph (apt) gefunden – wird entfernt (inkompatibel mit PySide6)..."
                sudo apt-get remove -y python3-pyqtgraph || true
            fi

            # Installiere PySide6 + OpenGL + Qt xcb Support via apt
            sudo apt-get install -y \
                python3-pyside6 python3-pyside6.qtopenglwidgets \
                python3-opengl \
                libopengl0 libegl1 \
                libxcb-cursor0 || \
                warn "Einige System-Pakete konnten nicht via apt installiert werden."

            sudo apt-get install -y python3-pip python3-hatchling || true
            sudo apt-get install -y linuxcnc-uspace 2>/dev/null || \
                warn "linuxcnc-uspace nicht installierbar (kein LinuxCNC-Repo konfiguriert?)."

            # pyqtgraph und PyOpenGL explizit via pip force-reinstall (stellt sicher dass
            # nicht das apt-Paket sondern die pip-Version aktiv ist)
            info "Installiere pyqtgraph + PyOpenGL via pip (force-reinstall)..."
            pip install $PIP_BREAK_FLAG --force-reinstall "pyqtgraph>=0.13" "PyOpenGL>=3.1" || \
                warn "pip force-reinstall fehlgeschlagen – Backplot funktioniert evtl. nicht."

            ok "System-Checks abgeschlossen."
            ;;
        
        *)
            info "Verwende Standard-Installation (pip) für Host-System."
            ;;
    esac
}

# ── ThorCNC installieren ──────────────────────────────────────────────────────
install_thorcnc() {
    cd "$SCRIPT_DIR"

    # Extras [backplot] enthält PySide6, pyqtgraph, PyOpenGL
    EXTRAS="[backplot]"
    
    if $DEV_MODE; then
        info "Editable Install (Entwicklungsmodus) mit Extras $EXTRAS..."
        pip install $PIP_BREAK_FLAG --upgrade -e ".$EXTRAS"
        ok "thorcnc im Entwicklungsmodus installiert."
    else
        info "Installiere thorcnc mit Extras $EXTRAS..."
        pip install $PIP_BREAK_FLAG --upgrade ".$EXTRAS"
        ok "thorcnc installiert."
    fi
}

# ── Desktop-Entry ─────────────────────────────────────────────────────────────
install_desktop_entry() {
    DESKTOP_DIR="$HOME/.local/share/applications"
    mkdir -p "$DESKTOP_DIR"
    cat > "$DESKTOP_DIR/thorcnc.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ThorCNC
Comment=LinuxCNC VCP – Fräse
Exec=thorcnc
Icon=applications-engineering
Categories=Engineering;
Terminal=false
EOF
    ok "Desktop-Eintrag erstellt: $DESKTOP_DIR/thorcnc.desktop"
}

# ── Update-Shortcut auf Schreibtisch ──────────────────────────────────────────
install_update_shortcut() {
    DESKTOP_PATH="$HOME/Desktop"
    if [ ! -d "$DESKTOP_PATH" ] && [ -d "$HOME/Schreibtisch" ]; then
        DESKTOP_PATH="$HOME/Schreibtisch"
    fi

    if [ -d "$DESKTOP_PATH" ]; then
        SHORTCUT="$DESKTOP_PATH/ThorCNC-Update.desktop"
        cat > "$SHORTCUT" <<EOF
[Desktop Entry]
Type=Application
Name=ThorCNC Update
Comment=Zieht neueste Version und installiert thorcnc neu
Exec=bash -c "cd '$SCRIPT_DIR' && ./update.sh; echo; echo 'Fertig.'; read -p 'Drücke Enter zum Schließen...' -n 1 -s"
Icon=system-software-update
Terminal=true
Categories=Utility;
EOF
        chmod +x "$SHORTCUT"
        ok "Update-Verknüpfung auf Schreibtisch erstellt."
    fi
}

# ── Simulation-Shortcut auf Schreibtisch ──────────────────────────────────────
install_sim_shortcut() {
    DESKTOP_PATH="$HOME/Desktop"
    if [ ! -d "$DESKTOP_PATH" ] && [ -d "$HOME/Schreibtisch" ]; then
        DESKTOP_PATH="$HOME/Schreibtisch"
    fi

    if [ -d "$DESKTOP_PATH" ]; then
        SHORTCUT="$DESKTOP_PATH/ThorCNC-Sim.desktop"
        cat > "$SHORTCUT" <<EOF
[Desktop Entry]
Type=Application
Name=ThorCNC Sim
Comment=Startet ThorCNC in der Simulation
Exec=bash -c "cd '\$SCRIPT_DIR' && ./start.sh"
Icon=applications-engineering
Terminal=false
Categories=Engineering;
EOF
        chmod +x "$SHORTCUT"
        ok "Simulation-Verknüpfung auf Schreibtisch erstellt."
    fi
}


# ── Subroutines kopieren ──────────────────────────────────────────────────────
install_subroutines() {
    SRC="$SCRIPT_DIR/configs/sim/subroutines"
    DEST="$HOME/linuxcnc/nc_files/subroutines"
    
    if [ -d "$SRC" ]; then
        info "Kopiere Subroutines von SIM nach $DEST..."
        mkdir -p "$DEST"
        # Kopiert den Inhalt von subroutines/ nach ~/linuxcnc/nc_files/subroutines/
        cp -rn "$SRC/"* "$DEST/" || true
        ok "Subroutines synchronisiert (bestehende Dateien wurden nicht überschrieben)."
    else
        warn "Subroutines-Quellordner nicht gefunden: $SRC"
    fi
}

# ── Deinstallation ────────────────────────────────────────────────────────────
uninstall_thorcnc() {
    info "Deinstalliere thorcnc..."
    pip uninstall $PIP_BREAK_FLAG -y thorcnc 2>/dev/null && ok "thorcnc entfernt." || warn "thorcnc war nicht installiert."
    rm -f "$HOME/.local/share/applications/thorcnc.desktop"
    ok "Desktop-Eintrag entfernt."
}

# ── Hauptprogramm ─────────────────────────────────────────────────────────────
echo -e "${BOLD}ThorCNC Installer${NC}"
echo "───────────────────────────────────────"

if $UNINSTALL; then
    uninstall_thorcnc
    exit 0
fi

# Python-Version prüfen
PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_REQ="3.11"
if python3 -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)"; then
    ok "Python $PYTHON_VER ✓"
else
    err "Python >= $PYTHON_REQ benötigt, gefunden: $PYTHON_VER"
fi

# LinuxCNC-Bindings prüfen (kein Fehler – läuft ggf. ohne echte Maschine)
if python3 -c "import linuxcnc" &>/dev/null; then
    ok "linuxcnc Python-Bindings gefunden ✓"
else
    warn "linuxcnc Python-Bindings nicht gefunden."
    warn "Auf Debian: sudo apt install linuxcnc-uspace"
fi

install_deps
detect_pip_flags  # nach apt-install nochmal prüfen, pip könnte neu installiert worden sein
install_thorcnc

if confirm "nc_files/subroutines nach ~/linuxcnc/nc_files/ kopieren?"; then
    install_subroutines
else
    info "nc_files übersprungen."
fi

echo ""
if confirm "Desktop-Verknüpfungen erstellen (App, Update, Sim)?"; then
    install_desktop_entry
    install_update_shortcut
    install_sim_shortcut
else
    info "Desktop-Verknüpfungen übersprungen."
fi

echo ""
echo -e "${BOLD}Installation abgeschlossen.${NC}"
echo ""
echo "Starten:"
if $DEV_MODE; then
    echo "  python -m thorcnc.main --ini /pfad/zur/maschine.ini"
else
    echo "  thorcnc --ini /pfad/zur/maschine.ini"
fi
echo ""
echo "Themes: dark (Standard), light"
echo "  thorcnc --theme light --ini ..."
echo ""
echo "Backplot funktioniert nicht? Schnellfix:"
echo "  sudo apt remove python3-pyqtgraph"
echo "  pip install --break-system-packages --force-reinstall pyqtgraph PyOpenGL"
