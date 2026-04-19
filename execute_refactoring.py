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

    # 1. Fix plunge depth for ALL inside routines
    if fname.startswith("inside_") or fname.startswith("center_"):
        # We need to make sure we don't replace Z-[#8] if it's already Z-[#<rad> + #8]
        # But currently it is Z-[#8]
        content = re.sub(r'G1 Z-\[#8\](.*)', r'G1 Z-[#<rad> + #8]\1', content)

    # 2. Fix Outside jumps (Remove #1 and #2)
    if fname.startswith("outside_edge_") or fname.startswith("outside_corner_"):
        content = content.replace("- #1 - #12", "- #12")
        content = content.replace("+ #1 + #12", "+ #12")
        content = content.replace("- #2 - #12", "- #12")
        content = content.replace("+ #2 + #12", "+ #12")

    # 3. Fix Z-Retract order for ALL Edge and Corner routines
    if ("edge_" in fname or "corner_" in fname) and not fname.startswith("center_"):
        # Extract the Z retract line at the very end
        # It usually looks like: G1 Z#7 F#11 or G1 Z#7 F#<rapid>
        # Let's find it. It should be right before the endsub.
        z_match = re.search(r'([ \t]*G1 Z#7 F#[^\n]*\n)(?=[ \t]*O<\w+>[ \t]*endsub)', content)
        if z_match:
            z_line = z_match.group(1)
            # Remove it from the end
            content = content.replace(z_line, "")
            
            # Now insert it before the final X/Y move.
            # The final X/Y move is usually: G1 X#<x_wall> F... or G1 X#<x_corner> Y#<y_corner> F...
            # We can find this by looking for the assignment of #<x_wall>, #<y_wall>, or #<y_corner>
            
            # Pattern 1: X wall
            content = re.sub(r'(#<x_wall>[ \t]*=[ \t]*\[.*?\]\n)', r'\1' + z_line, content)
            
            # Pattern 2: Y wall
            content = re.sub(r'(#<y_wall>[ \t]*=[ \t]*\[.*?\]\n)', r'\1' + z_line, content)
            
            # Pattern 3: Corners (insert after y_corner assignment)
            content = re.sub(r'(#<y_corner>[ \t]*=[ \t]*\[.*?\]\n)', r'\1' + z_line, content)

    if content != orig:
        with open(filepath, "w") as f:
            f.write(content)
        print(f"Refactored {fname}")
