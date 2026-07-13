"""Thin subprocess wrapper around the hayabusa CLI.

Only the subcommand names and the -d/-f/-o input/output flags are hardcoded here,
since those are stable across recent hayabusa releases. Everything else (rules
directory, minimum level, profile, wizard-skip flags, etc.) is passed through via
``extra_args`` so this wrapper doesn't silently rely on flag spellings that may
differ between hayabusa versions -- check ``hayabusa <subcommand> --help`` if a
flag doesn't behave as expected.
"""

from __future__ import annotations

import csv
import subprocess
from collections import Counter
from dataclasses import dataclass, field

from .config import HayabusaConfig

# Subcommands this server is willing to invoke. Keeps the generic run_subcommand()
# tool from being usable to shell out to arbitrary hayabusa functionality we haven't
# reasoned about (e.g. anything that could overwrite rule files unexpectedly).
ALLOWED_SUBCOMMANDS = {
    "csv-timeline",
    "json-timeline",
    "search",
    "logon-summary",
    "eid-metrics",
    "computer-metrics",
    "log-metrics",
    "pivot-keywords-list",
    "list-profiles",
    "update-rules",
}


class HayabusaSubcommandNotAllowedError(ValueError):
    pass


class HayabusaTimeoutError(RuntimeError):
    pass


@dataclass
class HayabusaResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass
class TimelineSummary:
    total_events: int
    level_counts: dict[str, int] = field(default_factory=dict)
    sample_rows: list[dict[str, str]] = field(default_factory=list)


def run_subcommand(
    config: HayabusaConfig,
    subcommand: str,
    args: list[str] | None = None,
    timeout: int | None = None,
) -> HayabusaResult:
    if subcommand not in ALLOWED_SUBCOMMANDS:
        raise HayabusaSubcommandNotAllowedError(
            f"Subcommand {subcommand!r} is not allowed. Allowed: {sorted(ALLOWED_SUBCOMMANDS)}"
        )

    full_args = [config.binary_path, subcommand, *(args or [])]
    try:
        proc = subprocess.run(
            full_args,
            capture_output=True,
            text=True,
            timeout=timeout or config.default_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HayabusaTimeoutError(
            f"hayabusa {subcommand} timed out after {timeout or config.default_timeout}s"
        ) from exc

    return HayabusaResult(
        args=full_args, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr
    )


def _input_flag(directory: str | None, file: str | None) -> list[str]:
    if bool(directory) == bool(file):
        raise ValueError("Provide exactly one of 'directory' or 'file'")
    return ["-d", directory] if directory else ["-f", file]  # type: ignore[list-item]


def csv_timeline(
    config: HayabusaConfig,
    output_path: str,
    directory: str | None = None,
    file: str | None = None,
    extra_args: list[str] | None = None,
    timeout: int | None = None,
) -> HayabusaResult:
    args = [*_input_flag(directory, file), "-o", output_path, *(extra_args or [])]
    return run_subcommand(config, "csv-timeline", args, timeout=timeout)


def json_timeline(
    config: HayabusaConfig,
    output_path: str,
    directory: str | None = None,
    file: str | None = None,
    extra_args: list[str] | None = None,
    timeout: int | None = None,
) -> HayabusaResult:
    args = [*_input_flag(directory, file), "-o", output_path, *(extra_args or [])]
    return run_subcommand(config, "json-timeline", args, timeout=timeout)


def search(
    config: HayabusaConfig,
    keywords: list[str],
    directory: str | None = None,
    file: str | None = None,
    extra_args: list[str] | None = None,
    timeout: int | None = None,
) -> HayabusaResult:
    args = [*_input_flag(directory, file), "-k", *keywords, *(extra_args or [])]
    return run_subcommand(config, "search", args, timeout=timeout)


def logon_summary(
    config: HayabusaConfig,
    directory: str | None = None,
    file: str | None = None,
    extra_args: list[str] | None = None,
    timeout: int | None = None,
) -> HayabusaResult:
    args = [*_input_flag(directory, file), *(extra_args or [])]
    return run_subcommand(config, "logon-summary", args, timeout=timeout)


def eid_metrics(
    config: HayabusaConfig,
    directory: str | None = None,
    file: str | None = None,
    extra_args: list[str] | None = None,
    timeout: int | None = None,
) -> HayabusaResult:
    args = [*_input_flag(directory, file), *(extra_args or [])]
    return run_subcommand(config, "eid-metrics", args, timeout=timeout)


def update_rules(config: HayabusaConfig, timeout: int | None = None) -> HayabusaResult:
    return run_subcommand(config, "update-rules", [], timeout=timeout)


def list_profiles(config: HayabusaConfig, timeout: int | None = None) -> HayabusaResult:
    return run_subcommand(config, "list-profiles", [], timeout=timeout)


def summarize_csv_timeline(csv_path: str, sample_size: int = 20) -> TimelineSummary:
    """Read a hayabusa csv-timeline output file and summarize it.

    Avoids returning a potentially huge CSV verbatim to the caller: counts rows by
    the 'Level' column (if present) and keeps only a small sample of rows.
    """
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        level_counts: Counter[str] = Counter()
        sample_rows: list[dict[str, str]] = []
        total = 0
        for row in reader:
            total += 1
            level = row.get("Level", "Unknown")
            level_counts[level] += 1
            if len(sample_rows) < sample_size:
                sample_rows.append(row)

    return TimelineSummary(
        total_events=total, level_counts=dict(level_counts), sample_rows=sample_rows
    )
