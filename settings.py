"""User settings for Macro Goblin, stored as JSON in the data folder.

Unknown keys are ignored and missing keys fall back to defaults, so old settings
files keep working after an update.
"""

import json
import os

import lol_coach

DEFAULTS = {
    "voice": True,
    "voice_name": "",          # "" = Windows default (Zira if installed)
    "voice_rate": 1,           # -10..10, System.Speech scale
    "voice_volume": 100,       # 0..100
    "overlay": True,
    "capture": True,           # record matches locally for replays and tuning
    "web": False,              # second-screen dashboard on 127.0.0.1:8765
    "summoner": "",            # only needed if auto-detect fails
    "cs_target": 8.0,
    "start_with_windows": False,
    "check_updates": True,
    "first_run_done": False,
}


def path():
    return lol_coach.data_path("settings.json")


def load():
    data = dict(DEFAULTS)
    try:
        with open(path(), encoding="utf-8") as handle:
            saved = json.load(handle)
        if isinstance(saved, dict):
            for key, value in saved.items():
                if key in DEFAULTS and isinstance(value, type(DEFAULTS[key])) or (
                    key in DEFAULTS and isinstance(DEFAULTS[key], float) and isinstance(value, (int, float))
                ):
                    data[key] = value
    except (OSError, ValueError):
        pass
    data["voice_rate"] = max(-10, min(10, int(data["voice_rate"])))
    data["voice_volume"] = max(0, min(100, int(data["voice_volume"])))
    data["cs_target"] = max(3.0, min(12.0, float(data["cs_target"])))
    return data


def save(data):
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    clean = {key: data.get(key, value) for key, value in DEFAULTS.items()}
    tmp = path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(clean, handle, indent=2)
    os.replace(tmp, path())
    return clean
