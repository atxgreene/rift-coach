"""Launcher logic that does not need a display: settings, updates, match-note parsing."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lol_coach  # noqa: E402
import settings  # noqa: E402
import updates  # noqa: E402
import app  # noqa: E402


class TempData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = lol_coach.DATA
        lol_coach.DATA = self.tmp

    def tearDown(self):
        lol_coach.DATA = self.old
        shutil.rmtree(self.tmp)


class SettingsTests(TempData):
    def test_defaults_then_round_trip(self):
        data = settings.load()
        self.assertTrue(data["voice"])
        self.assertFalse(data["first_run_done"])
        data["voice"] = False
        data["voice_rate"] = 3
        settings.save(data)
        again = settings.load()
        self.assertFalse(again["voice"])
        self.assertEqual(again["voice_rate"], 3)

    def test_bad_values_are_clamped_or_ignored(self):
        with open(settings.path(), "w", encoding="utf-8") as handle:
            handle.write('{"voice": "yes", "voice_rate": 99, "cs_target": 1, "unknown": 5}')
        data = settings.load()
        self.assertTrue(data["voice"])           # wrong type -> default
        self.assertEqual(data["voice_rate"], 10)  # clamped
        self.assertEqual(data["cs_target"], 3.0)  # clamped
        self.assertNotIn("unknown", data)

    def test_corrupt_file_falls_back_to_defaults(self):
        with open(settings.path(), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(settings.load(), settings.DEFAULTS)


class UpdateTests(unittest.TestCase):
    def test_version_compare(self):
        self.assertEqual(updates.parse_version("v1.2.10"), (1, 2, 10))
        self.assertEqual(updates.parse_version("1.1"), (1, 1, 0))
        current = lol_coach.__version__
        self.assertTrue(updates.newer_than_current({"version": "99.0.0"}))
        self.assertFalse(updates.newer_than_current({"version": current}))
        self.assertFalse(updates.newer_than_current(None))


class ReportListTests(TempData):
    def test_reads_new_and_old_notes(self):
        folder = os.path.join(self.tmp, "reports")
        os.makedirs(folder)
        coach = lol_coach.Coach(type("S", (), {"say": lambda *a, **k: None})(), None)
        coach.me = {"championName": "Ahri", "position": "MIDDLE",
                    "scores": {"kills": 5, "deaths": 1, "assists": 7}}
        coach.result = "win"
        coach.t = 1500
        coach.game_id = "abc12345"
        coach.death_log = [{"t": 300, "by": "Zed"}, {"t": 400, "by": "Zed"}]
        lol_coach.write_match_report(coach, "game end", folder=folder)
        with open(os.path.join(folder, "20260926-old.md"), "w", encoding="utf-8") as handle:
            handle.write("---\ntype: rift-coach-match\nchampion: Tristana\nrole: BOTTOM\nresult: unknown\n---\n\n"
                         "KDA 10/5/4. Game time 25:00.\n\n## Focus\nNext game: respect Akali. Give the wave.\n")
        rows = app.read_reports(folder)
        by_champ = {row["champion"]: row for row in rows}
        self.assertEqual(by_champ["Ahri"]["result"], "win")
        self.assertEqual(by_champ["Ahri"]["kda"], "5/1/7")
        self.assertEqual(by_champ["Ahri"]["role"], "Mid")
        self.assertEqual(by_champ["Tristana"]["kda"], "10/5/4")
        self.assertEqual(by_champ["Tristana"]["focus"], "respect Akali. Give the wave.")

    def test_next_objective_text(self):
        self.assertEqual(app.next_objective({"t": 600, "spawns": {"dragon": 700, "baron": 1200}})[0],
                         "Dragon in 1:40")
        self.assertEqual(app.next_objective({"t": 800, "spawns": {"dragon": 700}, "elder": True})[0],
                         "Elder is up")
        self.assertIsNone(app.next_objective({"t": 10, "spawns": {}}))


class DataDirTests(unittest.TestCase):
    def test_source_checkout_writes_next_to_code(self):
        if lol_coach.FROZEN or os.environ.get("MACROGOBLIN_HOME"):
            self.skipTest("only meaningful when running from source")
        self.assertEqual(os.path.abspath(lol_coach.DATA),
                         os.path.dirname(os.path.abspath(lol_coach.__file__)))


if __name__ == "__main__":
    unittest.main()
