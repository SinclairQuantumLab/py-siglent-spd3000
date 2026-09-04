from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_linux_gateway_launcher_is_repo_aware_and_supervisor_friendly() -> None:
    launcher = (ROOT / "gateway-startup.sh").read_text(encoding="utf-8")

    assert launcher.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert 'script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"' in launcher
    assert 'venv_python="./.venv/bin/python"' in launcher
    assert 'settings_path="./gateway-settings.toml"' in launcher
    assert "uv sync" in launcher
    assert "gateway-settings.toml.template" in launcher
    assert "exec \"$venv_python\" -m siglent_spd3000.cli gateway serve" in launcher
    assert '"$@"' in launcher


def test_windows_gateway_launcher_is_repo_aware_and_returns_exit_code() -> None:
    launcher = (ROOT / "gateway-startup.ps1").read_text(encoding="utf-8")

    assert "$ScriptDir = $PSScriptRoot" in launcher
    assert '".venv\\Scripts\\python.exe"' in launcher
    assert '"gateway-settings.toml"' in launcher
    assert "uv sync" in launcher
    assert "gateway-settings.toml.template" in launcher
    assert "-m siglent_spd3000.cli gateway serve" in launcher
    assert "@args" in launcher
    assert "exit $GatewayExitCode" in launcher


def test_supervisor_templates_follow_the_existing_platform_conventions() -> None:
    linux = (
        ROOT / "deployment/supervisor/spd3000-gateway-linux.conf.template"
    ).read_text(encoding="utf-8")
    windows = (
        ROOT / "deployment/supervisor/spd3000-gateway-windows.conf.template"
    ).read_text(encoding="utf-8")

    for config in (linux, windows):
        parser = ConfigParser(interpolation=None)
        parser.read_string(config)
        assert parser.sections() == ["program:spd3000-gateway"]
        assert "[program:spd3000-gateway]" in config
        assert "autostart=true" in config
        assert "startsecs=5" in config
        assert "startretries=5" in config
        assert "autorestart=unexpected" in config
        assert "%(here)s" in config

    assert "%(ENV_HOME)s/Projects/py-siglent-spd3000/gateway-startup.sh" in linux
    assert "stopsignal=INT" in linux
    assert "stopwaitsecs=15" in linux
    assert (
        "%(ENV_USERPROFILE)s\\Projects\\py-siglent-spd3000\\gateway-startup.ps1"
        in windows
    )
