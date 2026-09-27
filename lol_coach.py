#!/usr/bin/env python3
"""
Rift Coach - a live, voice-first League of Legends coaching companion.

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
import json
import os
import queue
import random
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import shop
import patterns

LIVE_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"
DDRAGON = "https://ddragon.leagueoflegends.com"
ROOT = os.path.dirname(os.path.abspath(__file__))

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
    "gold_bank_cooldown": 120,
    "gold_diff_every": 300,
    "gold_swing_alert": 1500,
    "legendary_min_gold": 2500,
    "claude_model": "claude-haiku-4-5-20251001",
    "claude_every": 300,
    "web_host": "127.0.0.1",
    "web_port": 8765,
    "overlay": {
        "hotkey": "ctrl+shift+o",
        "callout_fade_seconds": 12,
        "layouts": {
            "1080p": {"x": 1936, "y": -95, "w": 280, "scale": 1.0, "opacity": 0.94},
            "1440p": {"x": 20, "y": 240, "w": 268, "scale": 1.15, "opacity": 0.94},
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


class Speaker:
    def __init__(self, voice=True):
        self.q = queue.Queue()
        self.mode = self._detect() if voice else None
        self.proc = None
        self.clock = lambda: 0
        self._log_fp = None
        threading.Thread(target=self._run, daemon=True).start()

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

    def say(self, text):
        line = "[%s] %s" % (fmt_time(self.clock()), text)
        print(line, flush=True)
        if self._log_fp:
            self._log_fp.write(time.strftime("%H:%M:%S ") + line + "\n")
            self._log_fp.flush()
        if self.mode:
            self.q.put(text)

    def _win_proc(self):
        if self.proc is None or self.proc.poll() is not None:
            script = (
                "Add-Type -AssemblyName System.Speech;"
                "[Console]::InputEncoding = [Text.Encoding]::UTF8;"
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "$s.Rate=0; $s.Volume=100;"
                "try { $s.SelectVoice('Microsoft Zira Desktop') } catch {}"
                "while(($l=[Console]::In.ReadLine()) -ne $null){$s.Speak($l)}"
            )
            kwargs = dict(
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
            )
            if sys.platform.startswith("win"):
                kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            self.proc = subprocess.Popen(["powershell", "-NoProfile", "-Command", script], **kwargs)
        return self.proc

    def _run(self):
        while True:
            text = self.q.get()
            try:
                if self.mode == "win":
                    proc = self._win_proc()
                    proc.stdin.write(text.replace("\n", " ") + "\n")
                    proc.stdin.flush()
                elif self.mode == "mac":
                    subprocess.run(["say", text])
                elif self.mode == "espeak":
                    subprocess.run(["espeak", text], stderr=subprocess.DEVNULL)
            except Exception:
                self.mode = None


class DataDragon:
    def __init__(self):
        self.item_gold, self.item_tags, self.champ_info = {}, {}, {}
        self.catalog = {"_by_name": {}}
        self.patch = None
        try:
            ver = self._get("%s/api/versions.json" % DDRAGON)[0]
            self.patch = ver
            items = self._get("%s/cdn/%s/data/en_US/item.json" % (DDRAGON, ver))["data"]
            for key, value in items.items():
                try:
                    iid = int(key)
                except (TypeError, ValueError):
                    continue
                self.item_gold[iid] = value.get("gold", {}).get("total", 0)
                self.item_tags[iid] = value.get("tags", [])
                maps = value.get("maps") or {}
                if maps and not maps.get("11", False):
                    continue
                if iid >= 20000:
                    continue
                name = value.get("name") or ""
                self.catalog[iid] = {
                    "name": name,
                    "gold": value.get("gold", {}).get("total", 0) or 0,
                    "tags": value.get("tags") or [],
                    "desc": value.get("description") or "",
                    "from": value.get("from") or [],
                    "into": value.get("into") or [],
                    "in_store": value.get("inStore", True),
                }
                if name:
                    self.catalog["_by_name"][name.lower()] = iid
            champs = self._get("%s/cdn/%s/data/en_US/champion.json" % (DDRAGON, ver))["data"]
            for value in champs.values():
                self.champ_info[value["id"].lower()] = value["info"]
                self.champ_info[value["name"].lower()] = value["info"]
            print("Loaded game data for patch %s." % ver)
        except Exception:
            print("Couldn't reach Data Dragon - using in-game item prices; comp read disabled.")

    @staticmethod
    def _get(url):
        with urllib.request.urlopen(url, timeout=6) as response:
            return json.load(response)

    def gold(self, item):
        return self.item_gold.get(item.get("itemID"), item.get("price", 0))

    def is_legendary(self, item):
        if item.get("consumable"):
            return False
        tags = self.item_tags.get(item.get("itemID"), [])
        name = item.get("displayName", "")
        if "Boots" in tags or "Boots" in name or "Greaves" in name or "Treads" in name:
            return False
        return self.gold(item) >= CONFIG["legendary_min_gold"]

    def info(self, player):
        raw = player.get("rawChampionName", "").replace("game_character_displayname_", "")
        for key in (raw.lower(), player.get("championName", "").lower()):
            if key in self.champ_info:
                return self.champ_info[key]
        return None


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


class Coach:
    def __init__(self, speaker, dd, claude=None, bus=None, me_name=None):
        self.say = speaker.say
        self.dd = dd
        self.claude = claude
        self.bus = bus
        self.me_name = me_name
        self.on_new_event = None
        self.reset()

    def reset(self):
        self.last_event_id = -1
        self.first_tick = True
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
        self.last_gold_bank = -999
        self.last_diff_time = 0
        self.last_diff_said = 0
        self.last_swing_time = -999
        self.deaths = 0
        self.enemy_legendaries = {}
        self.profile_done = False
        self.me6 = self.opp6 = False
        self.last_claude = 0
        self.recent = []
        self.spikes = []
        self.seen_events = set()
        self.dragon_kills = 0
        self.elder = False
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
        self.pattern_said = set()
        self.guidance = ""
        self.cs_rates = []
        self.sample_prev = 0
        self.t = 0
        self.players = []
        self.me = None
        self.my_team = None
        self.enemies = []
        self.my_names = set()
        self.last_ui_diff = 0

    def note(self, text):
        self.recent.append((self.t, text, time.time()))
        self.recent = [row for row in self.recent if self.t - row[0] < 180]

    def speak(self, text):
        self.note(text)
        self.say(text)

    def player_by_name(self, name):
        if not name:
            return None
        for player in self.players:
            if name_hit(name, names_of(player)):
                return player
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
            mine.add(self.me_name)
            mine.add(self.me_name.lower())
            mine.add(self.me_name.split("#")[0])
            mine.add(self.me_name.split("#")[0].lower())
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
        self.my_team = self.me.get("team")
        self.enemies = [player for player in self.players if player.get("team") != self.my_team]
        self.my_names = names_of(self.me) | mine

        late = self.first_tick and self.t > 30
        events = data.get("events")
        if isinstance(events, dict):
            event_list = events.get("Events") or []
        elif isinstance(events, list):
            event_list = events
        else:
            event_list = []
        self.handle_events(as_list(event_list), silent=late)
        if self.first_tick:
            self.prev_t = self.t
            self.reconcile_clock()
        else:
            self.objective_timers()
        self.enemy_comp()
        self.enemy_items(silent=self.first_tick)
        self.levels()
        self.cs_check()
        self.gold_bank(active)
        self.gold_diff()
        self.sample()
        self.shop_check(active)
        self.pattern_check()
        self.claude_checkin(periodic=True)
        self.publish()
        self.first_tick = False

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

    def handle_events(self, events, silent):
        for idx, ev in enumerate(events):
            eid = ev.get("EventID")
            if eid is None:
                eid = idx
            if eid <= self.last_event_id:
                continue
            self.last_event_id = eid
            name = ev.get("EventName")
            et = ev.get("EventTime", self.t)
            if name and name not in self.seen_events:
                self.seen_events.add(name)
                print("[event] %s" % name, flush=True)
                if self.on_new_event:
                    self.on_new_event(name)
            killer = self.player_by_name(ev.get("KillerName", ""))
            ours = killer is not None and killer.get("team") == self.my_team
            who = "We" if ours else "They"
            out = None

            if name == "DragonKill":
                self.dragon_kills += 1
                kind = ev.get("DragonType") or "a"
                stolen = " Stolen!" if is_stolen(ev) else ""
                if self.dragon_kills >= 4:
                    self.elder = True
                    nxt = et + CONFIG["elder_respawn"]
                    out = "%s took %s dragon.%s Dragon soul. Elder next at %s." % (who, kind, stolen, fmt_time(nxt))
                else:
                    nxt = et + CONFIG["dragon_respawn"]
                    out = "%s took %s dragon.%s Next dragon at %s." % (who, kind, stolen, fmt_time(nxt))
                self.spawns["dragon"] = nxt
                self.objectives.append({"t": et, "name": "dragon", "who": who, "detail": kind})
            elif name == "BaronKill":
                nxt = et + CONFIG["baron_respawn"]
                self.spawns["baron"] = nxt
                self.objectives.append({"t": et, "name": "baron", "who": who, "detail": ""})
                out = "%s took Baron. Buff lasts about 3 minutes. Next Baron at %s." % (who, fmt_time(nxt))
            elif name == "HeraldKill":
                self.spawns.pop("herald", None)
                self.objectives.append({"t": et, "name": "herald", "who": who, "detail": ""})
                out = "%s took Herald." % who
            elif name in ("HordeKill", "VoidGrubKill"):
                self.spawns.pop("grubs", None)
                self.objectives.append({"t": et, "name": "grubs", "who": who, "detail": ""})
                out = "%s took a void grub." % who
            elif name == "ChampionKill" and name_hit(ev.get("VictimName"), self.my_names):
                self.deaths += 1
                if not silent:
                    self.on_death(ev)
            elif name == "Ace":
                team = ev.get("AcingTeam")
                if team:
                    out = (
                        "Ace. Their whole team is down - look for an objective."
                        if team == self.my_team
                        else "We got aced. Reset together."
                    )
            elif name == "InhibKilled":
                out = "An inhibitor just fell."
            elif name == "GameEnd":
                self.game_over = True
                winning = ev.get("WinningTeam")
                if winning and self.my_team:
                    self.result = "win" if str(winning) == str(self.my_team) else "loss"
                raw = ev.get("Result")
                if isinstance(raw, str) and raw.lower() in ("win", "victory"):
                    self.result = "win"
                elif isinstance(raw, str) and raw.lower() in ("loss", "defeat", "fail"):
                    self.result = "loss"
                out = "Game over. %s" % focus_line(self)

            if out and not silent:
                self.speak(out)
            elif out and silent:
                self.note(out)

    def on_death(self, ev):
        killer = self.player_by_name(ev.get("KillerName", ""))
        by = killer.get("championName") if killer else (ev.get("KillerName") or "something")
        timer = 0
        try:
            timer = int(float(self.me.get("respawnTimer", 0) or 0))
        except (TypeError, ValueError):
            timer = 0
        msg = "Death %d, to %s." % (self.deaths, by)
        if timer:
            msg += " %d seconds." % timer
        if self.t < 600 and self.deaths >= 3:
            msg += " Three early deaths. Farm and stay alive for a bit."
        self.death_log.append({"t": self.t, "by": by})
        self.speak(msg)
        pattern = self.fresh_pattern()
        if self.claude:
            self.claude_checkin(trigger="I just died to %s." % by)
        elif pattern:
            self.speak(pattern)
        else:
            self.say(random.choice(DEATH_QUESTIONS))

    def objective_timers(self):
        prev = self.prev_t
        labels = {"dragon": "Elder" if self.elder else "Dragon", "grubs": "Void grubs", "herald": "Herald", "baron": "Baron"}
        for obj, at in (("grubs", CONFIG["grubs_despawn"]), ("herald", CONFIG["herald_despawn"])):
            if obj in self.spawns and prev < at <= self.t:
                self.spawns.pop(obj, None)
                self.speak("%s left the pit." % labels[obj])
        for obj, at in list(self.spawns.items()):
            for warn in CONFIG["objective_warn_seconds"]:
                mark = at - warn
                key = (obj, at, warn)
                if prev < mark <= self.t and key not in self.warned:
                    self.warned.add(key)
                    self.speak("%s in %d seconds." % (labels[obj], warn))
            key = (obj, at, 0)
            if prev < at <= self.t and key not in self.warned:
                self.warned.add(key)
                verb = "are" if obj == "grubs" else "is"
                self.speak("%s %s up." % (labels[obj], verb))
        self.prev_t = self.t

    def enemy_comp(self):
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
            self.speak("Enemy comp leans magic damage - %d AP threats. Magic resist will go a long way." % ap)
        elif ad >= 4:
            self.speak("Enemy comp leans physical - %d AD threats. Armor will go a long way." % ad)
        else:
            self.speak("Enemy damage is mixed - %d AD, %d AP." % (ad, ap))

    def enemy_items(self, silent):
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
                if not silent:
                    self.speak(label)

    def levels(self):
        try:
            my_level = int(self.me.get("level") or 0)
        except (TypeError, ValueError):
            my_level = 0
        if not self.me6 and my_level >= 6:
            self.me6 = True
            self.speak("Level 6. Ult is online.")
        pos = norm_pos(self.me.get("position"))
        if not self.opp6 and pos:
            opp = next((player for player in self.enemies if norm_pos(player.get("position")) == pos), None)
            try:
                opp_level = int(opp.get("level") or 0) if opp else 0
            except (TypeError, ValueError):
                opp_level = 0
            if opp and opp_level >= 6:
                self.opp6 = True
                label = "Their %s just hit 6. Respect the ult." % opp.get("championName")
                self.spikes.append(label)
                self.spikes = self.spikes[-8:]
                self.speak(label)

    def cs_check(self):
        if norm_pos(self.me.get("position")) == "UTILITY" or self.t < 150:
            return
        if self.t - self.last_cs < CONFIG["cs_check_every"]:
            return
        self.last_cs = self.t
        cs = scores_of(self.me).get("creepScore", 0)
        try:
            cs = int(cs)
        except (TypeError, ValueError):
            cs = 0
        rate = cs / (self.t / 60.0) if self.t else 0
        target = CONFIG["cs_target_per_min"]
        self.cs_rates.append((self.t, rate))
        self.cs_rates = self.cs_rates[-6:]
        msg = "%d minutes, %s CS. %.1f per minute." % (int(self.t // 60), int(cs), rate)
        if rate < target - 1.5 and not self._cs_is_stuck():
            msg += " Target is %g." % target
        elif self._cs_is_stuck():
            msg = "CS has been under 5 all game. Catch the wave before you fight."
        self.speak(msg)

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
        self.speak("%d gold banked." % int(gold))

    def gold_diff(self):
        if not self.enemies or self.t < 240:
            return
        diff = self.live_diff()
        periodic = self.t - self.last_diff_time >= CONFIG["gold_diff_every"]
        swing = abs(diff - self.last_diff_said) >= CONFIG["gold_swing_alert"] and self.t - self.last_swing_time > 60
        if not (periodic or swing):
            return
        self.last_diff_time = self.t
        self.last_diff_said = diff
        if swing:
            self.last_swing_time = self.t
        if abs(diff) < 500:
            self.speak("Item gold is even.")
        else:
            side = "up" if diff > 0 else "down"
            self.speak("Item gold: %s %.1fk." % (side, abs(diff) / 1000.0))

    def claude_checkin(self, periodic=False, trigger=None):
        if not self.claude or self.t < 90:
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
        diff = self.live_diff()
        spawns = ", ".join("%s at %s" % (key, fmt_time(value)) for key, value in self.spawns.items())
        recent = "; ".join("%s %s" % (fmt_time(row[0]), row[1]) for row in self.recent[-8:]) or "none"
        return (
            "Game time %s. Trigger: %s\nME: %s\nALLIES:\n%s\nENEMIES:\n%s\n"
            "Team item gold diff (us minus them): %s\nUpcoming objective spawns: %s\nRecent callouts: %s"
            % (
                fmt_time(self.t),
                trigger,
                line(self.me),
                "\n".join(line(player) for player in allies),
                "\n".join(line(player) for player in self.enemies),
                diff,
                spawns,
                recent,
            )
        )

    def shop_check(self, active):
        try:
            gold = float(active.get("currentGold") or 0)
        except (TypeError, ValueError):
            gold = 0
        me = dict(self.me)
        me["_info"] = self.dd.info(self.me) or {}
        me["_ad"] = sum(1 for enemy in self.enemies if (self.dd.info(enemy) or {}).get("attack", 0) >= (self.dd.info(enemy) or {}).get("magic", 0))
        me["_ap"] = len(self.enemies) - me["_ad"]
        me["_move_speed"] = self.move_speed
        allies = [player for player in self.players if player.get("team") == self.my_team and player is not self.me]
        catalog = getattr(self.dd, "catalog", None) or {"_by_name": {}}
        advice = shop.advise(me, self.enemies, gold, catalog, self.t, allies=allies, deaths=self.deaths)
        self.shop_lines = advice.get("lines") or []
        key = advice.get("key")
        if not advice.get("speak") or key is None:
            return
        if key == self.last_shop_key and self.t - self.last_shop_said < 90:
            return
        if self.t - self.last_shop_said < 45:
            return
        self.last_shop_key = key
        self.last_shop_said = self.t
        self.speak(advice["speak"])

    def _pattern_state(self):
        owned = set()
        for item in as_list(self.me.get("items") if self.me else []):
            if isinstance(item, dict) and item.get("itemID") is not None:
                owned.add(int(item["itemID"]))
        catalog = getattr(self.dd, "catalog", None) or {}
        return {
            "t": self.t,
            "deaths": self.death_log,
            "has_boots": shop.has_boots(owned, catalog) or shop.quest_slot_boots(
                (self.me or {}).get("position"), self.move_speed
            ),
            "cs_rates": self.cs_rates,
            "gold_curve": self.gold_curve,
            "objectives": self.objectives,
        }

    def _cs_is_stuck(self):
        rates = [rate for stamp, rate in self.cs_rates if stamp >= 12 * 60]
        return len(rates) >= 2 and rates[-1] < 5.5 and rates[-2] < 5.5

    def fresh_pattern(self):
        for note in patterns.scan(self._pattern_state()):
            if note["key"] in self.pattern_said:
                continue
            if note["key"] == "cs-stuck":
                continue
            self.pattern_said.add(note["key"])
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
            self.speak(line)

    def publish(self):
        if not self.bus or not self.me:
            return
        scores = scores_of(self.me)
        cs = scores.get("creepScore", 0)
        rate = (cs / (self.t / 60.0)) if self.t else 0
        diff = self.live_diff()
        state = {
            "t": self.t,
            "clock": fmt_time(self.t),
            "status": "live",
            "champion": self.me.get("championName") or "",
            "level": self.me.get("level") or "",
            "kda": "%s/%s/%s" % (scores.get("kills", 0), scores.get("deaths", 0), scores.get("assists", 0)),
            "spawns": dict(self.spawns),
            "elder": self.elder,
            "callouts": list(self.recent[-3:]),
            "gold_diff": diff,
            "prev_gold_diff": self.last_ui_diff,
            "cs": cs,
            "cs_rate": rate,
            "cs_target": CONFIG["cs_target_per_min"],
            "position": norm_pos(self.me.get("position")),
            "spikes": list(self.spikes[-4:]),
            "shop": ([self.guidance] if self.guidance else []) + list(self.shop_lines),
            "in_game": True,
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
        path = os.path.join(self.dir, "%04d.json" % self.n)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
        self.n += 1
        self.last_write = now
        return path


class ReplayClient:
    def __init__(self, folder, speed):
        files = sorted(glob.glob(os.path.join(folder, "*.json")))
        if not files:
            raise SystemExit("No JSON frames in %s" % folder)
        self.frames = []
        for path in files:
            with open(path, encoding="utf-8") as handle:
                self.frames.append(json.load(handle))
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
        if killers.count(top) >= 2 and top != "something":
            return "Next game: respect %s. Give the wave." % top
    return "Next game: be at the objective 30 seconds early."


def write_match_report(coach, reason, folder=None):
    folder = folder or os.path.join(ROOT, "reports")
    os.makedirs(folder, exist_ok=True)
    champ = coach.me.get("championName") if coach.me else "unknown"
    pos = norm_pos(coach.me.get("position")) if coach.me else ""
    scores = scores_of(coach.me) if coach.me else {}
    kda = "%s/%s/%s" % (scores.get("kills", 0), scores.get("deaths", 0), scores.get("assists", 0))
    focus = focus_line(coach)
    lines = [
        "---",
        "type: rift-coach-match",
        "date: %s" % time.strftime("%Y-%m-%d"),
        "champion: %s" % champ,
        "role: %s" % (pos or "unknown"),
        "result: %s" % (coach.result or "unknown"),
        "reason: %s" % reason,
        "---",
        "",
        "# %s %s" % (champ, pos),
        "",
        "KDA %s. Game time %s." % (kda, fmt_time(coach.t)),
        "",
        "## CS",
    ]
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
        for row in coach.objectives:
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
    path = os.path.join(folder, "%s-%s.md" % (time.strftime("%Y%m%d-%H%M%S"), champ))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path


def publish_wait(coach):
    if not coach.bus:
        return
    coach.bus.publish({
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
    path = write_match_report(coach, reason)
    coach.reported = True
    print("Match note: %s" % path, flush=True)
    return path


def run_loop(args, speaker, coach, client, capture, stop):
    in_game = False
    last_t = -1
    waiting_shown = False
    last_tick_error = None
    delay = 0.05 if (args.demo or args.replay) else CONFIG["poll_seconds"]
    live = not (args.demo or args.replay)
    print("Rift Coach running. Ctrl+C to quit.", flush=True)
    if speaker.mode == "win":
        print("Voice: Microsoft Zira. Hide overlay: Ctrl+Shift+O. League must be Borderless.", flush=True)
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
            except (urllib.error.URLError, ConnectionError, OSError, ValueError, json.JSONDecodeError, AttributeError):
                if in_game:
                    finish_game(coach, "client closed", live)
                    print("Game closed. Waiting for the next one...", flush=True)
                    in_game = False
                    publish_wait(coach)
                elif not waiting_shown:
                    print("Waiting for a game to start...", flush=True)
                    publish_wait(coach)
                waiting_shown = True
                time.sleep(2)
                continue

            if not in_game or t < last_t - 5:
                if in_game:
                    finish_game(coach, "new game", live)
                coach.reset()
                if capture:
                    capture.begin()
                    coach.on_new_event = capture.note_event
                in_game = True
                waiting_shown = False
                speaker.say("Coach online. Let's get it.")
            last_t = t
            if capture:
                capture.maybe_write(data)
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
            if args.demo and t > 1700:
                speaker.say("Demo complete.")
                time.sleep(0.4)
                break
            if isinstance(client, ReplayClient) and client.clock() >= client.end_time + 2:
                speaker.say("Replay complete.")
                time.sleep(0.2)
                break
            time.sleep(delay)
    except KeyboardInterrupt:
        finish_game(coach, "stopped", live)
        print("\nCoach signing off.")
    finally:
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
    add("Voice backend", bool(voice_mode), voice_mode or "not found; use --no-voice")

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
        add("Riot Data Dragon", False, "%s: %s" % (type(exc).__name__, exc))

    try:
        LiveClient().get()
        add("League Live Client", True, "reachable; in-game data available")
    except Exception as exc:
        add("League Live Client", False, "%s: not reachable; normal unless you are in an active game" % type(exc).__name__)

    add("Claude / LLM", True, "not required; only used with --claude and ANTHROPIC_API_KEY")
    add("Safety posture", True, "read-only local Riot API; no memory reads, hooks, injection, or packet sniffing")

    print("Rift Coach doctor")
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
    parser = argparse.ArgumentParser(description="Rift Coach - live League coaching companion")
    parser.add_argument("--doctor", action="store_true", help="run setup checks and exit")
    parser.add_argument("--demo", action="store_true", help="run a simulated game")
    parser.add_argument("--speed", type=float, default=10, help="demo/replay speed multiplier")
    parser.add_argument("--no-voice", action="store_true", help="print callouts only")
    parser.add_argument("--claude", action="store_true", help="add Claude tips (needs ANTHROPIC_API_KEY)")
    parser.add_argument("--capture", action="store_true", help="write raw polls to captures/<timestamp>/")
    parser.add_argument("--replay", metavar="DIR", help="replay a captures/<timestamp> directory")
    parser.add_argument("--overlay", action="store_true", help="click-through overlay window")
    parser.add_argument("--overlay-edit", action="store_true", help="drag the overlay and save its position")
    parser.add_argument("--web", action="store_true", help="serve panels on 127.0.0.1:8765 only")
    parser.add_argument("--log", action="store_true", help="append callouts to logs/")
    parser.add_argument("--me", help="summoner name if auto-detect fails")
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    if args.doctor:
        return doctor_check()
    if args.demo and args.replay:
        raise SystemExit("Use either --demo or --replay, not both.")
    stop = threading.Event()
    speaker = Speaker(voice=not args.no_voice)
    if args.log:
        log_path = os.path.join(ROOT, "logs", time.strftime("coach-%Y%m%d-%H%M%S.log"))
        speaker.enable_log(log_path)
        print("Logging callouts to %s" % log_path, flush=True)
    dd = DataDragon()
    claude = None
    if args.claude:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            claude = ClaudeCoach(key, CONFIG["claude_model"], speaker)
            print("Claude mode on (%s)." % CONFIG["claude_model"])
        else:
            print("ANTHROPIC_API_KEY not set - running without Claude mode.")
    bus = UiBus()
    coach = Coach(speaker, dd, claude, bus=bus, me_name=args.me)
    speaker.clock = lambda: coach.t
    if args.replay:
        client = ReplayClient(args.replay, args.speed)
    elif args.demo:
        client = MockGame(args.speed)
    else:
        client = LiveClient()
    capture = Capture(os.path.join(ROOT, "captures")) if args.capture else None

    needs_ui = args.overlay or args.overlay_edit or args.web
    if not needs_ui:
        run_loop(args, speaker, coach, client, capture, stop)
        return

    worker = threading.Thread(
        target=run_loop, args=(args, speaker, coach, client, capture, stop), daemon=True
    )
    worker.start()
    if args.web:
        import web_dash
        threading.Thread(target=web_dash.serve, args=(bus, stop), daemon=True).start()
    if args.overlay or args.overlay_edit:
        import overlay
        try:
            overlay.run(bus, stop, edit=args.overlay_edit)
        except Exception as exc:
            print("Overlay failed (%s). Voice coach still running. Ctrl+C to quit." % exc, flush=True)
            while not stop.is_set():
                time.sleep(0.5)
    else:
        while not stop.is_set():
            time.sleep(0.2)


if __name__ == "__main__":
    raise SystemExit(main())
