"""FastMCP server exposing Hayabusa as MCP tools."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import hayabusa
from .config import HayabusaConfig, load_config

mcp = FastMCP(
    "hayabusa",
    instructions=(
        "Tools for running Hayabusa, a Windows event log (EVTX) forensics timeline "
        "generator and threat hunting tool, against a directory or file of .evtx logs. "
        "Scans can take a while on large log sets; results are summarized rather than "
        "returned in full to keep responses small, but the full output file path is "
        "always included so it can be inspected directly."
    ),
)

_config: HayabusaConfig | None = None


def _get_config() -> HayabusaConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _default_output_path(suffix: str) -> str:
    out_dir = Path(tempfile.gettempdir()) / "mcp-hayabusa"
    out_dir.mkdir(parents=True, exist_ok=True)
    return str(out_dir / f"hayabusa-{int(time.time() * 1000)}{suffix}")


@mcp.tool()
def hayabusa_update_rules() -> str:
    """Update Hayabusa's Sigma-based detection rules to the latest version."""
    result = hayabusa.update_rules(_get_config())
    return result.stdout if result.ok else f"update-rules failed:\n{result.stderr}"


@mcp.tool()
def hayabusa_list_profiles() -> str:
    """List the output profiles available for csv-timeline / json-timeline."""
    result = hayabusa.list_profiles(_get_config())
    return result.stdout if result.ok else f"list-profiles failed:\n{result.stderr}"


@mcp.tool()
def hayabusa_csv_timeline(
    directory: str | None = None,
    file: str | None = None,
    output_path: str | None = None,
    extra_args: list[str] | None = None,
) -> dict:
    """Scan .evtx event log(s) and build a detection timeline (CSV).

    Provide exactly one of `directory` (a folder of .evtx files) or `file` (a single
    .evtx file). Returns a summary (event count, counts by alert Level, and a small
    row sample) rather than the full CSV -- read `output_path` for the complete
    results. `extra_args` is passed through verbatim to `hayabusa csv-timeline`, e.g.
    `["-r", "rules/", "-m", "medium"]` to point at a rules directory or filter by
    minimum level; run `hayabusa csv-timeline --help` to see what your installed
    version supports.
    """
    out_path = output_path or _default_output_path(".csv")
    result = hayabusa.csv_timeline(
        _get_config(), out_path, directory=directory, file=file, extra_args=extra_args
    )
    if not result.ok:
        return {"ok": False, "stderr": result.stderr, "stdout": result.stdout}

    summary = hayabusa.summarize_csv_timeline(out_path)
    return {
        "ok": True,
        "output_path": out_path,
        "total_events": summary.total_events,
        "level_counts": summary.level_counts,
        "sample_rows": summary.sample_rows,
    }


@mcp.tool()
def hayabusa_search(
    keywords: list[str],
    directory: str | None = None,
    file: str | None = None,
    extra_args: list[str] | None = None,
) -> str:
    """Search .evtx event log(s) for keyword(s) or regular expressions.

    Provide exactly one of `directory` or `file`.
    """
    result = hayabusa.search(
        _get_config(), keywords, directory=directory, file=file, extra_args=extra_args
    )
    return result.stdout if result.ok else f"search failed:\n{result.stderr}"


@mcp.tool()
def hayabusa_logon_summary(
    directory: str | None = None,
    file: str | None = None,
    extra_args: list[str] | None = None,
) -> str:
    """Summarize successful/failed logon events from .evtx event log(s)."""
    result = hayabusa.logon_summary(
        _get_config(), directory=directory, file=file, extra_args=extra_args
    )
    return result.stdout if result.ok else f"logon-summary failed:\n{result.stderr}"


@mcp.tool()
def hayabusa_eid_metrics(
    directory: str | None = None,
    file: str | None = None,
    extra_args: list[str] | None = None,
) -> str:
    """Print event counts/percentages by Event ID for .evtx event log(s)."""
    result = hayabusa.eid_metrics(
        _get_config(), directory=directory, file=file, extra_args=extra_args
    )
    return result.stdout if result.ok else f"eid-metrics failed:\n{result.stderr}"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
