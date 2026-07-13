from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mcp_hayabusa import hayabusa
from mcp_hayabusa.config import HayabusaConfig


@pytest.fixture
def config() -> HayabusaConfig:
    return HayabusaConfig(binary_path="hayabusa", rules_path=None, default_timeout=60)


def test_run_subcommand_rejects_unknown_subcommand(config: HayabusaConfig) -> None:
    with pytest.raises(hayabusa.HayabusaSubcommandNotAllowedError):
        hayabusa.run_subcommand(config, "rm-rf-everything")


def test_run_subcommand_builds_expected_args(monkeypatch, config: HayabusaConfig) -> None:
    captured = {}

    def fake_run(args, capture_output, text, timeout, check):
        captured["args"] = args
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = hayabusa.run_subcommand(config, "list-profiles", ["--foo", "bar"])

    assert captured["args"] == ["hayabusa", "list-profiles", "--foo", "bar"]
    assert captured["timeout"] == 60
    assert result.ok
    assert result.stdout == "ok"


def test_run_subcommand_times_out(monkeypatch, config: HayabusaConfig) -> None:
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="hayabusa", timeout=60)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(hayabusa.HayabusaTimeoutError):
        hayabusa.run_subcommand(config, "eid-metrics")


def test_input_flag_requires_exactly_one_source() -> None:
    with pytest.raises(ValueError):
        hayabusa._input_flag(None, None)
    with pytest.raises(ValueError):
        hayabusa._input_flag("dir", "file.evtx")


def test_csv_timeline_uses_directory_flag(monkeypatch, config: HayabusaConfig) -> None:
    captured = {}

    def fake_run_subcommand(cfg, subcommand, args=None, timeout=None):
        captured["subcommand"] = subcommand
        captured["args"] = args
        return hayabusa.HayabusaResult(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(hayabusa, "run_subcommand", fake_run_subcommand)

    hayabusa.csv_timeline(config, "out.csv", directory="C:/logs", extra_args=["-m", "medium"])

    assert captured["subcommand"] == "csv-timeline"
    assert captured["args"] == ["-d", "C:/logs", "-o", "out.csv", "-m", "medium"]


def test_summarize_csv_timeline(tmp_path: Path) -> None:
    csv_path = tmp_path / "results.csv"
    csv_path.write_text(
        "Timestamp,Level,EventID\n"
        "2026-01-01,high,4625\n"
        "2026-01-02,medium,4624\n"
        "2026-01-03,high,4625\n",
        encoding="utf-8",
    )

    summary = hayabusa.summarize_csv_timeline(str(csv_path), sample_size=2)

    assert summary.total_events == 3
    assert summary.level_counts == {"high": 2, "medium": 1}
    assert len(summary.sample_rows) == 2
