# Rift Coach

Live voice coach for League of Legends. Read-only. Uses Riot's local Live Client Data API and Data Dragon. No memory reads, no injection, no keyboard hooks.

Project path: `C:\Users\austi\Projects\rift-coach`

## Run

Double-click `run_coach.bat` before you queue. That starts voice plus the overlay.

League must be **Borderless**, not exclusive Fullscreen, or Windows cannot draw the overlay on top.

```text
python lol_coach.py --demo --speed 20
python lol_coach.py --demo --speed 20 --no-voice
python lol_coach.py --overlay
python lol_coach.py --overlay-edit
python lol_coach.py --capture
python lol_coach.py --replay captures\<timestamp> --speed 20 --no-voice
python lol_coach.py --web
python lol_coach.py --log
python lol_coach.py --me YourName
```

`--web` binds to `127.0.0.1:8765` only. It will not listen on the LAN.

Show/hide overlay: `Ctrl+Shift+O`.

## What it will not do

- Read game memory, inject a DLL, hook DirectX, or sniff packets.
- Install a low-level keyboard hook. The hotkey is `RegisterHotKey`.
- Show information you cannot already see on the scoreboard, events, or the screen.
- Turn Claude mode on unless you pass `--claude`. Set `ANTHROPIC_API_KEY` yourself. It is never written into the script, the bat, or git.

## Verify

```text
python tests\test_coach.py
python tests\smoke_overlay.py
python tests\voice_check.py
python lol_coach.py --demo --speed 40 --no-voice
```

First real match: start with `--capture`, play the game, then diff `captures\<timestamp>` against `SCHEMA_NOTES.md`.
