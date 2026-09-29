"""Live pattern reads from scoreboard facts the player can already see.

Each read has a stable key. The coach speaks a key once. This is not a
second build page and it does not infer hidden cooldowns.
"""


def _recent(deaths, now, window):
    return [row for row in deaths if now - row.get("t", 0) <= window]


LEAD_PEAK = 3000
LEAD_DROP = 2500


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
            "line": "CS is under 5 and a half a minute. Catch waves before you fight.",
        })
    curve = state.get("gold_curve") or []
    if len(curve) >= 3:
        # Item gold jumps whenever one team backs and shops, so require the drop to
        # hold for two samples in a row before calling it a lost lead.
        latest = max(curve[-1][1], curve[-2][1])
        prior = curve[-5:-2]
        if prior:
            peak_t, peak = max(prior, key=lambda row: row[1])
            if peak >= state.get("lead_peak", LEAD_PEAK) and latest <= peak - state.get("lead_drop", LEAD_DROP):
                # Keyed by the peak, so one collapse is called once, not every minute it lasts.
                notes.append({
                    "key": "lead:%d" % int(peak_t),
                    "line": "That lead just slipped. Reset before the next fight.",
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
