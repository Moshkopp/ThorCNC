import os

BASE_DIR = "thorcnc/images/probe"
OUTSIDE_DIR = os.path.join(BASE_DIR, "outside")

def save_svg(path, content):
    with open(path, "w") as f:
        f.write(content)

svg_header = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">\n'
svg_footer = '</svg>\n'

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

# OUTSIDE CORNERS FIX
# corner_bl: Material is Top-Right. 
# Box: x=35..75, y=5..45. 
# Left wall: X=35, Y=5..45. Bottom wall: Y=45, X=35..75.
# Jump to (20, 60).
# Arrow to Left wall (Y=25): from (20, 25) to (35, 25)
# Arrow to Bottom wall (X=55): from (55, 60) to (55, 45)
corner_bl = f'''{svg_header}
  <rect x="35" y="5" width="40" height="40" {mat_style} />
  {start_point(50, 25)}
  {jump_line.format(x1=45, y1=30, x2=20, y2=60)}
  <g {cyan_style}>
{arrow(20, 25, 35, 25, 35, 25, 32, 22, 32, 28)}
{arrow(55, 60, 55, 45, 55, 45, 52, 48, 58, 48)}
  </g>
  {jump_line.format(x1=20, y1=60, x2=20, y2=25)}
  {jump_line.format(x1=20, y1=60, x2=55, y2=60)}
  {magenta_dot.format(cx=35, cy=25)}
  {magenta_dot.format(cx=55, cy=45)}
{svg_footer}'''
save_svg(os.path.join(OUTSIDE_DIR, "corner_bl.svg"), corner_bl)

# corner_br: Material is Top-Left. 
# Box: x=5..45, y=5..45. 
# Right wall: X=45, Y=5..45. Bottom wall: Y=45, X=5..45.
# Jump to (60, 60).
# Arrow to Right wall (Y=25): from (60, 25) to (45, 25)
# Arrow to Bottom wall (X=25): from (25, 60) to (25, 45)
corner_br = f'''{svg_header}
  <rect x="5" y="5" width="40" height="40" {mat_style} />
  {start_point(30, 25)}
  {jump_line.format(x1=35, y1=30, x2=60, y2=60)}
  <g {cyan_style}>
{arrow(60, 25, 45, 25, 45, 25, 48, 22, 48, 28)}
{arrow(25, 60, 25, 45, 25, 45, 22, 48, 28, 48)}
  </g>
  {jump_line.format(x1=60, y1=60, x2=60, y2=25)}
  {jump_line.format(x1=60, y1=60, x2=25, y2=60)}
  {magenta_dot.format(cx=45, cy=25)}
  {magenta_dot.format(cx=25, cy=45)}
{svg_footer}'''
save_svg(os.path.join(OUTSIDE_DIR, "corner_br.svg"), corner_br)

# corner_tl: Material is Bottom-Right. 
# Box: x=35..75, y=35..75. 
# Left wall: X=35, Y=35..75. Top wall: Y=35, X=35..75.
# Jump to (20, 20).
# Arrow to Left wall (Y=55): from (20, 55) to (35, 55)
# Arrow to Top wall (X=55): from (55, 20) to (55, 35)
corner_tl = f'''{svg_header}
  <rect x="35" y="35" width="40" height="40" {mat_style} />
  {start_point(50, 55)}
  {jump_line.format(x1=45, y1=50, x2=20, y2=20)}
  <g {cyan_style}>
{arrow(20, 55, 35, 55, 35, 55, 32, 52, 32, 58)}
{arrow(55, 20, 55, 35, 55, 35, 52, 32, 58, 32)}
  </g>
  {jump_line.format(x1=20, y1=20, x2=20, y2=55)}
  {jump_line.format(x1=20, y1=20, x2=55, y2=20)}
  {magenta_dot.format(cx=35, cy=55)}
  {magenta_dot.format(cx=55, cy=35)}
{svg_footer}'''
save_svg(os.path.join(OUTSIDE_DIR, "corner_tl.svg"), corner_tl)

# corner_tr: Material is Bottom-Left. 
# Box: x=5..45, y=35..75. 
# Right wall: X=45, Y=35..75. Top wall: Y=35, X=5..45.
# Jump to (60, 20).
# Arrow to Right wall (Y=55): from (60, 55) to (45, 55)
# Arrow to Top wall (X=25): from (25, 20) to (25, 35)
corner_tr = f'''{svg_header}
  <rect x="5" y="35" width="40" height="40" {mat_style} />
  {start_point(30, 55)}
  {jump_line.format(x1=35, y1=50, x2=60, y2=20)}
  <g {cyan_style}>
{arrow(60, 55, 45, 55, 45, 55, 48, 52, 48, 58)}
{arrow(25, 20, 25, 35, 25, 35, 22, 32, 28, 32)}
  </g>
  {jump_line.format(x1=60, y1=20, x2=60, y2=55)}
  {jump_line.format(x1=60, y1=20, x2=25, y2=20)}
  {magenta_dot.format(cx=45, cy=55)}
  {magenta_dot.format(cx=25, cy=35)}
{svg_footer}'''
save_svg(os.path.join(OUTSIDE_DIR, "corner_tr.svg"), corner_tr)
