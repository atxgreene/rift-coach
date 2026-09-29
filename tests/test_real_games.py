"""Regressions from real matches (anonymized fixtures in tests/fixtures/real).

Every bug here was found in real captures from 2026-09-26/27. Each fixture replays
a full game through the coach offline. No League client, voice, or network.
"""

import collections
import contextlib
import io
import os
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import lol_coach  # noqa: E402
import shop  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
REAL = os.path.join(FIX, "real")
DD = lol_coach.DataDragon(offline_file=os.path.join(FIX, "ddragon.json.gz"), quiet=True)


class Recorder:
    def __init__(self):
        self.voiced = []
        self.quiet = []

    def say(self, text, priority=lol_coach.P_NORMAL, ttl=None):
        (self.voiced if priority > lol_coach.P_QUIET else self.quiet).append(text)


def play(name):
    rec = Recorder()
    coach = lol_coach.Coach(rec, DD)
    with contextlib.redirect_stdout(io.StringIO()):
        for frame in lol_coach.load_frames(os.path.join(REAL, name)):
            coach.tick(frame)
    return coach, rec


def count(lines, needle):
    return sum(1 for line in lines if needle in line)


class RealGameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.games = {name: play(name) for name in os.listdir(REAL) if name.endswith(".jsonl.gz")}

    def test_fixtures_are_anonymized(self):
        import re
        for name in self.games:
            for frame in lol_coach.load_frames(os.path.join(REAL, name))[:1]:
                champions = {player.get("championName") for player in frame["allPlayers"]}
                for player in frame["allPlayers"]:
                    self.assertRegex(player["riotId"], r"^Player\d+#TEST$")
                    game = player["riotIdGameName"]
                    self.assertTrue(re.match(r"^Player\d+$", game) or game in champions, name)
                self.assertRegex(frame["activePlayer"]["riotId"], r"^Player\d+#TEST$")

    # --- P0: result ------------------------------------------------------
    def test_lose_result_is_recorded(self):
        # Riot sends {"EventName": "GameEnd", "Result": "Lose"}.
        self.assertEqual(self.games["veigar-mid-loss.jsonl.gz"][0].result, "loss")
        self.assertEqual(self.games["tristana-latejoin-loss.jsonl.gz"][0].result, "loss")
        self.assertEqual(self.games["kaisa-bot-win.jsonl.gz"][0].result, "win")
        self.assertEqual(lol_coach.result_of("Lose"), "loss")
        self.assertEqual(lol_coach.result_of("Win"), "win")

    # --- P0: dragon soul --------------------------------------------------
    def test_two_two_dragons_is_not_soul(self):
        coach, rec = self.games["jinx-bot-2v2-dragons.jsonl.gz"]
        self.assertEqual(coach.dragons(), (2, 2))
        self.assertIsNone(coach.soul_team)
        self.assertFalse(coach.elder)
        self.assertEqual(count(rec.voiced, "soul"), 0)
        self.assertEqual(count(rec.voiced, "Elder"), 0)

    def test_four_to_zero_is_our_soul(self):
        coach, rec = self.games["kaisa-bot-win.jsonl.gz"]
        self.assertEqual(coach.dragons(), (4, 0))
        self.assertEqual(coach.soul_team, coach.my_team)
        self.assertEqual(count(rec.voiced, "Our soul"), 1)

    def test_their_soul_at_one_to_four(self):
        coach, rec = self.games["tristana-latejoin-loss.jsonl.gz"]
        self.assertEqual(coach.dragons(), (1, 4))
        self.assertNotEqual(coach.soul_team, coach.my_team)
        self.assertEqual(count(rec.voiced, "Their soul"), 1)

    # --- P0: boots --------------------------------------------------------
    def test_no_boots_nag_when_quest_moves_boots(self):
        for name, (coach, rec) in self.games.items():
            self.assertEqual(count(rec.voiced + rec.quiet, "no boots"), 0, name)
        self.assertTrue(self.games["kaisa-bot-win.jsonl.gz"][0].boots_seen)

    def test_every_boot_counts(self):
        catalog = DD.catalog
        for name in ("Ionian Boots of Lucidity", "Boots of Swiftness", "Gluttonous Greaves", "Gunmetal Greaves"):
            iid = catalog["_by_name"][name.lower()]
            self.assertTrue(shop.has_boots({iid}, catalog), name)
            self.assertTrue(DD.is_boots({"itemID": iid, "displayName": name}), name)
        self.assertFalse(shop.has_boots({1001}, catalog), "300g Boots are not upgraded boots")

    # --- P1: noise --------------------------------------------------------
    def test_one_grub_line_per_camp_fight(self):
        for name, (coach, rec) in self.games.items():
            grub_lines = [line for line in rec.voiced if "grub" in line and " in " not in line
                          and "are up" not in line and "left the pit" not in line]
            self.assertLessEqual(len(grub_lines), 3, name)
            self.assertEqual(count(rec.voiced, "took a void grub"), 0, name)
        coach, rec = self.games["kaisa-bot-win.jsonl.gz"]
        rows = [row for row in coach.objectives if row["name"] == "grubs"]
        self.assertEqual(sum(sum(int(n) for n in row["detail"].split("-")) for row in rows), 3)

    def test_no_line_repeats_like_spam(self):
        timer_words = (" in 60 seconds.", " in 30 seconds.", " is up.", " are up.")
        for name, (coach, rec) in self.games.items():
            repeats = collections.Counter(line for line in rec.voiced if not line.endswith(timer_words))
            worst, times = repeats.most_common(1)[0]
            self.assertLessEqual(times, 3, "%s: %r x%d" % (name, worst, times))
            self.assertLessEqual(count(rec.voiced, "lead just slipped"), 2, name)

    def test_voice_budget(self):
        # Baseline before this release: about 3.6 voiced lines a minute on these games.
        for name, (coach, rec) in self.games.items():
            minutes = max(1.0, coach.t / 60.0)
            self.assertLess(len(rec.voiced) / minutes, 3.2, name)

    def test_late_join_rebuilds_history_quietly(self):
        coach, rec = self.games["tristana-latejoin-loss.jsonl.gz"]
        frames = lol_coach.load_frames(os.path.join(REAL, "tristana-latejoin-loss.jsonl.gz"))
        first = lol_coach.Coach(Recorder(), DD)
        first_rec = first.say.__self__
        with contextlib.redirect_stdout(io.StringIO()):
            first.tick(frames[0])
        self.assertEqual(len(first_rec.voiced), 1)
        self.assertTrue(first_rec.voiced[0].startswith("Coach synced at 12:27."))
        # Deaths before the coach started are still in the match report.
        pre_join = [row for row in coach.death_log if row["t"] < 747]
        self.assertGreater(len(pre_join), 0)

    def test_nothing_spoken_after_game_over(self):
        for name in ("veigar-mid-loss.jsonl.gz", "kaisa-bot-win.jsonl.gz"):
            _coach, rec = self.games[name]
            self.assertTrue(rec.voiced[-1].startswith("Game over."), rec.voiced[-3:])

    def test_report_is_one_file_per_match(self):
        import tempfile
        import shutil
        coach, _rec = self.games["veigar-mid-loss.jsonl.gz"]
        tmp = tempfile.mkdtemp()
        try:
            first = lol_coach.write_match_report(coach, "stopped", folder=tmp)
            second = lol_coach.write_match_report(coach, "game end", folder=tmp)
            self.assertEqual(first, second)
            self.assertEqual(len(os.listdir(tmp)), 1)
            with open(second, encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn("result: loss", text)
            self.assertIn("reason: game end", text)
        finally:
            shutil.rmtree(tmp)


class KillerLabelTests(unittest.TestCase):
    def test_raw_ids_become_words(self):
        self.assertEqual(lol_coach.killer_label("Turret_TOrder_L2_P3_1509986696"), "a tower")
        self.assertEqual(lol_coach.killer_label("SRU_Baron12.1.1"), "Baron")
        self.assertEqual(lol_coach.killer_label("Minion_T200L1S16N0126"), "minions")
        self.assertEqual(lol_coach.killer_label("SRU_Krug5.1.2"), "a jungle camp")
        self.assertEqual(lol_coach.killer_label("Miss Fortune"), "Miss Fortune")
        self.assertEqual(lol_coach.killer_label("x", {"championName": "Ahri"}), "Ahri")


class MageCoreTests(unittest.TestCase):
    def test_mage_first_buy_is_a_core_not_deathcap(self):
        me = {"position": "MIDDLE", "items": [], "_info": {"magic": 9, "attack": 2, "defense": 3},
              "_tags": ["Mage"], "_ad": 2, "_ap": 3, "_has_boots": False}
        advice = shop.advise(me, [], 3000, DD.catalog, 600)
        first_buy = advice["lines"][1]
        self.assertNotIn("Rabadon", first_buy)
        self.assertTrue(any(name in first_buy for name in ("Malignance", "Shadowflame")), first_buy)

    def test_battle_mage_gets_liandrys(self):
        me = {"position": "TOP", "items": [], "_info": {"magic": 7, "attack": 3, "defense": 6},
              "_tags": ["Mage", "Fighter"], "_ad": 2, "_ap": 3, "_has_boots": True}
        advice = shop.advise(me, [], 3500, DD.catalog, 600)
        self.assertIn("Liandry", advice["lines"][1])


class VoiceQueueTests(unittest.TestCase):
    def test_urgent_first_and_stale_lines_dropped(self):
        speaker = lol_coach.Speaker(voice=False)
        speaker.mode = "test"  # queue without starting a real voice
        with contextlib.redirect_stdout(io.StringIO()):
            speaker.say("low", lol_coach.P_LOW)
            speaker.say("urgent", lol_coach.P_URGENT)
            speaker.say("stale", lol_coach.P_URGENT, ttl=-1)
            speaker.say("overlay only", lol_coach.P_QUIET)
        self.assertEqual(speaker.next_line(block=False), "urgent")
        self.assertEqual(speaker.next_line(block=False), "low")
        self.assertIsNone(speaker.next_line(block=False))
        self.assertEqual(speaker.dropped, 1)


class VoiceAckTests(unittest.TestCase):
    def test_late_ack_does_not_desync_the_next_line(self):
        speaker = lol_coach.Speaker(voice=False)
        pending_at_write = []

        class Stdin(io.StringIO):
            def flush(inner):
                pending_at_write.append(speaker._acks.qsize())
                speaker._acks.put(True)  # the voice finishes this sentence

        class Proc:
            stdin = Stdin()

            def poll(self):
                return None

        speaker.proc = Proc()
        speaker._acks.put(True)  # a late "done" left over from a slow first start
        speaker._speak_win("Dragon in 30 seconds.")
        self.assertEqual(pending_at_write, [0], "stale ack must be drained before writing")
        self.assertIn("Dragon in 30 seconds.", Proc.stdin.getvalue())


class DisconnectTests(unittest.TestCase):
    """One bad poll must not end the game (it split a real Tristana game into three)."""

    def run_with_outage(self, outage_polls):
        frames = lol_coach.load_frames(os.path.join(REAL, "kaisa-bot-win.jsonl.gz"))[:80]

        class Flaky:
            def __init__(self):
                self.calls = 0

            def get(self):
                self.calls += 1
                idx = self.calls - 1
                if 30 <= idx < 30 + outage_polls:
                    raise lol_coach.urllib.error.URLError("hiccup")
                idx = idx - outage_polls if idx >= 30 + outage_polls else idx
                if idx >= len(frames):
                    stop.set()
                    raise lol_coach.urllib.error.URLError("done")
                return frames[idx]

        class Args:
            demo = False
            replay = None

        clock = {"t": 0.0}

        def sleep(seconds):
            clock["t"] += seconds

        rec = Recorder()
        rec.mode = None
        coach = lol_coach.Coach(rec, DD)
        stop = threading.Event()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            lol_coach.run_loop(Args(), rec, coach, Flaky(), None, stop, sleep=sleep, clock=lambda: clock["t"])
        return rec, coach, out.getvalue()

    def test_short_outage_keeps_the_game(self):
        rec, coach, out = self.run_with_outage(outage_polls=5)
        self.assertEqual(count(rec.voiced, "Coach online"), 1)
        self.assertNotIn("Game closed", out.split("hiccup")[0] if "hiccup" in out else out)
        self.assertGreater(coach.t, 600)

    def test_long_outage_same_match_resumes_quietly(self):
        rec, coach, out = self.run_with_outage(outage_polls=40)
        self.assertEqual(count(rec.voiced, "Coach online"), 1)
        self.assertIn("Reconnected to the same game", out)
        # Timers crossed during the gap must not all fire at once on reconnect.
        self.assertEqual(count(rec.voiced, "Coach synced"), 1)
        for line in ("Dragon in 60 seconds.", "Dragon in 30 seconds.", "Dragon is up."):
            self.assertLessEqual(rec.voiced.count(line), 1, line)

    def test_stop_mid_game_still_writes_the_match_note(self):
        written = []
        original = lol_coach.write_match_report
        lol_coach.write_match_report = lambda coach, reason, folder=None: written.append(reason) or "note.md"
        try:
            frames = lol_coach.load_frames(os.path.join(REAL, "veigar-mid-loss.jsonl.gz"))[:40]
            stop = threading.Event()

            class Client:
                n = 0

                def get(self):
                    Client.n += 1
                    if Client.n >= len(frames):
                        stop.set()  # like closing the overlay window
                    return frames[min(Client.n, len(frames) - 1)]

            class Args:
                demo = False
                replay = None

            rec = Recorder()
            rec.mode = None
            with contextlib.redirect_stdout(io.StringIO()):
                lol_coach.run_loop(Args(), rec, lol_coach.Coach(rec, DD), Client(), None, stop,
                                   sleep=lambda _s: None, clock=lambda: 0)
        finally:
            lol_coach.write_match_report = original
        self.assertEqual(written, ["stopped"])



if __name__ == "__main__":
    unittest.main(verbosity=2)
