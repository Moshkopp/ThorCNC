"""HAL (Hardware Abstraction Layer) Module.

Handles:
- HAL component initialization and pin creation
- Post-GUI HAL file loading from INI
- Hardware signal setup and verification
"""

import os
import subprocess
from .base import ThorModule


class HALModule(ThorModule):
    """Manages HAL component setup and hardware configuration."""

    def setup(self):
        """Initialize HAL component and pins."""
        self._setup_hal()

    def _setup_hal(self):
        """Initialize HAL component with all pins (called early for timing)."""
        try:
            import hal

            hal_comp = hal.component("thorcnc")
            self._t._hal_comp = hal_comp

            # Tool Sensor Pins (from SettingsTabModule config)
            if hasattr(self._t, 'settings_tab'):
                for _, key, _ in self._t.settings_tab._TOOLSENSOR_FIELDS:
                    pin_name = key.replace("_", "-")
                    hal_comp.newpin(pin_name, hal.HAL_FLOAT, hal.HAL_OUT)

            # Standard Pins
            hal_comp.newpin("probe-sim", hal.HAL_BIT, hal.HAL_OUT)
            hal_comp.newpin("spindle-atspeed", hal.HAL_BIT, hal.HAL_IN)
            hal_comp.newpin("spindle-speed-actual", hal.HAL_FLOAT, hal.HAL_IN)
            hal_comp.newpin("spindle-load", hal.HAL_FLOAT, hal.HAL_IN)

            # Manual Tool Changer Pins (M6)
            hal_comp.newpin("tool-change-request", hal.HAL_BIT, hal.HAL_IN)
            hal_comp.newpin("tool-number", hal.HAL_S32, hal.HAL_IN)
            hal_comp.newpin("tool-changed-confirm", hal.HAL_BIT, hal.HAL_OUT)

            # Handwheel / TsHW Integration Pins
            hal_comp.newpin("jog-vel-final", hal.HAL_FLOAT, hal.HAL_OUT)

            # Großwerkzeug-Versatz am Toolsetter
            hal_comp.newpin("ts-contact-diameter", hal.HAL_FLOAT, hal.HAL_OUT)
            hal_comp.newpin("ts-large-tool-enable", hal.HAL_BIT,   hal.HAL_OUT)
            hal_comp.newpin("ts-offset-dir-x",      hal.HAL_FLOAT, hal.HAL_OUT)
            hal_comp.newpin("ts-offset-dir-y",      hal.HAL_FLOAT, hal.HAL_OUT)

            hal_comp.ready()
            from thorcnc.i18n import _t
            self._t._status(_t("HAL component 'thorcnc' ready."))

            # Load Post-GUI HAL files from INI
            self._load_postgui_hal()

            # Simulation-specific setup
            if "sim" in self._t.ini_path.lower():
                self._setup_sim_hal()

        except Exception as e:
            print(f"[HAL] Initialisierung übersprungen: {e}")
            self._t._hal_comp = None

    def _load_postgui_hal(self):
        """Load all POSTGUI_HALFILE entries from INI configuration."""
        if not self._t.ini:
            return

        postgui_files = self._t.ini.findall("HAL", "POSTGUI_HALFILE")
        if not postgui_files:
            return

        ini_dir = os.path.dirname(self._t.ini_path) if self._t.ini_path else ""
        if not ini_dir:
            ini_dir = os.getcwd()

        for pfile in postgui_files:
            hal_path = os.path.join(ini_dir, pfile)
            if os.path.exists(hal_path):
                res = subprocess.run(
                    ["halcmd", "-i", self._t.ini_path, "-f", hal_path],
                    capture_output=True,
                    text=True
                )
                if res.returncode != 0:
                    print(f"[HAL] Fehler beim Laden von {pfile}:\n{res.stderr}")
            else:
                print(f"[HAL] FEHLER: Post-GUI Datei nicht gefunden: {hal_path}")

    def _setup_sim_hal(self):
        """Setup simulation-specific HAL connections and parameters."""
        def _hc(*args):
            result = subprocess.run(["halcmd"] + list(args), capture_output=True, text=True)
            if result.returncode != 0:
                print(f"[HAL ERROR] halcmd {' '.join(args)} failed: {result.stderr}")
            return result

        _hc("setp", "limit_speed.maxv", "600.0")
        _hc("setp", "spindle_mass.gain", "0.002")
        _hc("net", "spindle-at-speed", "thorcnc.spindle-atspeed")
        _hc("net", "spindle-rpm-filtered", "thorcnc.spindle-speed-actual")
