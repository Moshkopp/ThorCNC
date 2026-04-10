import os
import json

class SettingsManager:
    """Manages persistent GUI settings using a JSON file."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.prefs = {}
        self.is_new = not os.path.exists(filepath)
        self.load()

    def load(self):
        if not self.is_new:
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    self.prefs = json.load(f)
            except Exception as e:
                print(f"Error loading settings {self.filepath}: {e}")
                self.prefs = {}
        else:
            self.prefs = {}

    def get(self, key: str, default=None):
        return self.prefs.get(key, default)

    def set(self, key: str, value):
        self.prefs[key] = value

    def save(self):
        try:
            # Ensure the directory exists
            os.makedirs(os.path.dirname(os.path.abspath(self.filepath)), exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.prefs, f, indent=4)
        except Exception as e:
            print(f"Error saving settings in {self.filepath}: {e}")
