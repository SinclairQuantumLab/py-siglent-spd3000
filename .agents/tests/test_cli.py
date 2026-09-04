from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import siglent_spd3000.cli as cli
from siglent_spd3000 import (
    BatchResult,
    CommandBatch,
    ConnectionType,
    ExecutionSettings,
    Model,
)
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


def test_gateway_serve_reports_physical_connection_and_identity(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeExecutor:
        settings = ExecutionSettings()

        def __init__(self) -> None:
            self.commands: list[str] = []
            self.closed = False

        def execute(self, batch: CommandBatch) -> BatchResult:
            self.commands.extend(command.text for command in batch.commands)
            return BatchResult(("Siglent Technologies,SPD3303X,SPD0001,1.0",))

        def close(self) -> None:
            self.closed = True

    executor = FakeExecutor()
    instrument = SimpleNamespace(
        connection=ConnectionType.SOCKET,
        identifier="192.168.1.50",
        visa_backend=None,
        execution=executor.settings,
        open_executor=lambda: executor,
    )
    settings = SimpleNamespace(
        source=Path("gateway-settings.toml").resolve(),
        bind="localhost",
        port=8765,
        instrument=instrument,
    )

    class FakeGatewayServer:
        def __init__(self, *_args: object, port: int, **_kwargs: object) -> None:
            self.port = port

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def close(self) -> None:
            executor.close()

    monkeypatch.setattr(cli, "_configure_gateway_request_logging", lambda: None)
    monkeypatch.setattr(cli, "load_gateway_settings", lambda _path: settings)
    monkeypatch.setattr(cli, "load_gateway_auth", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "GatewayServer", FakeGatewayServer)
    gateway_logger = logging.getLogger(cli._GATEWAY_LOGGER_NAME)
    monkeypatch.setattr(gateway_logger, "handlers", [])
    monkeypatch.setattr(gateway_logger, "propagate", True)

    with caplog.at_level(logging.INFO, logger=cli._GATEWAY_LOGGER_NAME):
        assert cli.main(["gateway", "serve"]) == 0

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "gateway token authentication disabled" in messages
    assert (
        "opening physical instrument connection: type=socket identifier=192.168.1.50"
        in messages
    )
    assert (
        "SIGLENT SPD3000 Series gateway physical instrument connection\n"
        "- Identification:\n"
        "  - Manufacturer: Siglent Technologies\n"
        "  - Model: SPD3303X\n"
        "  - Serial number: SPD0001\n"
        "  - Firmware version: 1.0\n"
        "- Connection:\n"
        "  - Type: socket\n"
        "  - Identifier: 192.168.1.50\n"
        "  - State: open\n"
        "- Execution settings:\n"
        "  - Timeout: 5 s\n"
        "  - Minimum command interval: 100 ms"
        in messages
    )
    assert "shutdown requested by Ctrl+C" in messages
    assert executor.commands == ["*IDN?"]
    assert executor.closed is True
    assert "Serving SPD3000 gateway on localhost:8765" in capsys.readouterr().out
