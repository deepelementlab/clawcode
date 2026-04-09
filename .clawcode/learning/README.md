# `.clawcode/learning/`

**Closed-loop learning** root: observations, instincts, evolved promotions, and experience capsules (solo + team).

## Key paths

| Path | Purpose |
|------|---------|
| `observations.jsonl` | Append-only **raw observations** from runs. |
| [`instincts/`](./instincts/) | Learned **instincts** (`personal/` vs `inherited/`). |
| [`evolved/`](./evolved/) | Promoted **skills**, **commands**, **agents**. |
| [`experience/`](./experience/) | **Solo** experience capsules, exports, logs. |
| [`team-experience/`](./team-experience/) | **Team** capsules, exports, feedback. |

## Usage

- Consumed by `learning/service.py`, slash `/experience*` and `/team-experience*` flows, and `claw_learning` ops.
- Safe to archive or truncate in development; keep backups if you rely on historical evolution data.

## Git

Default to **not committing** large JSONL logs unless you have a reason to snapshot them.
