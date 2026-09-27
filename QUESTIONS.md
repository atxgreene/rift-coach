# Known limits

## Expected first-run warnings

`python lol_coach.py --doctor` will warn that the League Live Client is unreachable when the user is not in an active match. That is expected.

## Real-game tuning areas

- Champion/role item paths still need continued tuning from real games.
- The deterministic demo is synthetic and can produce unrealistic enemy item completion lines.
- Overlay position is local to each user's monitor layout and saved in `overlay_layout.json`.

## Optional features

- `--web` stays localhost-only.
- `--claude` stays opt-in and requires the user to set `ANTHROPIC_API_KEY` outside the repo.
