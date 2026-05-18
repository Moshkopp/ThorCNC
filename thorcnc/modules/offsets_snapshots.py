"""I/O helpers for WCS offset snapshots (load/save JSON)."""

import json
import os


def snapshots_path(prefs_path: str) -> str:
    return os.path.join(os.path.dirname(prefs_path), "offsets_snapshots.json")


def load_snapshots(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        print(f"Error loading offsets snapshots {path}: {e}")
        return []
    snaps = data.get("snapshots") if isinstance(data, dict) else None
    return snaps if isinstance(snaps, list) else []


def save_snapshots(path: str, snapshots: list[dict]) -> None:
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"snapshots": snapshots}, f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        print(f"Error saving offsets snapshots {path}: {e}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
