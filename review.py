"""Post-game report card and cross-game trends.

Grades come only from numbers the game already shows on the scoreboard (CS, K/D/A, vision
score) plus the objectives the coach heard during the match. Pure functions: easy to test.
"""

import re

AREAS = ("farming", "fighting", "survival", "vision", "objectives")
AREA_NAMES = {"farming": "Farming", "fighting": "Fighting", "survival": "Survival",
              "vision": "Vision", "objectives": "Objectives"}
GRADE_POINTS = {"A": 4, "B": 3, "C": 2, "D": 1}
MIN_GAME_SECONDS = 10 * 60  # remakes and early surrenders get no card

TIPS = {
    "farming": "Last-hit every wave you can before you look for fights. A wave is about 125 gold.",
    "fighting": "Walk to fights your team is already taking. Kill participation grows from being there, not from solo plays.",
    "survival": "Before you walk forward, count the enemies you can see. If some are missing, assume they are near you.",
    "vision": "Buy a control ward every back and use your trinket on cooldown.",
    "objectives": "Start moving to dragon and grubs 45 seconds early, after you push your wave.",
}


def _num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _grade(value, a, b, c, higher=True):
    if not higher:
        value, a, b, c = -value, -a, -b, -c
    if value >= a:
        return "A"
    if value >= b:
        return "B"
    if value >= c:
        return "C"
    return "D"


def vision_target(role):
    return 1.8 if role == "UTILITY" else (1.1 if role == "JUNGLE" else 0.8)


def cs_target(role, target):
    if role == "UTILITY":
        return None
    return target - 1.5 if role == "JUNGLE" else target


def report_card(stats):
    """stats: minutes, role, cs, kills, deaths, assists, team_kills, ward_score, objectives_us,
    objectives_them, cs_target. Returns {area: {"grade", "detail"}} or {} for short games."""
    minutes = _num(stats.get("minutes"))
    if minutes * 60 < MIN_GAME_SECONDS:
        return {}
    role = stats.get("role") or ""
    card = {}

    target = cs_target(role, _num(stats.get("cs_target")) or 8.0)
    if target:
        rate = _num(stats.get("cs")) / minutes
        card["farming"] = {"grade": _grade(rate, target, target - 1, target - 2),
                           "detail": "%.1f CS a minute (goal %g)" % (rate, target)}

    team_kills = _num(stats.get("team_kills"))
    if team_kills >= 5:
        kp = (_num(stats.get("kills")) + _num(stats.get("assists"))) / team_kills
        card["fighting"] = {"grade": _grade(kp, 0.6, 0.45, 0.3),
                            "detail": "%d%% kill participation" % round(min(kp, 1.0) * 100)}

    per10 = _num(stats.get("deaths")) / minutes * 10
    card["survival"] = {"grade": _grade(per10, 1.5, 2.5, 3.5, higher=False),
                        "detail": "%d deaths, %.1f per 10 min" % (_num(stats.get("deaths")), per10)}

    if stats.get("ward_score") is not None:
        vpm = _num(stats.get("ward_score")) / minutes
        goal = vision_target(role)
        card["vision"] = {"grade": _grade(vpm, goal, goal * 0.7, goal * 0.45),
                          "detail": "vision score %d, %.2f a minute" % (_num(stats.get("ward_score")), vpm)}

    us, them = _num(stats.get("objectives_us")), _num(stats.get("objectives_them"))
    if us + them >= 2:
        share = us / (us + them)
        card["objectives"] = {"grade": _grade(share, 0.65, 0.5, 0.35),
                              "detail": "%d of %d big objectives" % (us, us + them)}
    return card


def best_and_worst(card):
    if not card:
        return None, None
    ranked = sorted(card, key=lambda area: (-GRADE_POINTS[card[area]["grade"]], AREAS.index(area)))
    best, worst = ranked[0], ranked[-1]
    if card[best]["grade"] == card[worst]["grade"]:
        return best, None
    return best, worst


def spoken_summary(card):
    best, worst = best_and_worst(card)
    if not best:
        return ""
    line = "Report card. Best: %s, %s." % (AREA_NAMES[best].lower(), card[best]["grade"])
    if worst:
        line += " Work on %s, %s." % (AREA_NAMES[worst].lower(), card[worst]["grade"])
    return line


def encode(card):
    """Frontmatter value: 'farming=B fighting=A ...'."""
    return " ".join("%s=%s" % (area, card[area]["grade"]) for area in AREAS if area in card)


def decode(text):
    return {k: v for k, v in re.findall(r"(\w+)=([ABCD])", text or "") if k in AREAS}


def trends(games):
    """games: newest first, each {'champion','result','grades': {area: letter}}.

    Returns a dict for the launcher: record, streak, best champion, weakest area, per-area averages.
    """
    decided = [g for g in games if g.get("result") in ("win", "loss")]
    wins = sum(1 for g in decided if g["result"] == "win")
    out = {"games": len(games), "wins": wins, "losses": len(decided) - wins, "streak": "",
           "champions": [], "weakest": None, "strongest": None, "averages": {}}
    if decided:
        first = decided[0]["result"]
        run = 0
        for g in decided:
            if g["result"] != first:
                break
            run += 1
        if run >= 2:
            out["streak"] = "%d %s in a row" % (run, "wins" if first == "win" else "losses")
    champs = {}
    for g in decided:
        row = champs.setdefault(g.get("champion") or "?", [0, 0])
        row[0 if g["result"] == "win" else 1] += 1
    out["champions"] = sorted(((c, w, l) for c, (w, l) in champs.items()), key=lambda r: (-(r[1] + r[2]), -r[1], r[0]))
    totals = {}
    for g in games:
        for area, letter in (g.get("grades") or {}).items():
            totals.setdefault(area, []).append(GRADE_POINTS.get(letter, 0))
    averages = {area: sum(v) / float(len(v)) for area, v in totals.items() if len(v) >= 2}
    out["averages"] = averages
    if len(averages) >= 2:
        ordered = sorted(averages, key=lambda area: (averages[area], AREAS.index(area)))
        if averages[ordered[0]] < averages[ordered[-1]]:
            out["weakest"], out["strongest"] = ordered[0], ordered[-1]
    return out


def letter(points):
    for grade in ("A", "B", "C"):
        if points >= GRADE_POINTS[grade] - 0.5:
            return grade
    return "D"
