# Questions

## Blocking

- A real match with `--capture` is still required before schema mismatches can be fixed and before the post-game vault note (handoff T11).

## Assumptions used so the build could proceed

- Project lives at `C:\Users\austi\Projects\rift-coach`, not iCloud. Captures should not sync.
- Baron first spawn is 20:00. Grubs stay at 8:00 despite one stale wiki page saying 6:00.
- `run_coach.bat` starts voice and overlay. `--web` and `--claude` stay opt-in.
- No desktop shortcut. That would write outside this folder.
- No packages installed.
- Claude key is never written here. If you want Claude mode, set `ANTHROPIC_API_KEY` yourself with `setx`, then start with `--claude`.
