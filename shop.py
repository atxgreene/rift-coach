"""Situational shop list from the scoreboard and Data Dragon.

The card is a full adapting list: items you already finished, then the
empty slots rewritten from the live game. It does not copy a champion
build page. Voice only speaks the next click when that click is a
counter or the boots the comp already justifies.
"""

HEAL_NAMES = {
    "bloodthirster",
    "blade of the ruined king",
    "ravenous hydra",
    "goredrinker",
    "riftmaker",
    "moonstone renewer",
    "redemption",
    "mikael's blessing",
    "spirit visage",
    "immortal shieldbow",
}
SHIELD_NAMES = {
    "immortal shieldbow",
    "sterak's gage",
    "locket of the iron solari",
    "eclipse",
    "seraph's embrace",
    "crown of the shattered queen",
    "edge of night",
}
GRIEVOUS_NAMES = {
    "executioner's calling",
    "oblivion orb",
    "bramble vest",
    "mortal reminder",
    "morellonomicon",
    "thornmail",
    "chempunk chainsword",
}


def plain(text):
    out = []
    skip = False
    for char in text or "":
        if char == "<":
            skip = True
            continue
        if char == ">":
            skip = False
            continue
        if not skip:
            out.append(char)
    return "".join(out).lower()


def owned_ids(player):
    found = set()
    for item in player.get("items") or []:
        if isinstance(item, dict) and item.get("itemID") is not None:
            found.add(int(item["itemID"]))
    return found


def record(catalog, item_id):
    if not catalog:
        return {}
    return catalog.get(int(item_id)) or catalog.get(str(item_id)) or {}


def owns(owned, item_id, catalog):
    item_id = int(item_id)
    if item_id in owned:
        return True
    rec = record(catalog, item_id)
    for upgrade in rec.get("into") or []:
        try:
            if int(upgrade) in owned:
                return True
        except (TypeError, ValueError):
            continue
    for owned_id in owned:
        if item_id in [int(x) for x in (record(catalog, owned_id).get("from") or []) if str(x).isdigit()]:
            return True
    return False


def find_name(catalog, name):
    if not catalog:
        return None
    by_name = catalog.get("_by_name") or {}
    return by_name.get(name.lower())


def style_of(me, catalog):
    ad = ap = 0
    for item_id in owned_ids(me):
        tags = record(catalog, item_id).get("tags") or []
        if "SpellDamage" in tags:
            ap += 1
        if "Damage" in tags:
            ad += 1
    if ap > ad and ap > 0:
        return "ap"
    if ad > ap and ad > 0:
        return "ad"
    info = me.get("_info") or {}
    defense = info.get("defense", 0) or 0
    attack = info.get("attack", 0) or 0
    magic = info.get("magic", 0) or 0
    pos = me.get("position") or ""
    if defense >= 7 and attack <= 5 and magic <= 5 and pos in ("TOP", "JUNGLE", "UTILITY"):
        return "tank"
    if magic > attack:
        return "ap"
    return "ad"


def _enemy_flags(player, catalog):
    heal = shield = armor = mr = False
    for item in player.get("items") or []:
        if not isinstance(item, dict) or item.get("consumable"):
            continue
        iid = item.get("itemID")
        rec = record(catalog, iid) if iid is not None else {}
        name = (item.get("displayName") or rec.get("name") or "").lower()
        tags = rec.get("tags") or []
        desc = plain(rec.get("desc") or "")
        try:
            gold = int(rec.get("gold") or item.get("price") or 0)
        except (TypeError, ValueError):
            gold = 0
        if gold >= 2000 and ("LifeSteal" in tags or "SpellVamp" in tags or name in HEAL_NAMES):
            heal = True
        if gold >= 2000 and "heal and shield power" in desc:
            heal = True
        if name in SHIELD_NAMES or (gold >= 2500 and "shield" in desc and "grievous" not in desc):
            shield = True
        if "Armor" in tags and gold >= 1000:
            armor = True
        if "SpellBlock" in tags and gold >= 800:
            mr = True
    return heal, shield, armor, mr


def has_grievous(owned, catalog):
    for item_id in owned:
        name = (record(catalog, item_id).get("name") or "").lower()
        desc = plain(record(catalog, item_id).get("desc") or "")
        if name in GRIEVOUS_NAMES or "grievous" in desc:
            return True
    return False


BOOT_WORDS = ("Boots", "Greaves", "Treads", "Steelcaps", "Shoes")


def is_boots_record(rec):
    name = rec.get("name") or ""
    return "Boots" in (rec.get("tags") or []) or any(word in name for word in BOOT_WORDS)


def has_boots(owned, catalog):
    """Upgraded boots (anything past the 300g Boots). Gunmetal Greaves has no Boots tag, so names count too."""
    for item_id in owned:
        if int(item_id) == 1001:
            continue
        if is_boots_record(record(catalog, item_id)):
            return True
    return False


def quest_slot_boots(position, move_speed):
    """Bot quest moves boots out of the six slots. The live client does not send that slot.

    Tier-2 boots are +45 move speed. 365 is above base speed plus a cloud soul,
    and below a finished boot.
    """
    if (position or "") != "BOTTOM":
        return False
    try:
        speed = float(move_speed or 0)
    except (TypeError, ValueError):
        return False
    return speed >= 365


def step(catalog, name, note):
    item_id = find_name(catalog, name)
    if not item_id:
        return None
    rec = record(catalog, item_id)
    if rec.get("in_store") is False:
        return None
    return {
        "id": int(item_id),
        "name": rec.get("name") or name,
        "cost": int(rec.get("gold") or 0),
        "note": note,
    }


def grievous_path(style, position, owned, catalog):
    crit = any("CriticalStrike" in (record(catalog, iid).get("tags") or []) for iid in owned)
    if style == "tank":
        return ("Bramble Vest", "Thornmail")
    if style == "ap" or position == "UTILITY":
        return ("Oblivion Orb", "Morellonomicon")
    if position == "BOTTOM" or crit:
        return ("Executioner's Calling", "Mortal Reminder")
    return ("Executioner's Calling", "Chempunk Chainsword")


def ally_has_grievous(player, catalog):
    if has_grievous(owned_ids(player), catalog):
        return True
    for item in player.get("items") or []:
        if not isinstance(item, dict):
            continue
        if (item.get("displayName") or "").lower() in GRIEVOUS_NAMES:
            return True
    return False


CLICK = {
    "Mortal Reminder": "Executioner's Calling",
    "Chempunk Chainsword": "Executioner's Calling",
    "Morellonomicon": "Oblivion Orb",
    "Thornmail": "Bramble Vest",
    "Lord Dominik's Regards": "Last Whisper",
    "Serylda's Grudge": "Last Whisper",
    "Void Staff": "Blighting Jewel",
    "Cryptbloom": "Blighting Jewel",
}


def role_of(style, position, crit_carry):
    if position == "UTILITY" and style != "tank":
        return "enchanter"
    if style == "tank":
        return "tank"
    if style == "ap":
        return "mage"
    if crit_carry:
        return "adc"
    return "fighter"


def boots_name(role, ad, ap):
    if ad >= 4 and role != "mage":
        return "Plated Steelcaps"
    if ap >= 4:
        return "Mercury's Treads"
    if role == "adc":
        return "Berserker's Greaves"
    if role == "mage":
        return "Sorcerer's Shoes" if ad < 4 else "Plated Steelcaps"
    if role == "enchanter":
        return "Ionian Boots of Lucidity"
    if role == "tank":
        return "Plated Steelcaps" if ad >= ap else "Mercury's Treads"
    if ap > ad:
        return "Mercury's Treads"
    if ad >= 3:
        return "Plated Steelcaps"
    return "Plated Steelcaps" if ad >= ap else "Mercury's Treads"


def held_completed(player, catalog):
    found = []
    for item in player.get("items") or []:
        if not isinstance(item, dict) or item.get("consumable"):
            continue
        iid = item.get("itemID")
        rec = record(catalog, iid) if iid is not None else {}
        name = item.get("displayName") or rec.get("name") or ""
        tags = rec.get("tags") or []
        try:
            gold = int(rec.get("gold") or 0)
        except (TypeError, ValueError):
            gold = 0
        if not name:
            continue
        if "Boots" in tags and gold >= 1100:
            found.append(name)
        elif gold >= 2000:
            found.append(name)
    return found


def core_items(role, tags):
    """First legendaries by class. Only names that exist on the current patch survive step()."""
    if role == "adc":
        return ["Yun Tal Wildarrows", "Infinity Edge", "Navori Flickerblade"]
    if role == "mage":
        if "Fighter" in tags or "Tank" in tags:
            return ["Liandry's Torment", "Riftmaker"]
        if "Assassin" in tags:
            return ["Hextech Rocketbelt", "Shadowflame"]
        if "Support" in tags:
            return ["Malignance", "Liandry's Torment"]
        return ["Malignance", "Shadowflame"]
    if role == "fighter":
        return ["Sterak's Gage"] if "Tank" in tags else []
    return []


def slot_names(ctx):
    names = []

    def add(name):
        if name and name not in names:
            names.append(name)

    role = ctx["role"]
    if role == "adc":
        if ctx["heal"] and not ctx["skip_grievous"]:
            add("Mortal Reminder")
        if ctx["armor"] >= 2 or ctx["skip_grievous"]:
            add("Lord Dominik's Regards")
    elif role == "fighter":
        if ctx["heal"] and not ctx["team_cut"]:
            add("Chempunk Chainsword")
        if ctx["armor"] >= 2:
            add("Serylda's Grudge")
        if ctx["shield"] >= 2:
            add("Serpent's Fang")
    elif role == "mage":
        if ctx["heal"] and not ctx["team_cut"]:
            add("Morellonomicon")
        if ctx["mr"] >= 2:
            add("Void Staff")
        # Defensive picks come after the first core item; a mage with no damage item
        # gains nothing from buying Banshee's first.
        cores = core_items(role, ctx.get("tags") or [])
        if cores and not ctx.get("has_core"):
            add(cores[0])
        if ctx["ad"] >= 3 or ctx["deaths"] >= 3:
            add("Zhonya's Hourglass")
        if ctx["ap"] >= 3:
            add("Banshee's Veil")
    elif role == "tank":
        if ctx["heal"]:
            add("Thornmail")
        if ctx["ad"] >= 3:
            add("Frozen Heart")
        if ctx["ap"] >= 3:
            add("Force of Nature")
    else:
        if ctx["heal"] and not ctx["team_cut"]:
            add("Morellonomicon")
    if not ctx["has_boots"] and (ctx["ad"] >= 4 or ctx["ap"] >= 4):
        add(boots_name(role, ctx["ad"], ctx["ap"]))
    for name in core_items(role, ctx.get("tags") or []):
        add(name)
    if not ctx["has_boots"]:
        add(boots_name(role, ctx["ad"], ctx["ap"]))
    if ctx["deaths"] >= 4 and role in ("adc", "fighter", "mage"):
        add("Guardian Angel" if role != "mage" else "Zhonya's Hourglass")
    finishers = {
        "adc": ["Bloodthirster", "Infinity Edge", "Guardian Angel", "Mercurial Scimitar"],
        "fighter": ["Sterak's Gage", "Death's Dance", "Maw of Malmortius", "Guardian Angel"],
        "mage": ["Rabadon's Deathcap", "Zhonya's Hourglass", "Banshee's Veil"],
        "tank": ["Thornmail", "Frozen Heart", "Force of Nature", "Randuin's Omen"],
        "enchanter": ["Redemption", "Staff of Flowing Water", "Mikael's Blessing"],
    }
    for name in finishers.get(role, []):
        add(name)
    return names


def click_for(finished_name, owned, catalog, note):
    finished = step(catalog, finished_name, note)
    if not finished or owns(owned, finished["id"], catalog):
        return None
    component_name = CLICK.get(finished_name)
    if component_name:
        component = step(catalog, component_name, note)
        if component and not owns(owned, component["id"], catalog):
            component["into_name"] = finished["name"]
            return component
    finished["into_name"] = ""
    return finished


def spoken_reason(note, ad=0, ap=0, name=""):
    if note == "heal":
        return "for their healing"
    if note == "pen":
        magic = any(word in name for word in ("Void", "Blighting", "Cryptbloom"))
        return "for their magic resist" if magic else "for their armor"
    if note == "shield":
        return "for their shields"
    if note == "boots":
        return "for their %s damage" % ("physical" if ad >= ap else "magic")
    return "next item"


def advise(me, enemies, gold, catalog, game_time=0, allies=None, deaths=0):
    """Return a shop card. lines are overlay text. speak is None or one sentence."""
    empty = {"why": "", "lines": [], "speak": None, "key": None}
    if not me or not catalog or not catalog.get("_by_name"):
        return empty
    me = dict(me)
    owned = owned_ids(me)
    style = style_of(me, catalog)
    pos = me.get("position") or ""
    crit = any("CriticalStrike" in (record(catalog, iid).get("tags") or []) for iid in owned)
    crit_carry = pos == "BOTTOM" or crit
    team_cut = sum(1 for ally in (allies or []) if ally_has_grievous(ally, catalog))
    heal = shield = armor = mr = 0
    for enemy in enemies or []:
        flags = _enemy_flags(enemy, catalog)
        heal += int(flags[0])
        shield += int(flags[1])
        armor += int(flags[2])
        mr += int(flags[3])
    ad = me.get("_ad", 0)
    ap = me.get("_ap", 0)
    if me.get("_has_boots") is not None:
        current_has_boots = bool(me.get("_has_boots")) or has_boots(owned, catalog)
    else:
        current_has_boots = has_boots(owned, catalog) or quest_slot_boots(pos, me.get("_move_speed"))

    reasons = []
    if heal and not (team_cut and crit_carry and style == "ad"):
        reasons.append("healing")
    skip_grievous = team_cut and crit_carry and style == "ad"
    if skip_grievous and (heal or armor):
        reasons.append("team has anti-heal")
    if shield >= 2 and style == "ad" and not crit_carry:
        reasons.append("shields")
    if armor >= 2 and style == "ad":
        reasons.append("armor")
    if mr >= 2 and style == "ap":
        reasons.append("magic resist")
    if ad >= 4 and not current_has_boots:
        reasons.append("4 AD")
    if ap >= 4 and not current_has_boots:
        reasons.append("4 AP")
    if deaths >= 4:
        reasons.append("%d deaths" % deaths)

    role = role_of(style, pos, crit_carry)
    ctx = {
        "role": role,
        "heal": heal,
        "shield": shield,
        "armor": armor,
        "mr": mr,
        "ad": ad,
        "ap": ap,
        "deaths": deaths,
        "team_cut": team_cut,
        "skip_grievous": skip_grievous,
        "has_boots": current_has_boots,
        "tags": me.get("_tags") or [],
        "has_core": bool(held_completed({"items": [i for i in me.get("items") or []
                                                   if not is_boots_record(record(catalog, i.get("itemID") or 0))]},
                                        catalog)) if me.get("items") else False,
    }
    notes = {}
    if heal and not skip_grievous:
        notes["Mortal Reminder"] = "heal"
        notes["Chempunk Chainsword"] = "heal"
        notes["Morellonomicon"] = "heal"
        notes["Thornmail"] = "heal"
    if armor >= 2 or skip_grievous:
        notes["Lord Dominik's Regards"] = "pen"
        notes["Serylda's Grudge"] = "pen"
    if mr >= 2:
        notes["Void Staff"] = "pen"
        notes["Cryptbloom"] = "pen"
    if shield >= 2 and not crit_carry:
        notes["Serpent's Fang"] = "shield"
    if ad >= 4 or ap >= 4:
        notes[boots_name(role, ad, ap)] = "boots"

    resolved = []
    for name in slot_names(ctx):
        picked = step(catalog, name, notes.get(name, "later"))
        if not picked or owns(owned, picked["id"], catalog):
            continue
        resolved.append(name)
    if not resolved and not held_completed(me, catalog):
        return empty

    why = "vs " + ", ".join(reasons) if reasons else "adapting"
    lines = ["BUILD  " + why]
    speak = None
    key = None
    if resolved:
        action = click_for(resolved[0], owned, catalog, notes.get(resolved[0], "later"))
        if action:
            afford = gold >= action["cost"]
            mark = "BUY" if afford else "need %d" % int(action["cost"] - gold)
            lines.append("NEXT %s  %dg  %s" % (action["name"], action["cost"], mark))
            key = action["id"]
            urgent = action["note"] in ("heal", "pen", "shield", "boots")
            if afford and game_time >= 80 and urgent:
                speak = "Shop. %s, %d gold, %s." % (action["name"], action["cost"], spoken_reason(action["note"], ad, ap, action["name"]))
            if action.get("into_name") and action["into_name"] not in (action["name"],):
                lines.append("THEN %s" % action["into_name"])
        for name in resolved[1:5]:
            if any(name in line for line in lines):
                continue
            lines.append("LATER %s" % name)
    for name in held_completed(me, catalog)[:4]:
        lines.append("HAVE %s" % name)
    return {"why": why, "lines": lines, "speak": speak, "key": key}
