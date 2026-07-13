# Hayabusa MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that connects
Claude to [Hayabusa](https://github.com/Yamato-Security/hayabusa), a Windows event log (EVTX)
forensics timeline generator and threat hunting tool. It lets an LLM agent run real Hayabusa
scans against Windows event logs and reason about the results in plain conversation, instead of
a human manually running CLI commands and reading raw CSV output.

## Overview

Hayabusa is a fast, Rust-based command-line tool built by [Yamato Security](https://github.com/Yamato-Security)
that parses Windows Event Log (`.evtx`) files and matches them against thousands of
Sigma-based detection rules to flag suspicious activity — failed logons, lateral movement,
persistence mechanisms, credential access, and more.

This project wraps that CLI tool as an MCP server: a small Python process that exposes
Hayabusa's subcommands as **tools** an MCP-compatible client (such as Claude Desktop or
Claude Code) can call. Instead of memorizing Hayabusa's flags, a user can just ask Claude
in natural language — *"scan these event logs and tell me if anything looks suspicious"* —
and Claude invokes the appropriate tool, reads back a summarized result, and explains it.

## The cybersecurity problem it solves

Windows event logs are one of the richest sources of forensic evidence during incident
response and threat hunting, but they're also one of the least accessible:

- A single `.evtx` file can contain tens of thousands of events in a dense, semi-structured
  format that isn't practical to read by hand.
- Detection rules (Sigma/Hayabusa rules) require domain knowledge to write and interpret —
  knowing *that* an alert fired is only half the job; understanding *why* it matters takes
  security expertise.
- Junior analysts and students often have the tool access but not yet the pattern-recognition
  experience to triage results quickly; senior analysts have the experience but limited time
  to review every log by hand.

This project closes that gap by giving an LLM direct, structured access to Hayabusa's output.
Claude can run a scan, get back event counts grouped by severity (`Level`) instead of a raw
CSV dump, and use its own reasoning to help explain what a given alert means, which events look
most urgent, and what to investigate next — while the actual detection logic still comes from
Hayabusa's vetted rule engine, not from the LLM guessing.

## How MCP connects Claude to Hayabusa

```
┌─────────────┐        MCP (stdio)        ┌───────────────────┐      subprocess       ┌───────────┐
│   Claude     │ ◄──────────────────────► │  mcp-hayabusa       │ ◄──────────────────► │ hayabusa   │
│ (Desktop/CLI)│   JSON-RPC tool calls     │  (this project)     │   CLI invocation      │  .exe      │
└─────────────┘                           └───────────────────┘                        └───────────┘
                                                     │
                                                     ▼
                                           reads/writes .evtx, .csv
```

1. Claude (the MCP **client**) launches `mcp-hayabusa` as a local subprocess and talks to it
   over the MCP protocol (JSON-RPC over stdio).
2. On startup, the server (built with the [`mcp` Python SDK](https://github.com/modelcontextprotocol/python-sdk)'s
   `FastMCP`) advertises its available tools — e.g. `hayabusa_csv_timeline`, `hayabusa_search` —
   along with a description and parameter schema for each, generated from Python type hints and
   docstrings.
3. When the user asks something that maps to one of those tools, Claude calls it with structured
   arguments (e.g. `{"directory": "C:\\logs", "extra_args": ["-m", "medium"]}`).
4. The server translates that call into a real `hayabusa <subcommand> ...` invocation via
   Python's `subprocess`, waits for it to finish, and reads back the result.
5. For scans that produce large output files (like `csv-timeline`), the server doesn't return
   the raw file to Claude — it parses the CSV and returns a compact summary (total event count,
   counts grouped by alert `Level`, and a small row sample), plus the full file path so a human
   (or Claude, via other tools) can inspect the complete results directly.
6. Claude uses that summary to answer the user in natural language, and can chain further tool
   calls (e.g. `hayabusa_search` for a specific keyword) based on what it sees.

MCP is what makes this generic: the same server works unmodified with any MCP-compatible
client, and Claude doesn't need any Hayabusa-specific training — the tool descriptions *are*
the documentation it reads at connection time.

## Main features

- **Six MCP tools** covering the most common Hayabusa workflows: building a detection timeline,
  searching logs, summarizing logons, and reporting event-ID/rule metrics.
- **Result summarization, not raw dumps** — `hayabusa_csv_timeline` parses its own CSV output
  and returns event counts by severity level plus a small sample, so a large scan doesn't blow
  past the model's context window.
- **Subcommand allowlist** — the wrapper only ever invokes a fixed set of known-safe Hayabusa
  subcommands (`ALLOWED_SUBCOMMANDS` in `hayabusa.py`), rather than passing arbitrary
  attacker-or-model-controlled strings straight to a shell.
- **No shell interpolation** — all commands are built as argument lists and run with
  `subprocess.run(..., shell=False)`, which avoids shell/command-injection risk even though
  inputs (file paths, keywords) can come from model-generated text.
- **Version-tolerant flag handling** — only the input/output flags (`-d`, `-f`, `-o`) are
  hardcoded, since Hayabusa's other flags have changed across releases; everything else (rules
  directory, minimum level, output profile) is passed through an explicit `extra_args` list
  rather than guessed.
- **Configurable, fail-fast binary lookup** — the Hayabusa binary path is resolved once via
  `HAYABUSA_PATH` (or `PATH`), lazily on first tool call, with a clear error if it can't be found.
- **Unit-tested without needing the real binary** — tests mock `subprocess.run`, so the
  argument-building logic and CSV summarization can be verified in CI without installing
  Hayabusa or providing real `.evtx` files.

## Project architecture

The server is a thin, layered wrapper — it does not reimplement any detection or log-parsing
logic itself; all of that stays inside the Hayabusa binary.

```
Claude (MCP client)
      │  MCP tool calls (JSON-RPC / stdio)
      ▼
server.py        FastMCP app + @mcp.tool() functions.
                  Thin adapters: validate/shape arguments, call into hayabusa.py,
                  and summarize large results before returning them to the model.
      │
      ▼
hayabusa.py       subprocess wrapper. run_subcommand() is the single choke point every
                  call goes through — it enforces the ALLOWED_SUBCOMMANDS allowlist and
                  invokes the binary with an explicit argument list (no shell=True).
                  Convenience functions (csv_timeline, search, logon_summary, ...) build
                  argument lists on top of it. summarize_csv_timeline() reads scan output
                  back off disk and reduces it to counts + a sample.
      │
      ▼
config.py         Resolves the hayabusa binary path from HAYABUSA_PATH (env var) or PATH,
                  and reads HAYABUSA_TIMEOUT_SECONDS. Raises a clear error if the binary
                  can't be found; resolved lazily so the server can still start and list
                  its tools before Hayabusa is configured.
      │
      ▼
hayabusa.exe      The actual Hayabusa binary (external dependency, not bundled).
                  Reads .evtx files, applies Sigma-based detection rules, writes
                  CSV/JSON/stdout output.
```

## Technologies used

- **Python 3.10+** — implementation language
- **[`mcp`](https://pypi.org/project/mcp/) Python SDK (`FastMCP`)** — MCP server framework:
  tool registration, JSON-RPC/stdio transport, schema generation from type hints
- **`subprocess`** (standard library) — safe, shell-free invocation of the Hayabusa CLI
- **`csv`** (standard library) — parsing Hayabusa's CSV timeline output for summarization
- **[Hayabusa](https://github.com/Yamato-Security/hayabusa)** (Rust, external binary) — the
  actual event-log parsing and Sigma-rule detection engine this project wraps
- **pytest** — unit tests, with `subprocess.run` mocked out
- **`pyproject.toml` / `setuptools`** — packaging, editable installs, console-script entry point

## Installation and setup (Windows)

### Prerequisites

- Python 3.10 or later
- The [`hayabusa`](https://github.com/Yamato-Security/hayabusa/releases) binary, downloaded
  separately — this project does not bundle, download, or install it

### Steps

```powershell
# 1. Clone or download this repository, then from its root:
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install the project (editable install) plus dev/test dependencies
pip install -e ".[dev]"

# 3. Run the tests to confirm the install worked (no hayabusa binary required for this)
pytest
```

### Configuring `HAYABUSA_PATH`

The server needs to know where the Hayabusa binary lives. Set the `HAYABUSA_PATH` environment
variable to its full path — if it isn't set, the server falls back to looking for `hayabusa`
(or `hayabusa.exe`) on your system `PATH`.

**PowerShell (current session only):**

```powershell
$env:HAYABUSA_PATH = "C:\tools\hayabusa\hayabusa.exe"
```

**PowerShell (persist across sessions, current user):**

```powershell
[System.Environment]::SetEnvironmentVariable("HAYABUSA_PATH", "C:\tools\hayabusa\hayabusa.exe", "User")
```

**Or, if you'd rather not set an environment variable at all**, just add the folder containing
`hayabusa.exe` to your `PATH` instead — the server will find it automatically.

If `HAYABUSA_PATH` is unset and nothing named `hayabusa`/`hayabusa.exe` is found on `PATH`, tool
calls will fail with a clear `HayabusaNotFoundError` explaining how to fix it.

### Running the server

```powershell
mcp-hayabusa
```

or, without relying on the installed console script:

```powershell
python -m mcp_hayabusa.server
```

For interactive debugging (lets you call tools by hand and inspect responses) via the MCP
Inspector:

```powershell
mcp dev src/mcp_hayabusa/server.py
```

### Registering with Claude Desktop / Claude Code

Add an entry to your MCP client config (e.g. `claude_desktop_config.json`, or via
`claude mcp add`):

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

## Example usage

Once the server is registered with Claude, a conversation might look like this:

> **You:** I have some Windows Security event logs from a suspicious host at
> `C:\incident\host23`. Can you build a detection timeline and tell me if anything stands out?
>
> **Claude:** *(calls `hayabusa_csv_timeline` with `directory="C:\\incident\\host23"`)*
>
> I ran a scan across that directory — 4,812 events total. Severity breakdown: 3 `critical`,
> 12 `high`, 47 `medium`, the rest informational. The critical alerts are all related to
> potential credential dumping (LSASS access). Want me to pull the full detail on those three
> events, or search for related activity around the same timestamps?
>
> **You:** Search for "lsass" across the same logs.
>
> **Claude:** *(calls `hayabusa_search` with `directory="C:\\incident\\host23", keywords=["lsass"]`)*
>
> Found 9 matching events...

Equivalent direct tool calls (what Claude actually sends under the hood):

```json
{
  "tool": "hayabusa_csv_timeline",
  "arguments": {
    "directory": "C:\\incident\\host23",
    "extra_args": ["-m", "medium"]
  }
}
```

```json
{
  "tool": "hayabusa_search",
  "arguments": {
    "directory": "C:\\incident\\host23",
    "keywords": ["lsass"]
  }
}
```

### Available tools

| Tool | Purpose |
| --- | --- |
| `hayabusa_csv_timeline` | Scan `.evtx` file(s)/directory into a CSV detection timeline; returns a summary (total events, counts by `Level`, sample rows) plus the full output file path |
| `hayabusa_search` | Keyword/regex search across `.evtx` file(s)/directory |
| `hayabusa_logon_summary` | Summarize successful/failed logon events |
| `hayabusa_eid_metrics` | Event counts/percentages by Event ID |
| `hayabusa_list_profiles` | List available output profiles |
| `hayabusa_update_rules` | Sync Sigma-based detection rules to the latest version |

Every tool that takes log input accepts exactly one of `directory` (a folder of `.evtx` files)
or `file` (a single `.evtx` file), plus an `extra_args` passthrough list for flags this wrapper
doesn't hardcode (rules directory, minimum level, output profile, etc.) — run
`hayabusa <subcommand> --help` to see what your installed version supports, since flags have
changed across Hayabusa releases.

## Project folder structure

```
mcp-hayabusa/
├── src/
│   └── mcp_hayabusa/
│       ├── __init__.py     # package version
│       ├── config.py       # resolves HAYABUSA_PATH / timeout from environment
│       ├── hayabusa.py     # subprocess wrapper, subcommand allowlist, CSV summarizer
│       └── server.py       # FastMCP app and @mcp.tool() definitions
├── tests/
│   └── test_hayabusa.py    # unit tests (subprocess.run mocked out)
├── pyproject.toml          # packaging, dependencies, console-script entry point
├── README.md
└── CLAUDE.md                # guidance for AI coding agents working in this repo
```

## Skills demonstrated

- Designing and building an **MCP server** from the official Python SDK (`FastMCP`), including
  tool schemas, docstring-driven descriptions, and stdio transport
- **Secure subprocess handling**: shell-free command construction, an explicit
  subcommand allowlist, and timeout enforcement around an external security tool
- Applying **defensive security tooling** (Hayabusa / Sigma-based detection) in an
  agentic/LLM-assisted workflow
- **API/response design for LLM consumption** — summarizing large structured output (CSV
  timelines) into a compact, model-friendly shape instead of dumping raw data
- **Layered architecture** with clear separation of concerns (config resolution → CLI
  invocation → tool interface)
- **Test-driven verification without the real dependency** — unit tests that mock
  `subprocess.run` so core logic is verified without needing the Hayabusa binary installed
- Environment-based configuration and packaging for a Windows development workflow
  (`pyproject.toml`, editable installs, console-script entry points)

## Current limitations

- **Windows-oriented, manual dependency install** — Hayabusa itself is not bundled, vendored,
  or auto-downloaded; the user must install it separately and point `HAYABUSA_PATH` at it.
- **No automated integration tests against a real Hayabusa binary or real `.evtx` files** —
  current tests only cover argument-building and CSV-summarization logic with mocks.
- **`HAYABUSA_RULES_PATH` is defined but not yet wired up** — it's read into config but not
  currently passed to any Hayabusa invocation; a rules directory must be supplied per call via
  `extra_args` (e.g. `["-r", "C:\\hayabusa\\rules"]`) instead.
- **Flag coverage is intentionally partial** — only `-d`/`-f`/`-o` are hardcoded per subcommand;
  everything else relies on the caller supplying correct flags via `extra_args`, since Hayabusa's
  CLI flags have changed across releases and this project hasn't been verified against every
  version.
- **No output size/row cap on `search`, `logon-summary`, or `eid-metrics`** — unlike
  `hayabusa_csv_timeline`, these tools return raw stdout, which could be large on bigger log sets.
- **No authentication or multi-user access control** — this is a local, single-user MCP server
  intended to run on the same machine as the Claude client, not a shared network service.
- **No log/audit trail of tool invocations** — useful for a personal workflow, but a production
  or team deployment would likely want to record what scans were run, by whom, and when.

## Future improvements

- Wire up `HAYABUSA_RULES_PATH` so a configured rules directory is applied automatically
  instead of requiring `extra_args` on every call
- Add `hayabusa_json_timeline`, `computer_metrics`, `log_metrics`, and `pivot_keywords_list`
  tool wrappers (the underlying `hayabusa.py` functions/allowlist already support most of these)
- Cap and paginate output for `search`, `logon_summary`, and `eid_metrics` the same way
  `csv_timeline` is already summarized
- Add integration tests that run against sample/synthetic `.evtx` files and a real Hayabusa
  binary in CI
- Cross-platform support (Hayabusa itself runs on Linux/macOS too; this wrapper's binary
  resolution and packaging currently assume a Windows workflow)
- Structured logging of tool calls (subcommand, arguments, duration, result) for auditability
- Optional automatic rule updates on a schedule, rather than only on explicit
  `hayabusa_update_rules` calls

## Disclaimer

This project is built for **educational and defensive security purposes only**. It is a
personal/portfolio project demonstrating how to integrate an LLM agent with a legitimate,
publicly available forensics tool (Hayabusa) via the Model Context Protocol.

- It is intended for use on event logs you own or are explicitly authorized to analyze (e.g.
  your own systems, lab environments, or logs provided as part of an authorized incident
  response or training engagement).
- It performs **read-only analysis** of event log data — it does not modify, exploit, or attack
  any system. Detection logic comes entirely from Hayabusa's own Sigma-based rule engine, not
  from this project or from the LLM.
- It is not a replacement for professional incident response tooling, processes, or judgment.
  Always validate findings from any automated tool — including this one — against your own
  analysis before acting on them.
