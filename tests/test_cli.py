from __future__ import annotations

from siglent_spd3000.cli import main


def test_lookup_cli_reports_python_path(capsys: object) -> None:
    assert main(["lookup", "OUTP"]) == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "output(channel, state); output.ch1/ch2/ch3" in output


def test_lookup_cli_reports_missing_command(capsys: object) -> None:
    assert main(["lookup", "NOPE"]) == 1
    assert capsys.readouterr().out == ""  # type: ignore[attr-defined]
