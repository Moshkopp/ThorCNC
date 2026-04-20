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

if $DEV_MODE; then
    info "Editable Reinstall (--dev) mit Extras $EXTRAS..."
    pip install $PIP_BREAK_FLAG -e ".$EXTRAS"
    ok "thorcnc (dev) aktualisiert."
else
    info "Reinstalliere thorcnc mit Extras $EXTRAS..."
    pip install $PIP_BREAK_FLAG ".$EXTRAS"
    ok "thorcnc aktualisiert."
fi

# --- Subroutines synchronisieren ---------------------------------------------
install_subroutines() {
    SRC="$SCRIPT_DIR/configs/sim/subroutines"
    DEST="$HOME/linuxcnc/nc_files/subroutines"
    
    if [ -d "$SRC" ]; then
        info "Synchronisiere Subroutines nach $DEST..."
        mkdir -p "$DEST"
        # Kopiert nur neue Dateien (-n), damit Benutzeranpassungen in nc_files erhalten bleiben
        cp -rn "$SRC/"* "$DEST/" || true
        ok "Subroutines synchronisiert."
    else
        warn "Subroutines-Quellordner nicht gefunden: $SRC"
    fi
}

install_subroutines

echo ""
echo -e "${BOLD}Update abgeschlossen.${NC}"
echo ""

# --- Desktop Shortcut --------------------------------------------------------
DESKTOP_PATH="$HOME/Desktop"
if [ ! -d "$DESKTOP_PATH" ] && [ -d "$HOME/Schreibtisch" ]; then
    DESKTOP_PATH="$HOME/Schreibtisch"
fi

if [ -d "$DESKTOP_PATH" ]; then
    info "Erstelle/Aktualisiere Desktop-Verknüpfung in $DESKTOP_PATH..."
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
fi

echo ""
