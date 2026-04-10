# clawcode-performance

PyO3 + maturin extension. Provides `grep_path` (via `gsd-grep`) and `glob_scan` (ignore + globset).

## Build

```bash
cd clawcode/clawcode/llm/tools/performance/core/engine-py
pip install maturin
maturin develop --release
```

Requires Rust toolchain. The parent workspace is `llm/tools/performance` (`Cargo.toml` with `members = ["core/*"]`).
