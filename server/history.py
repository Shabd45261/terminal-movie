import json
import os
import threading

HISTORY_FILE = "history.json"

class HistoryManager:
    def __init__(self):
        self.lock = threading.Lock()
        self._load()

    def _load(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {"movies": [], "series": []}
        else:
            self.data = {"movies": [], "series": []}

    def _save(self):
        with open(HISTORY_FILE, "w") as f:
            json.dump(self.data, f, indent=2)

    def save_progress(self, item, time, season=0, episode=0):
        with self.lock:
            kind = "series" if item.get("type") == "series" else "movies"
            history = self.data[kind]

            # Find existing entry
            entry = next((i for i in history if i["id"] == item["id"]), None)
            if entry:
                history.remove(entry)
            else:
                entry = {
                    "id": item["id"],
                    "title": item["title"],
                    "poster": item.get("poster"),
                    "blurHash": item.get("blurHash"),
                    "detailPath": item["detailPath"],
                    "type": item["type"]
                }

            entry["time"] = time
            if kind == "series":
                entry["se"] = season
                entry["ep"] = episode

            # Insert at the beginning (most recent)
            history.insert(0, entry)

            # Keep only last 10
            self.data[kind] = history[:10]
            self._save()

    def get_history(self):
        with self.lock:
            return self.data
