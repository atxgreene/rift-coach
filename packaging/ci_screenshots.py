"""CI helper (Windows runner): run the built app and capture screenshots for review.

    python packaging/ci_screenshots.py dist/MacroGoblin shots [dist/MacroGoblin-Setup.exe]

Takes: first-run launcher, launcher + overlay mid-demo, and the installer's welcome page.
Never fails the build on its own; missing screenshots are reported instead.
"""

import json
import os
import subprocess
import sys
import tempfile
import time


def grab(path):
    try:
        from PIL import ImageGrab
        ImageGrab.grab(all_screens=True).save(path)
        print("saved", path)
    except Exception as exc:
        print("screenshot failed:", exc)


def run_app(exe, home, args, wait, shot):
    env = dict(os.environ, MACROGOBLIN_HOME=home)
    proc = subprocess.Popen([exe, "--no-update-check"] + args, env=env)
    time.sleep(wait)
    grab(shot)
    alive = proc.poll() is None
    proc.kill()
    proc.wait(10)
    log = os.path.join(home, "logs", "app.log")
    if os.path.exists(log):
        with open(log, encoding="utf-8", errors="replace") as handle:
            tail = handle.read()[-3000:]
        print("--- app.log tail ---\n" + tail)
    return alive


def main():
    app_dir, out = sys.argv[1], sys.argv[2]
    setup = sys.argv[3] if len(sys.argv) > 3 else None
    os.makedirs(out, exist_ok=True)
    exe = os.path.join(app_dir, "MacroGoblin.exe")
    ok = True

    first = tempfile.mkdtemp(prefix="mg-first-")
    ok &= run_app(exe, first, [], 8, os.path.join(out, "1-first-run.png"))

    live = tempfile.mkdtemp(prefix="mg-live-")
    with open(os.path.join(live, "settings.json"), "w", encoding="utf-8") as handle:
        json.dump({"first_run_done": True, "voice": False}, handle)
    ok &= run_app(exe, live, ["--demo"], 45, os.path.join(out, "2-demo-live.png"))

    if setup and os.path.exists(setup):
        proc = subprocess.Popen([setup, "/NOLAUNCH"])
        time.sleep(8)
        grab(os.path.join(out, "3-installer.png"))
        proc.kill()

    print("app stayed alive through screenshots:", bool(ok))
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
