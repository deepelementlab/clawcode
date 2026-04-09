# `.clawcode/claw_skills/`

**Skill packages** for the OpenClaw-compatible skill system: each skill is typically a folder with `SKILL.md` (and optional `references/`, `scripts/`, `assets/`, `templates/`).

Resolved via `get_claw_skills_paths()` in `claw_skills/skill_store.py` under the configured **data directory** (default `.clawcode/`).

## Operations

- **`skills_list` / `skill_view` / `skill_manage`** tools operate on this store.
- Evolved skills from the learning pipeline may be **imported** here (`experience_evolve_to_skills` flow).

## Git

Commit **project-shipped** skills you want in-repo; keep experimental or personal skills local or gitignored.
