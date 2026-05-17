#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# ThorCNC Updater
# Zieht die neuesten Änderungen aus dem Repository und reinstalliert das Paket
# nur, wenn nötig. Ist bereits alles aktuell und alle Abhängigkeiten vorhanden,
# beendet sich der Updater stumm.
#
# Verwendung:
#   ./update.sh            # normales Update
#   ./update.sh --dev      # Update im Entwicklungsmodus (editable)
#   ./update.sh --force    # erzwingt Reinstall auch ohne Pending-Update
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
            sed -n '2,12p' "$0" | sed 's/^# //; s/^#//'
            exit 0
            ;;
    esac
done

# --- Farben & Output-Helfer --------------------------------------------------
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

# --- PIP-Flag (Debian 12+ / PEP 668) -----------------------------------------
PIP_BREAK_FLAG=""
if pip install --help 2>/dev/null | grep -q 'break-system-packages'; then
    PIP_BREAK_FLAG="--break-system-packages"
fi

# --- Dependency-Checker ------------------------------------------------------
apt_installed() {
    dpkg -l "$1" 2>/dev/null | grep -q '^ii'
}

pip_installed() {
    # $1 = Paketname, $2 = Mindestversion (optional)
    local pkg="$1" minver="${2:-}"
    local installed
    installed=$(pip show "$pkg" 2>/dev/null | grep '^Version:' | cut -d' ' -f2)
    [ -z "$installed" ] && return 1
    if [ -n "$minver" ]; then
        python3 -c "
from packaging.version import Version
import sys
sys.exit(0 if Version('$installed') >= Version('$minver') else 1)
" 2>/dev/null || return 1
    fi
    return 0
}

OS=$(. /etc/os-release 2>/dev/null && echo "${ID:-unknown}" || echo "unknown")

# Sammelt fehlende apt-Pakete (nur auf Debian/Ubuntu relevant)
collect_missing_apt() {
    [ "$OS" != "debian" ] && [ "$OS" != "ubuntu" ] && return 0

    local pkgs=(
        python3-opengl
        libopengl0
        libegl1
        libxcb-icccm4
        libxcb-image0
        libxcb-keysyms1
        libxcb-randr0
        libxcb-render-util0
        libxcb-xinerama0
        libxcb-xkb1
        libxkbcommon-x11-0
    )

    if apt-cache show python3-pyside6 &>/dev/null; then
        pkgs+=(
            python3-pyside6
            python3-pyside6.qtopengl
            python3-pyside6.qtopenglwidgets
            python3-pyside6.qtuitools
            python3-pyside6.qtsvg
        )
    fi

    for pkg in "${pkgs[@]}"; do
        apt_installed "$pkg" || MISSING_APT+=("$pkg")
    done

    # libxcb-cursor: Debian 13 (t64-Übergang) kann libxcb-cursor0t64 heißen
    if ! apt_installed libxcb-cursor0 && ! apt_installed libxcb-cursor0t64; then
        MISSING_APT+=(libxcb-cursor0)
    fi
}

# Sammelt fehlende pip-Pakete
collect_missing_pip() {
    pip_installed pyqtgraph  0.13 || MISSING_PIP+=("pyqtgraph>=0.13")
    pip_installed PyOpenGL   3.1  || MISSING_PIP+=("PyOpenGL>=3.1")
    pip_installed matplotlib 3.5  || MISSING_PIP+=("matplotlib>=3.5")
    if [ "$OS" = "debian" ] || [ "$OS" = "ubuntu" ]; then
        pip_installed psutil || MISSING_PIP+=("psutil")
        if ! apt-cache show python3-pyside6 &>/dev/null; then
            pip_installed PySide6 || MISSING_PIP+=("PySide6")
        fi
    fi
}

install_missing_apt() {
    [ ${#MISSING_APT[@]} -eq 0 ] && return 0
    for pkg in "${MISSING_APT[@]}"; do
        sudo apt-get install -y "$pkg" 2>/dev/null || \
            warn "Paket nicht verfügbar: $pkg (übersprungen)"
    done
}

install_missing_pip() {
    [ ${#MISSING_PIP[@]} -eq 0 ] && return 0
    pip install $PIP_BREAK_FLAG "${MISSING_PIP[@]}" || \
        warn "pip install fehlgeschlagen – Backplot funktioniert evtl. nicht."
}

reinstall_thorcnc() {
    # PySide6-Konflikt entschärfen (apt vs pip)
    if { [ "$OS" = "debian" ] || [ "$OS" = "ubuntu" ]; } && apt-cache show python3-pyside6 &>/dev/null; then
        if pip show PySide6 &>/dev/null 2>&1; then
            info "Entferne pip-PySide6 (apt-Version soll genutzt werden)..."
            pip uninstall -y PySide6 PySide6-Addons PySide6-Essentials shiboken6 2>/dev/null || true
        fi
        if dpkg -l python3-pyqtgraph &>/dev/null 2>&1; then
            warn "python3-pyqtgraph (apt) gefunden – wird entfernt..."
            sudo apt-get remove -y python3-pyqtgraph || true
        fi

        if $DEV_MODE; then
            info "Editable Reinstall (Debian, ohne pip-PySide6)..."
            pip install $PIP_BREAK_FLAG --no-deps -e .
        else
            info "Reinstalliere thorcnc (Debian, ohne pip-PySide6)..."
            pip install $PIP_BREAK_FLAG --no-deps .
        fi
    else
        local extras="[backplot]"
        if $DEV_MODE; then
            info "Editable Reinstall mit Extras $extras..."
            pip install $PIP_BREAK_FLAG --upgrade -e ".$extras"
        else
            info "Reinstalliere thorcnc mit Extras $extras..."
            pip install $PIP_BREAK_FLAG --upgrade ".$extras"
        fi
    fi
    ok "thorcnc neu installiert."
}

# --- Subroutines + Desktop-Shortcuts (unverändert) ---------------------------
install_subroutines() {
    local SRC="$SCRIPT_DIR/configs/sim/subroutines"
    local DEST="$HOME/linuxcnc/nc_files/subroutines"

    if [ -d "$SRC" ]; then
        info "Synchronisiere Subroutines nach $DEST..."
        mkdir -p "$DEST"
        cp -r "$SRC/"* "$DEST/" || true
        ok "Subroutines synchronisiert."
    else
        warn "Subroutines-Quellordner nicht gefunden: $SRC"
    fi
}

install_desktop_shortcuts() {
    local DESKTOP_PATH="$HOME/Desktop"
    if [ ! -d "$DESKTOP_PATH" ] && [ -d "$HOME/Schreibtisch" ]; then
        DESKTOP_PATH="$HOME/Schreibtisch"
    fi
    [ -d "$DESKTOP_PATH" ] || { warn "Kein Desktop-Ordner gefunden."; return 0; }

    local THORCNC_ICON="$SCRIPT_DIR/thorcnc/images/icon.png"
    local SHORTCUT="$DESKTOP_PATH/ThorCNC-Update.desktop"

    cat > "$SHORTCUT" <<EOD
[Desktop Entry]
Type=Application
Name=ThorCNC Update
Comment=Zieht neueste Version und installiert thorcnc neu
Exec=bash -c "cd '$SCRIPT_DIR' && ./update.sh; echo; echo 'Fertig.'; read -p 'Drücke Enter zum Schließen...' -n 1 -s"
Icon=$THORCNC_ICON
Terminal=true
Categories=Utility;
EOD
    chmod +x "$SHORTCUT"
    ok "Verknüpfung erstellt: ThorCNC-Update.desktop"

    local SIM_SHORTCUT="$DESKTOP_PATH/ThorCNC-Sim.desktop"
    cat > "$SIM_SHORTCUT" <<EOD
[Desktop Entry]
Type=Application
Name=ThorCNC Sim
Comment=Startet ThorCNC in der Simulation
Exec=bash -c "cd '$SCRIPT_DIR' && ./start.sh"
Icon=$THORCNC_ICON
Terminal=false
Categories=Engineering;
EOD
    chmod +x "$SIM_SHORTCUT"
    ok "Verknüpfung erstellt: ThorCNC-Sim.desktop"
}

# =============================================================================
# Hauptablauf
# =============================================================================
echo -e "${BOLD}ThorCNC Updater${NC}"
echo "---------------------------------------"

cd "$SCRIPT_DIR"

if ! git rev-parse --git-dir &>/dev/null; then
    err "Kein Git-Repository gefunden in: $SCRIPT_DIR"
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
OLD_REV=""
NEW_REV=""
PENDING=false
PULLED=false
FIRST_INSTALL=false
MISSING_APT=()
MISSING_PIP=()

# --- Respawn nach Self-Update? -----------------------------------------------
if [ "${THORCNC_UPDATER_RESPAWNED:-0}" = "1" ]; then
    info "Updater neu gestartet mit aktualisierter Version."
    PULLED=true   # Pull wurde im vorigen Lauf schon gemacht
    OLD_REV="${THORCNC_UPDATER_OLD_REV:-}"
    NEW_REV=$(git rev-parse --short HEAD)
    unset THORCNC_UPDATER_RESPAWNED THORCNC_UPDATER_OLD_REV
else
    # --- Git: fetch + Pending-Check (stumm) ----------------------------------
    OLD_REV=$(git rev-parse --short HEAD)
    git fetch --quiet origin "$BRANCH" || warn "git fetch fehlgeschlagen — offline?"

    if ! git diff --quiet "HEAD" "origin/$BRANCH" 2>/dev/null; then
        PENDING=true
    fi
fi

# --- Deps-Check (stumm sammeln) ----------------------------------------------
collect_missing_apt
collect_missing_pip
pip show thorcnc &>/dev/null || FIRST_INSTALL=true

DEPS_MISSING=false
{ [ ${#MISSING_APT[@]} -gt 0 ] || [ ${#MISSING_PIP[@]} -gt 0 ]; } && DEPS_MISSING=true

# --- Entscheidungs-Gate: Silent Fast Path ------------------------------------
if ! $PENDING && ! $DEPS_MISSING && ! $FIRST_INSTALL && ! $FORCE_MODE && ! $PULLED; then
    ok "ThorCNC ist aktuell."
    exit 0
fi

# --- Pending Git-Update behandeln --------------------------------------------
if $PENDING; then
    echo ""
    info "Folgende Änderungen liegen vor:"
    git log --oneline --no-decorate "HEAD..origin/$BRANCH"
    echo ""
    if ! confirm "Diese Änderungen einspielen?"; then
        info "Update abgebrochen."
        exit 0
    fi

    # Self-Update-Hash merken
    UPDATER_HASH_BEFORE=$(md5sum "$0" | cut -d' ' -f1)

    # Pull-Sequenz (still — lokale Änderungen werden im Hintergrund gestasht)
    git stash push --quiet -m "update.sh auto-stash" >/dev/null 2>&1 || true
    if $FORCE_MODE; then
        git reset --hard "origin/$BRANCH" >/dev/null
    else
        git pull --ff-only --quiet origin "$BRANCH" || {
            warn "Fast-forward nicht möglich, versuche Rebase..."
            git pull --rebase --quiet origin "$BRANCH" || \
                err "Pull fehlgeschlagen. Bitte manuell beheben."
        }
    fi
    git stash pop --quiet >/dev/null 2>&1 || true

    NEW_REV=$(git rev-parse --short HEAD)
    ok "Aktualisiert: $OLD_REV → $NEW_REV"
    PULLED=true

    # Self-Update-Erkennung → Respawn
    UPDATER_HASH_AFTER=$(md5sum "$0" | cut -d' ' -f1)
    if [ "$UPDATER_HASH_BEFORE" != "$UPDATER_HASH_AFTER" ]; then
        info "update.sh wurde aktualisiert — starte Updater neu..."
        echo ""
        export THORCNC_UPDATER_RESPAWNED=1
        export THORCNC_UPDATER_OLD_REV="$OLD_REV"
        exec "$0" "$@"
    fi
fi

# --- Fehlende Abhängigkeiten installieren ------------------------------------
if $DEPS_MISSING; then
    echo ""
    info "Fehlende Abhängigkeiten gefunden:"
    [ ${#MISSING_APT[@]} -gt 0 ] && echo "  apt: ${MISSING_APT[*]}"
    [ ${#MISSING_PIP[@]} -gt 0 ] && echo "  pip: ${MISSING_PIP[*]}"
    echo ""
    if confirm "Installieren?"; then
        install_missing_apt
        install_missing_pip
    else
        warn "Abhängigkeiten übersprungen — ThorCNC funktioniert evtl. nicht vollständig."
    fi
fi

# --- thorcnc reinstallieren (nur wenn nötig) ---------------------------------
REINSTALL=false
if $FIRST_INSTALL || $FORCE_MODE; then
    REINSTALL=true
elif $PULLED && [ -n "$OLD_REV" ] && [ "$OLD_REV" != "$NEW_REV" ]; then
    REINSTALL=true
elif $DEV_MODE && $PULLED; then
    # Editable-Modus: nur bei Metadata-Änderung neu installieren
    if [ -n "$OLD_REV" ] && git diff --name-only "$OLD_REV..HEAD" 2>/dev/null | grep -q '^pyproject\.toml$'; then
        REINSTALL=true
    fi
fi

if $REINSTALL; then
    reinstall_thorcnc
fi

# --- Optionale Folge-Schritte (nur wenn etwas am Code passiert ist) ----------
if $PULLED || $REINSTALL; then
    echo ""
    if confirm "nc_files/subroutines nach ~/linuxcnc/nc_files/ synchronisieren?"; then
        install_subroutines
    fi

    if confirm "Desktop-Verknüpfungen erstellen/aktualisieren (Update, Sim)?"; then
        install_desktop_shortcuts
    fi
fi

echo ""
echo -e "${BOLD}Update abgeschlossen.${NC}"
echo ""
