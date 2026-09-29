#!/usr/bin/env python3
"""
Macro Goblin - a live, voice-first League of Legends macro companion.

Data source (read-only, Riot-sanctioned, localhost only):
  https://127.0.0.1:2999/liveclientdata/allgamedata
Static data: Data Dragon. No memory reads, no injection, no packet capture.

Usage
  python lol_coach.py                     # live game, voice
  python lol_coach.py --overlay           # voice + click-through overlay
  python lol_coach.py --demo --speed 20   # simulated game
  python lol_coach.py --capture           # write raw polls to captures/<stamp>/
  python lol_coach.py --replay captures/<stamp> --speed 20
  python lol_coach.py --web               # localhost:8765 dashboard (not LAN)
  python lol_coach.py --claude            # opt-in; needs ANTHROPIC_API_KEY in the env
"""

import argparse
import glob
import gzip
import hashlib
import json
import os
import queue
import random
import shutil
import signal
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import shop
import patterns
import review

__version__ = "1.2.0"

LIVE_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"
DDRAGON = "https://ddragon.leagueoflegends.com"
# ROOT: read-only resources (assets, demo game). Inside the installed .exe this is the
# unpacked bundle. DATA: everything the app writes (settings, reports, captures, cache).
ROOT = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
FROZEN = bool(getattr(sys, "frozen", False))


def _data_dir():
    override = os.environ.get("MACROGOBLIN_HOME")
    if override:
        return override
    if not FROZEN:
        return os.path.dirname(os.path.abspath(__file__))  # running from source: keep files in the repo
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "MacroGoblin")


DATA = _data_dir()
DEMO_GAME = os.path.join(ROOT, "tests", "fixtures", "real", "kaisa-bot-win.jsonl.gz")
BUNDLED_DDRAGON = os.path.join(ROOT, "tests", "fixtures", "ddragon.json.gz")
REPO_URL = "https://github.com/atxgreene/rift-coach"
RELEASES_API = "https://api.github.com/repos/atxgreene/rift-coach/releases/latest"


def data_path(*parts):
    return os.path.join(DATA, *parts)

# Objective clock checked 2026-09-26.
# Patch 26.1 moved Baron 25:00 -> 20:00 and said other epic spawn times were unchanged:
#   https://www.leagueoflegends.com/en-gb/news/game-updates/patch-26-1-notes/
# Patch 26.19 (2026-09-22) notes do not change these timers:
#   https://www.leagueoflegends.com/en-us/news/game-updates/league-of-legends-patch-26-19-notes/
# Voidgrubs 8:00, despawn 14:45 (camp page; the Baron-pit page still says 6:00 and is treated as stale):
#   https://wiki.leagueoflegends.com/en-us/Voidgrub_camp
# Dragon 5:00 / respawn 5:00, Elder 6:00 after the 4th kill:
#   https://wiki.leagueoflegends.com/en-us/Dragon_pit
# Confirm grubs against the first --capture. Atakhan was removed in 26.1; no handler until a capture shows an event name.
CONFIG = {
    "poll_seconds": 1.0,
    # A single failed poll is normal (loading, heavy fights). Only treat the game as
    # closed after this many seconds of consecutive failures.
    "disconnect_grace": 15,
    "dragon_first_spawn": 300,
    "dragon_respawn": 300,
    "elder_respawn": 360,
    "grubs_first_spawn": 480,
    "grubs_despawn": 885,
    "herald_first_spawn": 900,
    "herald_despawn": 1185,
    "baron_first_spawn": 1200,
    "baron_respawn": 360,
    "objective_warn_seconds": [60, 30],
    "cs_target_per_min": 8.0,
    "cs_check_every": 180,
    "gold_bank_threshold": 1300,
    "back_timing_seconds": 90,     # "Dragon in 90, good time to back" when you are holding gold
    "back_timing_gold": 1100,
    "vision_check_every": 300,
    "vision_reminders": 3,
    "gold_bank_cooldown": 180,
    "gold_diff_every": 300,
    "legendary_min_gold": 2500,
    "soul_dragons": 4,
    "grub_group_seconds": 25,
    # Voice pacing. Low-priority lines (CS, gold, items) are shown on the overlay
    # every time but spoken at most once per low_voice_gap seconds.
    "low_voice_gap": 20,
    "pattern_cooldown": 300,
    "lead_peak": 3000,
    "lead_drop": 2500,
    "claude_model": "claude-haiku-4-5-20251001",
    "claude_every": 300,
    "web_host": "127.0.0.1",
    "web_port": 8765,
    "overlay": {
        "hotkey": "ctrl+shift+o",
        "default_mode": "compact",  # compact HUD strip; Ctrl+Shift+O cycles compact / full card / hidden
        "callout_fade_seconds": 12,
        "layouts": {
            # x/y None = auto: top-right of the primary monitor. Your dragged position
            # is saved per machine in overlay_layout.json (not committed).
            "1080p": {"x": None, "y": 140, "w": 300, "scale": 1.0, "opacity": 0.94},
            "1440p": {"x": None, "y": 180, "w": 300, "scale": 1.15, "opacity": 0.94},
        },
    },
}

DEATH_QUESTIONS = [
    "Where was their jungler last seen?",
    "What did the minimap show right before that?",
    "Were your key cooldowns up going in?",
    "Did you have wave priority, or were you pushed up?",
    "Was that fight worth the risk?",
    "How many enemies were missing from the map?",
]

CLAUDE_SYSTEM = (
    "You are a calm, sharp League of Legends coach speaking into the player's ear "
    "mid-game. Given a game snapshot, give ONE insight in under 25 words, spoken "
    "style, no preamble, no lists, no emojis. Favor macro: wave management "
    "principles, objective setup, itemization against the enemy comp, tempo after "
    "deaths, and mental reset. Only use information present in the snapshot."
)

POS_ALIAS = {
    "TOP": "TOP",
    "JUNGLE": "JUNGLE",
    "MIDDLE": "MIDDLE",
    "MID": "MIDDLE",
    "BOTTOM": "BOTTOM",
    "BOT": "BOTTOM",
    "ADC": "BOTTOM",
    "UTILITY": "UTILITY",
    "SUPPORT": "UTILITY",
    "SUP": "UTILITY",
}


def fmt_time(seconds):
    seconds = max(0, int(seconds))
    return "%d:%02d" % (seconds // 60, seconds % 60)


def norm_pos(value):
    if not value:
        return ""
    return POS_ALIAS.get(str(value).upper(), str(value).upper())


def is_stolen(ev):
    value = ev.get("Stolen")
    if value is True or value == 1:
        return True
    return isinstance(value, str) and value.lower() == "true"


class UiBus:
    """Latest coach state for the overlay and the local web dashboard."""

    def __init__(self):
        self._lock = threading.Lock()
        self.state = {}

    def publish(self, state):
        with self._lock:
            self.state = state

    def snapshot(self):
        with self._lock:
            return dict(self.state)


# Voice priorities. 0 = overlay/log only, never spoken.
P_QUIET, P_LOW, P_NORMAL, P_URGENT = 0, 1, 2, 3
# Seconds a queued line stays worth saying. A late "Dragon in 30 seconds" is worse than silence.
VOICE_TTL = {P_LOW: 20, P_NORMAL: 15, P_URGENT: 10}

# Coach style: Beginner adds a short "why" to new kinds of callouts; Pro keeps voice to what
# changes a decision right now (low-priority lines and death reflections go to the overlay only).
STYLES = ("beginner", "standard", "pro")
# Callout families a player can mute. Muted lines still show on the overlay and in the notes.
CATEGORIES = {
    "objective": "Objectives and timers",
    "death": "Deaths",
    "reflect": "Death reflection questions",
    "shop": "Items and gold",
    "farm": "CS checks",
    "enemy": "Enemy power spikes",
    "vision": "Vision and wards",
    "macro": "Gold lead and patterns",
}
CONTROL_WARD = 2055


class Speaker:
    """Prints every line; speaks the ones worth hearing, newest-important first.

    Lines wait in a small priority queue. Anything older than its TTL is dropped
    instead of spoken late. On Windows the hidden PowerShell voice acknowledges
    each finished sentence, so the queue knows when the voice is actually free.
    """

    def __init__(self, voice=True, voice_name="", rate=1, volume=100):
        self.voice_name = voice_name or ""
        self.rate = max(-10, min(10, int(rate)))
        self.volume = max(0, min(100, int(volume)))
        self.proc = None
        self.studio = None
        self.mode = self._pick_mode() if voice else None
        self.clock = lambda: 0
        self._log_fp = None
        self._cv = threading.Condition()
        self._pending = []
        self._acks = queue.Queue()
        self.spoken = 0
        self.dropped = 0
        if self.mode:
            threading.Thread(target=self._run, daemon=True).start()

    @staticmethod
    def list_voices():
        """Installed Windows voices (names), or [] elsewhere. Takes about a second; call off the UI thread."""
        if not sys.platform.startswith("win"):
            return []
        script = ("Add-Type -AssemblyName System.Speech;"
                  "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices()"
                  " | ForEach-Object { $_.VoiceInfo.Name }")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                                 text=True, timeout=15, creationflags=0x08000000)
            return [line.strip() for line in out.stdout.splitlines() if line.strip()]
        except Exception:
            return []

    def _pick_mode(self):
        """Studio (offline neural) voice when installed, else the system voice."""
        try:
            import voice as studio_voice
            voice_id = studio_voice.resolve(self.voice_name)
            if voice_id and studio_voice.Player().ok:
                self.studio = studio_voice.Studio(voice_id, rate=self.rate, volume=self.volume)
                threading.Thread(target=self._warm, daemon=True).start()
                return "studio"
        except Exception as exc:
            print("Studio voice unavailable (%s); using the system voice." % type(exc).__name__, flush=True)
            self.studio = None
        return self._detect()

    def _warm(self):
        try:
            self.studio.warm()
        except Exception:
            pass

    @property
    def engine(self):
        if self.mode == "studio" and self.studio is not None:
            import voice as studio_voice
            return "Studio voice (%s)" % studio_voice.label(self.studio.voice_id)
        return {"win": "Windows voice", "mac": "macOS voice", "espeak": "eSpeak"}.get(self.mode, "text only")

    def _fall_back(self):
        """Studio voice broke mid-game: keep talking with the system voice."""
        studio, self.studio = self.studio, None
        if studio is not None:
            studio.close()
        self.mode = self._detect()
        print("Studio voice stopped; switched to %s." % self.engine, flush=True)

    def close(self):
        self.mode = None
        with self._cv:
            self._pending = []
            self._cv.notify_all()
        if self.studio is not None:
            try:
                self.studio.close()
            except Exception:
                pass
            self.studio = None
        if self.proc is not None:
            try:
                self.proc.stdin.close()
                self.proc.kill()
            except Exception:
                pass
            self.proc = None
        if self._log_fp:
            try:
                self._log_fp.close()
            except Exception:
                pass
            self._log_fp = None

    @staticmethod
    def _detect():
        if sys.platform.startswith("win"):
            return "win"
        if sys.platform == "darwin" and shutil.which("say"):
            return "mac"
        if shutil.which("espeak"):
            return "espeak"
        return None

    def enable_log(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._log_fp = open(path, "a", encoding="utf-8")

    def say(self, text, priority=P_NORMAL, ttl=None):
        mark = " " if priority > P_QUIET else "\u00b7"
        line = "[%s]%s%s" % (fmt_time(self.clock()), mark, text)
        print(line, flush=True)
        if self._log_fp:
            self._log_fp.write(time.strftime("%H:%M:%S ") + line + "\n")
            self._log_fp.flush()
        if self.mode and priority > P_QUIET:
            with self._cv:
                ttl = VOICE_TTL.get(priority, 15) if ttl is None else ttl
                self._pending.append((priority, time.monotonic(), ttl, text))
                self._cv.notify()

    def next_line(self, block=True):
        """Highest priority, then oldest, among lines that are still fresh."""
        with self._cv:
            while True:
                now = time.monotonic()
                fresh = [row for row in self._pending if now - row[1] <= row[2]]
                self.dropped += len(self._pending) - len(fresh)
                self._pending = fresh
                if fresh:
                    best = max(fresh, key=lambda row: (row[0], -row[1]))
                    self._pending.remove(best)
                    return best[3]
                if not block or self.mode is None:
                    return None
                self._cv.wait(timeout=1.0)

    def _win_proc(self):
        if self.proc is None or self.proc.poll() is not None:
            wanted = (self.voice_name or "Microsoft Zira Desktop").replace("'", "''")
            script = (
                "Add-Type -AssemblyName System.Speech;"
                "[Console]::InputEncoding = [Text.Encoding]::UTF8;"
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "$s.Rate=%d; $s.Volume=%d;" % (self.rate, self.volume) +
                "try { $s.SelectVoice('%s') } catch {};" % wanted +
                "while(($l=[Console]::In.ReadLine()) -ne $null){"
                "try { $s.Speak($l) } catch {};"
                "[Console]::Out.WriteLine('done'); [Console]::Out.Flush() }"
            )
            kwargs = dict(
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
            )
            if sys.platform.startswith("win"):
                kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            self.proc = subprocess.Popen(["powershell", "-NoProfile", "-Command", script], **kwargs)
            self._acks = queue.Queue()
            threading.Thread(target=self._read_acks, args=(self.proc, self._acks), daemon=True).start()
        return self.proc

    @staticmethod
    def _read_acks(proc, acks):
        try:
            for _line in proc.stdout:
                acks.put(True)
        except Exception:
            pass
        acks.put(None)

    def _speak_win(self, text):
        proc = self._win_proc()
        # A late ack from a slow first start must not satisfy the next wait,
        # or every later line would be sent before the previous one finished.
        while True:
            try:
                self._acks.get_nowait()
            except queue.Empty:
                break
        proc.stdin.write(text.replace("\n", " ") + "\n")
        proc.stdin.flush()
        # Wait for the sentence to finish so stale lines can still be dropped.
        try:
            self._acks.get(timeout=3 + len(text) / 8.0)
        except queue.Empty:
            pass

    def _run(self):
        failures = studio_failures = 0
        while True:
            text = self.next_line()
            if text is None:
                return  # speaker closed
            try:
                if self.mode == "studio":
                    try:
                        self.studio.speak(text)
                        studio_failures = 0
                    except Exception:
                        if self.mode is None:
                            return  # closed while speaking
                        studio_failures += 1
                        if studio_failures < 2:
                            continue  # Piper restarts on the next line
                        self._fall_back()
                if self.mode == "win":
                    self._speak_win(text)
                elif self.mode == "mac":
                    subprocess.run(["say", text])
                elif self.mode == "espeak":
                    subprocess.run(["espeak", text], stderr=subprocess.DEVNULL)
                elif self.mode is None:
                    return
                self.spoken += 1
                failures = 0
            except Exception as exc:
                failures += 1
                if self.proc is not None:
                    try:
                        self.proc.kill()  # never leave two voices talking over each other
                    except Exception:
                        pass
                self.proc = None  # restart the voice process on the next line
                if failures >= 3:
                    print("Voice stopped (%s). Callouts continue as text." % type(exc).__name__, flush=True)
                    self.mode = None
                    return


def _plain(text):
    out, skip = [], False
    for char in text or "":
        if char == "<":
            skip = True
        elif char == ">":
            skip = False
        elif not skip:
            out.append(char)
    return "".join(out)


class DataDragon:
    """Static item and champion data. Cached per patch so later starts are instant and offline-safe."""

    def __init__(self, cache_dir=None, offline_file=None, quiet=False):
        self.item_gold, self.item_tags, self.champ_info, self.champ_tags = {}, {}, {}, {}
        self.catalog = {"_by_name": {}}
        self.patch = None
        self.ok = False
        cache_dir = cache_dir or data_path("cache")
        if offline_file:
            self._load(self._read(offline_file))
            return
        compact = None
        try:
            ver = self._get("%s/api/versions.json" % DDRAGON)[0]
            path = os.path.join(cache_dir, "ddragon-%s.json.gz" % ver)
            if os.path.exists(path):
                compact = self._read(path)
            else:
                compact = self.fetch(ver)
                try:
                    os.makedirs(cache_dir, exist_ok=True)
                    with gzip.open(path + ".tmp", "wt", encoding="utf-8") as handle:
                        json.dump(compact, handle)
                    os.replace(path + ".tmp", path)
                except OSError:
                    pass
        except Exception:
            cached = sorted(glob.glob(os.path.join(cache_dir, "ddragon-*.json.gz")), key=os.path.getmtime)
            if not cached and os.path.exists(BUNDLED_DDRAGON):
                cached = [BUNDLED_DDRAGON]  # shipped snapshot: first run works offline
            if cached:
                try:
                    compact = self._read(cached[-1])
                except Exception:
                    compact = None
        if compact:
            self._load(compact)
            if not quiet:
                print("Loaded game data for patch %s." % self.patch)
        elif not quiet:
            print("Couldn't reach Data Dragon and no cache yet - item gold and comp read disabled.")

    @staticmethod
    def _get(url):
        with urllib.request.urlopen(url, timeout=6) as response:
            return json.load(response)

    @staticmethod
    def _read(path):
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)

    @classmethod
    def fetch(cls, ver):
        items = cls._get("%s/cdn/%s/data/en_US/item.json" % (DDRAGON, ver))["data"]
        champs = cls._get("%s/cdn/%s/data/en_US/champion.json" % (DDRAGON, ver))["data"]
        compact = {"patch": ver, "items": {}, "champs": {}}
        for key, value in items.items():
            maps = value.get("maps") or {}
            compact["items"][key] = {
                "name": value.get("name") or "",
                "gold": (value.get("gold") or {}).get("total", 0) or 0,
                "tags": value.get("tags") or [],
                "from": value.get("from") or [],
                "into": value.get("into") or [],
                "in_store": value.get("inStore", True),
                "sr": bool(maps.get("11", True)) if maps else True,
                "desc": _plain(value.get("description") or "").lower()[:600],
            }
        for value in champs.values():
            compact["champs"][value["id"]] = {"name": value["name"], "info": value["info"], "tags": value.get("tags") or []}
        return compact

    def _load(self, compact):
        self.patch = compact.get("patch")
        for key, value in (compact.get("items") or {}).items():
            try:
                iid = int(key)
            except (TypeError, ValueError):
                continue
            self.item_gold[iid] = value.get("gold", 0) or 0
            self.item_tags[iid] = value.get("tags") or []
            if not value.get("sr", True) or iid >= 20000:
                continue
            name = value.get("name") or ""
            self.catalog[iid] = {
                "name": name,
                "gold": value.get("gold", 0) or 0,
                "tags": value.get("tags") or [],
                "desc": value.get("desc") or "",
                "from": value.get("from") or [],
                "into": value.get("into") or [],
                "in_store": value.get("in_store", True),
            }
            if name and name.lower() not in self.catalog["_by_name"]:
                self.catalog["_by_name"][name.lower()] = iid
        for key, value in (compact.get("champs") or {}).items():
            for alias in (key.lower(), (value.get("name") or "").lower()):
                if alias:
                    self.champ_info[alias] = value.get("info") or {}
                    self.champ_tags[alias] = value.get("tags") or []
        self.ok = bool(self.item_gold)

    def gold(self, item):
        iid = item.get("itemID")
        if iid in self.item_gold:
            return self.item_gold[iid]
        # The live client's "price" is the combine cost (Trinity Force = 133), not the item's value.
        return 0

    def is_boots(self, item):
        if not isinstance(item, dict):
            return False
        tags = self.item_tags.get(item.get("itemID"), [])
        name = item.get("displayName") or ""
        return "Boots" in tags or any(word in name for word in ("Boots", "Greaves", "Treads", "Steelcaps", "Shoes"))

    def is_legendary(self, item):
        if item.get("consumable") or self.is_boots(item):
            return False
        return self.gold(item) >= CONFIG["legendary_min_gold"]

    def _key(self, player):
        raw = (player.get("rawChampionName") or "").replace("game_character_displayname_", "").lower()
        for key in (raw, (player.get("championName") or "").lower()):
            if key in self.champ_info:
                return key
        return None

    def info(self, player):
        key = self._key(player)
        return self.champ_info.get(key) if key else None

    def tags(self, player):
        key = self._key(player)
        return self.champ_tags.get(key, []) if key else []


class ClaudeCoach:
    def __init__(self, api_key, model, speaker):
        self.key, self.model, self.speaker = api_key, model, speaker
        self.busy = False

    def ask(self, snapshot):
        if self.busy:
            return
        self.busy = True
        threading.Thread(target=self._call, args=(snapshot,), daemon=True).start()

    def _call(self, snapshot):
        try:
            body = json.dumps({
                "model": self.model,
                "max_tokens": 120,
                "system": CLAUDE_SYSTEM,
                "messages": [{"role": "user", "content": snapshot}],
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=body,
                method="POST",
                headers={
                    "x-api-key": self.key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=20) as response:
                data = json.load(response)
            text = "".join(block.get("text", "") for block in data.get("content", [])).strip()
            if text:
                self.speaker.say("Coach: " + text)
        except Exception as exc:
            print("(Claude call failed: %s)" % type(exc).__name__)
        finally:
            self.busy = False


def names_of(player):
    raw = set()
    if not isinstance(player, dict):
        return raw
    for key in ("summonerName", "riotIdGameName", "riotId", "gameName", "playerName"):
        value = player.get(key)
        if isinstance(value, str) and value:
            raw.add(value)
            raw.add(value.split("#")[0])
    game = player.get("riotIdGameName") or player.get("gameName")
    tag = player.get("riotIdTagline") or player.get("tagLine")
    if game and tag:
        raw.add("%s#%s" % (game, tag))
        raw.add(game)
    out = set()
    for name in raw:
        out.add(name)
        out.add(name.lower())
    return out


def name_hit(name, names):
    if not name or not isinstance(name, str):
        return False
    return name in names or name.lower() in names


def as_list(value):
    return value if isinstance(value, list) else []


def scores_of(player):
    scores = player.get("scores") if isinstance(player, dict) else None
    return scores if isinstance(scores, dict) else {}


def _num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def killer_label(name, player=None):
    """Readable name for whatever got the kill. Riot sends raw IDs for towers and monsters."""
    if player:
        return player.get("championName") or name or "something"
    if not name or not isinstance(name, str):
        return "something"
    low = name.lower()
    if low.startswith("turret"):
        return "a tower"
    if "baron" in low:
        return "Baron"
    if "dragon" in low:
        return "the dragon"
    if "herald" in low:
        return "Herald"
    if "horde" in low or "voidgrub" in low:
        return "void grubs"
    if "minion" in low:
        return "minions"
    if low.startswith("sru_") or low.startswith("sru"):
        return "a jungle camp"
    return name


def game_key(data):
    """Stable id for one match: the ten players. Used to merge restarts into one report."""
    ids = []
    for player in as_list((data or {}).get("allPlayers")):
        if isinstance(player, dict):
            # Players plus their champions: the same premade playing twice still gets two notes.
            ids.append("%s/%s" % (player.get("riotId") or player.get("summonerName") or "",
                                  player.get("championName") or ""))
    if not ids:
        return None
    return hashlib.sha1("|".join(sorted(ids)).encode("utf-8")).hexdigest()[:8]


def result_of(raw):
    if not isinstance(raw, str):
        return ""
    raw = raw.strip().lower()
    if raw in ("win", "victory", "won"):
        return "win"
    if raw in ("lose", "loss", "lost", "defeat", "fail"):
        return "loss"
    return ""


class Coach:
    def __init__(self, speaker, dd, claude=None, bus=None, me_name=None, style="standard", muted=()):
        self.say = speaker.say
        self.style = style if style in STYLES else "standard"
        self.muted = set(muted or ())
        self.dd = dd
        self.claude = claude
        self.bus = bus
        self.me_name = me_name
        self.on_new_event = None
        self.reset()

    def reset(self):
        self.last_event_id = -1
        self.first_tick = True
        self.quiet = False
        self.missed_me = False
        self.spawns = {
            "dragon": CONFIG["dragon_first_spawn"],
            "grubs": CONFIG["grubs_first_spawn"],
            "herald": CONFIG["herald_first_spawn"],
            "baron": CONFIG["baron_first_spawn"],
        }
        self.warned = set()
        self.prev_t = 0
        self.last_cs = 0
        self.last_stuck = -999
        self.cs_checks = 0
        self.last_gold_bank = -999
        self.last_diff_time = 0
        self.last_diff_said = 0
        self.last_low_voice = -999
        self.deaths = 0
        self.enemy_legendaries = {}
        self.profile_done = False
        self.me6 = self.opp6 = False
        self.last_claude = 0
        self.recent = []
        self.spikes = []
        self.seen_events = set()
        self.dragon_count = {}
        self.soul_team = None
        self.elder = False
        self.grub_group = None
        self.death_log = []
        self.objectives = []
        self.cs_marks = {}
        self.gold_curve = []
        self.last_gold_sample = 0
        self.game_over = False
        self.reported = False
        self.result = ""
        self.shop_lines = []
        self.move_speed = 0
        self.last_shop_key = None
        self.last_shop_said = -999
        self.shop_said = {}
        self.pattern_said = set()
        self.pattern_last = {}
        self.guidance = ""
        self.cs_rates = []
        self.sample_prev = 0
        self.boots_seen = False
        self.boots_upgraded = False
        self.voiced = 0
        self.game_id = None
        self.t = 0
        self.players = []
        self.me = None
        self.my_team = None
        self.enemies = []
        self.my_names = set()
        self.last_ui_diff = 0
        self.last_voiced = ""
        self.why_said = {}
        self.last_vision = 0
        self.vision_said = 0
        self.back_said = set()
        self.card = {}
        self.gold = 0

    # ----- output -------------------------------------------------------
    def note(self, text):
        self.recent.append((self.t, text, time.time()))
        self.recent = [row for row in self.recent if self.t - row[0] < 180]

    def speak(self, text, priority=P_NORMAL, ttl=None, cat=None, why=None):
        """Everything goes to the overlay feed. Voice is rationed by priority, category and style.

        cat: callout family the player can mute (CATEGORIES). why: a one-sentence reason that
        Beginner style adds the first two times a kind of callout comes up.
        """
        if self.quiet:
            self.note(text)
            return
        if cat in self.muted:
            priority = P_QUIET
        elif self.style == "pro" and (priority == P_LOW or cat == "reflect"):
            priority = P_QUIET
        if priority == P_LOW:
            if self.t - self.last_low_voice < CONFIG["low_voice_gap"]:
                priority = P_QUIET
            else:
                self.last_low_voice = self.t
        # The reason is only used up when it is actually heard.
        if why and self.style == "beginner" and priority > P_QUIET and self.why_said.get(why, 0) < 2:
            self.why_said[why] = self.why_said.get(why, 0) + 1
            text = "%s %s" % (text, why)
        self.note(text)
        if priority > P_QUIET:
            self.voiced += 1
            self.last_voiced = text
        try:
            self.say(text, priority=priority, ttl=ttl)
        except TypeError:
            if priority > P_QUIET:
                self.say(text)

    # ----- lookups ------------------------------------------------------
    def player_by_name(self, name):
        if not name or not isinstance(name, str):
            return None
        for player in self.players:
            if name_hit(name, names_of(player)):
                return player
        # Bots are reported by champion name.
        for player in self.players:
            if (player.get("championName") or "").lower() == name.lower():
                return player
        return None

    def event_team(self, ev):
        killer = self.player_by_name(ev.get("KillerName"))
        if killer:
            return killer.get("team")
        for name in as_list(ev.get("Assisters")):
            helper = self.player_by_name(name)
            if helper:
                return helper.get("team")
        return None

    def team_gold(self, team):
        total = 0
        for player in self.players:
            if player.get("team") != team:
                continue
            for item in as_list(player.get("items")):
                if not isinstance(item, dict) or item.get("consumable"):
                    continue
                total += self.dd.gold(item) * max(1, item.get("count", 1) or 1)
        return total

    def live_diff(self):
        if not self.enemies:
            return 0
        enemy_team = self.enemies[0].get("team")
        if not enemy_team:
            return 0
        return self.team_gold(self.my_team) - self.team_gold(enemy_team)

    def dragons(self):
        us = self.dragon_count.get(self.my_team, 0)
        them = sum(count for team, count in self.dragon_count.items() if team != self.my_team)
        return us, them

    def lane_opponent(self):
        pos = norm_pos((self.me or {}).get("position"))
        if not pos:
            return None
        return next((player for player in self.enemies if norm_pos(player.get("position")) == pos), None)

    # ----- main tick ----------------------------------------------------
    def tick(self, data):
        game = data.get("gameData") if isinstance(data.get("gameData"), dict) else {}
        try:
            self.t = float(game.get("gameTime", 0) or 0)
        except (TypeError, ValueError):
            self.t = 0
        players = data.get("allPlayers")
        self.players = players if isinstance(players, list) else []
        active = data.get("activePlayer") if isinstance(data.get("activePlayer"), dict) else {}
        mine = names_of(active)
        if self.me_name:
            for value in (self.me_name, self.me_name.split("#")[0]):
                mine.add(value)
                mine.add(value.lower())
        self.me = next((player for player in self.players if names_of(player) & mine), None)
        stats = active.get("championStats") if isinstance(active.get("championStats"), dict) else {}
        try:
            self.move_speed = float(stats.get("moveSpeed") or 0)
        except (TypeError, ValueError):
            self.move_speed = 0
        if not self.me:
            if not self.missed_me:
                print("Couldn't match your summoner in allPlayers. Re-run with --me YourName", flush=True)
                self.missed_me = True
            return
        self.missed_me = False
        if self.game_id is None:
            self.game_id = game_key(data)
        self.my_team = self.me.get("team")
        self.enemies = [player for player in self.players if player.get("team") != self.my_team]
        self.my_names = names_of(self.me) | mine

        # Joined mid-game (or restarted): rebuild history silently, then say one line.
        late = self.first_tick and self.t > 30
        self.quiet = late
        events = data.get("events")
        if isinstance(events, dict):
            event_list = events.get("Events") or []
        elif isinstance(events, list):
            event_list = events
        else:
            event_list = []
        self.track_boots(late)
        self.handle_events(as_list(event_list))
        self.flush_grubs(force=self.quiet)
        if self.game_over:
            # The API keeps answering for a few seconds after the nexus falls; stay quiet.
            self.quiet = False
            self.publish()
            self.first_tick = False
            return
        if self.first_tick:
            self.prev_t = self.t
            self.reconcile_clock()
        else:
            self.objective_timers()
        self.enemy_comp()
        self.enemy_items()
        self.levels()
        self.cs_check()
        try:
            self.gold = float(active.get("currentGold", 0) or 0)
        except (TypeError, ValueError):
            self.gold = 0
        self.gold_bank(active)
        self.sample()
        self.gold_diff()
        self.shop_check(active)
        self.vision_check()
        self.pattern_check()
        self.claude_checkin(periodic=True)
        if late:
            self.quiet = False
            self.speak(self.sync_line(), P_NORMAL)
        self.publish()
        self.first_tick = False

    def sync_line(self):
        line = "Coach synced at %s." % fmt_time(self.t)
        upcoming = [(at - self.t, obj) for obj, at in self.spawns.items() if at - self.t > 0]
        if upcoming:
            remain, obj = min(upcoming)
            label = {"dragon": "Elder" if self.soul_team else "Dragon", "grubs": "Void grubs",
                     "herald": "Herald", "baron": "Baron"}.get(obj, obj)
            line += " %s in %s." % (label, fmt_time(remain))
        return line

    def track_boots(self, late=False):
        for item in as_list(self.me.get("items")):
            if not isinstance(item, dict):
                continue
            is_boots = getattr(self.dd, "is_boots", None)
            boots = is_boots(item) if is_boots else "Boots" in (item.get("displayName") or "")
            if boots:
                self.boots_seen = True
                if item.get("itemID") != 1001:
                    self.boots_upgraded = True
        # Bot lane's role quest moves finished boots out of the item list. If we join
        # late and cannot see them, trust the quest instead of nagging.
        if late and norm_pos(self.me.get("position")) == "BOTTOM" and self.t >= 15 * 60:
            self.boots_seen = self.boots_upgraded = True

    def sample(self):
        cs = scores_of(self.me).get("creepScore", 0)
        if not self.first_tick:
            for mark in (10, 15, 20):
                boundary = mark * 60
                if mark not in self.cs_marks and self.sample_prev < boundary <= self.t:
                    self.cs_marks[mark] = cs
        self.sample_prev = self.t
        if self.t - self.last_gold_sample >= 60:
            self.last_gold_sample = self.t
            self.gold_curve.append((int(self.t), int(self.live_diff())))
            self.gold_curve = self.gold_curve[-40:]

    def reconcile_clock(self):
        if self.t >= CONFIG["grubs_despawn"] and self.spawns.get("grubs", 0) <= CONFIG["grubs_first_spawn"]:
            self.spawns.pop("grubs", None)
        if self.t >= CONFIG["herald_despawn"] and self.spawns.get("herald", 0) <= CONFIG["herald_first_spawn"]:
            self.spawns.pop("herald", None)

    # ----- events -------------------------------------------------------
    def handle_events(self, events):
        for idx, ev in enumerate(events):
            if not isinstance(ev, dict):
                continue
            eid = ev.get("EventID")
            if eid is None:
                eid = idx
            if eid <= self.last_event_id:
                continue
            self.last_event_id = eid
            name = ev.get("EventName")
            try:
                et = float(ev.get("EventTime", self.t))
            except (TypeError, ValueError):
                et = self.t
            if name and name not in self.seen_events:
                self.seen_events.add(name)
                if self.on_new_event:
                    self.on_new_event(name)
            team = self.event_team(ev)
            who = "We" if team is not None and team == self.my_team else "They"

            if name == "DragonKill":
                self.on_dragon(ev, et, team, who)
            elif name == "BaronKill":
                nxt = et + CONFIG["baron_respawn"]
                self.spawns["baron"] = nxt
                self.objectives.append({"t": et, "name": "baron", "who": who, "detail": ""})
                stolen = " Stolen!" if is_stolen(ev) else ""
                self.speak("%s took Baron.%s Buff for about 3 minutes. Next Baron at %s." % (who, stolen, fmt_time(nxt)), P_URGENT, 15,
                           cat="objective", why=("Group and push a lane together while the buff lasts." if who == "We" else "Stay together and defend under your towers."))
            elif name == "HeraldKill":
                self.spawns.pop("herald", None)
                self.objectives.append({"t": et, "name": "herald", "who": who, "detail": ""})
                self.speak("%s took Herald." % who, P_NORMAL, cat="objective")
            elif name in ("HordeKill", "VoidGrubKill"):
                self.add_grub(et, who)
            elif name == "ChampionKill" and name_hit(ev.get("VictimName"), self.my_names):
                self.on_death(ev, et)
            elif name == "Ace":
                team = ev.get("AcingTeam")
                if team:
                    if team == self.my_team:
                        self.speak("Ace. Their whole team is down. Take an objective.", P_URGENT, cat="objective")
                    else:
                        self.speak("We got aced. Reset together.", P_URGENT, cat="objective")
            elif name == "InhibKilled":
                if team is None:
                    self.speak("An inhibitor fell.", P_LOW, cat="objective")
                elif who == "We":
                    self.speak("We took an inhibitor. Push with the super minions.", P_LOW, cat="objective")
                else:
                    self.speak("We lost an inhibitor. Clear the super minions.", P_NORMAL, cat="objective")
            elif name == "GameEnd":
                self.game_over = True
                winning = ev.get("WinningTeam")
                if winning and self.my_team:
                    self.result = "win" if str(winning) == str(self.my_team) else "loss"
                self.result = result_of(ev.get("Result")) or self.result
                self.card = self.report_card()
                summary = review.spoken_summary(self.card)
                self.speak(" ".join(x for x in ("Game over.", summary, focus_line(self)) if x), P_URGENT, 30)

    def on_dragon(self, ev, et, team, who):
        kind = (ev.get("DragonType") or "").strip()
        stolen = " Stolen!" if is_stolen(ev) else ""
        ours = who == "We"
        if kind.lower() == "elder":
            nxt = et + CONFIG["elder_respawn"]
            self.objectives.append({"t": et, "name": "elder", "who": who, "detail": ""})
            self.speak("%s took Elder.%s Next Elder at %s." % (who, stolen, fmt_time(nxt)), P_URGENT, 15, cat="objective")
        else:
            if team:
                self.dragon_count[team] = self.dragon_count.get(team, 0) + 1
            us, them = self.dragons()
            label = ("%s dragon" % kind) if kind else "the dragon"
            if team and self.soul_team is None and self.dragon_count[team] >= CONFIG["soul_dragons"]:
                self.soul_team = team
                self.elder = True
                nxt = et + CONFIG["elder_respawn"]
                self.speak("%s took %s.%s %s soul. Elder at %s." % (
                    who, label, stolen, "Our" if ours else "Their", fmt_time(nxt)), P_URGENT, 15, cat="objective")
            else:
                nxt = et + (CONFIG["elder_respawn"] if self.soul_team else CONFIG["dragon_respawn"])
                self.speak("%s took %s.%s Dragons %d to %d. Next at %s." % (
                    who, label, stolen, us, them, fmt_time(nxt)), P_NORMAL, cat="objective",
                    why="Each dragon is a permanent team buff; four gives soul.")
            self.objectives.append({"t": et, "name": "dragon", "who": who, "detail": kind})
        self.spawns["dragon"] = nxt

    def add_grub(self, et, who):
        group = self.grub_group
        if group is None or et - group["last"] > CONFIG["grub_group_seconds"]:
            self.flush_grubs(force=True)
            group = self.grub_group = {"start": et, "last": et, "us": 0, "them": 0}
        group["last"] = et
        group["us" if who == "We" else "them"] += 1
        self.spawns.pop("grubs", None)

    def flush_grubs(self, force=False):
        group = self.grub_group
        if not group:
            return
        total = group["us"] + group["them"]
        if not force and total < 3 and self.t - group["last"] < CONFIG["grub_group_seconds"]:
            return
        self.grub_group = None

        def count(n):
            return "all 3 void grubs" if n == 3 else ("%d void grub%s" % (n, "" if n == 1 else "s"))

        if group["them"] == 0:
            line = "We took %s." % count(group["us"])
        elif group["us"] == 0:
            line = "They took %s." % count(group["them"])
        else:
            line = "Grubs split. We took %d, they took %d." % (group["us"], group["them"])
        self.objectives.append({
            "t": group["start"],
            "name": "grubs",
            "who": "We" if group["us"] >= group["them"] else "They",
            "detail": "%d-%d" % (group["us"], group["them"]),
        })
        self.speak(line, P_NORMAL, cat="objective")

    def on_death(self, ev, et):
        self.deaths += 1
        killer = self.player_by_name(ev.get("KillerName"))
        by = killer_label(ev.get("KillerName"), killer)
        self.death_log.append({"t": et, "by": by})
        if self.quiet:
            return
        timer = 0
        try:
            timer = int(float(self.me.get("respawnTimer", 0) or 0))
        except (TypeError, ValueError):
            timer = 0
        msg = "Death %d, to %s." % (self.deaths, by)
        if timer:
            msg += " %d seconds." % timer
        if self.t < 600 and self.deaths == 3:
            msg += " Three early deaths. Farm and stay alive for a bit."
        self.speak(msg, P_URGENT, 10, cat="death")
        pattern = self.fresh_pattern()
        if self.claude:
            self.claude_checkin(trigger="I just died to %s." % by)
        elif pattern:
            self.speak(pattern, P_NORMAL, 20, cat="reflect")
        elif self.deaths % 2 == 1:
            # A reflection question every other death; more than that becomes background noise.
            self.speak(random.choice(DEATH_QUESTIONS), P_NORMAL, 20, cat="reflect")

    # ----- clocks -------------------------------------------------------
    def objective_timers(self):
        prev = self.prev_t
        labels = {"dragon": "Elder" if self.soul_team else "Dragon", "grubs": "Void grubs",
                  "herald": "Herald", "baron": "Baron"}
        for obj, at in (("grubs", CONFIG["grubs_despawn"]), ("herald", CONFIG["herald_despawn"])):
            if obj in self.spawns and prev < at <= self.t:
                self.spawns.pop(obj, None)
                self.speak("%s left the pit." % labels[obj], P_LOW, cat="objective")
        self.back_timing(labels)
        for obj, at in list(self.spawns.items()):
            for warn in CONFIG["objective_warn_seconds"]:
                mark = at - warn
                key = (obj, at, warn)
                if prev < mark <= self.t and key not in self.warned:
                    self.warned.add(key)
                    self.speak("%s in %d seconds." % (labels[obj], warn),
                               P_URGENT if warn <= 30 else P_NORMAL, 8 if warn <= 30 else 12, cat="objective",
                               why="Push your wave first, then walk over with your team." if warn > 30 else None)
            key = (obj, at, 0)
            if prev < at <= self.t and key not in self.warned:
                self.warned.add(key)
                verb = "are" if obj == "grubs" else "is"
                self.speak("%s %s up." % (labels[obj], verb), P_URGENT, 10, cat="objective")
        self.prev_t = self.t

    # ----- reads --------------------------------------------------------
    def enemy_comp(self):
        """One read of the enemy team from what the loading screen shows: damage mix and threats."""
        if self.profile_done or self.t < 15:
            return
        self.profile_done = True
        ap = ad = 0
        for player in self.enemies:
            info = self.dd.info(player)
            if not info:
                return
            if info.get("magic", 0) > info.get("attack", 0):
                ap += 1
            else:
                ad += 1
        if ap >= 4:
            self.speak("Enemy comp is magic damage. %d AP threats. Magic resist goes a long way." % ap, P_NORMAL, cat="enemy")
        elif ad >= 4:
            self.speak("Enemy comp is physical. %d AD threats. Armor goes a long way." % ad, P_NORMAL, cat="enemy")
        else:
            self.speak("Enemy damage is mixed, %d AD and %d AP." % (ad, ap), P_LOW, cat="enemy")
        threat = self.threat_line()
        if threat:
            self.speak(threat, P_LOW, cat="enemy")
        intro = self.lane_intro()
        if intro and self.style == "beginner":
            self.speak(intro, P_NORMAL, cat="enemy")
        elif intro:
            self.note(intro)

    def threat_line(self):
        tags = getattr(self.dd, "tags", None)
        if not tags:
            return ""
        assassins = [p.get("championName") for p in self.enemies
                     if "Assassin" in (tags(p) or []) and (tags(p) or [""])[0] != "Marksman"]
        tanks = [p.get("championName") for p in self.enemies if "Tank" in (tags(p) or [])]
        if len(assassins) >= 2:
            return "They have %d assassins, %s. Ward your flanks and stay near your team." % (
                len(assassins), " and ".join(assassins[:3]))
        if len(tanks) >= 3:
            return "They have %d tanks. Fights will go long; damage that shreds health helps." % len(tanks)
        return ""

    def lane_intro(self):
        opp = self.lane_opponent()
        tags = getattr(self.dd, "tags", None)
        if not opp or not tags:
            return ""
        kinds = [t.lower() for t in (tags(opp) or [])]
        if not kinds:
            return ""
        kind = kinds[0]
        article = "an" if kind[0] in "aeiou" else "a"
        return "You are laning against %s, %s %s." % (opp.get("championName"), article, kind)

    def back_timing(self, labels):
        """"Dragon in 90, good time to back": gold in pocket before an objective is wasted."""
        lead = CONFIG["back_timing_seconds"]
        if not self.me or self.me.get("isDead") or self.gold < CONFIG["back_timing_gold"]:
            return
        for obj, at in self.spawns.items():
            if obj not in ("dragon", "baron", "grubs"):
                continue
            mark = at - lead
            key = (obj, at)
            if self.prev_t < mark <= self.t and key not in self.back_said:
                self.back_said.add(key)
                self.speak("%s in %d. You have %d gold. Good time to back and shop." % (
                    labels[obj], lead, int(self.gold)), P_NORMAL, 20, cat="shop",
                    why="Arrive with your items bought and your wave pushed.")
                return

    def vision_check(self):
        """Control ward and vision score reminders, a few times a game at most."""
        if self.t < 8 * 60 or self.me.get("isDead") or self.vision_said >= CONFIG["vision_reminders"]:
            return
        if self.t - self.last_vision < CONFIG["vision_check_every"]:
            return
        self.last_vision = self.t
        has_control = any(isinstance(i, dict) and i.get("itemID") == CONTROL_WARD for i in as_list(self.me.get("items")))
        score = scores_of(self.me).get("wardScore")
        try:
            per_min = float(score) / (self.t / 60.0) if score is not None else None
        except (TypeError, ValueError):
            per_min = None
        low = per_min is not None and per_min < review.vision_target(norm_pos(self.me.get("position"))) * 0.6
        if has_control and not low:
            return
        if low and not has_control:
            line = "Low vision and no control ward. Buy one next back."
        elif low:
            line = "Low vision. Place your control ward and use your trinket."
        else:
            line = "No control ward. Grab one next back."
        self.vision_said += 1
        self.speak(line, P_LOW, cat="vision",
                   why="Wards show who is coming. Most deaths come from the side you cannot see.")

    def report_card(self):
        if not self.me:
            return {}
        scores = scores_of(self.me)
        team_kills = sum(int(_num(scores_of(p).get("kills"))) for p in self.players if p.get("team") == self.my_team)
        big = [row for row in self.objectives if row.get("name") in ("dragon", "elder", "baron", "herald", "grubs")]
        return review.report_card({
            "minutes": self.t / 60.0,
            "role": norm_pos(self.me.get("position")),
            "cs": scores.get("creepScore", 0),
            "kills": scores.get("kills", 0),
            "deaths": scores.get("deaths", 0),
            "assists": scores.get("assists", 0),
            "team_kills": team_kills,
            "ward_score": scores.get("wardScore"),
            "objectives_us": sum(1 for row in big if row.get("who") == "We"),
            "objectives_them": sum(1 for row in big if row.get("who") != "We"),
            "cs_target": CONFIG["cs_target_per_min"],
        })

    # ----- hotkeys ------------------------------------------------------
    def repeat_last(self):
        """Ctrl+Shift+R: say the last voiced callout again."""
        if self.last_voiced:
            self.say(self.last_voiced, priority=P_URGENT, ttl=10)
        else:
            self.say("Nothing to repeat yet.", priority=P_URGENT, ttl=10)

    def whats_next(self):
        """Ctrl+Shift+N: next objective, and what to buy next."""
        parts = []
        spawns, shop_lines = dict(self.spawns), list(self.shop_lines)  # the poll thread may change these
        if self.me:
            upcoming = sorted((at - self.t, obj) for obj, at in spawns.items())
            if upcoming:
                remain, obj = upcoming[0]
                label = {"dragon": "Elder" if self.soul_team else "Dragon", "grubs": "Void grubs",
                         "herald": "Herald", "baron": "Baron"}.get(obj, obj)
                parts.append("%s is up." % label if remain <= 0 else "%s in %s." % (label, fmt_time(remain)))
            for line in shop_lines:
                if line.startswith("NEXT "):
                    fields = [f for f in line[5:].split("  ") if f.strip()]
                    item = fields[0].strip() if fields else ""
                    cost = fields[1].strip().rstrip("g") if len(fields) > 1 else ""
                    if item:
                        parts.append("Buy next: %s%s." % (item, (", %s gold" % cost) if cost.isdigit() else ""))
                    break
        self.say(" ".join(parts) or "No game yet.", priority=P_URGENT, ttl=10)

    def enemy_items(self):
        opp = self.lane_opponent()
        fed = None
        kills = [(scores_of(player).get("kills", 0) or 0, player) for player in self.enemies]
        if kills:
            top_kills, top = max(kills, key=lambda row: row[0])
            if top_kills >= 5:
                fed = top
        for player in self.enemies:
            champ = player.get("championName", "?")
            seen = self.enemy_legendaries.setdefault(champ, set())
            for item in as_list(player.get("items")):
                if not isinstance(item, dict):
                    continue
                iid = item.get("itemID")
                if iid in seen or not self.dd.is_legendary(item):
                    continue
                seen.add(iid)
                label = "Enemy %s finished %s." % (champ, item.get("displayName", "an item"))
                self.spikes.append(label)
                self.spikes = self.spikes[-8:]
                if self.first_tick:
                    continue
                # Voice only the threats that matter to you. The rest stays on the overlay.
                if player is opp or player is fed:
                    self.speak(label, P_LOW, cat="enemy")
                else:
                    self.speak(label, P_QUIET, cat="enemy")

    def levels(self):
        try:
            my_level = int(self.me.get("level") or 0)
        except (TypeError, ValueError):
            my_level = 0
        if not self.me6 and my_level >= 6:
            self.me6 = True
            self.speak("Level 6. Ult is online.", P_NORMAL, cat="enemy",
                       why="Fights you could not win before may be winnable now.")
        opp = self.lane_opponent()
        if not self.opp6 and opp:
            try:
                opp_level = int(opp.get("level") or 0)
            except (TypeError, ValueError):
                opp_level = 0
            if opp_level >= 6:
                self.opp6 = True
                label = "Their %s just hit 6. Respect the ult." % opp.get("championName")
                self.spikes.append(label)
                self.spikes = self.spikes[-8:]
                self.speak(label, P_NORMAL, cat="enemy",
                           why="Their all-in just got stronger. Play a step back until you see it used.")

    def cs_check(self):
        if norm_pos(self.me.get("position")) == "UTILITY" or self.t < 150:
            return
        if self.t - self.last_cs < CONFIG["cs_check_every"]:
            return
        self.last_cs = self.t
        try:
            cs = int(scores_of(self.me).get("creepScore", 0) or 0)
        except (TypeError, ValueError):
            cs = 0
        rate = cs / (self.t / 60.0) if self.t else 0
        target = CONFIG["cs_target_per_min"]
        self.cs_rates.append((self.t, rate))
        self.cs_rates = self.cs_rates[-6:]
        if self._cs_is_stuck():
            if self.t - self.last_stuck >= 600:
                self.last_stuck = self.t
                self.speak("CS is under 5 and a half a minute. Catch waves before you fight.", P_NORMAL, cat="farm")
            return
        msg = "%d minutes, %d CS. %.1f a minute." % (int(self.t // 60), cs, rate)
        self.cs_checks = getattr(self, "cs_checks", 0) + 1
        if rate < target - 1.5:
            self.speak(msg + " Target is %g." % target, P_LOW if self.cs_checks % 2 == 1 else P_QUIET, cat="farm",
                       why="Each wave is about 125 gold. Last-hit before you trade.")
        else:
            # On pace: say it now and then, otherwise just show it.
            self.speak(msg, P_LOW if self.cs_checks % 3 == 1 else P_QUIET, cat="farm")

    def gold_bank(self, active):
        try:
            gold = float(active.get("currentGold", 0) or 0)
        except (TypeError, ValueError):
            return
        if self.me.get("isDead") or gold < CONFIG["gold_bank_threshold"]:
            return
        if self.t - self.last_gold_bank < CONFIG["gold_bank_cooldown"]:
            return
        self.last_gold_bank = self.t
        self.speak("%d gold banked." % int(gold), P_LOW, cat="shop",
                   why="Gold in your pocket does nothing. Back and buy when your wave is pushed.")

    def gold_diff(self):
        """Every five minutes, the item-gold lead averaged over the last three samples.

        A raw reading swings 3-4k whenever one team backs and shops, so it is never
        spoken on its own. The overlay bar shows the live number.
        """
        if not self.enemies or self.t < 240 or not getattr(self.dd, "ok", True):
            return
        if self.t - self.last_diff_time < CONFIG["gold_diff_every"]:
            return
        self.last_diff_time = self.t
        recent = [diff for _stamp, diff in self.gold_curve[-3:]] or [self.live_diff()]
        diff = sum(recent) / float(len(recent))
        self.last_diff_said = diff
        if abs(diff) < 750:
            line = "Item gold is about even."
        else:
            line = "Item gold %s about %.1fk." % ("up" if diff > 0 else "down", abs(diff) / 1000.0)
        why = None
        if diff <= -750:
            why = "Play safe, farm, and fight next to your team."
        elif diff >= 750:
            why = "Turn the lead into towers and dragons, not just kills."
        self.speak(line, P_LOW, cat="macro", why=why)

    # ----- optional LLM -------------------------------------------------
    def claude_checkin(self, periodic=False, trigger=None):
        if not self.claude or self.t < 90 or self.quiet:
            return
        if periodic and self.t - self.last_claude < CONFIG["claude_every"]:
            return
        self.last_claude = self.t
        self.claude.ask(self.snapshot(trigger or "Periodic check-in."))

    def snapshot(self, trigger):
        def line(player):
            scores = scores_of(player)
            items = ", ".join(
                item.get("displayName", "")
                for item in as_list(player.get("items"))
                if isinstance(item, dict) and not item.get("consumable")
            ) or "none"
            dead = " (dead)" if player.get("isDead") else ""
            return "%s %s lvl%s %s/%s/%s %scs%s [%s]" % (
                player.get("championName"),
                norm_pos(player.get("position")),
                player.get("level"),
                scores.get("kills", 0),
                scores.get("deaths", 0),
                scores.get("assists", 0),
                scores.get("creepScore", 0),
                dead,
                items,
            )

        allies = [player for player in self.players if player.get("team") == self.my_team]
        us, them = self.dragons()
        spawns = ", ".join("%s at %s" % (key, fmt_time(value)) for key, value in self.spawns.items())
        recent = "; ".join("%s %s" % (fmt_time(row[0]), row[1]) for row in self.recent[-8:]) or "none"
        return (
            "Game time %s. Trigger: %s\nME: %s\nALLIES:\n%s\nENEMIES:\n%s\n"
            "Team item gold diff (us minus them): %s\nDragons us %d, them %d\n"
            "Upcoming objective spawns: %s\nRecent callouts: %s"
            % (
                fmt_time(self.t), trigger, line(self.me),
                "\n".join(line(player) for player in allies),
                "\n".join(line(player) for player in self.enemies),
                self.live_diff(), us, them, spawns, recent,
            )
        )

    # ----- shop + patterns ----------------------------------------------
    def has_boots_for_shop(self):
        return self.boots_upgraded or shop.quest_slot_boots(norm_pos((self.me or {}).get("position")), self.move_speed)

    def shop_check(self, active):
        try:
            gold = float(active.get("currentGold") or 0)
        except (TypeError, ValueError):
            gold = 0
        me = dict(self.me)
        me["position"] = norm_pos(me.get("position"))
        me["_info"] = self.dd.info(self.me) or {}
        tags = getattr(self.dd, "tags", None)
        me["_tags"] = tags(self.me) if tags else []
        infos = [self.dd.info(enemy) or {} for enemy in self.enemies]
        me["_ad"] = sum(1 for info in infos if info.get("attack", 0) >= info.get("magic", 0))
        me["_ap"] = len(self.enemies) - me["_ad"]
        me["_move_speed"] = self.move_speed
        me["_has_boots"] = self.has_boots_for_shop()
        allies = [player for player in self.players if player.get("team") == self.my_team and player is not self.me]
        catalog = getattr(self.dd, "catalog", None) or {"_by_name": {}}
        advice = shop.advise(me, self.enemies, gold, catalog, self.t, allies=allies, deaths=self.deaths)
        self.shop_lines = advice.get("lines") or []
        key = advice.get("key")
        if not advice.get("speak") or key is None or self.quiet:
            return
        # Each suggestion is spoken once, with one reminder four minutes later. It stays on the overlay.
        said = self.shop_said.get(key, [])
        if len(said) >= 2 or (said and self.t - said[-1] < 240):
            return
        if self.t - self.last_shop_said < 45:
            return
        self.shop_said[key] = said + [self.t]
        self.last_shop_key = key
        self.last_shop_said = self.t
        self.speak(advice["speak"], P_NORMAL, 30, cat="shop")

    def _pattern_state(self):
        return {
            "t": self.t,
            "deaths": self.death_log,
            "has_boots": self.boots_seen or shop.quest_slot_boots(
                norm_pos((self.me or {}).get("position")), self.move_speed
            ),
            "cs_rates": self.cs_rates,
            "gold_curve": self.gold_curve,
            "objectives": self.objectives,
            "lead_peak": CONFIG["lead_peak"],
            "lead_drop": CONFIG["lead_drop"],
        }

    def _cs_is_stuck(self):
        rates = [rate for stamp, rate in self.cs_rates if stamp >= 12 * 60]
        return len(rates) >= 2 and rates[-1] < 5.5 and rates[-2] < 5.5

    def fresh_pattern(self):
        for note in patterns.scan(self._pattern_state()):
            key = note["key"]
            if key in self.pattern_said or key == "cs-stuck":
                continue
            prefix = key.split(":")[0]
            if self.t - self.pattern_last.get(prefix, -99999) < CONFIG["pattern_cooldown"]:
                continue
            self.pattern_said.add(key)
            self.pattern_last[prefix] = self.t
            self.guidance = note["line"]
            return note["line"]
        return None

    def pattern_check(self):
        notes = patterns.scan(self._pattern_state())
        if notes:
            self.guidance = notes[0]["line"]
        if self.t - self.last_shop_said <= 8:
            return
        line = self.fresh_pattern()
        if line:
            self.speak(line, P_NORMAL, 20, cat="macro")

    # ----- UI -----------------------------------------------------------
    def publish(self):
        if not self.bus or not self.me:
            return
        scores = scores_of(self.me)
        cs = scores.get("creepScore", 0)
        rate = (cs / (self.t / 60.0)) if self.t else 0
        diff = self.live_diff() if getattr(self.dd, "ok", True) else 0
        us, them = self.dragons()
        state = {
            "t": self.t,
            "clock": fmt_time(self.t),
            "status": "live",
            "champion": self.me.get("championName") or "",
            "level": self.me.get("level") or "",
            "kda": "%s/%s/%s" % (scores.get("kills", 0), scores.get("deaths", 0), scores.get("assists", 0)),
            "spawns": dict(self.spawns),
            "elder": bool(self.soul_team),
            "dragons": {"us": us, "them": them},
            "soul": ("us" if self.soul_team == self.my_team else "them") if self.soul_team else "",
            "callouts": list(self.recent[-3:]),
            "gold_diff": diff,
            "gold_ok": bool(getattr(self.dd, "ok", True)),
            "prev_gold_diff": self.last_ui_diff,
            "cs": cs,
            "cs_rate": rate,
            "cs_target": CONFIG["cs_target_per_min"],
            "position": norm_pos(self.me.get("position")),
            "spikes": list(self.spikes[-4:]),
            "shop": ([self.guidance] if self.guidance else []) + list(self.shop_lines),
            "in_game": True,
            "version": __version__,
            "style": self.style,
            "card": dict(self.card),
        }
        self.last_ui_diff = diff
        self.bus.publish(state)


class LiveClient:
    def __init__(self):
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def get(self):
        with urllib.request.urlopen(LIVE_URL, context=self.ctx, timeout=2) as response:
            return json.load(response)


class Capture:
    """Raw polls for debugging and regression tests. Gzipped: about 1/7 the disk of plain JSON."""

    def __init__(self, root):
        self.root = root
        self.dir = None
        self.n = 0
        self.last_write = 0
        self.seen_ids = set()
        self.events_fp = None

    def begin(self):
        self.close()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.dir = os.path.join(self.root, stamp)
        os.makedirs(self.dir, exist_ok=True)
        self.n = 0
        self.last_write = 0
        self.seen_ids = set()
        self.events_fp = open(os.path.join(self.dir, "events.txt"), "a", encoding="utf-8")
        print("Capturing to %s" % self.dir, flush=True)
        return self.dir

    def close(self):
        if self.events_fp:
            self.events_fp.close()
            self.events_fp = None

    def note_event(self, name):
        if not self.events_fp:
            return
        self.events_fp.write(name + "\n")
        self.events_fp.flush()

    def maybe_write(self, data, now=None):
        if not self.dir:
            self.begin()
        events = (data.get("events") or {}).get("Events") or []
        if not isinstance(events, list):
            events = []
        ids = set()
        for idx, ev in enumerate(events):
            if isinstance(ev, dict):
                ids.add(ev.get("EventID", idx))
        new_event = bool(ids - self.seen_ids)
        self.seen_ids |= ids
        now = time.time() if now is None else now
        if not new_event and self.n and now - self.last_write < 5:
            return None
        path = os.path.join(self.dir, "%04d.json.gz" % self.n)
        tmp = path + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
        self.n += 1
        self.last_write = now
        return path


def load_frames(source):
    """Frames from a capture folder (*.json / *.json.gz) or a single .jsonl(.gz) fixture."""
    frames = []
    if os.path.isdir(source):
        files = sorted(glob.glob(os.path.join(source, "*.json")) + glob.glob(os.path.join(source, "*.json.gz")))
        for path in files:
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8") as handle:
                frames.append(json.load(handle))
    elif os.path.isfile(source):
        opener = gzip.open if source.endswith(".gz") else open
        with opener(source, "rt", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    frames.append(json.loads(line))
    frames.sort(key=lambda frame: (frame.get("gameData") or {}).get("gameTime", 0) or 0)
    return frames


class ReplayClient:
    def __init__(self, folder, speed):
        self.frames = load_frames(folder)
        if not self.frames:
            raise SystemExit("No capture frames in %s" % folder)
        self.speed = speed
        self.start = time.time()
        self.origin = self.frames[0].get("gameData", {}).get("gameTime", 0) or 0
        self.end_time = self.frames[-1].get("gameData", {}).get("gameTime", 0) or 0

    def clock(self):
        # Frame gameTime stops at the last capture. This clock keeps moving.
        return self.origin + (time.time() - self.start) * self.speed

    def get(self):
        target = self.clock()
        chosen = self.frames[0]
        for frame in self.frames:
            if (frame.get("gameData", {}).get("gameTime", 0) or 0) <= target:
                chosen = frame
            else:
                break
        return chosen


class MockGame:
    ITEMS = [
        (3031, "Infinity Edge", 3450),
        (3089, "Rabadon's Deathcap", 3600),
        (3071, "Black Cleaver", 3000),
        (3157, "Zhonya's Hourglass", 3250),
        (3065, "Spirit Visage", 2900),
        (6653, "Liandry's Torment", 3000),
        (1037, "Pickaxe", 875),
        (1026, "Blasting Wand", 850),
    ]
    CHAMPS = [
        ("Garen", "TOP"),
        ("Lee Sin", "JUNGLE"),
        ("Ahri", "MIDDLE"),
        ("Jinx", "BOTTOM"),
        ("Thresh", "UTILITY"),
        ("Darius", "TOP"),
        ("Elise", "JUNGLE"),
        ("Syndra", "MIDDLE"),
        ("Kai'Sa", "BOTTOM"),
        ("Lulu", "UTILITY"),
    ]

    def __init__(self, speed):
        self.speed = speed
        self.t = 0.0
        self.start = time.time()
        self.events = []
        self.gold = 500.0
        self.players = []
        for idx, (champ, pos) in enumerate(self.CHAMPS):
            raw = champ.replace(" ", "").replace("'", "")
            self.players.append({
                "championName": champ,
                "rawChampionName": "game_character_displayname_" + raw,
                "position": pos,
                "team": "ORDER" if idx < 5 else "CHAOS",
                "summonerName": "You" if idx == 2 else "Player%d" % idx,
                "riotIdGameName": "You" if idx == 2 else "Player%d" % idx,
                "level": 1,
                "isDead": False,
                "respawnTimer": 0,
                "items": [],
                "scores": {"kills": 0, "deaths": 0, "assists": 0, "creepScore": 0, "wardScore": 0},
            })
        self.script = [
            (5, "GameStart", {}),
            (400, "DragonKill", {"KillerName": "Player1", "DragonType": "Fire", "Stolen": False}),
            (455, "ChampionKill", {"KillerName": "Player7", "VictimName": "You"}),
            (530, "HordeKill", {"KillerName": "Player6"}),
            (760, "DragonKill", {"KillerName": "Player6", "DragonType": "Ocean", "Stolen": "True"}),
            (1000, "HeraldKill", {"KillerName": "Player1"}),
            (1320, "Ace", {"AcingTeam": "ORDER"}),
            (1560, "BaronKill", {"KillerName": "Player1"}),
        ]

    def get(self):
        self.t = (time.time() - self.start) * self.speed
        while self.script and self.script[0][0] <= self.t:
            et, name, extra = self.script.pop(0)
            self.events.append({"EventID": len(self.events), "EventName": name, "EventTime": float(et), **extra})
            if name == "ChampionKill":
                self.players[2]["scores"]["deaths"] += 1
                self.players[2]["respawnTimer"] = 12
                self.gold = 0
        for player in self.players:
            player["level"] = min(18, 1 + int(self.t / 70))
            if player["position"] != "UTILITY" and self.t > 65:
                player["scores"]["creepScore"] = int((self.t - 65) / 60 * 7.2)
            owned = [item["itemID"] for item in player["items"]]
            if self.t > 360 * (len(owned) + 1) and len(owned) < 6:
                choice = next((item for item in self.ITEMS if item[0] not in owned), None)
                if choice:
                    iid, name, price = choice
                    player["items"].append({
                        "itemID": iid,
                        "displayName": name,
                        "price": price,
                        "count": 1,
                        "consumable": False,
                    })
        self.gold += 0.02 * self.speed * 40
        return {
            "activePlayer": {
                "summonerName": "You",
                "riotIdGameName": "You",
                "currentGold": self.gold,
                "level": self.players[2]["level"],
            },
            "allPlayers": self.players,
            "events": {"Events": self.events},
            "gameData": {"gameTime": self.t, "gameMode": "CLASSIC"},
        }


def focus_line(coach):
    early = [row for row in coach.death_log if row.get("t", 0) < 600]
    if len(early) >= 3:
        return "Next game: farm the first ten minutes."
    cs15 = coach.cs_marks.get(15)
    pos = norm_pos(coach.me.get("position")) if coach.me else ""
    if cs15 is not None and pos != "UTILITY":
        try:
            rate = float(cs15) / 15.0
        except (TypeError, ValueError):
            rate = 99
        if rate < 6.5:
            return "Next game: last-hit the cannon before you roam."
    killers = [row.get("by") for row in coach.death_log if row.get("by")]
    if killers:
        top = max(set(killers), key=killers.count)
        if killers.count(top) >= 2 and top not in ("something", "a tower", "minions"):
            return "Next game: respect %s. Give the wave." % top
    return "Next game: be at the objective 30 seconds early."


def safe_name(text):
    return "".join(ch for ch in str(text) if ch.isalnum() or ch in "-_") or "unknown"


def write_match_report(coach, reason, folder=None):
    """One markdown note per match. A restart mid-game overwrites the same note instead of splitting it."""
    folder = folder or data_path("reports")
    os.makedirs(folder, exist_ok=True)
    champ = coach.me.get("championName") if coach.me else "unknown"
    pos = norm_pos(coach.me.get("position")) if coach.me else ""
    scores = scores_of(coach.me) if coach.me else {}
    kda = "%s/%s/%s" % (scores.get("kills", 0), scores.get("deaths", 0), scores.get("assists", 0))
    focus = focus_line(coach)
    us, them = coach.dragons() if coach.my_team else (0, 0)
    card = coach.card or (coach.report_card() if coach.me else {})
    lines = [
        "---",
        "type: rift-coach-match",
        "date: %s" % time.strftime("%Y-%m-%d"),
        "champion: %s" % champ,
        "role: %s" % (pos or "unknown"),
        "result: %s" % (coach.result or "unknown"),
        "kda: %s" % kda,
        "game_id: %s" % (coach.game_id or "unknown"),
        "minutes: %d" % int(coach.t // 60),
        "grades: %s" % review.encode(card),
        "reason: %s" % reason,
        "---",
        "",
        "# %s %s%s" % (champ, pos, (" - %s" % coach.result.upper()) if coach.result else ""),
        "",
        "KDA %s. Game time %s. Dragons %d to %d." % (kda, fmt_time(coach.t), us, them),
        "",
    ]
    if card:
        lines.append("## Report card")
        for area in review.AREAS:
            if area in card:
                lines.append("- %s: **%s** (%s)" % (review.AREA_NAMES[area], card[area]["grade"], card[area]["detail"]))
        _best, worst = review.best_and_worst(card)
        if worst:
            lines.append("")
            lines.append("Tip for %s: %s" % (review.AREA_NAMES[worst].lower(), review.TIPS[worst]))
        lines.append("")
    lines.append("## CS")
    if coach.cs_marks:
        for mark in (10, 15, 20):
            if mark in coach.cs_marks:
                lines.append("- %d min: %s CS" % (mark, coach.cs_marks[mark]))
    else:
        lines.append("- not sampled")
    lines.extend(["", "## Deaths"])
    if coach.death_log:
        for row in coach.death_log:
            lines.append("- %s to %s" % (fmt_time(row.get("t", 0)), row.get("by")))
    else:
        lines.append("- none recorded")
    lines.extend(["", "## Objectives"])
    if coach.objectives:
        for row in sorted(coach.objectives, key=lambda item: item.get("t", 0)):
            detail = (" " + row["detail"]) if row.get("detail") else ""
            lines.append("- %s %s %s%s" % (fmt_time(row.get("t", 0)), row.get("who"), row.get("name"), detail))
    else:
        lines.append("- none recorded")
    lines.extend(["", "## Item gold"])
    if coach.gold_curve:
        for stamp, diff in coach.gold_curve:
            lines.append("- %s %s%d" % (fmt_time(stamp), "+" if diff >= 0 else "", diff))
    else:
        lines.append("- not sampled")
    lines.extend(["", "## Focus", focus, ""])
    name = "%s-%s-%s.md" % (time.strftime("%Y%m%d"), safe_name(champ), coach.game_id or time.strftime("%H%M%S"))
    path = os.path.join(folder, name)
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    os.replace(path + ".tmp", path)
    return path


def publish_wait(coach):
    if coach.bus:
        publish_idle(coach.bus)


def publish_idle(bus):
    bus.publish({
        "in_game": False,
        "clock": "READY",
        "status": "Queue up",
        "hint": "Borderless   ·   Ctrl+Shift+O hides",
        "champion": "",
        "kda": "",
        "level": "",
        "spawns": {},
        "callouts": [],
        "spikes": [],
        "gold_diff": 0,
        "prev_gold_diff": 0,
        "position": "",
    })


def finish_game(coach, reason, live):
    if not live or coach.reported or not coach.me or coach.t < 30:
        return None
    try:
        path = write_match_report(coach, reason)
    except OSError as exc:
        # OneDrive or antivirus can briefly lock the file. Never take the coach down for it.
        print("Match note not written (%s: %s)." % (type(exc).__name__, exc), flush=True)
        return None
    coach.reported = True
    print("Match note: %s" % path, flush=True)
    return path


POLL_ERRORS = (urllib.error.URLError, ConnectionError, OSError, ValueError, json.JSONDecodeError, AttributeError)


def run_loop(args, speaker, coach, client, capture, stop, sleep=time.sleep, clock=time.monotonic):
    """Poll -> coach.tick. Survives API hiccups: one bad poll never ends a game.

    - Failures shorter than CONFIG["disconnect_grace"] are ignored.
    - After a longer outage, the same match (same ten players, clock not rewound)
      resumes with its history instead of starting over.
    """
    in_game = False
    last_t = -1
    waiting_shown = False
    fail_since = None
    last_tick_error = None
    replaying = bool(getattr(args, "demo", False) or getattr(args, "replay", None))
    delay = 0.05 if replaying else CONFIG["poll_seconds"]
    live = not replaying
    grace = 0 if replaying else CONFIG["disconnect_grace"]
    print("Macro Goblin %s running. Ctrl+C to quit." % __version__, flush=True)
    if speaker.mode == "win":
        print("Voice on. Hide overlay: Ctrl+Shift+O. League must be Borderless.", flush=True)
    elif speaker.mode:
        print("Voice on (%s)." % speaker.mode, flush=True)
    else:
        print("Text only. Hide overlay: Ctrl+Shift+O. League must be Borderless.", flush=True)
    publish_wait(coach)
    try:
        while not stop.is_set():
            try:
                data = client.get()
                t = (data.get("gameData") or {}).get("gameTime") if isinstance(data, dict) else None
                if t is None or not isinstance(data, dict) or "activePlayer" not in data:
                    raise ValueError("loading")
                t = float(t)
            except POLL_ERRORS:
                if in_game:
                    if fail_since is None:
                        fail_since = clock()
                    if clock() - fail_since < grace:
                        sleep(1)
                        continue
                    finish_game(coach, "client closed", live)
                    print("Game closed. Waiting for the next one...", flush=True)
                    in_game = False
                    publish_wait(coach)
                elif not waiting_shown:
                    print("Waiting for a game to start...", flush=True)
                    publish_wait(coach)
                waiting_shown = True
                sleep(2)
                continue
            fail_since = None

            same_match = (
                last_t >= 0
                and coach.game_id is not None
                and game_key(data) == coach.game_id
                and t >= last_t - 5
            )
            if in_game and t < last_t - 5:
                finish_game(coach, "new game", live)
                in_game = False
                same_match = False
            if not in_game:
                if same_match:
                    # Long outage, same match: keep history, capture folder, and report.
                    # Re-sync quietly so timers crossed during the gap are not all spoken at once.
                    coach.reported = False
                    coach.first_tick = True
                    print("Reconnected to the same game at %s." % fmt_time(t), flush=True)
                else:
                    coach.reset()
                    if capture:
                        capture.begin()
                        coach.on_new_event = capture.note_event
                    speaker.say("Coach online. Let's get it.", P_NORMAL)
                in_game = True
                waiting_shown = False
            last_t = t
            if capture:
                try:
                    capture.maybe_write(data)
                except OSError as exc:
                    print("Capture write skipped (%s)." % type(exc).__name__, flush=True)
            try:
                coach.tick(data)
                last_tick_error = None
            except Exception as exc:
                msg = "%s: %s" % (type(exc).__name__, exc)
                if msg != last_tick_error:
                    print("Tick error, coach still running: %s" % msg, flush=True)
                    last_tick_error = msg
            if coach.game_over:
                finish_game(coach, "game end", live)
            if isinstance(client, MockGame) and t > 1700:
                speaker.say("Demo complete.", P_NORMAL)
                sleep(0.4)
                break
            if isinstance(client, ReplayClient) and client.clock() >= client.end_time + 2:
                speaker.say("Replay complete.", P_NORMAL)
                sleep(0.2)
                break
            sleep(delay)
    except KeyboardInterrupt:
        finish_game(coach, "stopped", live)
        print("\nCoach signing off.")
    finally:
        # Also covers stops from the overlay (window closed, Ctrl+C in the UI thread).
        if in_game:
            finish_game(coach, "stopped", live)
        if capture:
            capture.close()
        stop.set()
        if coach.seen_events:
            print("Event names seen: %s" % ", ".join(sorted(coach.seen_events)), flush=True)


def doctor_check():
    """Print a buddy-friendly preflight report without starting the coach."""
    rows = []

    def add(name, ok, detail):
        rows.append((name, bool(ok), detail))

    add("Python", sys.version_info >= (3, 9), sys.version.split()[0])
    add("No required pip packages", True, "stdlib-only runtime")

    voice_mode = Speaker._detect()
    add("System voice", bool(voice_mode), voice_mode or "not found; use --no-voice")
    try:
        import voice as studio_voice
        ok, detail = studio_voice.self_test()
    except Exception as exc:
        ok, detail = False, "%s: %s" % (type(exc).__name__, exc)
    add("Studio voice", ok, detail if ok else detail + "; the system voice is used instead")

    try:
        import tkinter  # noqa: F401
        add("Tkinter / overlay UI", True, "available")
    except Exception as exc:
        add("Tkinter / overlay UI", False, "%s: %s" % (type(exc).__name__, exc))

    try:
        versions = DataDragon._get("%s/api/versions.json" % DDRAGON)
        latest = versions[0] if versions else "unknown"
        add("Riot Data Dragon", True, "latest patch %s" % latest)
    except Exception as exc:
        cached = glob.glob(data_path("cache", "ddragon-*.json.gz")) or glob.glob(BUNDLED_DDRAGON)
        add("Riot Data Dragon", bool(cached), "offline; using cached game data" if cached else "%s: %s" % (type(exc).__name__, exc))

    try:
        LiveClient().get()
        add("League Live Client", True, "reachable; in-game data available")
    except Exception as exc:
        add("League Live Client", False, "%s: not reachable; normal unless you are in an active game" % type(exc).__name__)

    add("Claude / LLM", True, "not required; only used with --claude and ANTHROPIC_API_KEY")
    add("Safety posture", True, "read-only local Riot API; no memory reads, hooks, injection, or packet sniffing")

    print("Macro Goblin %s doctor" % __version__)
    hard_fail = False
    for name, ok, detail in rows:
        mark = "OK" if ok else "WARN"
        print("[%s] %-24s %s" % (mark, name, detail))
        if not ok and name in ("Python", "Tkinter / overlay UI", "Riot Data Dragon"):
            hard_fail = True
    if hard_fail:
        print("\nDoctor found a required setup issue. Fix WARN rows above, or run without overlay/voice where noted.")
        return 1
    print("\nDoctor complete. If League Live Client warns while out of game, that is expected.")
    return 0


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Macro Goblin - local League macro companion")
    parser.add_argument("--doctor", action="store_true", help="run setup checks and exit")
    parser.add_argument("--demo", action="store_true", help="replay a real anonymized match (no League needed)")
    parser.add_argument("--synthetic", action="store_true", help="with --demo: use the old scripted fake game")
    parser.add_argument("--speed", type=float, default=10, help="demo/replay speed multiplier")
    parser.add_argument("--no-voice", action="store_true", help="print callouts only")
    parser.add_argument("--claude", action="store_true", help="add Claude tips (needs ANTHROPIC_API_KEY)")
    parser.add_argument("--capture", action="store_true", help="write raw polls to captures/<timestamp>/")
    parser.add_argument("--replay", metavar="DIR", help="replay a captures/<timestamp> directory")
    parser.add_argument("--overlay", action="store_true", help="floating overlay window; Ctrl+Shift+M toggles click-through lock")
    parser.add_argument("--overlay-edit", action="store_true", help="drag the overlay and save its position")
    parser.add_argument("--web", action="store_true", help="serve panels on 127.0.0.1:8765 only")
    parser.add_argument("--log", action="store_true", help="append callouts to logs/")
    parser.add_argument("--me", help="summoner name if auto-detect fails")
    parser.add_argument("--style", choices=STYLES, default="standard",
                        help="beginner explains why; pro keeps voice to decisions only")
    parser.add_argument("--mute", action="append", default=[], choices=sorted(CATEGORIES), metavar="KIND",
                        help="voice off for one kind of callout (repeatable): %s" % ", ".join(sorted(CATEGORIES)))
    parser.add_argument("--voice-name", default="", help='voice to use, e.g. "studio:en_US-norman-medium" or a Windows voice name')
    parser.add_argument("--no-hotkeys", action="store_true", help="skip Ctrl+Shift+R (repeat) and Ctrl+Shift+N (next)")
    parser.add_argument("--version", action="version", version="Macro Goblin %s" % __version__)
    return parser


class SessionOptions:
    """Everything one coach run needs. The launcher builds it from settings; the CLI from flags."""

    def __init__(self, **kw):
        self.demo = kw.get("demo", False)
        self.synthetic = kw.get("synthetic", False)
        self.replay = kw.get("replay")
        self.speed = float(kw.get("speed", 10))
        self.voice = kw.get("voice", True)
        self.voice_name = kw.get("voice_name", "")
        self.voice_rate = kw.get("voice_rate", 1)
        self.voice_volume = kw.get("voice_volume", 100)
        self.capture = kw.get("capture", False)
        self.log = kw.get("log", False)
        self.log_path = kw.get("log_path")
        self.web = kw.get("web", False)
        self.me = kw.get("me") or None
        self.claude = kw.get("claude", False)
        self.cs_target = kw.get("cs_target")
        self.coach_style = kw.get("coach_style", "standard")
        self.muted = list(kw.get("muted") or [])
        self.hotkeys = kw.get("hotkeys", False)


class CoachSession:
    """One running coach: voice, Data Dragon, poll loop and optional dashboard, all on background threads.

    The overlay is not part of the session; it reads session.bus from the UI thread.
    """

    def __init__(self, options, bus=None):
        self.options = options
        self.stop_event = threading.Event()
        self.bus = bus or UiBus()
        self.speaker = None
        self.coach = None
        self.worker = None
        self.error = None
        self.client_kind = "live"

    @property
    def running(self):
        return bool(self.worker and self.worker.is_alive())

    def _client(self):
        opts = self.options
        if opts.replay:
            self.client_kind = "replay"
            return ReplayClient(opts.replay, opts.speed)
        if opts.demo and os.path.exists(DEMO_GAME) and not opts.synthetic:
            self.client_kind = "demo"
            print("Demo: replaying a real anonymized match at %gx speed." % opts.speed, flush=True)
            return ReplayClient(DEMO_GAME, opts.speed)
        if opts.demo:
            self.client_kind = "demo"
            return MockGame(opts.speed)
        self.client_kind = "live"
        return LiveClient()

    def start(self):
        opts = self.options
        if opts.cs_target:
            CONFIG["cs_target_per_min"] = float(opts.cs_target)
        self.speaker = Speaker(voice=opts.voice, voice_name=opts.voice_name,
                               rate=opts.voice_rate, volume=opts.voice_volume)
        if opts.log:
            log_path = opts.log_path or data_path("logs", time.strftime("coach-%Y%m%d-%H%M%S.log"))
            try:
                self.speaker.enable_log(log_path)
                print("Logging callouts to %s" % log_path, flush=True)
            except OSError as exc:
                print("Callout log disabled (%s)." % exc, flush=True)
        claude = None
        if opts.claude:
            key = os.environ.get("ANTHROPIC_API_KEY")
            if key:
                claude = ClaudeCoach(key, CONFIG["claude_model"], self.speaker)
                print("Claude mode on (%s)." % CONFIG["claude_model"], flush=True)
            else:
                print("ANTHROPIC_API_KEY not set - running without Claude mode.", flush=True)
        self.coach = Coach(self.speaker, None, claude, bus=self.bus, me_name=opts.me,
                           style=opts.coach_style, muted=opts.muted)
        self.speaker.clock = lambda: self.coach.t
        client = self._client()
        capture = Capture(data_path("captures")) if (opts.capture and self.client_kind == "live") else None
        publish_wait(self.coach)

        def work():
            try:
                self.coach.dd = DataDragon()  # can take a few seconds on a new patch; off the UI thread
                if self.stop_event.is_set():
                    return  # stopped while loading; do not publish over a newer session
                run_loop(opts, self.speaker, self.coach, client, capture, self.stop_event,
                         sleep=self.stop_event.wait)
            except Exception as exc:  # never die silently
                self.error = "%s: %s" % (type(exc).__name__, exc)
                print("Coach stopped: %s" % self.error, flush=True)
            finally:
                self.stop_event.set()

        self.worker = threading.Thread(target=work, name="coach-poll", daemon=True)
        self.worker.start()
        if opts.hotkeys:
            try:
                import winplat
                winplat.global_hotkeys(self.on_hotkey, self.stop_event, active=self.in_game)
            except Exception as exc:
                print("Hotkeys unavailable (%s)." % exc, flush=True)
        if opts.web:
            import web_dash
            threading.Thread(target=web_dash.serve, args=(self.bus, self.stop_event),
                             name="coach-web", daemon=True).start()
        return self

    def in_game(self):
        """Hotkeys are held only during a match, so Ctrl+Shift+R/N work normally in other apps."""
        coach = self.coach
        return bool(coach and coach.me and not coach.game_over and not self.stop_event.is_set())

    def on_hotkey(self, name):
        if not self.coach:
            return
        if name == "repeat":
            self.coach.repeat_last()
        elif name == "next":
            self.coach.whats_next()

    def stop(self, timeout=5.0):
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout)
        if self.speaker:
            self.speaker.close()

    def stop_in_background(self):
        """Stop without blocking the caller (the UI thread). The match note is still written."""
        self.stop_event.set()
        threading.Thread(target=self.stop, name="coach-stop", daemon=True).start()


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    if args.doctor:
        return doctor_check()
    if args.demo and args.replay:
        raise SystemExit("Use either --demo or --replay, not both.")
    options = SessionOptions(
        demo=args.demo, synthetic=args.synthetic, replay=args.replay, speed=args.speed,
        voice=not args.no_voice, capture=args.capture, log=args.log, web=args.web,
        me=args.me, claude=args.claude, coach_style=args.style, muted=args.mute,
        voice_name=args.voice_name, hotkeys=not args.no_hotkeys,
    )
    session = CoachSession(options).start()
    try:
        if args.overlay or args.overlay_edit:
            import overlay
            # Tk swallows KeyboardInterrupt inside its callbacks. Turn Ctrl+C into a clean stop instead.
            try:
                signal.signal(signal.SIGINT, lambda *_args: session.stop_event.set())
            except (ValueError, OSError):
                pass
            try:
                overlay.run(session.bus, session.stop_event, edit=args.overlay_edit)
            except Exception as exc:
                print("Overlay failed (%s). Voice coach still running. Ctrl+C to quit." % exc, flush=True)
                while not session.stop_event.is_set():
                    time.sleep(0.5)
        else:
            while session.running:
                time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nCoach signing off.", flush=True)
    finally:
        # Let the poll thread write the match note and close the capture before exit.
        session.stop()
    return 1 if session.error else 0


if __name__ == "__main__":
    raise SystemExit(main())
