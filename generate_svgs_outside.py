import os

BASE_DIR = "thorcnc/images/probe"
OUTSIDE_DIR = os.path.join(BASE_DIR, "outside")
CENTER_DIR = os.path.join(BASE_DIR, "center_finder")

os.makedirs(OUTSIDE_DIR, exist_ok=True)
os.makedirs(CENTER_DIR, exist_ok=True)

def save_svg(path, content):
    with open(path, "w") as f:
        f.write(content)

# Common SVG elements
svg_header = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">\n'
svg_footer = '</svg>\n'

# Styles
mat_style = 'fill="#4a4a4a" stroke="#333" stroke-width="1"'
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

# 1. Center Finder - center_round (Outside Boss)
center_round = f'''{svg_header}
  <circle cx="40" cy="40" r="22" {mat_style} />
  {start_point(40, 40)}
  {jump_line.format(x1=40, y1=40, x2=10, y2=40)}
  {jump_line.format(x1=40, y1=40, x2=70, y2=40)}
  {jump_line.format(x1=40, y1=40, x2=40, y2=10)}
  {jump_line.format(x1=40, y1=40, x2=40, y2=70)}
  <g {cyan_style}>
{arrow(10, 40, 18, 40, 18, 40, 15, 37, 15, 43)}
{arrow(70, 40, 62, 40, 62, 40, 65, 37, 65, 43)}
{arrow(40, 10, 40, 18, 40, 18, 37, 15, 43, 15)}
{arrow(40, 70, 40, 62, 40, 62, 37, 65, 43, 65)}
  </g>
  {magenta_dot.format(cx=10, cy=40)}
  {magenta_dot.format(cx=70, cy=40)}
  {magenta_dot.format(cx=40, cy=10)}
  {magenta_dot.format(cx=40, cy=70)}
{svg_footer}'''
save_svg(os.path.join(CENTER_DIR, "center_round.svg"), center_round)

# 2. Center Finder - center_rect_x (Outside Rect X)
center_rect_x = f'''{svg_header}
  <rect x="25" y="15" width="30" height="50" {mat_style} rx="2" />
  {start_point(40, 40)}
  {jump_line.format(x1=40, y1=40, x2=10, y2=40)}
  {jump_line.format(x1=40, y1=40, x2=70, y2=40)}
  <g {cyan_style}>
{arrow(10, 40, 25, 40, 25, 40, 22, 37, 22, 43)}
{arrow(70, 40, 55, 40, 55, 40, 58, 37, 58, 43)}
  </g>
  {magenta_dot.format(cx=10, cy=40)}
  {magenta_dot.format(cx=70, cy=40)}
{svg_footer}'''
save_svg(os.path.join(CENTER_DIR, "center_rect_x.svg"), center_rect_x)

# 3. Center Finder - center_rect_y (Outside Rect Y)
center_rect_y = f'''{svg_header}
  <rect x="15" y="25" width="50" height="30" {mat_style} rx="2" />
  {start_point(40, 40)}
  {jump_line.format(x1=40, y1=40, x2=40, y2=10)}
  {jump_line.format(x1=40, y1=40, x2=40, y2=70)}
  <g {cyan_style}>
{arrow(40, 10, 40, 25, 40, 25, 37, 22, 43, 22)}
{arrow(40, 70, 40, 55, 40, 55, 37, 58, 43, 58)}
  </g>
  {magenta_dot.format(cx=40, cy=10)}
  {magenta_dot.format(cx=40, cy=70)}
{svg_footer}'''
save_svg(os.path.join(CENTER_DIR, "center_rect_y.svg"), center_rect_y)

# OUTSIDE EDGES
# edge_left: Left edge of material. Material is on the RIGHT.
edge_left = f'''{svg_header}
  <rect x="35" y="5" width="40" height="70" {mat_style} />
  {start_point(50, 40)}
  {jump_line.format(x1=45, y1=40, x2=20, y2=40)}
  <g {cyan_style}>
{arrow(20, 40, 35, 40, 35, 40, 32, 37, 32, 43)}
  </g>
  {magenta_dot.format(cx=20, cy=40)}
{svg_footer}'''
save_svg(os.path.join(OUTSIDE_DIR, "edge_left.svg"), edge_left)

# edge_right: Right edge of material. Material is on the LEFT.
edge_right = f'''{svg_header}
  <rect x="5" y="5" width="40" height="70" {mat_style} />
  {start_point(30, 40)}
  {jump_line.format(x1=35, y1=40, x2=60, y2=40)}
  <g {cyan_style}>
{arrow(60, 40, 45, 40, 45, 40, 48, 37, 48, 43)}
  </g>
  {magenta_dot.format(cx=60, cy=40)}
{svg_footer}'''
save_svg(os.path.join(OUTSIDE_DIR, "edge_right.svg"), edge_right)

# edge_top: Top edge of material. Material is on the BOTTOM.
edge_top = f'''{svg_header}
  <rect x="5" y="35" width="70" height="40" {mat_style} />
  {start_point(40, 50)}
  {jump_line.format(x1=40, y1=45, x2=40, y2=20)}
  <g {cyan_style}>
{arrow(40, 20, 40, 35, 40, 35, 37, 32, 43, 32)}
  </g>
  {magenta_dot.format(cx=40, cy=20)}
{svg_footer}'''
save_svg(os.path.join(OUTSIDE_DIR, "edge_top.svg"), edge_top)

# edge_bottom: Bottom edge of material. Material is on the TOP.
edge_bottom = f'''{svg_header}
  <rect x="5" y="5" width="70" height="40" {mat_style} />
  {start_point(40, 30)}
  {jump_line.format(x1=40, y1=35, x2=40, y2=60)}
  <g {cyan_style}>
{arrow(40, 60, 40, 45, 40, 45, 37, 48, 43, 48)}
  </g>
  {magenta_dot.format(cx=40, cy=60)}
{svg_footer}'''
save_svg(os.path.join(OUTSIDE_DIR, "edge_bottom.svg"), edge_bottom)

# OUTSIDE CORNERS
# corner_bl: Bottom-Left corner of material. Material is Top-Right.
corner_bl = f'''{svg_header}
  <rect x="35" y="5" width="40" height="40" {mat_style} />
  {start_point(50, 20)}
  {jump_line.format(x1=45, y1=25, x2=20, y2=60)}
  <g {cyan_style}>
{arrow(20, 60, 35, 60, 35, 60, 32, 57, 32, 63)}
{arrow(20, 60, 20, 45, 20, 45, 17, 48, 23, 48)}
  </g>
  {magenta_dot.format(cx=20, cy=60)}
{svg_footer}'''
save_svg(os.path.join(OUTSIDE_DIR, "corner_bl.svg"), corner_bl)

# corner_br: Bottom-Right corner of material. Material is Top-Left.
corner_br = f'''{svg_header}
  <rect x="5" y="5" width="40" height="40" {mat_style} />
  {start_point(30, 20)}
  {jump_line.format(x1=35, y1=25, x2=60, y2=60)}
  <g {cyan_style}>
{arrow(60, 60, 45, 60, 45, 60, 48, 57, 48, 63)}
{arrow(60, 60, 60, 45, 60, 45, 57, 48, 63, 48)}
  </g>
  {magenta_dot.format(cx=60, cy=60)}
{svg_footer}'''
save_svg(os.path.join(OUTSIDE_DIR, "corner_br.svg"), corner_br)

# corner_tl: Top-Left corner of material. Material is Bottom-Right.
corner_tl = f'''{svg_header}
  <rect x="35" y="35" width="40" height="40" {mat_style} />
  {start_point(50, 50)}
  {jump_line.format(x1=45, y1=45, x2=20, y2=20)}
  <g {cyan_style}>
{arrow(20, 20, 35, 20, 35, 20, 32, 17, 32, 23)}
{arrow(20, 20, 20, 35, 20, 35, 17, 32, 23, 32)}
  </g>
  {magenta_dot.format(cx=20, cy=20)}
{svg_footer}'''
save_svg(os.path.join(OUTSIDE_DIR, "corner_tl.svg"), corner_tl)

# corner_tr: Top-Right corner of material. Material is Bottom-Left.
corner_tr = f'''{svg_header}
  <rect x="5" y="35" width="40" height="40" {mat_style} />
  {start_point(30, 50)}
  {jump_line.format(x1=35, y1=45, x2=60, y2=20)}
  <g {cyan_style}>
{arrow(60, 20, 45, 20, 45, 20, 48, 17, 48, 23)}
{arrow(60, 20, 60, 35, 60, 35, 57, 32, 63, 32)}
  </g>
  {magenta_dot.format(cx=60, cy=20)}
{svg_footer}'''
save_svg(os.path.join(OUTSIDE_DIR, "corner_tr.svg"), corner_tr)
