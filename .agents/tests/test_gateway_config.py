from __future__ import annotations

from pathlib import Path

import pytest

from siglent_spd3000 import GatewayConfigurationError
from siglent_spd3000._constants import DEFAULT_GATEWAY_PORT, DEFAULT_SCPI_PORT
from siglent_spd3000.cli import build_parser, main
from siglent_spd3000.gateway import config
from siglent_spd3000.models import ConnectionType


def test_gateway_settings_load_socket(tmp_path: Path) -> None:
    source = tmp_path / "gateway-settings.toml"
    source.write_text(
        """
[gateway]
bind = "192.168.50.20"
port = 18765

[instrument]
connection = "socket"
identifier = "192.168.50.30"
timeout_s = 7.5
min_command_interval_ms = 50
""".strip(),
        encoding="utf-8",
    )

    settings = config.load_gateway_settings(source)

    assert settings.source == source.resolve()
    assert settings.bind == "192.168.50.20"
    assert settings.port == 18765
    assert settings.instrument.connection is ConnectionType.SOCKET
    assert settings.instrument.identifier == "192.168.50.30"
    assert settings.instrument.execution.timeout == 7.5
    assert settings.instrument.execution.min_command_interval == 0.05


def test_gateway_settings_apply_safe_defaults(tmp_path: Path) -> None:
    source = tmp_path / "gateway-settings.toml"
    source.write_text(
        '[instrument]\nconnection = "vxi11"\nidentifier = "power-supply.local"\n',
        encoding="utf-8",
    )

    settings = config.load_gateway_settings(source)

    assert settings.bind == "localhost"
    assert settings.port == DEFAULT_GATEWAY_PORT
    assert settings.instrument.connection is ConnectionType.VXI11
    assert settings.instrument.visa_backend is None
    assert settings.instrument.execution.timeout == 5.0
    assert settings.instrument.execution.min_command_interval == 0.1


def test_distributed_gateway_templates_match_repository_copies() -> None:
    root = Path(__file__).resolve().parents[2]
    packaged = root / "src" / "siglent_spd3000" / "gateway" / "templates"
    for name in config.GATEWAY_TEMPLATE_NAMES:
        assert (packaged / name).read_bytes() == (root / name).read_bytes()
    auth_template = (root / "gateway-auth.toml.template").read_text(encoding="utf-8")
    assert "[auth]" not in auth_template
    assert "Any non-empty custom string is a valid token" in auth_template
    assert "secrets.token_urlsafe(32)" in auth_template


def test_socket_executor_always_uses_fixed_siglent_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "gateway-settings.toml"
    source.write_text(
        '[instrument]\nconnection = "socket"\nidentifier = "power-supply.local"\n',
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class FakeTransport:
        def __init__(self, host: str, *, port: int, timeout: float) -> None:
            captured.update(host=host, port=port, timeout=timeout)

        def write(self, data: bytes) -> None:
            del data

        def read(self) -> bytes:
            return b""

        def close(self) -> None:
            pass

    monkeypatch.setattr(config, "SocketTransport", FakeTransport)
    executor = config.load_gateway_settings(source).instrument.open_executor()
    try:
        assert captured == {
            "host": "power-supply.local",
            "port": DEFAULT_SCPI_PORT,
            "timeout": 5.0,
        }
    finally:
        executor.close()


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        (
            '[instrument]\nconnection = "socket"\nidentifier = "host"\nport = 5000\n',
            "Unknown key in [instrument]: port",
        ),
        (
            '[instrument]\nconnection = "gateway"\nidentifier = "host"\n',
            "instrument.connection cannot be 'gateway'",
        ),
        (
            '[instrument]\nconnection = "socket"\nidentifier = "host"\nvisa_backend = "@py"\n',
            "visa_backend can only be used",
        ),
        (
            '[gateway]\nport = 0\n[instrument]\nconnection = "socket"\nidentifier = "host"\n',
            "port must be an integer from 1 through 65535",
        ),
    ],
)
def test_gateway_settings_reject_invalid_or_misleading_options(
    tmp_path: Path, contents: str, message: str
) -> None:
    source = tmp_path / "gateway-settings.toml"
    source.write_text(contents, encoding="utf-8")

    with pytest.raises(GatewayConfigurationError) as captured:
        config.load_gateway_settings(source)
    assert message in str(captured.value)


def test_gateway_serve_uses_external_settings_file_by_default() -> None:
    args = build_parser().parse_args(["gateway", "serve"])
    assert args.config == Path("gateway-settings.toml")
    assert args.auth is None
    assert not hasattr(args, "socket")
    assert not hasattr(args, "bind")


def test_gateway_client_uses_authentication_toml_option() -> None:
    args = build_parser().parse_args(
        ["idn", "--gateway", "gateway.local:3333", "--gateway-auth", "client-auth.toml"]
    )
    assert args.gateway == "gateway.local:3333"
    assert args.gateway_auth == Path("client-auth.toml")
    assert not hasattr(args, "gateway_port")
    assert not hasattr(args, "socket_port")


def test_gateway_init_creates_both_files_without_overwriting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["gateway", "init", "--directory", str(tmp_path)]) == 0
    assert (tmp_path / "gateway-settings.toml").is_file()
    auth = tmp_path / "gateway-auth.toml"
    assert auth.is_file()
    auth.write_text("do not replace", encoding="utf-8")

    assert main(["gateway", "init", "--directory", str(tmp_path)]) == 1
    assert auth.read_text(encoding="utf-8") == "do not replace"
    assert "Refusing to overwrite existing file" in capsys.readouterr().err


def test_gateway_auth_loads_token(tmp_path: Path) -> None:
    source = tmp_path / "gateway-auth.toml"
    source.write_text('token = "correct-horse-battery-staple"\n', encoding="utf-8")

    assert config.load_gateway_auth(source) == "correct-horse-battery-staple"


def test_missing_optional_gateway_auth_means_no_authentication(tmp_path: Path) -> None:
    assert config.load_gateway_auth(tmp_path / "missing.toml", required=False) is None


def test_empty_optional_gateway_auth_means_local_only(tmp_path: Path) -> None:
    source = tmp_path / "gateway-auth.toml"
    source.write_text('token = ""\n', encoding="utf-8")

    assert config.load_gateway_auth(source, required=False) is None


@pytest.mark.parametrize(
    "contents",
    [
        'token = ""\n',
        'token = "secret"\nextra = true\n',
        '[auth]\ntoken = "secret"\n',
    ],
)
def test_gateway_auth_rejects_invalid_files(tmp_path: Path, contents: str) -> None:
    source = tmp_path / "gateway-auth.toml"
    source.write_text(contents, encoding="utf-8")

    with pytest.raises(GatewayConfigurationError):
        config.load_gateway_auth(source)


def test_explicit_missing_gateway_auth_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing-auth.toml"
    assert (
        main(
            [
                "idn",
                "--gateway",
                "localhost",
                "--gateway-auth",
                str(missing),
            ]
        )
        == 1
    )
    assert "Gateway authentication file not found" in capsys.readouterr().err


def test_gateway_serve_reports_missing_settings_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.toml"
    assert main(["gateway", "serve", "--config", str(missing)]) == 1
    assert "Gateway settings file not found" in capsys.readouterr().err
