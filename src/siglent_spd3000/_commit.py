"""Resolve the exact source commit used by gateway compatibility checks."""

from __future__ import annotations

import os
import re
import subprocess
from importlib import import_module
from pathlib import Path

UNKNOWN_COMMIT = "unknown"
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")


def _resolve_commit() -> str:
    """Resolve the commit represented by the code being imported."""

    try:
        embedded_commit = getattr(
            import_module(f"{__package__}._build_commit"), "COMMIT", ""
        )
    except ImportError:
        embedded_commit = ""
    if isinstance(embedded_commit, str) and _COMMIT_RE.fullmatch(embedded_commit):
        return embedded_commit.lower()

    environment = os.environ.get("SIGLENT_SPD3000_BUILD_COMMIT", "")
    if _COMMIT_RE.fullmatch(environment):
        return environment.lower()

    repository = Path(__file__).resolve().parents[2]
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN_COMMIT
    commit = completed.stdout.strip()
    return commit.lower() if _COMMIT_RE.fullmatch(commit) else UNKNOWN_COMMIT


_RUNTIME_COMMIT = _resolve_commit()


def get_commit() -> str:
    """Return the commit captured when this process imported the package."""

    return _RUNTIME_COMMIT
