# `.clawcode/claw_metrics/`

**Telemetry and tuning** for ClawCode’s learning/metrics pipeline.

## Typical files

| File | Purpose |
|------|---------|
| `events.jsonl` | Append-only **event stream** for metrics and analysis. |
| `canary_results.jsonl` | **Canary / promotion** outcomes (see `learning/canary_promotion.py`). |
| `reports/` *(optional)* | Timestamped **report** snapshots — see [`reports/README.md`](./reports/README.md). |
| `snapshots/` *(optional)* | Point-in-time metric **snapshots** — see [`snapshots/README.md`](./snapshots/README.md). |
| `tuning_state.json` *(optional)* | State for adaptive tuning flows. |

## Git

Usually **ignored** or treated as local/CI artifacts. Commit only if you need reproducible metrics for a paper or regression baseline.
