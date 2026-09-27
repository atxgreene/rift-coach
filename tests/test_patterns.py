import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import patterns


class PatternTests(unittest.TestCase):
    def test_repeat_killer_replaces_a_generic_question(self):
        deaths = [{"t": 100, "by": "Caitlyn"}, {"t": 200, "by": "Caitlyn"}, {"t": 300, "by": "Caitlyn"}]
        notes = patterns.scan({"t": 300, "deaths": deaths})
        self.assertEqual(notes[0]["key"], "killer:Caitlyn:3")
        self.assertIn("Stop taking that fight", notes[0]["line"])

    def test_death_spiral(self):
        deaths = [{"t": 1700, "by": "Caitlyn"}, {"t": 1800, "by": "Yasuo"}, {"t": 1900, "by": "Caitlyn"}]
        notes = patterns.scan({"t": 1900, "deaths": deaths})
        self.assertTrue(any(note["key"].startswith("spiral:") for note in notes))

    def test_cs_stuck_and_missing_boots(self):
        notes = patterns.scan({
            "t": 1500,
            "deaths": [],
            "has_boots": False,
            "cs_rates": [(800, 4.4), (980, 4.6)],
        })
        keys = [note["key"] for note in notes]
        self.assertIn("boots:20", keys)
        self.assertIn("cs-stuck", keys)

    def test_dragon_for_baron_trade(self):
        notes = patterns.scan({
            "t": 2000,
            "objectives": [
                {"t": 1700, "who": "We", "name": "dragon"},
                {"t": 1810, "who": "They", "name": "baron"},
            ],
        })
        self.assertTrue(any("Baron" in note["line"] for note in notes))


if __name__ == "__main__":
    unittest.main()
