import FreeCAD
from FreeCAD import Units
import datetime
import Path.Post.Utils as PostUtils
from builtins import open as pyopen

# ================= SETTINGS =================
POSTPROCESSOR_NAME = "LinuxCNC ThorCNC Post"
AUTHOR_NAME = "Moshy"  

UNITS = "G21"
UNIT_FORMAT = "mm"
UNIT_SPEED_FORMAT = "mm/min"
PRECISION = 3

PARK_X = 0
PARK_Y = 0
HOMING_AFTER_FINISH = True

LINE_START = 10
LINE_STEP = 10

OUTPUT_HEADER = True
OUTPUT_COMMENTS = True
SHOW_EDITOR = True
TOOL_LENGTH_COMP_AFTER_M6 = False  # Auf False gesetzt, da Werkzeuglänge automatisch gemessen wird
JOB_NAME_OVERRIDE = ""

PREAMBLE = """G17 G40 G49 G80 G90 """
POSTAMBLE = ""
# ===========================================

line_number = LINE_START


def emit(line: str) -> str:
    global line_number
    if not line.strip():
        return ""
    if line.startswith("("):
        return line + "\n"
    out = f"N{line_number} {line}\n"
    line_number += LINE_STEP
    return out


def sanitize(txt: str) -> str:
    if not txt:
        return ""
    return (
        txt.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
           .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue")
           .replace("ß", "ss")
    )


def collect_tools_in_order(objects):
    sequence = []
    active_tool_num = None

    def get_feed(tc):
        if hasattr(tc, "HorizFeed"):
            return float(Units.Quantity(tc.HorizFeed, FreeCAD.Units.Velocity).getValueAs("mm/min"))
        elif hasattr(tc, "FeedRate"):
            return float(Units.Quantity(tc.FeedRate, FreeCAD.Units.Velocity).getValueAs("mm/min"))
        return None

    for obj in objects:
        # Fall 1: Der User exportiert den kompletten Job
        if is_job_object(obj) and hasattr(obj, "Operations") and hasattr(obj.Operations, "Group"):
            for op in obj.Operations.Group:
                op_name = sanitize(getattr(op, "Label", getattr(op, "Name", "")))
                tc = getattr(op, "ToolController", None)

                # Werkzeug prüfen und ggf. als neuen Rüst-Schritt eintragen
                if tc and hasattr(tc, "Tool"):
                    num = getattr(tc, "ToolNumber", None)
                    if num is not None:
                        if num != active_tool_num:
                            tool = tc.Tool
                            name = sanitize(getattr(tool, "Label", getattr(tool, "Name", f"Tool_{num}")))
                            sequence.append({
                                "num": num,
                                "info": {
                                    "name": name,
                                    "dia": float(tool.Diameter.Value) if hasattr(tool, "Diameter") else None,
                                    "len": float(tool.Length.Value) if hasattr(tool, "Length") else None,
                                    "rpm": getattr(tc, "SpindleSpeed", None),
                                    "feed": get_feed(tc)
                                },
                                "ops": []
                            })
                            active_tool_num = num

                # Operationsnamen an das aktuell aktive Werkzeug anhängen
                if hasattr(op, "Path") and op_name and not op_name.lower().startswith("fixture"):
                    if sequence and op_name not in sequence[-1]["ops"]:
                        sequence[-1]["ops"].append(op_name)
            continue

        # Fall 2: Der User exportiert nur einzelne Operationen
        obj_name = sanitize(getattr(obj, "Label", getattr(obj, "Name", "")))
        
        tc = None
        if hasattr(obj, "ToolController"):
            tc = obj.ToolController
        elif hasattr(obj, "Tool") and hasattr(obj, "ToolNumber"):
            tc = obj

        # Werkzeug prüfen und ggf. wechseln
        if tc and hasattr(tc, "Tool"):
            num = getattr(tc, "ToolNumber", None)
            if num is not None:
                if num != active_tool_num:
                    tool = tc.Tool
                    name = sanitize(getattr(tool, "Label", getattr(tool, "Name", f"Tool_{num}")))
                    sequence.append({
                        "num": num,
                        "info": {
                            "name": name,
                            "dia": float(tool.Diameter.Value) if hasattr(tool, "Diameter") else None,
                            "len": float(tool.Length.Value) if hasattr(tool, "Length") else None,
                            "rpm": getattr(tc, "SpindleSpeed", None),
                            "feed": get_feed(tc)
                        },
                        "ops": []
                    })
                    active_tool_num = num

        # Operationsnamen an das aktive Werkzeug anhängen
        if hasattr(obj, "Path"):
            if obj_name and not obj_name.lower().startswith("fixture"):
                if sequence and obj_name not in sequence[-1]["ops"]:
                    sequence[-1]["ops"].append(obj_name)

    # Kosmetik: Falls ein Werkzeug wirklich mal gar keine OP haben sollte
    for item in sequence:
        if not item["ops"]:
            item["ops"].append("Manuell/Setup")

    return sequence


def find_job(objects):
    if JOB_NAME_OVERRIDE:
        return JOB_NAME_OVERRIDE
    job = find_job_object(objects)
    if job is not None:
        return getattr(job, "Label", getattr(job, "Name", "Unnamed"))
    doc = getattr(FreeCAD, "ActiveDocument", None)
    if doc is not None:
        label = getattr(doc, "Label", "")
        if label:
            return label
        name = getattr(doc, "Name", "")
        if name:
            return name
    return "Unnamed"


def is_job_object(obj):
    if obj is None:
        return False
    type_id = str(getattr(obj, "TypeId", "") or "")
    if "Path::Job" in type_id:
        return True
    if hasattr(obj, "Stock") and hasattr(obj, "Operations"):
        return True
    proxy = getattr(obj, "Proxy", None)
    if proxy is not None and "job" in proxy.__class__.__name__.lower():
        return True
    return False


def get_job_candidate_from_object(obj):
    if obj is None:
        return None
    if is_job_object(obj):
        return obj
    for attr in ["Job", "ParentJob"]:
        cand = getattr(obj, attr, None)
        if is_job_object(cand):
            return cand
    for parent in getattr(obj, "InList", []) or []:
        if is_job_object(parent):
            return parent
    return None


def find_job_object(objects):
    for o in objects:
        job = get_job_candidate_from_object(o)
        if job is not None:
            return job
    doc = getattr(FreeCAD, "ActiveDocument", None)
    if doc is not None:
        for o in getattr(doc, "Objects", []) or []:
            if is_job_object(o):
                return o
    return None


def parse_argstring(argstring):
    opts = {}
    if not argstring:
        return opts
    for token in str(argstring).replace(",", " ").split():
        if "=" not in token:
            continue
        k, v = token.split("=", 1)
        opts[k.strip().upper()] = v.strip()
    return opts


def parse_int_opt(opts, key, default):
    val = opts.get(key)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def parse_float_opt(opts, key, default):
    val = opts.get(key)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def parse_bool_opt(opts, key, default):
    val = opts.get(key)
    if val is None:
        return default
    v = str(val).strip().lower()
    if v in ["1", "true", "yes", "on"]:
        return True
    if v in ["0", "false", "no", "off"]:
        return False
    return default


def parse_str_opt(opts, key, default):
    val = opts.get(key)
    if val is None:
        return default
    return str(val)


def export(objects, filename, argstring):
    global line_number
    line_number = LINE_START

    now = datetime.datetime.now()
    opts = parse_argstring(argstring)
    
    precision_value = max(0, parse_int_opt(opts, "PRECISION", PRECISION))
    park_x = parse_float_opt(opts, "PARK_X", PARK_X)
    park_y = parse_float_opt(opts, "PARK_Y", PARK_Y)
    homing_after_finish = parse_bool_opt(opts, "HOMING_AFTER_FINISH", HOMING_AFTER_FINISH)
    tool_length_comp_after_m6 = parse_bool_opt(opts, "TOOL_LENGTH_COMP_AFTER_M6", TOOL_LENGTH_COMP_AFTER_M6)
    job_name_override = parse_str_opt(opts, "JOB_NAME", JOB_NAME_OVERRIDE).strip()

    gcode = ""

    # ---------- HEADER ----------
    if OUTPUT_HEADER:
        header_job = job_name_override if job_name_override else find_job(objects)
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        gcode += emit("(=================================)")
        gcode += emit(f"(Postprocessor: {POSTPROCESSOR_NAME})")
        gcode += emit(f"(Author:        {AUTHOR_NAME})")
        gcode += emit(f"(Exported by:   FreeCAD)")
        gcode += emit(f"(Time:          {time_str})")
        gcode += emit(f"(Job:           {header_job})")
        gcode += emit("(=================================)")

        sequence = collect_tools_in_order(objects)
        if sequence:
            gcode += emit("(========= TOOL SEQUENCE =========)")
            for step, item in enumerate(sequence, 1):
                n = item["num"]
                t = item["info"]
                ops_str = ", ".join(item["ops"])
                radius = t['dia'] / 2.0 if t['dia'] is not None else 0.0
                gcode += emit(f"G10 L1 P{n} R{radius:.3f} ({step}. T{n} {t['name']} D{t['dia']} L{t['len']} RPM{t['rpm']} F{t['feed']} | Ops: {ops_str})")
            gcode += emit("(=================================)")

    # ---------- PREAMBLE ----------
    if OUTPUT_COMMENTS:
        gcode += emit("(Begin Preamble)")
        
    for l in PREAMBLE.splitlines():
        gcode += emit(l)
    
    gcode += emit(UNITS)

    # ---------- G64 VARIABLE DEFS ----------
    gcode += emit("G64 P0.03")

    # ---------- SAFETY ----------
    gcode += emit("G53 G0 Z0")

    precision = "." + str(precision_value) + "f"
    tol = 1e-9

    last_g = None
    last_feed = None
    last_pos = {"X": None, "Y": None, "Z": None}

    pending_rapid_z = None   # buffered rapid Z-down, emitted after next XY
    active_tool_number = None
    
    current_coolant = "M9"
    target_coolant = "M9"

    canned_cycles = {"G81", "G82", "G83", "G73", "G74", "G76", "G84", "G85", "G86", "G87", "G88", "G89"}

    def emit_motion(g_cmd, axes=None, feed_val=None, extra_words=""):
        nonlocal gcode, last_g, last_feed, current_coolant, target_coolant
        if axes is None:
            axes = {}

        g_upper = str(g_cmd).upper() if g_cmd else ""
        is_cut = g_upper in ["G1", "G01", "G2", "G02", "G3", "G03"] or g_upper in canned_cycles

        if target_coolant in ["M7", "M07", "M8", "M08"] and current_coolant != target_coolant:
            if is_cut:
                gcode += emit(target_coolant)
                current_coolant = target_coolant
                
        elif target_coolant in ["M9", "M09"] and current_coolant != target_coolant:
            gcode += emit(target_coolant)
            current_coolant = target_coolant

        line = extra_words
        for ax in ["X", "Y", "Z"]:
            if ax not in axes or axes[ax] is None:
                continue
            val = axes[ax]
            if last_pos[ax] is None or abs(val - last_pos[ax]) > tol:
                line += f" {ax}{val:{precision}}"
                last_pos[ax] = val

        feed_changed = feed_val is not None and g_cmd not in ["G0", "G00"] and (last_feed is None or abs(feed_val - last_feed) > tol)
        is_motion_cmd = g_upper in ["G0", "G00", "G1", "G01", "G2", "G02", "G3", "G03"]
        
        if is_motion_cmd and not line.strip() and not feed_changed:
            return

        out = ""
        force_repeat = g_cmd in ["G2", "G02", "G3", "G03"]
        if g_cmd != last_g or force_repeat:
            out += g_cmd
            last_g = g_cmd
        out += line

        if feed_changed:
            out += f" F{int(round(feed_val))}"
            last_feed = feed_val

        if out.strip():
            gcode += emit(out)

    # ---------- PATH ----------
    source_motion_g = None
    active_canned_cycle = None
    active_plane = "G17"

    def axis_mm(cmd, axis):
        if axis not in cmd.Parameters:
            return None
        return float(Units.Quantity(cmd.Parameters[axis], FreeCAD.Units.Length).getValueAs(UNIT_FORMAT))

    for obj in objects:
        if not hasattr(obj, "Path"):
            continue

        if OUTPUT_COMMENTS:
            gcode += emit(f"(Operation: {obj.Label})")

        target_coolant = "M9"
        if hasattr(obj, "CoolantMode"):
            mode = str(obj.CoolantMode)
            if mode == "Mist":
                target_coolant = "M7"
            elif mode == "Flood":
                target_coolant = "M8"

        # Flush any leftover buffered Z and reset modal G state between operations
        if pending_rapid_z is not None:
            emit_motion("G0", {"Z": pending_rapid_z}, None)
            pending_rapid_z = None
        source_motion_g = None

        commands = obj.Path.Commands

        for idx, c in enumerate(commands):
            if c.Name.startswith("("):
                if OUTPUT_COMMENTS:
                    gcode += emit(c.Name)
                continue

            raw_g = c.Name.strip() if isinstance(c.Name, str) else c.Name
            raw_g_upper = str(raw_g).upper() if raw_g is not None else ""
            
            if raw_g_upper in ["G17", "G18", "G19"]:
                active_plane = raw_g_upper

            if active_canned_cycle and raw_g_upper == "G80":
                active_canned_cycle = None
            elif (active_canned_cycle and raw_g_upper in canned_cycles and raw_g_upper != "G80"):
                gcode += emit("G80")
                active_canned_cycle = None

            if raw_g in ["G0", "G00", "G1", "G01"]:
                source_motion_g = raw_g
                current_g = raw_g
            elif not raw_g:
                current_g = source_motion_g if source_motion_g is not None else ""
            else:
                current_g = raw_g

            hasX = "X" in c.Parameters
            hasY = "Y" in c.Parameters
            hasZ = "Z" in c.Parameters

            x_val = axis_mm(c, "X") if hasX else None
            y_val = axis_mm(c, "Y") if hasY else None
            z_val = axis_mm(c, "Z") if hasZ else None

            feed_val = None
            extra_words = ""
            
            is_arc_cmd = current_g in ["G2", "G02", "G3", "G03"]
            allowed_arc_centers = {"I", "J", "K"}
            if is_arc_cmd:
                if active_plane == "G17":
                    allowed_arc_centers = {"I", "J"}
                elif active_plane == "G18":
                    allowed_arc_centers = {"I", "K"}
                elif active_plane == "G19":
                    allowed_arc_centers = {"J", "K"}

            for k, v in c.Parameters.items():
                if k == "F":
                    sp = Units.Quantity(v, FreeCAD.Units.Velocity)
                    feed_val = float(sp.getValueAs(UNIT_SPEED_FORMAT))
                elif k in ["I", "J", "K", "R", "Q"]:
                    if is_arc_cmd and k in ["I", "J", "K"] and k not in allowed_arc_centers:
                        continue
                    try:
                        arc_val = float(Units.Quantity(v, FreeCAD.Units.Length).getValueAs(UNIT_FORMAT))
                        extra_words += f" {k}{arc_val:{precision}}"
                    except Exception:
                        try:
                            extra_words += f" {k}{float(v):{precision}}"
                        except (TypeError, ValueError):
                            extra_words += f" {k}{v}"
                elif k in ["S", "T", "H", "D"]:
                    try:
                        int_word = int(float(v))
                        extra_words += f" {k}{int_word}"
                        if k == "T":
                            active_tool_number = int_word
                            last_pos["Z"] = None  # Force Z unknown after tool change
                    except (TypeError, ValueError):
                        extra_words += f" {k}{v}"

            if current_g in ["M7", "M07", "M8", "M08", "M9", "M09"]:
                current_coolant = current_g.replace("0", "")
                target_coolant = current_coolant

            is_rapid = current_g in ["G0", "G00"]
            is_motion = current_g in ["G0", "G00", "G1", "G01", "G2", "G02", "G3", "G03"] or raw_g_upper in canned_cycles
            
            # Buffer a rapid Z-only downward move — emit it after the next XY
            if is_rapid and hasZ and not (hasX or hasY) and is_motion:
                current_z = last_pos["Z"]
                if current_z is None or z_val < current_z:
                    # Update pending rapid Z if one already exists, or set a new one
                    pending_rapid_z = z_val
                    # do NOT update last_pos here — emit_motion must do it when flushed
                    continue

            # Flush pending Z: if XY arrives, do XY first then Z
            if pending_rapid_z is not None:
                if hasX or hasY:
                    xy = {}
                    if hasX: xy["X"] = x_val
                    if hasY: xy["Y"] = y_val
                    emit_motion(current_g, xy, None, extra_words if not hasZ else "")
                    emit_motion("G0", {"Z": pending_rapid_z}, None)
                    pending_rapid_z = None
                    if hasZ:
                        emit_motion(current_g, {"Z": z_val}, feed_val)
                    continue
                elif hasZ:
                    # It's a Z-only move that was NOT buffered (e.g. G1 Z plunge or upward Z)
                    # Flush the buffered Z first, then process this Z move
                    emit_motion("G0", {"Z": pending_rapid_z}, None)
                    pending_rapid_z = None
                else:
                    # Non-XY, non-Z move (e.g. spindle cmd, coolant, or empty command)
                    # Do NOT flush Z yet! Let the non-XY command be emitted, 
                    # and keep Z buffered until XY arrives.
                    pass

            emit_motion(current_g, {"X": x_val, "Y": y_val, "Z": z_val}, feed_val, extra_words)

            if raw_g_upper in canned_cycles:
                active_canned_cycle = raw_g_upper

            if raw_g_upper in ["M6", "M06"]:
                # Machine is at G53 Z0 after tool change — Z position in WCS is unknown.
                # Force XY-first on the next move by invalidating tracked Z.
                last_pos["Z"] = None

            if (tool_length_comp_after_m6 and raw_g_upper in ["M6", "M06"] and active_tool_number is not None):
                gcode += emit(f"G43 H{active_tool_number}")

    if pending_rapid_z is not None:
        emit_motion("G0", {"Z": pending_rapid_z}, None)
        pending_rapid_z = None

    if active_canned_cycle:
        gcode += emit("G80")

    # ---------- POSTAMBLE ----------
    if OUTPUT_COMMENTS:
        gcode += emit("(End Program)")

    gcode += emit("M9")
    gcode += emit("M5")
    
    if homing_after_finish:
        gcode += emit("G53 G0 Z0")
        gcode += emit(f"G53 G0 X{park_x} Y{park_y}")
        
    gcode += emit("M30")

    for l in POSTAMBLE.splitlines():
        gcode += emit(l)

    # ---------- WRITE ----------
    if FreeCAD.GuiUp and SHOW_EDITOR:
        dia = PostUtils.GCodeEditorDialog()
        dia.editor.setText(gcode)
        if dia.exec_():
            gcode = dia.editor.toPlainText()

    if filename != "-":
        with pyopen(filename, "w") as f:
            f.write(gcode)

    return gcode
