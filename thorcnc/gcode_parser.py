"""
Minimaler G-Code Parser für Backplot-Visualisierung.
Gibt Toolpath-Segmente zurück: (mode, start_xyz, end_xyz)

Unterstützt:
  G0, G1        lineare Bewegungen
  G2, G3        Kreisinterpolation (I/J/K und R-Format)
  G20 / G21     Inch / Metrisch
  G90 / G91     Absolut / Inkremental
  G54–G59       Werkstück-Koordinatensysteme (werden ignoriert, nur Position)
"""

import re
import math
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

# Segment-Typen
RAPID = 0   # G0
FEED  = 1   # G1
ARC   = 2   # G2/G3 (already resolved into lines)


@dataclass
class Segment:
    kind: int               # RAPID / FEED / ARC
    points: List[Tuple[float, float, float]]  # Start + ggf. Zwischenpunkte + End
    line_num: int = 0       # Zeilennummer im G-Code


def _word(letter: str, line: str) -> Optional[float]:
    """Sucht einen G-Code-Buchstaben und gibt seinen Wert zurück."""
    m = re.search(r'(?<![A-Z])' + letter + r'([-+]?(?:\d+\.?\d*|\.\d+))',
                  line, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _arc_points(
    sx, sy, sz,      # Start
    ex, ey, ez,      # End
    i, j, k,         # Center-Offsets (relativ zum Start)
    clockwise: bool,
    steps: int = 32,
) -> List[Tuple[float, float, float]]:
    """Zerlegt einen Kreisbogen in Liniensegmente."""
    cx, cy = sx + i, sy + j

    r_start = math.sqrt((sx - cx)**2 + (sy - cy)**2)
    a_start = math.atan2(sy - cy, sx - cx)
    a_end   = math.atan2(ey - cy, ex - cx)

    if clockwise:
        if a_end >= a_start:
            a_end -= 2 * math.pi
    else:
        if a_end <= a_start:
            a_end += 2 * math.pi

    pts = []
    for n in range(steps + 1):
        t = n / steps
        a = a_start + t * (a_end - a_start)
        pts.append((cx + r_start * math.cos(a),
                    cy + r_start * math.sin(a),
                    sz + t * (ez - sz)))
    return pts


def parse_file(path: str) -> List[Segment]:
    """Parst eine G-Code-Datei und gibt Toolpath-Segmente zurück."""
    segments: List[Segment] = []

    x = y = z = 0.0
    mode     = RAPID    # aktueller Bewegungsmodus (G0)
    absolute = True
    metric   = True

    try:
        with open(path, 'r', errors='replace') as fh:
            lines = fh.readlines()
    except OSError:
        return segments

    for lineno, raw in enumerate(lines, start=1):
        # Kommentare entfernen
        line = re.sub(r'\(.*?\)', '', raw)
        line = re.sub(r';.*', '', line)
        line = line.upper().strip()
        if not line:
            continue

        # ── G-Codes ──────────────────────────────────────────────────
        for gm in re.finditer(r'G(\d+(?:\.\d+)?)', line):
            gv = float(gm.group(1))
            if   gv == 0:               mode = RAPID
            elif gv == 1:               mode = FEED
            elif gv in (2, 3):          mode = ARC + (0 if gv == 2 else 1)
            elif gv == 20:              metric = False
            elif gv == 21:              metric = True
            elif gv == 90:              absolute = True
            elif gv == 91:              absolute = False

        # ── Koordinaten ──────────────────────────────────────────────
        xw = _word('X', line)
        yw = _word('Y', line)
        zw = _word('Z', line)

        if xw is None and yw is None and zw is None:
            continue

        factor = 25.4 if not metric else 1.0

        if absolute:
            nx = xw * factor if xw is not None else x
            ny = yw * factor if yw is not None else y
            nz = zw * factor if zw is not None else z
        else:
            nx = x + (xw * factor if xw is not None else 0.0)
            ny = y + (yw * factor if yw is not None else 0.0)
            nz = z + (zw * factor if zw is not None else 0.0)

        # ── Segment erzeugen ─────────────────────────────────────────
        if mode == RAPID:
            segments.append(Segment(RAPID, [(x, y, z), (nx, ny, nz)], lineno))

        elif mode == FEED:
            segments.append(Segment(FEED, [(x, y, z), (nx, ny, nz)], lineno))

        else:
            # G2 = clockwise (mode==2), G3 = counter-clockwise (mode==3)
            clockwise = (mode == 2)
            iw = (_word('I', line) or 0.0) * factor
            jw = (_word('J', line) or 0.0) * factor
            kw = (_word('K', line) or 0.0) * factor

            rw = _word('R', line)
            if rw is not None:
                # R-Format → I/J berechnen
                rw *= factor
                dx, dy = nx - x, ny - y
                d = math.sqrt(dx*dx + dy*dy)
                if d > 1e-9:
                    h = math.sqrt(max(rw*rw - (d/2)**2, 0))
                    mx, my = (x + nx)/2, (y + ny)/2
                    px, py = -dy/d, dx/d
                    if clockwise:
                        px, py = -px, -py
                    cx = mx + h * px
                    cy = my + h * py
                    iw, jw = cx - x, cy - y

            pts = _arc_points(x, y, z, nx, ny, nz, iw, jw, kw, clockwise)
            segments.append(Segment(ARC, pts, lineno))
            # mode zurücksetzen auf letzten linearen Modus
            mode = FEED

        x, y, z = nx, ny, nz

    return segments


def bounding_box(segments: List[Segment]):
    """Gibt (min_x, max_x, min_y, max_y, min_z, max_z) zurück."""
    xs, ys, zs = [], [], []
    for seg in segments:
        for px, py, pz in seg.points:
            xs.append(px); ys.append(py); zs.append(pz)
    if not xs:
        return (0, 0, 0, 0, 0, 0)
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))
