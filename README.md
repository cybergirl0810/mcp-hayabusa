# mcp-hayabusa

An MCP (Model Context Protocol) server that exposes [Hayabusa](https://github.com/Yamato-Security/hayabusa)
— a Windows event log (EVTX) forensics timeline generator and threat hunting tool — as tools
an LLM agent can call.

It's a thin wrapper: each tool shells out to the `hayabusa` binary and returns a summarized
result (full output files are written to disk and their path returned, rather than dumping
potentially huge CSV/JSON into the model's context).

## Prerequisites

- Python 3.10+
- The [`hayabusa`](https://github.com/Yamato-Security/hayabusa/releases) binary, downloaded
  separately (this project does not bundle or install it)

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Configuration (environment variables)

| Variable | Required | Purpose |
| --- | --- | --- |
| `HAYABUSA_PATH` | No | Full path to `hayabusa.exe`. Falls back to `hayabusa` on `PATH` if unset. |
| `HAYABUSA_RULES_PATH` | No | Not read directly by the server yet — pass a rules directory per call via `extra_args`, e.g. `["-r", "C:\\hayabusa\\rules"]`. |
| `HAYABUSA_TIMEOUT_SECONDS` | No | Default subprocess timeout for scans (default `600`). |

## Running the server

```powershell
mcp-hayabusa
```

or, without installing the console script:

```powershell
python -m mcp_hayabusa.server
```

For interactive debugging with the MCP Inspector:

```powershell
mcp dev src/mcp_hayabusa/server.py
```

## Registering with Claude Code / Claude Desktop

Add to your MCP client config (e.g. `claude_desktop_config.json`, or via `claude mcp add`):

```json
{
  "mcpServers": {
    "hayabusa": {
      "command": "mcp-hayabusa",
      "env": {
        "HAYABUSA_PATH": "C:\\tools\\hayabusa\\hayabusa.exe"
      }
    }
  }
}
```

## Tools

- `hayabusa_update_rules` — sync Sigma-based detection rules to the latest version
- `hayabusa_list_profiles` — list available output profiles
- `hayabusa_csv_timeline` — scan `.evtx` file(s)/directory into a CSV timeline; returns a
  summary (total events, counts by `Level`, sample rows) plus the full output file path
- `hayabusa_search` — keyword/regex search across `.evtx` file(s)/directory
- `hayabusa_logon_summary` — summarize logon events
- `hayabusa_eid_metrics` — event counts/percentages by Event ID

Every tool that takes log input accepts exactly one of `directory` (a folder of `.evtx`
files) or `file` (a single `.evtx` file), plus an `extra_args` passthrough list for flags
this wrapper doesn't hardcode (rules directory, minimum level, output profile, etc.) —
run `hayabusa <subcommand> --help` to see what your installed version supports, since
flags have changed across hayabusa releases.

## Tests

```powershell
pytest
```

Tests mock `subprocess.run`, so they don't require the `hayabusa` binary to be installed.
