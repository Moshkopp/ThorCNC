"""
LinuxCNC Status Poller
Polls linuxcnc.stat() via QTimer and emits Qt signals on state changes.
"""
import linuxcnc
try:
    import hal as _hal
except ImportError:
    _hal = None
from PySide6.QtCore import QObject, QTimer, Signal


class StatusPoller(QObject):
    # Machine state
    estop_changed        = Signal(bool)   # True = estop active
    machine_on_changed   = Signal(bool)   # True = machine on
    mode_changed         = Signal(int)    # linuxcnc.MODE_MANUAL/MDI/AUTO
    interp_changed       = Signal(int)    # linuxcnc.INTERP_IDLE/READING/PAUSED/WAITING

    # Position (mm, absolute machine coords)
    position_changed     = Signal(list)   # [x, y, z, ...]
    g5x_offset_changed   = Signal(list)   # work coord offsets
    g5x_index_changed    = Signal(int)    # active WCS index (1=G54 … 9=G59.3)
    tool_in_spindle      = Signal(int)
    tool_offset_changed  = Signal(list)   # [x, y, z, ...] current tool offset

    # Program
    file_loaded          = Signal(str)
    program_line         = Signal(int)
    gcodes_changed       = Signal(tuple)  # tuple of active G-codes
    mcodes_changed       = Signal(tuple)  # tuple of active M-codes
    digital_outputs_changed = Signal(tuple) # tuple of 64 digital outs (0/1)

    # Overrides
    feed_override        = Signal(float)  # 0.0–2.0
    spindle_override     = Signal(float)
    rapid_override       = Signal(float)  # 0.0-1.0

    # Spindle
    spindle_speed_cmd    = Signal(float)  # commanded (setpoint) rpm
    spindle_direction    = Signal(int)    # 1=fwd, -1=rev, 0=stop
    spindle_at_speed     = Signal(bool)   # HAL: thorcnc.spindle-atspeed
    spindle_speed_actual = Signal(float)  # HAL: thorcnc.spindle-speed-actual
    spindle_load         = Signal(float)  # HAL: thorcnc.spindle-load (0-100%)
    tool_change_request  = Signal(int)    # HAL: thorcnc.tool-change-request (value is tool number)

    # Homing
    homed_changed        = Signal(list)   # list of bools per axis

    # Error / info messages
    error_message        = Signal(str)
    info_message         = Signal(str)

    # Periodic tick (for anything not covered above)
    periodic             = Signal()

    def __init__(self, interval_ms: int = 100, parent=None, hal_comp=None):
        super().__init__(parent)
        self.stat = linuxcnc.stat()
        self.error_channel = linuxcnc.error_channel()
        self._hal_comp = hal_comp

        # Shadow values to detect changes
        self._estop          = None
        self._machine_on     = None
        self._mode           = None
        self._interp         = None
        self._position       = None
        self._g5x_offset     = None
        self._g5x_index      = None
        self._tool           = None
        self._tool_offset    = None
        self._file           = None
        self._line           = None
        self._feed_override  = None
        self._spindle_over   = None
        self._spindle_cmd   = None
        self._spindle_dir    = None
        self._spindle_at_spd = None
        self._spindle_actual = -1.0
        self._spindle_load   = -1.0
        self._tool_change_req = None
        self._homed          = None
        self._gcodes         = None
        self._mcodes         = None
        self._dout           = None

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _poll(self):
        try:
            self.stat.poll()
        except linuxcnc.error:
            return

        self._check_errors()
        self._emit_if_changed()
        self.periodic.emit()

    def _check_errors(self):
        try:
            error = self.error_channel.poll()
            while error:
                kind, text = error
                if kind in (linuxcnc.NML_ERROR, linuxcnc.OPERATOR_ERROR):
                    self.error_message.emit(text)
                else:
                    self.info_message.emit(text)
                error = self.error_channel.poll()
        except Exception:
            pass

    def _emit_if_changed(self):
        s = self.stat

        estop = s.task_state == linuxcnc.STATE_ESTOP
        if estop != self._estop:
            self._estop = estop
            self.estop_changed.emit(estop)

        machine_on = s.task_state == linuxcnc.STATE_ON
        if machine_on != self._machine_on:
            self._machine_on = machine_on
            self.machine_on_changed.emit(machine_on)

        if s.task_mode != self._mode:
            self._mode = s.task_mode
            self.mode_changed.emit(s.task_mode)

        if s.interp_state != self._interp:
            self._interp = s.interp_state
            self.interp_changed.emit(s.interp_state)

        # -- Position update --
        # We use Cartesian 'position' (commanded) instead of 'actual_position' (feedback).
        # This ensures the DRO matches the G-code target exactly when the segment ends,
        # making DTG behavior intuitive and eliminating servo-lag flicker in the UI.
        pos = tuple(s.position[:3])

        if pos != self._position:
            self._position = pos
            self.position_changed.emit(list(pos))

        g5x = tuple(s.g5x_offset[:3])
        if g5x != self._g5x_offset:
            self._g5x_offset = g5x
            self.g5x_offset_changed.emit(list(g5x))

        g5x_idx = s.g5x_index
        if g5x_idx != self._g5x_index:
            self._g5x_index = g5x_idx
            self.g5x_index_changed.emit(g5x_idx)

        if s.tool_in_spindle != self._tool:
            self._tool = s.tool_in_spindle
            self.tool_in_spindle.emit(s.tool_in_spindle)

        tool_off = tuple(s.tool_offset[:3])
        if tool_off != self._tool_offset:
            self._tool_offset = tool_off
            self.tool_offset_changed.emit(list(tool_off))

        if s.file != self._file:
            self._file = s.file
            self.file_loaded.emit(s.file)

        active_line = s.motion_line if s.motion_line > 0 else s.current_line
        if active_line != self._line:
            self._line = active_line
            self.program_line.emit(active_line)

        gcodes = s.gcodes
        if gcodes != self._gcodes:
            self._gcodes = gcodes
            self.gcodes_changed.emit(gcodes)

        mcodes = s.mcodes
        if mcodes != self._mcodes:
            self._mcodes = mcodes
            self.mcodes_changed.emit(mcodes)

        dout = s.dout
        if dout != self._dout:
            # Debugging digital output changes
            # print(f"[DEBUG] Digital Outs changed! Bit 0: {dout[0]}")
            self._dout = dout
            self.digital_outputs_changed.emit(dout)

        if s.feedrate != self._feed_override:
            self._feed_override = s.feedrate
            self.feed_override.emit(s.feedrate)

        spindle_over = s.spindle[0]['override']
        if spindle_over != self._spindle_over:
            self._spindle_over = spindle_over
            self.spindle_override.emit(spindle_over)

        rapid_over = s.rapidrate
        if rapid_over != getattr(self, '_rapid_over', None):
            self._rapid_over = rapid_over
            self.rapid_override.emit(rapid_over)

        # We use 'speed' as the commanded setpoint here if no better key exists,
        # but in many configs 'speed' is actually feedback.
        # So we emit it as 'commanded' and let HAL provide 'actual'.
        spindle_cmd = s.spindle[0]['speed']
        if spindle_cmd != self._spindle_cmd:
            self._spindle_cmd = spindle_cmd
            self.spindle_speed_cmd.emit(spindle_cmd)

        spindle_dir = s.spindle[0]['direction']
        if spindle_dir != self._spindle_dir:
            self._spindle_dir = spindle_dir
            self.spindle_direction.emit(spindle_dir)

        if not _hal:
            return

        try:
            if self._hal_comp:
                # Direkter Zugriff auf die eigene Komponente ist zuverlässiger
                at_spd  = bool(self._hal_comp["spindle-atspeed"])
                actual  = float(self._hal_comp["spindle-speed-actual"])
                load    = float(self._hal_comp["spindle-load"])
            elif _hal:
                at_spd  = bool(_hal.get_value("thorcnc.spindle-atspeed"))
                actual  = float(_hal.get_value("thorcnc.spindle-speed-actual"))
                load    = float(_hal.get_value("thorcnc.spindle-load"))
            else:
                at_spd, actual, load = False, 0.0, 0.0
        except Exception as e:
            # Nur einmal melden, um Terminal nicht zu fluten
            if not hasattr(self, "_hal_err_shown"):
                print(f"[ThorCNC] Fehler beim Lesen der HAL-Pins: {e}")
                self._hal_err_shown = True
            at_spd = False
            actual = 0.0
            load   = 0.0
        if at_spd != self._spindle_at_spd:
            self._spindle_at_spd = at_spd
            self.spindle_at_speed.emit(at_spd)
        if round(actual) != self._spindle_actual:
            self._spindle_actual = round(actual)
            self.spindle_speed_actual.emit(actual)
        if round(load) != self._spindle_load:
            self._spindle_load = round(load)
            self.spindle_load.emit(load)

        # Tool Change Request (HAL)
        try:
            # Wir prüfen, ob der Bit-Pin High ist
            if bool(_hal.get_value("thorcnc.tool-change-request")):
                t_nr = int(_hal.get_value("thorcnc.tool-number"))
                if self._tool_change_req != t_nr:
                    self._tool_change_req = t_nr
                    self.tool_change_request.emit(t_nr)
            else:
                self._tool_change_req = None
        except Exception:
            pass

        homed = tuple(s.homed[:3])
        if homed != self._homed:
            self._homed = homed
            self.homed_changed.emit(list(homed))
