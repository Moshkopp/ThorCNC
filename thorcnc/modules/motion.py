"""Motion module for ThorCNC — jogging, homing, and override controls."""

import time
import linuxcnc
from PySide6.QtCore import Qt, Slot, QPointF, QRectF
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QBrush, QRadialGradient, QIcon

from .base import ThorModule
from ..i18n import _t


class MotionModule(ThorModule):
    """Manages jogging, homing, and override controls."""

    def __init__(self, thorc):
        super().__init__(thorc)
        self._jog_velocity = 100.0
        self._jog_increment = 0.0

    def setup(self):
        self._setup_jog_display()

    def connect_signals(self):
        p = self._t.poller
        ui = self._t.ui

        p.feed_override.connect(self._on_feed_override)
        p.spindle_override.connect(self._on_spindle_override)
        if hasattr(p, 'rapid_override'):
            p.rapid_override.connect(self._on_rapid_override)
        p.homed_changed.connect(self._on_homed)

        def btn(name):
            from PySide6.QtWidgets import QPushButton
            return ui.findChild(QPushButton, name)

        if b := btn("ref_all_button"):
            b.clicked.connect(self._home_all)
        if b := btn("ref_x_button"):
            b.clicked.connect(lambda: self._home_joint(0))
        if b := btn("ref_y_button"):
            b.clicked.connect(lambda: self._home_joint(1))
        if b := btn("ref_z_button"):
            b.clicked.connect(lambda: self._home_joint(2))
        if b := btn("v_override_to_100_button"):
            b.clicked.connect(self._on_v_override_to_100)
        if b := btn("btn_go_to_home"):
            b.clicked.connect(self._go_to_home)

        for axis, joint in (("x", 0), ("y", 1), ("z", 2)):
            for dirn, sign in (("plus", 1), ("minus", -1)):
                if b := btn(f"{axis}_{dirn}_jogbutton_3"):
                    b.pressed.connect(lambda a=joint, s=sign: self._jog_start(a, s))
                    b.released.connect(lambda a=joint: self._jog_stop(a))

        def sld(name):
            from PySide6.QtWidgets import QSlider
            return ui.findChild(QSlider, name)

        if s := sld("v_override_slider"):
            s.valueChanged.connect(self._on_v_override_changed)
        if s := sld("jog_vel_slider"):
            s.valueChanged.connect(self._on_jog_vel_changed)

        if b := btn("btn_jog_cont"):
            b.clicked.connect(lambda: self._set_jog_increment(0.0))
        if b := btn("btn_jog_1_0"):
            b.clicked.connect(lambda: self._set_jog_increment(1.0))
        if b := btn("btn_jog_0_1"):
            b.clicked.connect(lambda: self._set_jog_increment(0.1))
        if b := btn("btn_jog_0_01"):
            b.clicked.connect(lambda: self._set_jog_increment(0.01))

    def _update_goto_home_style(self, all_homed: bool):
        in_auto = getattr(self._t, "_current_mode", None) == linuxcnc.MODE_AUTO

        btn = self._t.navigation._flyout_item_buttons.get("SHORTS_GO TO HOME") if self._t.navigation else None

        if not btn:
            return

        if in_auto:
            btn.setEnabled(False)
            self._t._add_class(btn, "")
        elif all_homed:
            btn.setEnabled(True)
            self._t._add_class(btn, "btn-green")
        else:
            btn.setEnabled(True)
            self._t._add_class(btn, "btn-red")

    def _setup_jog_display(self):
        """Jog-Display-Page aus INI setzen, Icons auf Buttons legen."""
        from PySide6.QtWidgets import QStackedWidget, QPushButton

        coords = ""
        if self._t.ini:
            coords = (self._t.ini.find("TRAJ", "COORDINATES") or
                      self._t.ini.find("DISPLAY", "GEOMETRY") or "XYZ").upper().replace(" ", "")

        page_map = {"XYZ": 0, "XYZA": 1, "XYZAB": 2, "XYZAC": 3, "XYZBC": 4, "XYZABC": 5}
        page = page_map.get(coords, 0)

        jog_stack = self._t.ui.findChild(QStackedWidget, "jogDisplay")
        if jog_stack:
            jog_stack.setCurrentIndex(page)

        btn_icons = {
            "z_plus_jogbutton_3":  ("Z", "up"),
            "z_minus_jogbutton_3": ("Z", "down"),
            "y_plus_jogbutton_3":  ("Y", "up"),
            "y_minus_jogbutton_3": ("Y", "down"),
            "x_plus_jogbutton_3":  ("X", "right"),
            "x_minus_jogbutton_3": ("X", "left"),
        }
        for btn_name, (axis, direction) in btn_icons.items():
            b = self._t.ui.findChild(QPushButton, btn_name)
            if b:
                b.setIcon(self._make_jog_icon(axis, direction))
                b.setIconSize(b.minimumSize())
                b.setText("")

    @staticmethod
    def _make_jog_icon(axis: str, direction: str, size: int = 42):
        """Zeichnet ein Jog-Button-Icon: farbiger Ring + Achsbeschriftung."""
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy = size / 2.0, size / 2.0
        r = size / 2.0 - 1.5

        axis_colors = {
            "X": QColor(210, 55,  55),
            "Y": QColor(45,  190, 75),
            "Z": QColor(55,  120, 215),
        }
        ac = axis_colors.get(axis, QColor(160, 160, 160))

        bg = QRadialGradient(cx, cy, r)
        bg.setColorAt(0.0, QColor(52, 57, 62))
        bg.setColorAt(1.0, QColor(28, 31, 34))
        p.setBrush(QBrush(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r, r)

        ring_pen = QPen(ac, 2.2)
        ring_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(ring_pen)
        p.drawEllipse(QPointF(cx, cy), r, r)

        sign = "+" if direction in ("up", "right") else "-"
        font = QFont("Bebas Kai", max(8, size // 3))
        font.setBold(True)
        p.setFont(font)
        label_color = ac.lighter(160)
        label_color.setAlpha(230)
        p.setPen(QPen(label_color))
        p.drawText(QRectF(0, 0, size, size),
                   Qt.AlignmentFlag.AlignCenter, f"{axis}{sign}")

        p.end()
        return QIcon(pix)

    @Slot(float)
    def _on_feed_override(self, val: float):
        from PySide6.QtWidgets import QLabel, QSlider
        pct = f"F {val*100:.0f}%"
        ival = int(val * 100)
        for lbl_name, sld_name in [
            ("feed_override_status",       "feed_override_slider"),
            ("probe_feed_override_status", "probe_feed_override_slider"),
        ]:
            if lbl := self._t._w(QLabel, lbl_name):
                lbl.setText(pct)
            if s := self._t._w(QSlider, sld_name):
                s.blockSignals(True)
                s.setValue(ival)
                s.blockSignals(False)

    @Slot(float)
    def _on_spindle_override(self, val: float):
        from PySide6.QtWidgets import QLabel, QSlider
        pct = f"S {val*100:.0f}%"
        ival = int(val * 100)
        for lbl_name, sld_name in [
            ("spindle_override_status",       "spindle_override_slider"),
            ("probe_spindle_override_status", "probe_spindle_override_slider"),
        ]:
            if lbl := self._t._w(QLabel, lbl_name):
                lbl.setText(pct)
            if s := self._t._w(QSlider, sld_name):
                s.blockSignals(True)
                s.setValue(ival)
                s.blockSignals(False)

    @Slot(float)
    def _on_rapid_override(self, val: float):
        from PySide6.QtWidgets import QLabel, QSlider
        pct = f"R {val*100:.0f}%"
        ival = int(val * 100)
        for lbl_name, sld_name in [
            ("rapid_override_status",       "rapid_override_slider"),
            ("probe_rapid_override_status", "probe_rapid_override_slider"),
        ]:
            if lbl := self._t._w(QLabel, lbl_name):
                lbl.setText(pct)
            if s := self._t._w(QSlider, sld_name):
                s.blockSignals(True)
                s.setValue(ival)
                s.blockSignals(False)

    def _on_v_override_changed(self, val: int):
        from PySide6.QtWidgets import QLabel
        if lbl := self._t._w(QLabel, "v_override_status"):
            lbl.setText(f"V {val}%")
        self._t.cmd.feedrate(val / 100.0)
        self._t.cmd.spindleoverride(val / 100.0)

    def _on_v_override_to_100(self):
        from PySide6.QtWidgets import QSlider, QLabel
        if s := self._t._w(QSlider, "v_override_slider"):
            s.setValue(100)
        if lbl := self._t._w(QLabel, "v_override_status"):
            lbl.setText(f"V 100%")
        self._t.cmd.feedrate(1.0)
        self._t.cmd.spindleoverride(1.0)

    @Slot(list)
    def _on_homed(self, homed: list):
        self._t._all_joints_homed = all(i < len(homed) and homed[i] for i in range(3))
        self._update_goto_home_style(self._t._is_machine_on and self._t._all_joints_homed)

        if self._t.dro._btn_ref_all:
            self._t.dro._btn_ref_all.setText("HOMED" if self._t._all_joints_homed else "REF ALL")
            cls = "btn-green btn-homed" if self._t._all_joints_homed else "btn-green"
            self._t.dro._btn_ref_all.setProperty("class", cls)
            self._t.dro._btn_ref_all.style().unpolish(self._t.dro._btn_ref_all)
            self._t.dro._btn_ref_all.style().polish(self._t.dro._btn_ref_all)

        enable_g53 = self._t.settings.get("homing_g53_conversion", False)

        for i, axis in enumerate(("X", "Y", "Z")):
            is_homed = i < len(homed) and homed[i]
            if axis in self._t.dro._dro_work:
                lbl = self._t.dro._dro_work[axis]
                lbl.setProperty("homed", is_homed)
                lbl.style().unpolish(lbl)
                lbl.style().polish(lbl)
            
            if axis in self._t.dro._dro_ref_btn:
                btn = self._t.dro._dro_ref_btn[axis]

                if enable_g53 and is_homed:
                    btn.setText(f"G53 {axis} 0")
                    btn.setProperty("class", "btn-blue btn-homed")
                else:
                    btn.setText(f"REF {axis}")
                    btn.setProperty("class", "btn-green btn-homed" if is_homed else "btn-green")

                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()

    def _go_to_home(self):
        """Move to machine zero via O<go_to_home> subroutine."""
        try:
            old_mode = self._t.poller.stat.task_mode
            self._t.cmd.mode(linuxcnc.MODE_MDI)
            self._t.cmd.wait_complete()

            self._t.cmd.mdi("O<go_to_home> CALL")
            self._t.cmd.wait_complete()

            start_t = time.time()
            timeout = 60.0

            self._t._status(_t("Fahrt auf Home-Position (G53) läuft..."))

            while time.time() - start_t < timeout:
                QApplication.processEvents()

                if self._t.poller.stat.interp_state == linuxcnc.INTERP_IDLE:
                    break
                time.sleep(0.05)

            self._t.cmd.mode(old_mode)
            self._t.cmd.wait_complete()
            self._t._status(_t("Home-Position erreicht."))
        except Exception as e:
            self._t._status(f"Homing error: {e}", error=True)

    def _home_all(self):
        self._t.cmd.mode(linuxcnc.MODE_MANUAL)
        self._t.cmd.wait_complete()
        self._t.cmd.home(-1)

    def _home_joint(self, joint: int):
        is_homed = False
        homed_status = getattr(self._t.poller, "_homed", [])
        if 0 <= joint < len(homed_status):
            is_homed = homed_status[joint]

        enable_g53 = self._t.settings.get("homing_g53_conversion", False)

        if enable_g53 and is_homed:
            axis_map = {0: "X", 1: "Y", 2: "Z"}
            axis = axis_map.get(joint)
            if axis:
                self._t._send_mdi(f"G53 G0 {axis}0")
            return

        self._t.cmd.mode(linuxcnc.MODE_MANUAL)
        self._t.cmd.wait_complete()
        self._t.cmd.home(joint)

    def _set_jog_increment(self, inc: float):
        self._jog_increment = inc
        from PySide6.QtWidgets import QPushButton
        for name, val in [("btn_jog_cont", 0.0), ("btn_jog_1_0", 1.0), ("btn_jog_0_1", 0.1), ("btn_jog_0_01", 0.01)]:
            if b := self._t._w(QPushButton, name):
                b.setChecked(abs(inc - val) < 0.0001)

    def _on_jog_vel_changed(self, val: int):
        self._jog_velocity = float(val)
        from PySide6.QtWidgets import QLabel
        if lbl := self._t._w(QLabel, "jog_vel_label"):
            lbl.setText(f"Velocity: {val}")

    def _jog_start(self, joint: int, direction: int):
        self._t.cmd.mode(linuxcnc.MODE_MANUAL)
        self._t.cmd.wait_complete()
        if self._jog_increment <= 0.0:
            self._t.cmd.jog(linuxcnc.JOG_CONTINUOUS, False, joint, direction * self._jog_velocity)
        else:
            self._t.cmd.jog(linuxcnc.JOG_INCREMENT, False, joint, direction * self._jog_velocity, self._jog_increment)

    def _jog_stop(self, joint: int):
        if self._jog_increment <= 0.0:
            self._t.cmd.jog(linuxcnc.JOG_STOP, False, joint)
