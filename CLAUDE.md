# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An MCP (Model Context Protocol) server that exposes [Hayabusa](https://github.com/Yamato-Security/hayabusa)
— a Windows event log (EVTX) forensics timeline generator and threat hunting tool — as tools an
LLM agent can call. It is a thin `subprocess` wrapper: it does not reimplement any of Hayabusa's
parsing/detection logic, it just shells out to the `hayabusa` binary and shapes the results for
an LLM context window.

The `hayabusa` binary itself is not vendored — it must be installed separately and located via
`HAYABUSA_PATH` (see Configuration below).

## Commands

```powershell
# one-time setup
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# run the full test suite (mocks subprocess.run, no real hayabusa binary needed)
pytest

# run a single test
pytest tests/test_hayabusa.py::test_csv_timeline_uses_directory_flag

# run the MCP server directly
mcp-hayabusa
# or
python -m mcp_hayabusa.server

# interactive debugging via MCP Inspector
mcp dev src/mcp_hayabusa/server.py
```

## Configuration (environment variables)

- `HAYABUSA_PATH` — full path to `hayabusa.exe`; falls back to `hayabusa` on `PATH`.
- `HAYABUSA_TIMEOUT_SECONDS` — default subprocess timeout for scans (default `600`).
- `HAYABUSA_RULES_PATH` — currently unused by the server directly; pass a rules directory
  per-call via a tool's `extra_args` instead (e.g. `["-r", "C:\\hayabusa\\rules"]`).

## Architecture

Three-module layering, each with a single responsibility:

- **`config.py`** — resolves the `hayabusa` binary path from the environment. `load_config()`
  raises `HayabusaNotFoundError` if the binary can't be found; this is called lazily (on first
  tool invocation, not at import time) so the MCP server can still start and list its tools even
  before `HAYABUSA_PATH` is configured.
- **`hayabusa.py`** — the subprocess wrapper. `run_subcommand()` is the single choke point all
  calls go through; it enforces `ALLOWED_SUBCOMMANDS`, an allowlist of the Hayabusa CLI
  subcommands this server is willing to invoke. Convenience functions (`csv_timeline`,
  `json_timeline`, `search`, `logon_summary`, `eid_metrics`, `update_rules`, `list_profiles`)
  build argument lists on top of that. `summarize_csv_timeline()` reads a CSV output file back
  and reduces it to a total count, counts-by-`Level`, and a small row sample — full results are
  never round-tripped through the model, only written to disk and referenced by path.
- **`server.py`** — the FastMCP app (`mcp = FastMCP("hayabusa", ...)`) and `@mcp.tool()`
  registrations. Each tool is a thin adapter over a `hayabusa.py` function; tool docstrings are
  what the MCP client sees as the tool description, so keep them accurate when changing
  behavior.

### Why only `-d`/`-f`/`-o` are hardcoded

Only the input (`-d` directory / `-f` file) and output (`-o`) flags, plus the subcommand names
themselves, are treated as stable across hayabusa versions. Everything else — rules directory,
minimum level, output profile, wizard-skip flags — is passed through via each tool's
`extra_args` parameter rather than hardcoded, because those flags have changed across hayabusa
releases and getting one wrong silently would be worse than not hardcoding it. If you're adding
a new convenience wrapper, follow this pattern: hardcode only what you've verified against
`hayabusa <subcommand> --help` for the version in use, pass through the rest.

### Adding a new tool

1. Add a function in `hayabusa.py` that calls `run_subcommand()` (add the subcommand to
   `ALLOWED_SUBCOMMANDS` if it's new).
2. Add a corresponding `@mcp.tool()` function in `server.py` that calls it and shapes the
   return value — summarize rather than return raw output if it could be large (see
   `hayabusa_csv_timeline` / `summarize_csv_timeline` for the pattern).
3. Add tests in `tests/test_hayabusa.py` mocking `subprocess.run` (unit-level) — no real
   `hayabusa` binary or `.evtx` files are needed to test this layer.
