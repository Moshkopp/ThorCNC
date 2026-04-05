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

# ── Farben ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()     { echo -e "${RED}[FEHLER]${NC} $*" >&2; exit 1; }

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

# ── Abhängigkeiten installieren ───────────────────────────────────────────────
install_deps() {
    case "$OS" in
        debian|ubuntu)
            info "Installiere System-Pakete (apt)..."
            sudo apt-get update -qq
            sudo apt-get install -y \
                python3-pyside6 \
                python3-pyqtgraph \
                python3-opengl \
                python3-pip \
                python3-hatchling \
                linuxcnc-uspace
            ok "System-Pakete installiert."
            ;;

        arch|cachyos|endeavouros|manjaro)
            info "Installiere Pakete (pacman / pip)..."
            # PySide6 kommt aus den Repo oder ist schon da
            if ! python3 -c "import PySide6" &>/dev/null; then
                sudo pacman -S --needed --noconfirm python-pyside6
            fi
            # pyqtgraph & PyOpenGL über pip (AUR-Pakete optional)
            pip install --user pyqtgraph PyOpenGL
            ok "Pakete installiert."
            ;;

        *)
            warn "Unbekanntes System '$OS'. Versuche pip-Only-Installation."
            pip install --user "PySide6>=6.5" pyqtgraph PyOpenGL
            ;;
    esac
}

# ── ThorCNC installieren ──────────────────────────────────────────────────────
install_thorcnc() {
    cd "$SCRIPT_DIR"

    if $DEV_MODE; then
        info "Editable Install (Entwicklungsmodus)..."
        pip install --user -e .
        ok "thorcnc im Entwicklungsmodus installiert."
        info "Änderungen am Quellcode sind sofort aktiv."
    else
        info "Installiere thorcnc..."
        pip install --user .
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
Exec=thorcnc --theme dark
Icon=applications-engineering
Categories=Engineering;
Terminal=false
EOF
    ok "Desktop-Eintrag erstellt: $DESKTOP_DIR/thorcnc.desktop"
}

# ── Deinstallation ────────────────────────────────────────────────────────────
uninstall_thorcnc() {
    info "Deinstalliere thorcnc..."
    pip uninstall -y thorcnc 2>/dev/null && ok "thorcnc entfernt." || warn "thorcnc war nicht installiert."
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
install_thorcnc
install_desktop_entry

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
echo "Themes: dark (Standard), light, dark_green, dark_orange"
echo "  thorcnc --theme dark_green --ini ..."
