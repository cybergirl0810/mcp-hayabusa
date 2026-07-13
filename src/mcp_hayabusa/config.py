"""Environment-driven configuration for locating the Hayabusa binary and its data."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass


class HayabusaNotFoundError(RuntimeError):
    """Raised when the hayabusa binary cannot be located."""


@dataclass(frozen=True)
class HayabusaConfig:
    binary_path: str
    rules_path: str | None
    default_timeout: int


def _resolve_binary_path() -> str:
    configured = os.environ.get("HAYABUSA_PATH")
    if configured:
        return configured

    on_path = shutil.which("hayabusa") or shutil.which("hayabusa.exe")
    if on_path:
        return on_path

    raise HayabusaNotFoundError(
        "Could not locate the hayabusa binary. Set the HAYABUSA_PATH environment "
        "variable to the full path of hayabusa(.exe), or add it to your PATH."
    )


def load_config() -> HayabusaConfig:
    return HayabusaConfig(
        binary_path=_resolve_binary_path(),
        rules_path=os.environ.get("HAYABUSA_RULES_PATH"),
        default_timeout=int(os.environ.get("HAYABUSA_TIMEOUT_SECONDS", "600")),
    )
