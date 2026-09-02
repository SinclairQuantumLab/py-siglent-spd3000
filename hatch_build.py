"""Hatch build hook embedding an exact Git commit in built artifacts."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Generate temporary commit metadata for wheels and source archives."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        del version
        target = Path(self.root) / "src" / "siglent_spd3000" / "_build_commit.py"
        original = target.read_text(encoding="utf-8") if target.exists() else None
        commit = os.environ.get("SIGLENT_SPD3000_BUILD_COMMIT", "")
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", commit):
            try:
                commit = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=self.root,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                embedded = re.search(
                    r"^COMMIT\s*=\s*['\"]([0-9a-fA-F]{40,64})['\"]",
                    original or "",
                    re.MULTILINE,
                )
                commit = embedded.group(1) if embedded else "unknown"
        target.write_text(
            f'"""Generated at build time; do not edit."""\n\nCOMMIT = {commit.lower()!r}\n',
            encoding="utf-8",
        )
        destination = (
            "siglent_spd3000/_build_commit.py"
            if self.target_name == "wheel"
            else "src/siglent_spd3000/_build_commit.py"
        )
        build_data["force_include"][str(target)] = destination
        self._target = target
        self._original = original

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        del version, build_data, artifact_path
        target = getattr(self, "_target", None)
        if target is not None:
            original = getattr(self, "_original", None)
            if original is None:
                target.unlink(missing_ok=True)
            else:
                target.write_text(original, encoding="utf-8")
