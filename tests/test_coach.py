"""Coach regressions. No live client, no network, no packages."""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lol_coach
import web_dash

BANNED = (
    "ReadProcessMemory",
    "WriteProcessMemory",
    "OpenProcess",
    "SetWindowsHookEx",
    "VirtualAllocEx",
    "CreateRemoteThread",
    "pymem",
    "frida",
)


class Silent:
    def __init__(self):
        self.lines = []

    def say(self, text):
        self.lines.append(text)


class FakeDD:
    def gold(self, item):
        return item.get("price", 0)

    def is_legendary(self, item):
        if item.get("consumable"):
            return False
        return self.gold(item) >= 2500

    def info(self, player):
        name = player.get("championName", "")
        if name in ("Syndra", "Elise", "Lulu", "Ahri"):
            return {"magic": 8, "attack": 2}
        return {"magic": 2, "attack": 8}


def frame(t, events=None, me_level=1, gold=500, pos="MIDDLE", items=None):
    me = {
        "championName": "Ahri",
        "position": pos,
        "team": "ORDER",
        "summonerName": "You",
        "riotIdGameName": "You",
        "level": me_level,
        "isDead": False,
        "respawnTimer": 0,
        "items": [],
        "scores": {"kills": 0, "deaths": 0, "assists": 0, "creepScore": int(t / 8), "wardScore": 0},
    }
    enemy = {
        "championName": "Syndra",
        "position": pos,
        "team": "CHAOS",
        "summonerName": "Enemy",
        "riotIdGameName": "Enemy",
        "level": 1,
        "isDead": False,
        "items": items or [],
        "scores": {"kills": 0, "deaths": 0, "assists": 0, "creepScore": 0, "wardScore": 0},
    }
    return {
        "activePlayer": {"summonerName": "You", "riotIdGameName": "You", "currentGold": gold, "level": me_level},
        "allPlayers": [me, enemy],
        "events": {"Events": events or []},
        "gameData": {"gameTime": t, "gameMode": "CLASSIC"},
    }


class CoachTests(unittest.TestCase):
    def setUp(self):
        self.voice = Silent()
        self.coach = lol_coach.Coach(self.voice, FakeDD())

    def test_timers_match_patch_notes(self):
        self.assertEqual(lol_coach.CONFIG["baron_first_spawn"], 1200)
        self.assertEqual(lol_coach.CONFIG["dragon_first_spawn"], 300)
        self.assertEqual(lol_coach.CONFIG["dragon_respawn"], 300)
        self.assertEqual(lol_coach.CONFIG["elder_respawn"], 360)
        self.assertEqual(lol_coach.CONFIG["grubs_first_spawn"], 480)
        self.assertEqual(lol_coach.CONFIG["herald_first_spawn"], 900)

    def test_warning_survives_a_large_tick_jump(self):
        self.coach.tick(frame(20))
        self.coach.tick(frame(250))
        self.assertIn("Dragon in 60 seconds.", self.voice.lines)

    def test_stolen_accepts_bool_and_string(self):
        self.coach.tick(frame(10))
        kill = {
            "EventID": 1,
            "EventName": "DragonKill",
            "EventTime": 400,
            "KillerName": "Enemy",
            "DragonType": "Fire",
            "Stolen": True,
        }
        self.coach.tick(frame(400, events=[kill]))
        self.assertTrue(any("Stolen!" in line for line in self.voice.lines))
        self.coach.reset()
        self.voice.lines.clear()
        self.coach.tick(frame(10))
        kill["Stolen"] = "True"
        kill["EventID"] = 2
        self.coach.tick(frame(401, events=[kill]))
        self.assertTrue(any("Stolen!" in line for line in self.voice.lines))

    def test_fourth_dragon_schedules_elder(self):
        self.coach.tick(frame(10))
        events = []
        for idx in range(4):
            events.append({
                "EventID": idx + 1,
                "EventName": "DragonKill",
                "EventTime": 300 + idx * 300,
                "KillerName": "You",
                "DragonType": "Fire",
                "Stolen": False,
            })
        self.coach.tick(frame(1200, events=events))
        self.assertTrue(self.coach.elder)
        self.assertEqual(self.coach.spawns["dragon"], 1200 + 360)
        self.assertTrue(any("Elder next" in line for line in self.voice.lines))

    def test_late_join_does_not_replay_old_callouts(self):
        events = [{
            "EventID": 1,
            "EventName": "DragonKill",
            "EventTime": 400,
            "KillerName": "Enemy",
            "DragonType": "Ocean",
            "Stolen": False,
        }]
        self.coach.tick(frame(700, events=events))
        self.assertFalse(any("dragon" in line.lower() for line in self.voice.lines))
        self.assertEqual(self.coach.spawns["dragon"], 700)

    def test_grubs_leave_at_despawn(self):
        self.coach.tick(frame(20))
        self.coach.tick(frame(890))
        self.assertIn("Void grubs left the pit.", self.voice.lines)
        self.assertNotIn("grubs", self.coach.spawns)

    def test_support_skips_cs(self):
        self.coach.tick(frame(20, pos="UTILITY"))
        self.coach.tick(frame(400, pos="UTILITY"))
        self.assertFalse(any("CS" in line for line in self.voice.lines))

    def test_me_flag_matches_riot_id(self):
        data = frame(40)
        data["activePlayer"] = {"riotId": "Austin#NA1"}
        data["allPlayers"][0]["summonerName"] = ""
        data["allPlayers"][0]["riotIdGameName"] = "Austin"
        data["allPlayers"][0]["riotIdTagline"] = "NA1"
        coach = lol_coach.Coach(self.voice, FakeDD(), me_name="Austin#NA1")
        coach.tick(data)
        self.assertFalse(coach.missed_me)
        self.assertEqual(coach.me["championName"], "Ahri")

    def test_capture_throttles_and_keeps_new_events(self):
        tmp = tempfile.mkdtemp()
        try:
            cap = lol_coach.Capture(tmp)
            first = frame(10)
            second = frame(12)
            third = frame(14, events=[{"EventID": 1, "EventName": "GameStart", "EventTime": 5}])
            self.assertIsNotNone(cap.maybe_write(first, now=100))
            self.assertIsNone(cap.maybe_write(second, now=102))
            self.assertIsNotNone(cap.maybe_write(third, now=103))
            files = sorted(os.listdir(cap.dir))
            self.assertEqual(files, ["0000.json", "0001.json"])
        finally:
            shutil.rmtree(tmp)

    def test_replay_frames_drive_coach(self):
        tmp = tempfile.mkdtemp()
        try:
            early = frame(20)
            later = frame(250)
            for idx, data in enumerate((early, later)):
                with open(os.path.join(tmp, "%04d.json" % idx), "w", encoding="utf-8") as handle:
                    json.dump(data, handle)
            client = lol_coach.ReplayClient(tmp, speed=100)
            self.assertEqual(client.end_time, 250)
            self.coach.tick(client.frames[0])
            self.coach.tick(client.frames[1])
            self.assertIn("Dragon in 60 seconds.", self.voice.lines)
        finally:
            shutil.rmtree(tmp)

    def test_source_has_no_process_hooks(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("lol_coach.py", "overlay.py", "web_dash.py", "run_coach.bat"):
            text = open(os.path.join(root, name), encoding="utf-8").read()
            for banned in BANNED:
                self.assertNotIn(banned, text, "%s contains %s" % (name, banned))

    def test_web_state_is_localhost_json(self):
        bus = lol_coach.UiBus()
        bus.publish({"ok": True, "t": 12})
        stop = threading.Event()
        port = 8766
        thread = threading.Thread(target=web_dash.serve, args=(bus, stop, "127.0.0.1", port), daemon=True)
        thread.start()
        try:
            import urllib.request
            deadline = time.time() + 3
            body = None
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen("http://127.0.0.1:%d/state" % port, timeout=1) as response:
                        body = json.loads(response.read().decode("utf-8"))
                    break
                except OSError:
                    time.sleep(0.05)
            self.assertEqual(body, {"ok": True, "t": 12})
        finally:
            stop.set()
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=1).read()
            except OSError:
                pass

    def test_tick_is_cheap(self):
        data = frame(300)
        self.coach.tick(data)
        start = time.perf_counter()
        for _ in range(500):
            self.coach.tick(frame(301))
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed / 500.0, 0.01)


if __name__ == "__main__":
    unittest.main(verbosity=2)
