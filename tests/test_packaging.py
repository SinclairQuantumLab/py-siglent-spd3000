from __future__ import annotations

import re
from pathlib import Path


def test_public_extras_are_exactly_driver_and_gateway() -> None:
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    extras_section = pyproject.split("[project.optional-dependencies]", 1)[1].split("\n[", 1)[0]
    extras = set(re.findall(r"^([A-Za-z][A-Za-z0-9_-]*)\s*=", extras_section, re.MULTILINE))

    assert extras == {"driver", "gateway"}
