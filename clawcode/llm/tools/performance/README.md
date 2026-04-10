# Clawcode performance (Rust)

This directory contains the **GSD-aligned Rust workspace** used by Clawcode for fast search and related tooling.

## Layout

- **`core/`** — workspace members (directory name is intentionally `core`, not `crates`):
  - `core/grep` — `gsd-grep` (ripgrep internals)
  - `core/ast` — AST / ast-grep helpers
  - `core/engine` — Node **N-API** addon (`gsd-engine`) for Node.js consumers
  - `core/engine-py` — **PyO3 + maturin** extension (`clawcode_performance`) for Python

Python code does **not** load Node `.node` binaries. Use **`engine-py`** only.

## Python extension (`clawcode_performance`)

Build (requires Rust + Python 3.12+ and `pip install maturin`):

```bash
cd clawcode/clawcode/llm/tools/performance/core/engine-py
maturin develop --release
```

If PyO3 reports your Python is newer than its supported range, set:

```bash
set PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1   # Windows CMD
# PowerShell: $env:PYO3_USE_ABI3_FORWARD_COMPATIBILITY="1"
```

Then run `maturin develop` again.

The module exposes:

- `grep_path(...)` — filesystem search via `gsd-grep`
- `glob_scan(...)` — glob + `.gitignore` via `ignore` + `globset`

`clawcode.llm.tools.search` tries this extension first for **glob** and **grep**, then falls back to ripgrep / pure Python.

## Node N-API engine (`core/engine`)

From this directory:

```bash
node scripts/build.js          # release
node scripts/build.js --dev    # debug
```

Writes `addon/gsd_engine.<platform>.node` (see `scripts/build.js`). Used by GSD-style Node tooling, not by Clawcode Python.

## Workspace

Root `Cargo.toml` uses `members = ["core/*"]`. Build one crate:

```bash
cargo build -p clawcode-performance
cargo build -p gsd-engine
```
