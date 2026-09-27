import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import shop


def catalog():
    rows = {
        3123: ("Executioner's Calling", 800, ["Damage"], ["3033", "6609"], "grievous wounds"),
        3033: ("Mortal Reminder", 3000, ["Damage", "ArmorPenetration"], [], "grievous wounds"),
        6609: ("Chempunk Chainsword", 3000, ["Damage", "Health"], [], "grievous wounds"),
        3916: ("Oblivion Orb", 800, ["SpellDamage"], ["3165"], "grievous wounds"),
        3165: ("Morellonomicon", 2850, ["SpellDamage", "Health"], [], "grievous wounds"),
        3076: ("Bramble Vest", 800, ["Armor"], ["3075"], "grievous wounds"),
        3075: ("Thornmail", 2450, ["Health", "Armor"], [], "grievous wounds"),
        3035: ("Last Whisper", 1450, ["ArmorPenetration", "Damage"], ["3036"], ""),
        3036: ("Lord Dominik's Regards", 3300, ["Damage", "ArmorPenetration"], [], ""),
        6694: ("Serylda's Grudge", 3000, ["Damage", "ArmorPenetration"], [], ""),
        4630: ("Blighting Jewel", 1100, ["MagicPenetration", "SpellDamage"], ["3135"], ""),
        3135: ("Void Staff", 3000, ["MagicPenetration", "SpellDamage"], [], ""),
        3137: ("Cryptbloom", 3000, ["SpellDamage", "MagicPenetration"], [], ""),
        3047: ("Plated Steelcaps", 1200, ["Armor", "Boots"], [], ""),
        3111: ("Mercury's Treads", 1250, ["Boots", "SpellBlock"], [], ""),
        6695: ("Serpent's Fang", 2500, ["Damage"], [], "shield reaver"),
        3072: ("Bloodthirster", 3400, ["Damage", "LifeSteal"], [], "life steal"),
        3047: ("Plated Steelcaps", 1200, ["Armor", "Boots"], [], ""),
    }
    cat = {"_by_name": {}}
    for iid, (name, gold, tags, into, desc) in rows.items():
        cat[iid] = {
            "name": name, "gold": gold, "tags": tags, "desc": desc,
            "from": [], "into": into, "in_store": True,
        }
        cat["_by_name"][name.lower()] = iid
    return cat


def me(position, info, items=None, ad=2, ap=2):
    return {
        "position": position,
        "items": items or [],
        "_info": info,
        "_ad": ad,
        "_ap": ap,
    }


def add_adc_items(cat):
    for iid, name, gold, tags in (
        (3031, "Infinity Edge", 3500, ["Damage", "CriticalStrike"]),
        (3032, "Yun Tal Wildarrows", 3000, ["Damage", "CriticalStrike"]),
        (6675, "Navori Flickerblade", 2650, ["Damage", "CriticalStrike"]),
        (3026, "Guardian Angel", 3200, ["Armor", "Damage"]),
        (3006, "Berserker's Greaves", 1100, ["Boots", "AttackSpeed"]),
    ):
        cat[iid] = {"name": name, "gold": gold, "tags": tags, "desc": "", "from": [], "into": [], "in_store": True}
        cat["_by_name"][name.lower()] = iid
    return cat


class ShopTests(unittest.TestCase):
    def test_adc_versus_healing_buys_executioners(self):
        enemies = [{
            "items": [{"itemID": 3072, "displayName": "Bloodthirster", "consumable": False}],
        }]
        advice = shop.advise(me("BOTTOM", {"attack": 8, "magic": 2, "defense": 3}), enemies, 900, catalog(), 200)
        self.assertIn("healing", advice["why"])
        self.assertIn("Executioner's Calling", advice["lines"][1])
        self.assertIn("BUY", advice["lines"][1])
        self.assertIn("Executioner's", advice["speak"])

    def test_owned_component_points_at_the_legendary(self):
        enemies = [{
            "items": [{"itemID": 3072, "displayName": "Bloodthirster", "consumable": False}],
        }]
        player = me("BOTTOM", {"attack": 8, "magic": 2, "defense": 3}, [{"itemID": 3123, "consumable": False}])
        advice = shop.advise(player, enemies, 3000, catalog(), 400)
        self.assertIn("Mortal Reminder", advice["lines"][1])

    def test_tank_gets_bramble(self):
        enemies = [{
            "items": [{"itemID": 3072, "displayName": "Bloodthirster", "consumable": False}],
        }]
        player = me("TOP", {"attack": 4, "magic": 3, "defense": 8}, ad=1, ap=0)
        advice = shop.advise(player, enemies, 800, catalog(), 200)
        self.assertIn("Bramble Vest", advice["lines"][1])

    def test_quiet_when_nothing_to_counter(self):
        advice = shop.advise(me("MIDDLE", {"attack": 3, "magic": 8, "defense": 2}), [], 2000, catalog(), 200)
        self.assertEqual(advice["lines"], [])
        self.assertIsNone(advice["speak"])

    def test_does_not_recommend_an_unowned_store_item_as_a_core_build(self):
        advice = shop.advise(me("MIDDLE", {"attack": 8, "magic": 2, "defense": 4}), [], 5000, catalog(), 500)
        self.assertIsNone(advice["speak"])

    def test_team_antiheal_sends_a_crit_carry_to_ldr(self):
        enemies = [
            {"items": [
                {"itemID": 3072, "displayName": "Bloodthirster", "consumable": False},
                {"itemID": 3075, "displayName": "Thornmail", "consumable": False},
            ]},
            {"items": [{"itemID": 3047, "displayName": "Plated Steelcaps", "consumable": False}]},
        ]
        allies = [{"items": [{"itemID": 3033, "displayName": "Mortal Reminder", "consumable": False}]}]
        advice = shop.advise(
            me("BOTTOM", {"attack": 8, "magic": 2, "defense": 3}),
            enemies, 1600, catalog(), 900, allies=allies,
        )
        text = " ".join(advice["lines"])
        self.assertNotIn("Executioner's", text)
        self.assertIn("Last Whisper", text)
        self.assertIn("Lord Dominik", text)
        self.assertIn("anti-heal", advice["why"])

    def test_default_adc_core_is_yun_tal_ie_navori(self):
        cat = add_adc_items(catalog())
        advice = shop.advise(
            me("BOTTOM", {"attack": 8, "magic": 2, "defense": 3}, ad=2, ap=3),
            [],
            0,
            cat,
            500,
        )
        text = "\n".join(advice["lines"])
        self.assertLess(text.index("Yun Tal Wildarrows"), text.index("Infinity Edge"))
        self.assertLess(text.index("Infinity Edge"), text.index("Navori Flickerblade"))

    def test_full_list_keeps_owned_items_and_adapts_the_rest(self):
        cat = add_adc_items(catalog())
        player = me(
            "BOTTOM",
            {"attack": 8, "magic": 2, "defense": 3},
            [
                {"itemID": 3032, "displayName": "Yun Tal Wildarrows", "consumable": False},
                {"itemID": 6675, "displayName": "Navori Flickerblade", "consumable": False},
                {"itemID": 3031, "displayName": "Infinity Edge", "consumable": False},
            ],
            ad=4,
            ap=1,
        )
        enemies = [
            {"items": [
                {"itemID": 3072, "displayName": "Bloodthirster", "consumable": False},
                {"itemID": 3075, "displayName": "Thornmail", "consumable": False},
            ]},
            {"items": [{"itemID": 3047, "displayName": "Plated Steelcaps", "consumable": False}]},
        ]
        allies = [{"items": [{"itemID": 3033, "displayName": "Mortal Reminder", "consumable": False}]}]
        advice = shop.advise(player, enemies, 900, cat, 1800, allies=allies, deaths=6)
        text = " ".join(advice["lines"])
        self.assertIn("HAVE Yun Tal", text)
        self.assertIn("HAVE Infinity Edge", text)
        self.assertIn("Last Whisper", text)
        self.assertIn("Lord Dominik", text)
        self.assertIn("Steelcaps", text)
        self.assertNotIn("Executioner's", text)
        self.assertGreaterEqual(len(advice["lines"]), 6)

    def test_adc_quest_slot_boots_are_not_missing(self):
        player = me("BOTTOM", {"attack": 8, "magic": 2, "defense": 3}, ad=4, ap=1)
        player["_move_speed"] = 386
        advice = shop.advise(player, [], 900, catalog(), 900)
        text = " ".join(advice["lines"])
        self.assertNotIn("Steelcaps", text)
        self.assertNotIn("Berserker", text)
        self.assertIsNone(advice["speak"])
        self.assertTrue(shop.quest_slot_boots("BOTTOM", 386))
        self.assertFalse(shop.quest_slot_boots("BOTTOM", 340))
        self.assertFalse(shop.quest_slot_boots("MIDDLE", 400))


if __name__ == "__main__":
    unittest.main()
