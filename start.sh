#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ThorCNC – Schnellstart
# Installiert (editable) falls nötig und startet LinuxCNC + ThorCNC.
#
# Verwendung:
#   ./start.sh                        # Sim-Config (Standard)
#   ./start.sh --theme light          # anderes Theme
#   ./start.sh /pfad/zur/maschine.ini # eigene INI
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_INI="$SCRIPT_DIR/configs/sim/thorcnc_sim.ini"
THEME=""
CUSTOM_INI=""

# ── PIP Flags (Debian 12+ / PEP 668) ──────────────────────────────────────────
PIP_BREAK_FLAG=""
if pip install --help | grep -q 'break-system-packages'; then
    PIP_BREAK_FLAG="--break-system-packages"
fi

for arg in "$@"; do
    case "$arg" in
        --theme=*) THEME="${arg#--theme=}" ;;
        --theme)   ;;   # nächstes Argument wird Theme
        *.ini)     CUSTOM_INI="$arg" ;;
    esac
done
# --theme VALUE als zwei Argumente
args=("$@")
for i in "${!args[@]}"; do
    if [[ "${args[$i]}" == "--theme" && $((i+1)) -lt ${#args[@]} ]]; then
        THEME="${args[$((i+1))]}"
    fi
done

INI="${CUSTOM_INI:-$SIM_INI}"

export PATH="$HOME/.local/bin:$PATH"

# ── Dev-Install falls thorcnc-Befehl nicht gefunden ─────────────────────────
if ! command -v thorcnc &>/dev/null; then
    echo "[start.sh] 'thorcnc' nicht im PATH – führe 'pip install $PIP_BREAK_FLAG -e .' aus..."
    pip install $PIP_BREAK_FLAG -e "$SCRIPT_DIR" --quiet
    echo "[start.sh] Installation abgeschlossen."
fi

# ── pyqtgraph / PyOpenGL prüfen (optional, für Backplot) ─────────────────────
if ! python3 -c "import pyqtgraph.opengl" &>/dev/null 2>&1; then
    echo "[start.sh] HINWEIS: pyqtgraph/OpenGL nicht gefunden – Backplot deaktiviert."
    echo "           pip install pyqtgraph PyOpenGL"
fi

# ── Umgebungsvariablen setzen ────────────────────────────────────────────────
[ -n "$THEME" ] && export THORCNC_THEME="$THEME"
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

echo "[start.sh] Starte LinuxCNC mit: $INI"
echo "[start.sh] Theme: $THEME"
echo "[start.sh] PYTHONPATH: $SCRIPT_DIR"
echo ""

# Wir nutzen exec, damit der Prozess die Umgebung übernimmt
exec linuxcnc "$INI"
