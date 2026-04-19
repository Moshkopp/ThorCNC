import os

DIR = "/home/moshy/linuxcnc/dev/ThorCNC/configs/sim/subroutines/probing"

for fname in os.listdir(DIR):
    if not fname.startswith("inside_") or not fname.endswith(".ngc"):
        continue
    
    filepath = os.path.join(DIR, fname)
    with open(filepath, "r") as f:
        content = f.read()
        
    orig_content = content

    if fname == "inside_round.ngc":
        content = content.replace("G38.2 X-[#3] F#5", "G38.2 X-[[#1 / 2] + #3] F#5")
        content = content.replace("G38.2 X#3 F#5", "G38.2 X[[#1 / 2] + #3] F#5")
        content = content.replace("G38.2 Y-[#3] F#5", "G38.2 Y-[[#1 / 2] + #3] F#5")
        content = content.replace("G38.2 Y#3 F#5", "G38.2 Y[[#1 / 2] + #3] F#5")
    
    elif fname == "inside_rect_x.ngc":
        content = content.replace("G38.2 X-[#3] F#5", "G38.2 X-[[#1 / 2] + #3] F#5")
        content = content.replace("G38.2 X#3 F#5", "G38.2 X[[#1 / 2] + #3] F#5")
        
    elif fname == "inside_rect_y.ngc":
        content = content.replace("G38.2 Y-[#3] F#5", "G38.2 Y-[[#2 / 2] + #3] F#5")
        content = content.replace("G38.2 Y#3 F#5", "G38.2 Y[[#2 / 2] + #3] F#5")
        
    elif fname.startswith("inside_edge_") or fname.startswith("inside_corner_"):
        content = content.replace("G38.2 X-[#3] F#5", "G38.2 X-[#12 + #3] F#5")
        content = content.replace("G38.2 X#3 F#5", "G38.2 X[#12 + #3] F#5")
        content = content.replace("G38.2 Y-[#3] F#5", "G38.2 Y-[#12 + #3] F#5")
        content = content.replace("G38.2 Y#3 F#5", "G38.2 Y[#12 + #3] F#5")

    if content != orig_content:
        with open(filepath, "w") as f:
            f.write(content)
        print(f"Fixed {fname}")
