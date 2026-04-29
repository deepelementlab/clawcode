# ResearchTeam Mode

`ResearchTeam` extends research mode with role-based collaboration inspired by team orchestration.

## What It Adds

- Specialized research roles (literature, analysis, review, synthesis, verification)
- Parallel phase execution with merge strategies
- Handoff contracts and convergence checks
- ResearchTECAP persistence for team-learning feedback

## CLI

```bash
clawcode research team "quantum error correction" \
  --roles literature_researcher,deep_analyst,fact_verifier \
  --strategy parallel \
  --max-iters 5
```

Dry run:

```bash
clawcode research team "topic" --dry-run
```

## Slash

```text
/research team quantum error correction --roles literature_researcher,deep_analyst --strategy hybrid --max-iters 3
```

## Acceptance Script

```bash
py -3 scripts/e2e_research_team_acceptance.py
```

## Live LLM acceptance (optional)

Deterministic acceptance uses mocks; **real-provider** smoke lives under pytest marker `live_llm`:

- See **Live LLM acceptance tests** in `docs/RESEARCH_MODE.md`.
- Team-specific gates: `CLAWCODE_RESEARCH_LIVE_TEST=1` **and** `CLAWCODE_RESEARCH_TEAM_LIVE_TEST=1`; optional `CLAWCODE_RESEARCH_TEAM_LIVE_ONE_ROLE=1` for minimal parallel fan-out.
- Test module: `tests/test_research_team_live_llm.py`.
