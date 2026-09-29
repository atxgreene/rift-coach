import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hud  # noqa: E402

PERSISTED = {
    "description": "",
    "files": [{
        "name": "Game.cfg",
        "sections": [
            {"name": "General", "settings": [{"name": "Width", "value": "1920"}, {"name": "Height", "value": "1080"}]},
            {"name": "HUD", "settings": [{"name": "MinimapScale", "value": "0.3333"},
                                         {"name": "FlipMiniMap", "value": "1"}]},
        ],
    }],
}


class LeagueSettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_reads_persisted_settings(self):
        with open(os.path.join(self.dir, "PersistedSettings.json"), "w", encoding="utf-8") as handle:
            json.dump(PERSISTED, handle)
        got = hud.league_settings([self.dir])
        self.assertAlmostEqual(got["minimap_scale"], 0.3333)
        self.assertTrue(got["minimap_left"])

    def test_reads_game_cfg(self):
        with open(os.path.join(self.dir, "game.cfg"), "w", encoding="utf-8") as handle:
            handle.write("[HUD]\nMinimapScale=1.5\nFlipMiniMap=0\n")
        got = hud.league_settings([self.dir])
        self.assertEqual(got["minimap_scale"], 1.0)  # clamped
        self.assertFalse(got["minimap_left"])

    def test_missing_or_broken_files(self):
        self.assertIsNone(hud.league_settings([self.dir])["minimap_scale"])
        with open(os.path.join(self.dir, "PersistedSettings.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertIsNone(hud.league_settings([self.dir])["minimap_scale"])


class PlacementTests(unittest.TestCase):
    def test_sits_above_the_minimap_on_its_side(self):
        right = hud.default_spot(1920, 1080, 356, 70, {"minimap_scale": 0.0})
        left = hud.default_spot(1920, 1080, 356, 70, {"minimap_scale": 0.0, "minimap_left": True})
        self.assertGreater(right[0], 1500)
        self.assertLess(left[0], 20)
        self.assertEqual(right[1] + 70, 1080 - hud.minimap_px(1080, 0.0) - hud.HUD_DEFAULTS["gap"])

    def test_unknown_scale_assumes_the_biggest_minimap(self):
        unknown = hud.default_spot(1920, 1080, 356, 70, {})
        small = hud.default_spot(1920, 1080, 356, 70, {"minimap_scale": 0.0})
        self.assertLess(unknown[1], small[1])

    def test_scales_with_resolution(self):
        self.assertEqual(hud.minimap_px(2160, 0.5), 2 * hud.minimap_px(1080, 0.5))


class TextTests(unittest.TestCase):
    def test_timers_mark_the_next_pit(self):
        state = {"t": 300, "spawns": {"dragon": 300, "baron": 1200, "grubs": 340}, "elder": False}
        cells, soonest = hud.timer_cells(state)
        self.assertEqual(cells[0][:2], ("DRG", "UP"))
        self.assertEqual(cells[2][:2], ("GRB", "0:40"))
        self.assertEqual(cells[3][1], "--")
        self.assertEqual(soonest, "DRG")

    def test_next_buy(self):
        self.assertEqual(hud.next_buy({"shop": ["BUILD anti-heal", "NEXT Serrated Dirk  1000g  need 350"]}),
                         "Serrated Dirk  ·  need 350")
        self.assertEqual(hud.next_buy({"shop": ["NEXT Boots  300g  BUY"]}), "Boots  ·  buy now")
        self.assertEqual(hud.next_buy({"shop": []}), "")

    def test_latest_call_fades(self):
        state = {"callouts": [(100, "old", 1000.0), (110, "Dragon in 60 seconds.", 1010.0)]}
        self.assertEqual(hud.latest_call(state, now=1012.0), "Dragon in 60 seconds.")
        self.assertEqual(hud.latest_call(state, now=1030.0), "")

    def test_clip(self):
        self.assertEqual(hud.clip("abcdef", 4), "abc…")
        self.assertEqual(hud.clip("abc", 4), "abc")


if __name__ == "__main__":
    unittest.main()
