# Build report

Date: 2026-09-26
Path: `C:\Users\austi\Projects\rift-coach`
Status: baseline runs. Real-match schema is not verified. Port 2999 was not read.

## How to run

```text
run_coach.bat
python lol_coach.py --overlay
python lol_coach.py --demo --speed 20
python lol_coach.py --capture
python lol_coach.py --replay captures\<timestamp> --speed 20 --no-voice
python lol_coach.py --web
```

`--web` is `http://127.0.0.1:8765` only. League must be Borderless for the overlay. Show/hide is `Ctrl+Shift+O`.

## What changed

- Moved the handoff into this folder and replaced the Downloads script with the working copy here. Downloads copies were left in place.
- Baron first spawn set to 20:00. Grubs 8:00 with a 14:45 despawn. Herald 15:00 with a 19:45 despawn. Elder 6:00 after the fourth dragon.
- Added `--capture`, `--replay`, `--overlay`, `--overlay-edit`, `--web`, `--log`, `--me`.
- Overlay is a separate window. Click-through uses `WS_EX_TRANSPARENT`. Hotkey uses `RegisterHotKey`. No process hook, no memory read.
- Claude mode stays off unless `--claude` is passed. The key is read from the environment only.

## Verification

`python tests/test_coach.py` — 13 tests, OK, 0.546s. Includes capture throttle, stolen bool/string, elder scheduling, late-join silence, localhost `/state`, and a source ban on process-memory / hook APIs.

`python tests/smoke_overlay.py`

```text
HWND 21630432
EXSTYLE 0x80800a8
LAYERED True
TRANSPARENT True
TOOLWINDOW True
HOTKEY_REGISTERED True
OVERLAY_SMOKE_OK
```

Window was created off-screen. Not drawn over League.

`python tests/voice_check.py`

```text
mode win
VOICE_PROC alive
CREATE_NO_WINDOW set
```

The hidden PowerShell voice process started and stayed alive. Speaker output was not confirmed by ear from this session.

`python lol_coach.py --demo --speed 40 --no-voice` ended with `Demo complete.` Baron warning fired at 19:01 and Baron up at 20:01. Grubs up at 8:00. Herald up at 15:00. Ocean dragon callout included `Stolen!`. Event names in the simulation: Ace, BaronKill, ChampionKill, DragonKill, GameStart, HeraldKill, HordeKill.

`python lol_coach.py --replay tests/fixtures/mini --speed 200 --no-voice` ended with `Replay complete.` Data Dragon loaded patch `16.19.1`.

Coach tick test: 500 ticks stayed under 10ms each. That is logic cost only. FPS during a real match was not measured.

## Not done

- No live JSON captured. `SCHEMA_NOTES.md` is still an assumption list.
- Overlay was not shown over a Borderless League client.
- Post-game Obsidian report is waiting on a real `GameEnd`.
- No desktop shortcut. That would write outside this folder.
- No packages installed. No API key written.

## Security

- Live data source remains `https://127.0.0.1:2999/liveclientdata/allgamedata` only, unverified SSL for that localhost cert.
- Dashboard bind is hardcoded to localhost and refuses other hosts.
- `captures/`, `logs/`, `.env`, and `overlay_layout.json` are gitignored.
