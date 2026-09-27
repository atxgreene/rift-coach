"""Live pattern reads from scoreboard facts the player can already see.

Each read has a stable key. The coach speaks a key once. This is not a
second build page and it does not infer hidden cooldowns.
"""


def _recent(deaths, now, window):
    return [row for row in deaths if now - row.get("t", 0) <= window]


def scan(state):
    """Return reads in priority order. Each is {key, line}."""
    notes = []
    deaths = state.get("deaths") or []
    now = state.get("t") or 0
    if deaths:
        latest = deaths[-1].get("by") or ""
        count = sum(1 for row in deaths if row.get("by") == latest and latest)
        if latest and count >= 3:
            milestone = 3 if count < 5 else 5 if count < 8 else 8
            notes.append({
                "key": "killer:%s:%d" % (latest, milestone),
                "line": "%s has killed you %d times. Stop taking that fight." % (latest, count),
            })
        cluster = _recent(deaths, now, 240)
        if len(cluster) >= 3:
            notes.append({
                "key": "spiral:%d" % int(cluster[0].get("t", 0) // 60),
                "line": "Three deaths in four minutes. Reset with the team. Do not walk back in.",
            })
    if not state.get("has_boots") and now >= 12 * 60:
        mark = 20 if now >= 20 * 60 else 12
        notes.append({
            "key": "boots:%d" % mark,
            "line": "Still no boots. Buy them this back.",
        })
    rates = [rate for _t, rate in (state.get("cs_rates") or []) if _t >= 12 * 60]
    if len(rates) >= 2 and rates[-1] < 5.5 and rates[-2] < 5.5:
        notes.append({
            "key": "cs-stuck",
            "line": "CS has been under 5 all game. Catch the wave before you fight.",
        })
    curve = state.get("gold_curve") or []
    if len(curve) >= 2:
        latest = curve[-1][1]
        prior = [diff for _t, diff in curve[-4:-1]]
        if prior and max(prior) >= 2500 and latest <= max(prior) - 2000:
            notes.append({
                "key": "lead:%d" % int(curve[-1][0] // 60),
                "line": "That lead just vanished. Reset before the next fight.",
            })
    objectives = state.get("objectives") or []
    ours = [row for row in objectives if row.get("who") == "We" and row.get("name") == "dragon"]
    theirs = [row for row in objectives if row.get("who") == "They" and row.get("name") == "baron"]
    if ours and theirs:
        last_dragon = ours[-1].get("t", 0)
        last_baron = theirs[-1].get("t", 0)
        if 0 <= last_baron - last_dragon <= 150:
            notes.append({
                "key": "trade:%d" % int(last_baron),
                "line": "They answered your dragon with Baron. Do not chase.",
            })
    return notes
