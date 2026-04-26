"""Surface Map Heatmap Widget — bilinear interpolation rendering."""

from PySide6.QtWidgets import QWidget, QToolTip
from PySide6.QtCore import Qt, QRect, QRectF
from PySide6.QtGui import (QPainter, QColor, QPen, QFont,
                            QFontMetrics, QImage)

# 5-stop color ramp: blue → cyan → green → yellow → red
_RAMP = [
    (0.00, (30,  30, 220)),
    (0.25, (30, 200, 220)),
    (0.50, (30, 190,  30)),
    (0.75, (220, 220, 30)),
    (1.00, (220,  30,  30)),
]

_OVERSAMPLE   = 12   # pixels per grid cell in the intermediate image
_MARGIN_LEFT  = 48
_MARGIN_BOTTOM = 28
_MARGIN_TOP    = 10
_MARGIN_RIGHT  = 72   # scale bar + labels
_SCALE_BAR_W  = 20


def _lerp_color(t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    for i in range(len(_RAMP) - 1):
        t0, c0 = _RAMP[i]
        t1, c1 = _RAMP[i + 1]
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            return (
                int(c0[0] + f * (c1[0] - c0[0])),
                int(c0[1] + f * (c1[1] - c0[1])),
                int(c0[2] + f * (c1[2] - c0[2])),
            )
    return _RAMP[-1][1]


class SurfaceMapWidget(QWidget):
    """Bilinearly interpolated heatmap for surface scan Z data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[list[float]] = []
        self._cols = 0
        self._rows = 0
        self._x_labels: list[str] = []
        self._y_labels: list[str] = []
        self._z_min = 0.0
        self._z_max = 0.0
        self._z_mean = 0.0
        self._cached_image: QImage | None = None
        self.setMouseTracking(True)
        self.setMinimumSize(300, 200)

    def set_data(self, grid: list[list[float]],
                 x_coords: list[float], y_coords: list[float]):
        self._data = grid
        self._rows = len(grid)
        self._cols = len(grid[0]) if grid else 0
        self._x_labels = [f"{v:.1f}" for v in x_coords]
        self._y_labels = [f"{v:.1f}" for v in y_coords]

        flat = [z for row in grid for z in row]
        if flat:
            self._z_min  = min(flat)
            self._z_max  = max(flat)
            self._z_mean = sum(flat) / len(flat)

        self._cached_image = None   # invalidate cache
        self.update()

    def clear(self):
        self._data = []
        self._cols = self._rows = 0
        self._cached_image = None
        self.update()

    # ── rendering ─────────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        self._cached_image = None   # invalidate on resize
        super().resizeEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(28, 28, 28))

        if not self._data or self._cols == 0 or self._rows == 0:
            p.setPen(QColor(110, 110, 110))
            p.setFont(QFont("monospace", 12))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Noch kein Scan vorhanden")
            return

        gx = _MARGIN_LEFT
        gy = _MARGIN_TOP
        gw = w - _MARGIN_LEFT - _MARGIN_RIGHT
        gh = h - _MARGIN_TOP - _MARGIN_BOTTOM
        if gw < 10 or gh < 10:
            return

        # Build / reuse cached interpolated image
        if self._cached_image is None:
            self._cached_image = self._build_image()

        # Draw interpolated heatmap scaled to grid area
        p.drawImage(QRect(gx, gy, gw, gh), self._cached_image)

        # Grid lines at measurement positions (subtle)
        cell_w = gw / self._cols
        cell_h = gh / self._rows
        grid_pen = QPen(QColor(0, 0, 0, 60), 1)
        p.setPen(grid_pen)
        for col in range(1, self._cols):
            x = int(gx + col * cell_w)
            p.drawLine(x, gy, x, gy + gh)
        for row in range(1, self._rows):
            y = int(gy + row * cell_h)
            p.drawLine(gx, y, gx + gw, y)
        p.drawRect(gx, gy, gw, gh)

        # Measurement point dots + Z value labels
        dot_r = max(3, min(6, int(min(cell_w, cell_h) * 0.10)))
        lbl_font = QFont("monospace", max(7, min(11, int(min(cell_w, cell_h) * 0.13))))
        p.setFont(lbl_font)
        lfm = QFontMetrics(lbl_font)
        lbl_h = lfm.height()

        for row in range(self._rows):
            draw_row = self._rows - 1 - row
            for col in range(self._cols):
                cx = int(gx + (col + 0.5) * cell_w)
                cy = int(gy + (draw_row + 0.5) * cell_h)

                # Dot
                p.setPen(QPen(QColor(255, 255, 255, 200), 1))
                p.setBrush(QColor(255, 255, 255, 220))
                p.drawEllipse(cx - dot_r, cy - dot_r, dot_r * 2, dot_r * 2)

                # Z label below dot
                z = self._data[row][col]
                lbl = f"{z:.3f}"
                lw = lfm.horizontalAdvance(lbl)
                tx = cx - lw // 2
                ty = cy + dot_r + 2

                # Dark background pill for readability
                pad = 2
                bg_rect = QRect(tx - pad, ty - lfm.ascent() - pad,
                                lw + pad * 2, lbl_h + pad * 2)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, 150))
                p.drawRoundedRect(bg_rect, 2, 2)

                p.setPen(QColor(255, 255, 255))
                p.drawText(tx, ty, lbl)

        self._draw_axis_labels(p, gx, gy, gw, gh, cell_w, cell_h)
        self._draw_scale_bar(p, w, gy, gh)

    def _build_image(self) -> QImage:
        """Render bilinearly interpolated heatmap into a QImage."""
        img_w = self._cols * _OVERSAMPLE
        img_h = self._rows * _OVERSAMPLE
        z_range = self._z_max - self._z_min

        # Build raw ARGB bytes — much faster than setPixelColor
        buf = bytearray(img_w * img_h * 4)

        for py in range(img_h):
            draw_row_continuous = (py / max(img_h - 1, 1)) * self._rows - 0.5
            fr = (self._rows - 1) - draw_row_continuous
            # Clamp to valid range [0, rows - 1]
            fr = max(0.0, min(fr, self._rows - 1.0))
            
            r0 = max(0, min(int(fr), self._rows - 2))
            r1 = r0 + 1
            tr = fr - r0

            row_offset = py * img_w * 4

            for px in range(img_w):
                col_continuous = (px / max(img_w - 1, 1)) * self._cols - 0.5
                # Clamp to valid range [0, cols - 1]
                fc = max(0.0, min(col_continuous, self._cols - 1.0))
                
                c0 = max(0, min(int(fc), self._cols - 2))
                c1 = c0 + 1
                tc = fc - c0

                z00 = self._data[r0][c0]
                z01 = self._data[r0][c1]
                z10 = self._data[r1][c0]
                z11 = self._data[r1][c1]
                z = (z00 * (1 - tc) * (1 - tr) +
                     z01 * tc       * (1 - tr) +
                     z10 * (1 - tc) * tr +
                     z11 * tc       * tr)

                t = (z - self._z_min) / z_range if z_range > 1e-9 else 0.5
                r, g, b = _lerp_color(t)

                i = row_offset + px * 4
                buf[i]     = b          # Qt ARGB32: BGRA in memory
                buf[i + 1] = g
                buf[i + 2] = r
                buf[i + 3] = 255

        return QImage(bytes(buf), img_w, img_h,
                      img_w * 4, QImage.Format.Format_ARGB32)

    def _draw_axis_labels(self, p, gx, gy, gw, gh, cell_w, cell_h):
        af = QFont("monospace", 8)
        p.setFont(af)
        afm = QFontMetrics(af)
        p.setPen(QColor(190, 190, 190))

        for col in range(self._cols):
            if col < len(self._x_labels):
                cx = int(gx + (col + 0.5) * cell_w)
                lbl = self._x_labels[col]
                lw = afm.horizontalAdvance(lbl)
                p.drawText(cx - lw // 2, gy + gh + afm.height(), lbl)

        for row in range(self._rows):
            draw_row = self._rows - 1 - row
            if row < len(self._y_labels):
                cy = int(gy + (draw_row + 0.5) * cell_h + afm.ascent() // 2)
                lbl = self._y_labels[row]
                lw = afm.horizontalAdvance(lbl)
                p.drawText(gx - lw - 4, cy, lbl)

    def _draw_scale_bar(self, p, w, gy, gh):
        bx = w - _MARGIN_RIGHT + 6
        bw = _SCALE_BAR_W

        for i in range(gh):
            t = 1.0 - i / max(gh - 1, 1)
            r, g, b = _lerp_color(t)
            p.setPen(QPen(QColor(r, g, b), 1))
            p.drawLine(bx, gy + i, bx + bw, gy + i)

        p.setPen(QPen(QColor(140, 140, 140), 1))
        p.drawRect(bx, gy, bw, gh)

        lf = QFont("monospace", 8)
        p.setFont(lf)
        lfm = QFontMetrics(lf)
        p.setPen(QColor(210, 210, 210))
        for label, frac in ((f"{self._z_max:.3f}", 0.0),
                             (f"{self._z_mean:.3f}", 0.5),
                             (f"{self._z_min:.3f}", 1.0)):
            ly = int(gy + frac * gh)
            p.drawLine(bx + bw, ly, bx + bw + 4, ly)
            p.drawText(bx + bw + 6, ly + lfm.ascent() // 2, label)

    # ── tooltip ───────────────────────────────────────────────────────────────

    def mouseMoveEvent(self, event):
        if not self._data or self._cols == 0:
            return
        w, h = self.width(), self.height()
        gw = w - _MARGIN_LEFT - _MARGIN_RIGHT
        gh = h - _MARGIN_TOP - _MARGIN_BOTTOM
        mx = event.position().x() - _MARGIN_LEFT
        my = event.position().y() - _MARGIN_TOP

        if 0 <= mx < gw and 0 <= my < gh:
            col = int(mx / gw * self._cols)
            draw_row = int(my / gh * self._rows)
            row = self._rows - 1 - draw_row
            col = max(0, min(col, self._cols - 1))
            row = max(0, min(row, self._rows - 1))
            z = self._data[row][col]
            xl = self._x_labels[col] if col < len(self._x_labels) else "?"
            yl = self._y_labels[row] if row < len(self._y_labels) else "?"
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"X={xl}  Y={yl}\nZ={z:.4f} mm", self)
        else:
            QToolTip.hideText()
