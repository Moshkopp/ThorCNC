import os
import re

DIR = "/home/moshy/linuxcnc/dev/ThorCNC/configs/sim/subroutines/probing"

for fname in os.listdir(DIR):
    if not fname.endswith(".ngc"):
        continue
    filepath = os.path.join(DIR, fname)
    with open(filepath, "r") as f:
        content = f.read()
    orig = content

    if ("edge_" in fname or "corner_" in fname) and not fname.startswith("center_"):
        # We need to find the Z retract block anywhere after the x_wall/y_wall assignments
        
        # 1. Find the Z retract line
        # It's usually "G1 Z#7 F#11" or "G1 Z#7 F#<rapid>"
        z_matches = re.findall(r'([ \t]*G1 Z#7 F#[^\n]*\n)', content)
        if z_matches:
            # We want the LAST one (which is the retract at the end)
            # Actually, there's also the Z retract AFTER the Z-probe at the very beginning!
            # "G1 Z#7 F#11 ( Move to Z Clearance )"
            # So the last one is the one at the end of the file.
            z_line = z_matches[-1]
            
            # Remove ONLY the last occurrence
            # We can split by this string and join
            parts = content.rsplit(z_line, 1)
            if len(parts) == 2:
                content = parts[0] + parts[1]
                
                # Now insert it right after the #<x_wall>, #<y_wall>, or #<x_corner> / #<y_corner> assignments.
                # For corners, there are two assignments, we want to insert after the second one (#<y_corner>).
                
                if "#<y_corner>" in content:
                    content = re.sub(r'(#<y_corner>[ \t]*=[ \t]*\[.*?\]\n)', r'\1' + z_line, content)
                elif "#<y_wall>" in content:
                    content = re.sub(r'(#<y_wall>[ \t]*=[ \t]*\[.*?\]\n)', r'\1' + z_line, content)
                elif "#<x_wall>" in content:
                    content = re.sub(r'(#<x_wall>[ \t]*=[ \t]*\[.*?\]\n)', r'\1' + z_line, content)

    if content != orig:
        with open(filepath, "w") as f:
            f.write(content)
        print(f"Fixed retract in {fname}")
