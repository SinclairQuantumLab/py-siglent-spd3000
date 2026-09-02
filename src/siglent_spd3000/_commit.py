"""Resolve the exact source commit used by gateway compatibility checks."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

UNKNOWN_COMMIT = "unknown"
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")


def get_commit() -> str:
    """Return embedded, environment-provided, or source-checkout Git commit."""

    try:
        from ._build_commit import COMMIT  # type: ignore[import-not-found]
    except ImportError:
        COMMIT = ""
    if isinstance(COMMIT, str) and _COMMIT_RE.fullmatch(COMMIT):
        return COMMIT.lower()

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
