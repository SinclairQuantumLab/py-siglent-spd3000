from __future__ import annotations

from types import SimpleNamespace

import pytest

import siglent_spd3000.cli as cli
from siglent_spd3000 import Model
from siglent_spd3000.models import parse_identification, parse_status


class FakeDevice:
    def __init__(self) -> None:
        self.idn = parse_identification("SIGLENT,SPD3303X,SERIAL,1.2.3")
        self.system = SimpleNamespace(status=parse_status("0x10", Model.SPD3303X))

    def __enter__(self) -> FakeDevice:
        return self

    def __exit__(self, *_args: object) -> None:
        pass


def test_lookup_cli_reports_python_path(capsys: object) -> None:
    assert cli.main(["lookup", "OUTP"]) == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "SIGLENT SPD3000 Series SCPI command" in output
    assert "output(channel, state)" in output
    assert "- Friendly Python aliases:" in output
    assert "  - ch1.output" in output
    assert "  - ch2.output" in output
    assert "  - ch3.output" in output


def test_lookup_cli_reports_missing_command(capsys: object) -> None:
    assert cli.main(["lookup", "NOPE"]) == 1
    assert capsys.readouterr().out == ""  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("command", "title"),
    (
        ("idn", "SIGLENT SPD3000 Series instrument identification"),
        ("status", "SIGLENT SPD3000 Series system status"),
    ),
)
def test_typed_cli_results_use_their_readable_string_form(
    command: str,
    title: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_open_device", lambda _args: FakeDevice())

    assert cli.main([command, "--socket", "instrument.local"]) == 0

    assert capsys.readouterr().out.startswith(f"{title}\n")
