"""1.2 features: coach style, muted kinds, vision and back-timing calls, report card, trends, hotkeys."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lol_coach  # noqa: E402
import review  # noqa: E402
from test_coach import FakeDD, Silent, frame  # noqa: E402

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
REAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "real")


def coach_with(style="standard", muted=()):
    voice = Silent()
    return lol_coach.Coach(voice, FakeDD(), style=style, muted=muted), voice


class StyleTests(unittest.TestCase):
    def test_beginner_adds_the_why_twice_then_stops(self):
        coach, voice = coach_with("beginner")
        coach.tick(frame(10))
        coach.tick(frame(240))
        self.assertIn("Dragon in 60 seconds. Push your wave first, then walk over with your team.", voice.lines)
        coach.spawns["dragon"] = 700
        coach.tick(frame(640))
        coach.spawns["dragon"] = 1100
        coach.tick(frame(1040))
        plain = [line for line in voice.lines if line.startswith("Dragon in 60")]
        self.assertEqual(plain[-1], "Dragon in 60 seconds.")

    def test_standard_has_no_why(self):
        coach, voice = coach_with("standard")
        coach.tick(frame(10))
        coach.tick(frame(240))
        self.assertIn("Dragon in 60 seconds.", voice.lines)

    def test_pro_moves_low_lines_and_reflections_to_the_overlay(self):
        coach, voice = coach_with("pro")
        coach.tick(frame(10))
        coach.speak("gold banked", lol_coach.P_LOW, cat="shop")
        coach.speak("Was that worth it?", lol_coach.P_NORMAL, cat="reflect")
        coach.speak("Baron in 30 seconds.", lol_coach.P_URGENT, cat="objective")
        self.assertEqual(voice.lines, ["Baron in 30 seconds."])
        self.assertIn("gold banked", voice.quiet)
        self.assertTrue(any(row[1] == "gold banked" for row in coach.recent))  # still on the overlay

    def test_why_is_not_used_up_by_overlay_only_lines(self):
        coach, voice = coach_with("beginner")
        coach.tick(frame(10))
        for _ in range(3):
            coach.speak("CS low.", lol_coach.P_QUIET, cat="farm", why="Each wave is about 125 gold.")
        coach.speak("CS low.", lol_coach.P_NORMAL, cat="farm", why="Each wave is about 125 gold.")
        self.assertEqual(voice.lines[-1], "CS low. Each wave is about 125 gold.")

    def test_unknown_style_falls_back(self):
        coach, _voice = coach_with("wizard")
        self.assertEqual(coach.style, "standard")

    def test_muted_kind_stays_on_the_overlay(self):
        coach, voice = coach_with(muted=["objective"])
        coach.tick(frame(10))
        coach.tick(frame(240))
        self.assertNotIn("Dragon in 60 seconds.", voice.lines)
        self.assertIn("Dragon in 60 seconds.", voice.quiet)

    def test_every_spoken_line_has_a_kind(self):
        with open(os.path.join(os.path.dirname(TOOLS), "lol_coach.py"), encoding="utf-8") as handle:
            source = handle.read()
        coach_src = source[source.index("class Coach:"):source.index("class LiveClient:")]
        import re
        calls = re.findall(r"self\.speak\((.*?)\)\n", coach_src, flags=re.S)
        untagged = [c for c in calls if "cat=" not in c and "sync_line" not in c and "Game over" not in c]
        self.assertEqual(untagged, [])


class NewCallTests(unittest.TestCase):
    def test_control_ward_reminder_limited(self):
        coach, voice = coach_with()
        coach.tick(frame(10))
        for minute in range(8, 40):
            coach.tick(frame(minute * 60))
        ward = [line for line in voice.lines + voice.quiet if "control ward" in line.lower()]
        self.assertGreaterEqual(len(ward), 1)
        self.assertLessEqual(len(ward), lol_coach.CONFIG["vision_reminders"])

    def test_no_reminder_when_holding_a_control_ward_and_vision_is_fine(self):
        coach, voice = coach_with()
        coach.tick(frame(10))
        data = frame(600)
        me = data["allPlayers"][0]
        me["items"] = [{"itemID": lol_coach.CONTROL_WARD, "displayName": "Control Ward", "count": 1}]
        me["scores"]["wardScore"] = 20
        coach.tick(data)
        self.assertFalse(any("ward" in line.lower() for line in voice.lines + voice.quiet))

    def test_back_timing_before_dragon_with_gold(self):
        coach, voice = coach_with()
        coach.tick(frame(10))
        coach.tick(frame(205, gold=1500))
        coach.tick(frame(212, gold=1500))
        self.assertTrue(any("Dragon in 90. You have 1500 gold" in line for line in voice.lines), voice.lines)

    def test_no_back_timing_when_broke(self):
        coach, voice = coach_with()
        coach.tick(frame(10))
        coach.tick(frame(212, gold=400))
        self.assertFalse(any("back and shop" in line for line in voice.lines))

    def test_repeat_and_next(self):
        coach, voice = coach_with()
        coach.repeat_last()
        self.assertEqual(voice.lines[-1], "Nothing to repeat yet.")
        coach.tick(frame(10))
        coach.tick(frame(240))
        before = voice.lines[-1]
        coach.repeat_last()
        self.assertEqual(voice.lines[-1], before)
        coach.whats_next()
        self.assertTrue(voice.lines[-1].startswith("Dragon in 1:0"), voice.lines[-1])


    def test_next_reads_the_item_name_and_cost(self):
        coach, voice = coach_with()
        coach.tick(frame(10))
        coach.shop_lines = ["NEXT Serrated Dirk  1000g  need 350", "LATER Opportunity"]
        coach.whats_next()
        self.assertIn("Buy next: Serrated Dirk, 1000 gold.", voice.lines[-1])
        self.assertNotIn("NEXT", voice.lines[-1])

    def test_hotkeys_only_held_in_a_match(self):
        session = lol_coach.CoachSession(lol_coach.SessionOptions(voice=False))
        self.assertFalse(session.in_game())
        coach, _voice = coach_with()
        session.coach = coach
        coach.tick(frame(10))
        self.assertTrue(session.in_game())
        coach.game_over = True
        self.assertFalse(session.in_game())


class ReportCardTests(unittest.TestCase):
    def test_short_games_get_no_card(self):
        self.assertEqual(review.report_card({"minutes": 6, "cs": 50}), {})

    def test_grades(self):
        card = review.report_card({
            "minutes": 30, "role": "MIDDLE", "cs": 240, "kills": 8, "deaths": 2, "assists": 10,
            "team_kills": 25, "ward_score": 30, "objectives_us": 5, "objectives_them": 1, "cs_target": 8,
        })
        self.assertEqual(card["farming"]["grade"], "A")      # 8.0 a minute
        self.assertEqual(card["fighting"]["grade"], "A")     # 72% KP
        self.assertEqual(card["survival"]["grade"], "A")
        self.assertEqual(card["vision"]["grade"], "A")       # 1.0 a minute
        self.assertEqual(card["objectives"]["grade"], "A")
        self.assertEqual(review.best_and_worst(card), ("farming", None))

    def test_support_is_not_graded_on_cs_and_needs_more_vision(self):
        card = review.report_card({"minutes": 30, "role": "UTILITY", "cs": 30, "deaths": 6,
                                   "ward_score": 30, "cs_target": 8})
        self.assertNotIn("farming", card)
        self.assertEqual(card["vision"]["grade"], "C")
        self.assertEqual(card["survival"]["grade"], "B")
        self.assertIn("vision", review.spoken_summary(card).lower())

    def test_encode_round_trip(self):
        card = {"farming": {"grade": "B"}, "vision": {"grade": "D"}}
        self.assertEqual(review.encode(card), "farming=B vision=D")
        self.assertEqual(review.decode("farming=B vision=D junk=A"), {"farming": "B", "vision": "D"})

    def test_real_game_report_has_card_and_game_over_line(self):
        sys.path.insert(0, TOOLS)
        import replay_eval
        dd = replay_eval.data_dragon()
        coach, rec, _minutes = replay_eval.replay(os.path.join(REAL, "kaisa-bot-win.jsonl.gz"), dd)
        self.assertTrue(coach.card)
        last = [text for _t, p, text in rec.lines if p > lol_coach.P_QUIET][-1]
        self.assertTrue(last.startswith("Game over. Report card. Best:"), last)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = lol_coach.write_match_report(coach, "game end", folder=folder)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("## Report card", text)
        self.assertRegex(text, r"grades: farming=[ABCD] ")


class TrendTests(unittest.TestCase):
    def test_record_streak_champs_and_weakest(self):
        games = [
            {"champion": "Ahri", "result": "win", "grades": {"farming": "B", "vision": "D"}},
            {"champion": "Ahri", "result": "win", "grades": {"farming": "A", "vision": "C"}},
            {"champion": "Zed", "result": "loss", "grades": {"farming": "B", "vision": "D"}},
            {"champion": "Ahri", "result": "", "grades": {}},
        ]
        info = review.trends(games)
        self.assertEqual((info["wins"], info["losses"]), (2, 1))
        self.assertEqual(info["streak"], "2 wins in a row")
        self.assertEqual(info["champions"][0], ("Ahri", 2, 0))
        self.assertEqual(info["weakest"], "vision")
        self.assertEqual(info["strongest"], "farming")

    def test_no_history(self):
        info = review.trends([])
        self.assertEqual(info["wins"] + info["losses"], 0)
        self.assertIsNone(info["weakest"])


class SettingsTests(unittest.TestCase):
    def test_style_and_mutes_are_validated(self):
        import settings
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        with mock.patch.object(lol_coach, "DATA", home):
            with open(os.path.join(home, "settings.json"), "w", encoding="utf-8") as handle:
                json.dump({"coach_style": "godlike", "muted": ["farm", "nonsense", 3], "hotkeys": "yes"}, handle)
            data = settings.load()
        self.assertEqual(data["coach_style"], "standard")
        self.assertEqual(data["muted"], ["farm"])
        self.assertIs(data["hotkeys"], True)

    def test_cli_flags(self):
        args = lol_coach.build_arg_parser().parse_args(["--style", "pro", "--mute", "farm", "--mute", "vision"])
        self.assertEqual(args.style, "pro")
        self.assertEqual(args.mute, ["farm", "vision"])


if __name__ == "__main__":
    unittest.main()
