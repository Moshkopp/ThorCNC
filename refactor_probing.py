import os

DIR = "/home/moshy/linuxcnc/dev/ThorCNC/configs/sim/subroutines/probing"

def fix_z_retract(content):
    # Find the dangerous block
    # It usually looks like:
    # G1 X#<x_wall> F#...
    # O102 if [#9 GT 0.5]
    #     G10 L20 P0 X0
    # O102 endif
    # G1 Z#7 F#...
    
    # Or for corners:
    # G1 X#<x_corner> Y#<y_corner> F#...
    
    import re
    
    # We want to move G1 Z#7 F#... to be right after the #<...> = ... calculations
    # and before G1 X... Y... F...
    
    # Look for the section ( Move to Edge & Zero ) or ( Move to Corner & Zero )
    # or ( Final Positioning & Zeroing )
    
    # Let's just do targeted string replacements for the known structures.
    # It's safer to do this manually per pattern.
    pass

for fname in os.listdir(DIR):
    if not fname.endswith(".ngc"):
        continue
    filepath = os.path.join(DIR, fname)
    with open(filepath, "r") as f:
        content = f.read()
    orig = content

    # 1. Fix Outside Jumps (Remove #1 and #2 from jumps in outside_edge and outside_corner)
    if fname.startswith("outside_edge_") or fname.startswith("outside_corner_"):
        content = content.replace("- #1 - #12", "- #12")
        content = content.replace("+ #1 + #12", "+ #12")
        content = content.replace("- #2 - #12", "- #12")
        content = content.replace("+ #2 + #12", "+ #12")

    # 2. Fix Z Retract Order
    # Find the G1 Z#7 F... line
    import re
    # Match G1 Z#7 F#11 or F#<rapid> at the end
    z_retract_match = re.search(r'([ \t]*G1 Z#7 F#(?:\d+|<rapid>)[ \t]*\n)', content)
    if z_retract_match:
        z_line = z_retract_match.group(1)
        # Remove it from the end
        content = content.replace(z_line, "")
        
        # Now insert it right after the #<x_wall> or #<y_wall> or #<x_corner> calculations
        # and before G1 X#<x_wall> or G1 X#<x_corner>
        
        # Edge X
        content = re.sub(r'(#<x_wall> = \[[^\]]+\]\n)', r'\1' + z_line, content)
        # Edge Y
        content = re.sub(r'(#<y_wall> = \[[^\]]+\]\n)', r'\1' + z_line, content)
        # Corner X/Y (insert after #<y_corner>)
        content = re.sub(r'(#<y_corner> = \[[^\]]+\]\n)', r'\1' + z_line, content)
        # Inside Pocket X/Y (insert after #<y_center> or #<x_center> if it's rect_x)
        # Actually for inside_round and inside_rect, it's safe to move X/Y then Z.
        # But for consistency, let's retract Z first for EVERYTHING except center finding?
        # Wait, if we retract Z first for inside pockets, we might crash into the top of the pocket if there's an overhang!
        # Usually for pockets, moving to center while down is safer.
        # Let's ONLY fix Z retract for edges and corners!
        
    if (fname.startswith("inside_edge_") or fname.startswith("inside_corner_") or 
        fname.startswith("outside_edge_") or fname.startswith("outside_corner_")):
        
        # We need to re-apply carefully if we messed up.
        # Let's do it robustly:
        pass

# Actually, the regex approach above might be slightly risky if it matches multiple times.
