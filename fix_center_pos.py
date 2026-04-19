import os

DIR = "/home/moshy/linuxcnc/dev/ThorCNC/configs/sim/subroutines/probing"

for fname in os.listdir(DIR):
    if not fname.endswith(".ngc"):
        continue
    
    filepath = os.path.join(DIR, fname)
    with open(filepath, "r") as f:
        content = f.read()
        
    orig_content = content

    # Replace incorrectly used probe result variables with current position variables
    content = content.replace("#<center_x> = #5061", "#<center_x> = #5420")
    content = content.replace("#<center_y> = #5062", "#<center_y> = #5421")

    if content != orig_content:
        with open(filepath, "w") as f:
            f.write(content)
        print(f"Fixed {fname}")
