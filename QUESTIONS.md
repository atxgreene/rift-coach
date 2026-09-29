# Known limits

- `--doctor` warns that the League Live Client is unreachable outside a match. That is expected.
- Item gold lead is item value only (enemy unspent gold is not visible), so it lags right after a back.
- Bot-lane quest boots are inferred: seen once in the item list = owned. If you start the coach after the quest completed, bot lane from 15:00 is assumed to have boots.
- Item cores are class-based, not champion-specific build pages. Counters (anti-heal, pen, boots vs comp) are the priority.
- Overlay position is per machine (`overlay_layout.json`).
- `--web` is localhost-only. `--claude` is opt-in and needs `ANTHROPIC_API_KEY` in the environment.
