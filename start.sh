#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# ThorCNC – Schnellstart
# Installiert (editable) falls nötig und startet LinuxCNC + ThorCNC.
#
# Verwendung:
#   ./start.sh                        # Sim-Config (Standard)
#   ./start.sh --theme dark_green     # anderes Theme
#   ./start.sh /pfad/zur/maschine.ini # eigene INI
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_INI="$SCRIPT_DIR/configs/sim/thorcnc_sim.ini"
THEME="dark"
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

# ── Venv aktivieren falls vorhanden, sonst ~/.local/bin ─────────────────────
VENV_ACTIVATE="$SCRIPT_DIR/../venv/bin/activate"
if [ -f "$VENV_ACTIVATE" ]; then
    # shellcheck disable=SC1090
    source "$VENV_ACTIVATE"
    echo "[start.sh] Venv aktiviert: $(dirname "$VENV_ACTIVATE")"
else
    export PATH="$HOME/.local/bin:$PATH"
fi

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
export THORCNC_THEME="$THEME"
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

# Falls wir nicht im venv sind, stellen wir sicher, dass ~/.local/bin ganz vorne ist
if [ -z "${VIRTUAL_ENV:-}" ]; then
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "[start.sh] Starte LinuxCNC mit: $INI"
echo "[start.sh] Theme: $THEME"
echo "[start.sh] PYTHONPATH: $SCRIPT_DIR"
echo ""

# Wir nutzen exec, damit der Prozess die Umgebung übernimmt
exec linuxcnc "$INI"
