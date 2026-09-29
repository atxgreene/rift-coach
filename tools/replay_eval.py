#!/usr/bin/env python3
"""Replay captures offline, as fast as possible, and print what the coach would say.

    python tools/replay_eval.py captures/20260926-235207
    python tools/replay_eval.py captures/* --summary
    python tools/replay_eval.py tests/fixtures/real/*.jsonl.gz --quiet-lines

Use it before and after a change: voiced-lines-per-game is the noise budget.
No League client, voice, or network needed (Data Dragon comes from the local cache
or the test fixture).
"""

import argparse
import collections
import contextlib
import glob
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import lol_coach  # noqa: E402


class Recorder:
    def __init__(self):
        self.lines = []
        self.clock = lambda: 0

    def say(self, text, priority=lol_coach.P_NORMAL, ttl=None):
        self.lines.append((self.clock(), priority, text))


def data_dragon():
    cached = sorted(glob.glob(os.path.join(ROOT, "cache", "ddragon-*.json.gz")), key=os.path.getmtime)
    source = cached[-1] if cached else os.path.join(ROOT, "tests", "fixtures", "ddragon.json.gz")
    return lol_coach.DataDragon(offline_file=source, quiet=True)


def replay(source, dd):
    rec = Recorder()
    coach = lol_coach.Coach(rec, dd)
    rec.clock = lambda: coach.t
    frames = lol_coach.load_frames(source)
    with contextlib.redirect_stdout(io.StringIO()):
        for frame in frames:
            coach.tick(frame)
    start = (frames[0].get("gameData") or {}).get("gameTime", 0) if frames else 0
    return coach, rec, max(0.0, coach.t - (start or 0)) / 60.0


def main():
    parser = argparse.ArgumentParser(description="Offline replay of captures")
    parser.add_argument("sources", nargs="+")
    parser.add_argument("--summary", action="store_true", help="counts only")
    parser.add_argument("--quiet-lines", action="store_true", help="also show overlay-only lines")
    args = parser.parse_args()
    dd = data_dragon()
    total_voiced = total_minutes = 0
    top = collections.Counter()
    for source in args.sources:
        coach, rec, minutes = replay(source, dd)
        voiced = [row for row in rec.lines if row[1] > lol_coach.P_QUIET]
        total_voiced += len(voiced)
        total_minutes += minutes
        top.update(text for _t, _p, text in voiced)
        print("%s  %s %s  %.1f min  voiced %d  (%.1f/min)  result=%s  dragons=%s" % (
            os.path.basename(source.rstrip("/")), (coach.me or {}).get("championName", "?"),
            lol_coach.norm_pos((coach.me or {}).get("position")), minutes, len(voiced),
            len(voiced) / minutes if minutes else 0, coach.result or "-", "%d-%d" % coach.dragons()))
        if not args.summary:
            for t, priority, text in rec.lines:
                if priority > lol_coach.P_QUIET or args.quiet_lines:
                    print("   [%s] %s%s" % (lol_coach.fmt_time(t), "" if priority else "(overlay) ", text))
    if len(args.sources) > 1:
        print("\nTOTAL voiced %d over %.0f min (%.2f/min)" % (
            total_voiced, total_minutes, total_voiced / total_minutes if total_minutes else 0))
        for text, count in top.most_common(10):
            print("%4d  %s" % (count, text))


if __name__ == "__main__":
    main()
