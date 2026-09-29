"""Entry point for the packaged app.

MacroGoblin.exe     -> the launcher window (no console)
MacroGoblinCLI.exe  -> the command line (lol_coach.py flags: --doctor, --demo, --replay, ...)
"""

import os
import sys


def _quiet_streams():
    """A windowed exe has no console; keep prints in a log file for support instead of dropping them."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        import lol_coach
        folder = lol_coach.data_path("logs")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "app.log")
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".old")  # keep it small; never wipe a running copy's log
        stream = open(path, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    except Exception:
        null = open(os.devnull, "w")
        sys.stdout = sys.stdout or null
        sys.stderr = sys.stderr or null


def main():
    exe = os.path.basename(sys.executable).lower()
    if "cli" in exe:
        import lol_coach
        return lol_coach.main()
    _quiet_streams()
    import app
    return app.main()


if __name__ == "__main__":
    raise SystemExit(main())
