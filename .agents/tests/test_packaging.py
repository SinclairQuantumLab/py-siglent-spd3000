from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


def test_all_runtime_features_use_the_default_install() -> None:
    with (Path(__file__).parents[2] / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]

    assert "optional-dependencies" not in project
    assert set(project["dependencies"]) == {
        "ipykernel>=7.3.0",
        "pyvisa>=1.16",
        "pyvisa-py[usb]>=0.8",
        "python-vxi11>=0.9",
        "standard-xdrlib; python_version >= '3.13'",
        "tomli>=2.2; python_version < '3.11'",
        "zeroconf>=0.151.3",
    }
