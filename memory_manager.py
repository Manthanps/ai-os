import json
import os
from collections import Counter


MEMORY_PATH = os.path.join(os.path.dirname(__file__), "memory.json")


def _load_memory():
    if os.path.exists(MEMORY_PATH):
        try:
            with open(MEMORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _save_memory(data):
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def save_event(event_type, value):
    data = _load_memory()
    events = data.get("events", [])
    events.append({"type": event_type, "value": value})
    data["events"] = events[-200:]

    if event_type == "user":
        data["username"] = value
    if event_type == "project":
        data["last_project"] = value
    if event_type == "app":
        apps = data.get("frequent_apps", [])
        apps.append(value)
        data["frequent_apps"] = apps[-200:]
    if event_type == "search":
        searches = data.get("recent_searches", [])
        searches.append(value)
        data["recent_searches"] = searches[-200:]

    _save_memory(data)


def get_last_project():
    data = _load_memory()
    return data.get("last_project")


def get_frequent_apps(limit=5):
    data = _load_memory()
    apps = data.get("frequent_apps", [])
    if not apps:
        return []
    counts = Counter(apps)
    return [name for name, _ in counts.most_common(limit)]


def recall_context():
    data = _load_memory()
    return {
        "username": data.get("username"),
        "last_project": data.get("last_project"),
        "frequent_apps": get_frequent_apps(),
        "recent_searches": data.get("recent_searches", [])[-5:],
    }
