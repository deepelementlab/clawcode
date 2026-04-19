# Performance & Testing

## PyO3 Performance Extension

ClawCode includes a Rust-native performance extension for high-speed file operations.

### Components

| Function | Source | Purpose |
|----------|--------|---------|
| `grep_path` | `gsd-grep` | Fast content search via ripgrep |
| `glob_scan` | `ignore + globset` | Fast file glob with gitignore support |

### Build

```bash
cd clawcode/clawcode/llm/tools/performance/core/engine-py
pip install maturin
maturin develop --release
```

Requires Rust toolchain. The parent workspace is `llm/tools/performance` (`Cargo.toml` with `members = ["core/*"]`).

## Test Suite

| Suite | Tests | Status |
|-------|-------|--------|
| Unit + Integration | 833 | ✅ Agent, tools, and deep-loop regression (`max_iters=100`) |
| CLI Flags | 22 | ✅ CLI and provider `cli_bridge` paths |
| Harness Features | 6 | ✅ Multi-step workflows and closed-loop smoke |
| Textual TUI | 3 | ✅ Welcome screen, HUD overlay, and status line |
| TUI Interactions | 27 | ✅ Chat actions, permission dialogs, and Plan/Arc panels |
| Real Skills + Plugins | 53 | ✅ Built-in skill registration/execution and plugin sandbox |

**Collected:** 944 pytest items. **Latest full run:** 935 passed, 9 skipped, 0 failed.

### Running Tests

```bash
pytest
ruff check .
mypy .
```

## Architecture Performance

- **Terminal-native**: No IDE overhead, minimal memory footprint
- **Async ReAct loop**: Non-blocking tool execution
- **SQLite persistence**: Fast local session storage
- **Structured logging**: `structlog` for minimal overhead

## Related Documentation

| Topic | Location |
|-------|----------|
| Architecture | [`docs/architecture.md`](./architecture.md) |
| Configuration | [`docs/clawcode-configuration.md`](./clawcode-configuration.md) |
| Agent & team orchestration | [`docs/agent-team-orchestration.md`](./agent-team-orchestration.md) |
| Project overview | [`README.md`](../README.md) |
