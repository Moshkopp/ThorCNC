import os

BASE_DIR = "thorcnc/images/probe"
INSIDE_DIR = os.path.join(BASE_DIR, "inside")
CENTER_DIR = os.path.join(BASE_DIR, "center_finder")

os.makedirs(INSIDE_DIR, exist_ok=True)
os.makedirs(CENTER_DIR, exist_ok=True)

def save_svg(path, content):
    with open(path, "w") as f:
        f.write(content)

# Common SVG elements
svg_header = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">\n'
svg_footer = '</svg>\n'

# Styles
mat_style = 'fill="#4a4a4a" stroke="#333" stroke-width="1"'
pocket_style = 'fill="#1a1a1a" stroke="#000" stroke-width="1.5"'
green_style = 'stroke="#00ff00" stroke-width="1.5" fill="none"'
cyan_style = 'stroke="#00ffff" stroke-width="1.5" fill="none"'
magenta_dot = '<circle cx="{cx}" cy="{cy}" r="3" fill="#ff00ff" stroke="none" />'
jump_line = '<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#00ff00" stroke-width="1.5" stroke-dasharray="3,3" />'

def start_point(cx, cy):
    return f'''  <g {green_style}>
    <line x1="{cx-5}" y1="{cy}" x2="{cx+5}" y2="{cy}" />
    <line x1="{cx}" y1="{cy-5}" x2="{cx}" y2="{cy+5}" />
    <circle cx="{cx}" cy="{cy}" r="5" />
  </g>'''

def arrow(x1, y1, x2, y2, head_x, head_y, hx1, hy1, hx2, hy2):
    return f'''    <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" />
    <polyline points="{hx1},{hy1} {head_x},{head_y} {hx2},{hy2}" />'''

# 1. Center Finder - inside_round (Start Left, Jump Center, Probe all 4)
inside_round = f'''{svg_header}
  <rect x="5" y="5" width="70" height="70" {mat_style} rx="2" />
  <circle cx="50" cy="40" r="22" {pocket_style} />
  {start_point(15, 40)}
  {jump_line.format(x1=20, y1=40, x2=50, y2=40)}
  <g {cyan_style}>
{arrow(50, 40, 31, 40, 31, 40, 34, 37, 34, 43)}
{arrow(50, 40, 69, 40, 69, 40, 66, 37, 66, 43)}
{arrow(50, 40, 50, 21, 50, 21, 47, 24, 53, 24)}
{arrow(50, 40, 50, 59, 50, 59, 47, 56, 53, 56)}
  </g>
  {magenta_dot.format(cx=50, cy=40)}
{svg_footer}'''
save_svg(os.path.join(CENTER_DIR, "inside_round.svg"), inside_round)

# 2. Center Finder - inside_rect_x (Start Left, Jump Center, Probe Left/Right)
inside_rect_x = f'''{svg_header}
  <rect x="5" y="5" width="70" height="70" {mat_style} rx="2" />
  <rect x="35" y="15" width="30" height="50" {pocket_style} rx="2" />
  {start_point(15, 40)}
  {jump_line.format(x1=20, y1=40, x2=50, y2=40)}
  <g {cyan_style}>
{arrow(50, 40, 38, 40, 38, 40, 41, 37, 41, 43)}
{arrow(50, 40, 62, 40, 62, 40, 59, 37, 59, 43)}
  </g>
  {magenta_dot.format(cx=50, cy=40)}
{svg_footer}'''
save_svg(os.path.join(CENTER_DIR, "inside_rect_x.svg"), inside_rect_x)

# 3. Center Finder - inside_rect_y (Start Bottom, Jump Center, Probe Top/Bottom)
inside_rect_y = f'''{svg_header}
  <rect x="5" y="5" width="70" height="70" {mat_style} rx="2" />
  <rect x="15" y="35" width="50" height="30" {pocket_style} rx="2" />
  {start_point(40, 75)}
  {jump_line.format(x1=40, y1=70, x2=40, y2=50)}
  <g {cyan_style}>
{arrow(40, 50, 40, 38, 40, 38, 37, 41, 43, 41)}
{arrow(40, 50, 40, 62, 40, 62, 37, 59, 43, 59)}
  </g>
  {magenta_dot.format(cx=40, cy=50)}
{svg_footer}'''
save_svg(os.path.join(CENTER_DIR, "inside_rect_y.svg"), inside_rect_y)

# INSIDE EDGES
# edge_left: Pocket is right of the wall. Wall is left. So material is LEFT.
edge_left = f'''{svg_header}
  <rect x="5" y="5" width="25" height="70" {mat_style} />
  <rect x="30" y="5" width="45" height="70" {pocket_style} />
  {start_point(15, 40)}
  {jump_line.format(x1=20, y1=40, x2=45, y2=40)}
  <g {cyan_style}>
{arrow(45, 40, 33, 40, 33, 40, 36, 37, 36, 43)}
  </g>
  {magenta_dot.format(cx=45, cy=40)}
{svg_footer}'''
save_svg(os.path.join(INSIDE_DIR, "edge_left.svg"), edge_left)

# edge_right: Material is RIGHT.
edge_right = f'''{svg_header}
  <rect x="50" y="5" width="25" height="70" {mat_style} />
  <rect x="5" y="5" width="45" height="70" {pocket_style} />
  {start_point(65, 40)}
  {jump_line.format(x1=60, y1=40, x2=35, y2=40)}
  <g {cyan_style}>
{arrow(35, 40, 47, 40, 47, 40, 44, 37, 44, 43)}
  </g>
  {magenta_dot.format(cx=35, cy=40)}
{svg_footer}'''
save_svg(os.path.join(INSIDE_DIR, "edge_right.svg"), edge_right)

# edge_top: Material is TOP.
edge_top = f'''{svg_header}
  <rect x="5" y="5" width="70" height="25" {mat_style} />
  <rect x="5" y="30" width="70" height="45" {pocket_style} />
  {start_point(40, 15)}
  {jump_line.format(x1=40, y1=20, x2=40, y2=45)}
  <g {cyan_style}>
{arrow(40, 45, 40, 33, 40, 33, 37, 36, 43, 36)}
  </g>
  {magenta_dot.format(cx=40, cy=45)}
{svg_footer}'''
save_svg(os.path.join(INSIDE_DIR, "edge_top.svg"), edge_top)

# edge_bottom: Material is BOTTOM.
edge_bottom = f'''{svg_header}
  <rect x="5" y="50" width="70" height="25" {mat_style} />
  <rect x="5" y="5" width="70" height="45" {pocket_style} />
  {start_point(40, 65)}
  {jump_line.format(x1=40, y1=60, x2=40, y2=35)}
  <g {cyan_style}>
{arrow(40, 35, 40, 47, 40, 47, 37, 44, 43, 44)}
  </g>
  {magenta_dot.format(cx=40, cy=35)}
{svg_footer}'''
save_svg(os.path.join(INSIDE_DIR, "edge_bottom.svg"), edge_bottom)

# INSIDE CORNERS
# corner_bl: Pocket is TR. Material is BL.
corner_bl = f'''{svg_header}
  <path d="M5,75 L75,75 L75,50 L30,50 L30,5 L5,5 Z" {mat_style} />
  <rect x="30" y="5" width="45" height="45" {pocket_style} />
  {start_point(15, 65)}
  {jump_line.format(x1=20, y1=60, x2=45, y2=35)}
  <g {cyan_style}>
{arrow(45, 35, 33, 35, 33, 35, 36, 32, 36, 38)}
{arrow(45, 35, 45, 47, 45, 47, 42, 44, 48, 44)}
  </g>
  {magenta_dot.format(cx=45, cy=35)}
{svg_footer}'''
save_svg(os.path.join(INSIDE_DIR, "corner_bl.svg"), corner_bl)

# corner_br: Pocket is TL. Material is BR.
corner_br = f'''{svg_header}
  <path d="M5,75 L75,75 L75,5 L50,5 L50,50 L5,50 Z" {mat_style} />
  <rect x="5" y="5" width="45" height="45" {pocket_style} />
  {start_point(65, 65)}
  {jump_line.format(x1=60, y1=60, x2=35, y2=35)}
  <g {cyan_style}>
{arrow(35, 35, 47, 35, 47, 35, 44, 32, 44, 38)}
{arrow(35, 35, 35, 47, 35, 47, 32, 44, 38, 44)}
  </g>
  {magenta_dot.format(cx=35, cy=35)}
{svg_footer}'''
save_svg(os.path.join(INSIDE_DIR, "corner_br.svg"), corner_br)

# corner_tl: Pocket is BR. Material is TL.
corner_tl = f'''{svg_header}
  <path d="M5,5 L75,5 L75,30 L30,30 L30,75 L5,75 Z" {mat_style} />
  <rect x="30" y="30" width="45" height="45" {pocket_style} />
  {start_point(15, 15)}
  {jump_line.format(x1=20, y1=20, x2=45, y2=45)}
  <g {cyan_style}>
{arrow(45, 45, 33, 45, 33, 45, 36, 42, 36, 48)}
{arrow(45, 45, 45, 33, 45, 33, 42, 36, 48, 36)}
  </g>
  {magenta_dot.format(cx=45, cy=45)}
{svg_footer}'''
save_svg(os.path.join(INSIDE_DIR, "corner_tl.svg"), corner_tl)

# corner_tr: Pocket is BL. Material is TR.
corner_tr = f'''{svg_header}
  <path d="M75,5 L5,5 L5,30 L50,30 L50,75 L75,75 Z" {mat_style} />
  <rect x="5" y="30" width="45" height="45" {pocket_style} />
  {start_point(65, 15)}
  {jump_line.format(x1=60, y1=20, x2=35, y2=45)}
  <g {cyan_style}>
{arrow(35, 45, 47, 45, 47, 45, 44, 42, 44, 48)}
{arrow(35, 45, 35, 33, 35, 33, 32, 36, 38, 36)}
  </g>
  {magenta_dot.format(cx=35, cy=45)}
{svg_footer}'''
save_svg(os.path.join(INSIDE_DIR, "corner_tr.svg"), corner_tr)
