#!/usr/bin/env python3
"""Turn a local capture into a small, anonymized regression fixture.

    python tools/make_fixture.py captures/20260926-235207 tests/fixtures/real/kaisa-bot-win.jsonl.gz

- Every Riot ID is replaced with Player1..Player10 (you become the same PlayerN in
  every field, so matching still works).
- Heavy fields the coach never reads (abilities, runes, skins, descriptions) are dropped.
- Frames are thinned to one every --every seconds, but any frame that adds an
  event is always kept, so event timing is exact.
Output is one JSON frame per line, gzipped. lol_coach.py --replay reads it directly.
"""

import argparse
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lol_coach  # noqa: E402

PLAYER_KEEP = ("championName", "rawChampionName", "position", "team", "level", "isDead",
               "respawnTimer", "isBot", "scores")
ITEM_KEEP = ("itemID", "displayName", "count", "consumable", "price", "slot")
STAT_KEEP = ("moveSpeed", "currentHealth", "maxHealth", "abilityPower", "attackDamage")


def build_map(frames):
    mapping = {}
    for frame in frames:
        for idx, player in enumerate(frame.get("allPlayers") or []):
            game = player.get("riotIdGameName") or (player.get("summonerName") or "").split("#")[0]
            if game and game not in mapping:
                mapping[game] = "Player%d" % (idx + 1)
        if mapping:
            break
    return mapping


def anon(name, mapping):
    if not isinstance(name, str):
        return name
    return mapping.get(name.split("#")[0], name)


def scrub(value, mapping):
    if isinstance(value, str):
        return anon(value, mapping)
    if isinstance(value, list):
        return [scrub(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: scrub(item, mapping) for key, item in value.items()}
    return value


def trim(frame, mapping):
    active = frame.get("activePlayer") or {}
    me = anon(active.get("riotIdGameName") or (active.get("summonerName") or "").split("#")[0], mapping)
    out = {
        "gameData": {key: frame.get("gameData", {}).get(key) for key in ("gameTime", "gameMode", "mapNumber")},
        "activePlayer": {
            "summonerName": "%s#TEST" % me,
            "riotId": "%s#TEST" % me,
            "riotIdGameName": me,
            "riotIdTagLine": "TEST",
            "currentGold": active.get("currentGold"),
            "level": active.get("level"),
            "championStats": {key: (active.get("championStats") or {}).get(key) for key in STAT_KEEP},
        },
        "allPlayers": [],
        "events": {"Events": []},
    }
    for player in frame.get("allPlayers") or []:
        row = {key: player.get(key) for key in PLAYER_KEEP}
        game = anon(player.get("riotIdGameName") or (player.get("summonerName") or "").split("#")[0], mapping)
        row.update({"summonerName": "%s#TEST" % game, "riotId": "%s#TEST" % game,
                    "riotIdGameName": game, "riotIdTagLine": "TEST"})
        row["items"] = [{key: item.get(key) for key in ITEM_KEEP} for item in player.get("items") or []]
        out["allPlayers"].append(row)
    for ev in (frame.get("events") or {}).get("Events") or []:
        # Anonymize every string in every event: Riot adds name-bearing fields
        # (KillerName, Recipient, Acer, Assisters...) and we should not have to know them all.
        out["events"]["Events"].append(scrub(ev, mapping))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("capture")
    parser.add_argument("out")
    parser.add_argument("--every", type=float, default=10.0, help="seconds between kept frames")
    args = parser.parse_args()
    frames = lol_coach.load_frames(args.capture)
    if not frames:
        raise SystemExit("no frames in %s" % args.capture)
    mapping = build_map(frames)
    kept, last_t, last_events = [], -1e9, -1
    for frame in frames:
        t = (frame.get("gameData") or {}).get("gameTime") or 0
        count = len((frame.get("events") or {}).get("Events") or [])
        if t - last_t >= args.every or count != last_events or frame is frames[-1]:
            kept.append(trim(frame, mapping))
            last_t, last_events = t, count
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with gzip.open(args.out, "wt", encoding="utf-8") as handle:
        for frame in kept:
            handle.write(json.dumps(frame, separators=(",", ":")) + "\n")
    text = gzip.open(args.out, "rt", encoding="utf-8").read()
    # Bots are named after their champion; that is public, not a leak.
    champions = {player.get("championName") for frame in frames[:1] for player in frame.get("allPlayers") or []}
    leaks = [name for name in mapping if name and name not in champions and name in text]
    if leaks:
        os.remove(args.out)
        raise SystemExit("refusing to write: real names still present (%d)" % len(leaks))
    print("%s: %d of %d frames, %d bytes" % (args.out, len(kept), len(frames), os.path.getsize(args.out)))


if __name__ == "__main__":
    main()
