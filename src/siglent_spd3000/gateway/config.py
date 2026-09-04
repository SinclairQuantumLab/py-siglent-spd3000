"""Load a gateway process and physical instrument connection from TOML."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

from .._constants import DEFAULT_GATEWAY_PORT, DEFAULT_SCPI_PORT
from ..exceptions import GatewayConfigurationError, SPD3000ValidationError
from ..execution import DirectExecutor, ExecutionSettings, Transport
from ..models import ConnectionType
from ..transport import SocketTransport, VisaTransport, VXI11Transport

GATEWAY_TEMPLATE_NAMES = (
    "gateway-settings.toml.template",
    "gateway-auth.toml.template",
)


@dataclass(frozen=True)
class InstrumentSettings:
    """Validated physical instrument settings owned by the gateway process."""

    connection: ConnectionType
    identifier: str
    visa_backend: str | None
    execution: ExecutionSettings

    def __str__(self) -> str:
        """Return the configured physical connection without opening it."""

        return "\n".join(
            (
                "SIGLENT SPD3000 Series gateway instrument settings",
                *_instrument_settings_lines(self),
            )
        )

    def open_executor(self) -> DirectExecutor:
        """Open the configured physical transport and wrap it in a direct executor."""

        transport: Transport
        if self.connection is ConnectionType.SOCKET:
            transport = SocketTransport(
                self.identifier,
                port=DEFAULT_SCPI_PORT,
                timeout=self.execution.timeout,
            )
        elif self.connection is ConnectionType.VXI11:
            transport = VXI11Transport(self.identifier, timeout=self.execution.timeout)
        else:
            transport = VisaTransport(
                self.identifier,
                backend=self.visa_backend,
                timeout=self.execution.timeout,
            )
        return DirectExecutor(transport, self.execution)


@dataclass(frozen=True)
class GatewaySettings:
    """Validated settings needed to run one gateway process."""

    source: Path
    bind: str
    port: int
    instrument: InstrumentSettings

    def __str__(self) -> str:
        """Return listener and physical instrument settings in a readable summary."""

        return "\n".join(
            (
                "SIGLENT SPD3000 Series gateway settings",
                f"- Source: {self.source}",
                "- Listener:",
                f"  - Bind address: {self.bind}",
                f"  - Port: {self.port}",
                "- Instrument:",
                *_instrument_settings_lines(self.instrument, indent="  "),
            )
        )


def _instrument_settings_lines(
    settings: InstrumentSettings, *, indent: str = ""
) -> tuple[str, ...]:
    lines = [
        f"{indent}- Connection:",
        f"{indent}  - Type: {settings.connection.value}",
        f"{indent}  - Identifier: {settings.identifier}",
    ]
    if settings.connection is ConnectionType.VISA:
        lines.append(f"{indent}  - VISA backend: {settings.visa_backend or 'default'}")
    lines.extend(
        (
            f"{indent}- Execution:",
            (
                f"{indent}  - Minimum command interval: "
                f"{settings.execution.min_command_interval * 1000:.15g} ms"
            ),
            f"{indent}  - Timeout: {settings.execution.timeout:.15g} s",
        )
    )
    return tuple(lines)


def load_gateway_settings(path: str | Path = "gateway-settings.toml") -> GatewaySettings:
    """Load and validate the gateway process and physical instrument settings."""

    source = Path(path).expanduser().resolve()
    try:
        with source.open("rb") as stream:
            document = _load_toml(stream)
    except FileNotFoundError as exc:
        raise GatewayConfigurationError(
            f"Gateway settings file not found: {source}. "
            "Copy gateway-settings.toml.template to gateway-settings.toml and edit it."
        ) from exc
    except OSError as exc:
        raise GatewayConfigurationError(f"Could not read gateway settings {source}: {exc}") from exc
    except Exception as exc:
        if type(exc).__module__.split(".", 1)[0] not in {"tomllib", "tomli"}:
            raise
        raise GatewayConfigurationError(f"Invalid TOML in {source}: {exc}") from exc

    if not isinstance(document, dict):
        raise GatewayConfigurationError("Gateway settings must contain TOML tables")
    _reject_unknown_keys(document, {"gateway", "instrument"}, "document root")
    gateway = _table(document, "gateway", required=False)
    instrument = _table(document, "instrument", required=True)
    _reject_unknown_keys(gateway, {"bind", "port"}, "[gateway]")
    _reject_unknown_keys(
        instrument,
        {
            "connection",
            "identifier",
            "visa_backend",
            "timeout_s",
            "min_command_interval_ms",
        },
        "[instrument]",
    )

    bind = _string(gateway, "bind", default="localhost")
    gateway_port = _port(gateway, "port", default=DEFAULT_GATEWAY_PORT)

    connection_name = _string(instrument, "connection").lower()
    try:
        connection = ConnectionType(connection_name)
    except ValueError as exc:
        raise GatewayConfigurationError(
            "instrument.connection must be 'socket', 'vxi11', or 'visa'"
        ) from exc
    if connection is ConnectionType.GATEWAY:
        raise GatewayConfigurationError(
            "instrument.connection cannot be 'gateway'; the server must own a physical connection"
        )

    identifier = _string(instrument, "identifier")
    visa_backend_value = instrument.get("visa_backend")
    if connection is ConnectionType.SOCKET:
        if visa_backend_value is not None:
            raise GatewayConfigurationError(
                "instrument.visa_backend can only be used with connection='visa'"
            )
        visa_backend = None
    elif connection is ConnectionType.VISA:
        visa_backend = _optional_string(instrument, "visa_backend")
    else:
        if visa_backend_value is not None:
            raise GatewayConfigurationError(
                "instrument.visa_backend can only be used with connection='visa'"
            )
        visa_backend = None

    timeout = _number(instrument, "timeout_s", default=5.0)
    interval_ms = _number(instrument, "min_command_interval_ms", default=100.0)
    try:
        execution = ExecutionSettings(
            min_command_interval=interval_ms / 1000.0,
            timeout=timeout,
            _warning_stacklevel=3,
        )
    except SPD3000ValidationError as exc:
        raise GatewayConfigurationError(f"Invalid [instrument] execution setting: {exc}") from exc

    return GatewaySettings(
        source=source,
        bind=bind,
        port=gateway_port,
        instrument=InstrumentSettings(
            connection=connection,
            identifier=identifier,
            visa_backend=visa_backend,
            execution=execution,
        ),
    )


def load_gateway_auth(
    path: str | Path = "gateway-auth.toml", *, required: bool = False
) -> str | None:
    """Read an optional pre-shared token from a gateway authentication file."""

    source = Path(path).expanduser().resolve()
    try:
        with source.open("rb") as stream:
            document = _load_toml(stream)
    except FileNotFoundError as exc:
        if not required:
            return None
        raise GatewayConfigurationError(
            f"Gateway authentication file not found: {source}. "
            "Copy gateway-auth.toml.template to gateway-auth.toml and set token."
        ) from exc
    except OSError as exc:
        raise GatewayConfigurationError(
            f"Could not read gateway authentication file {source}: {exc}"
        ) from exc
    except Exception as exc:
        if type(exc).__module__.split(".", 1)[0] not in {"tomllib", "tomli"}:
            raise
        raise GatewayConfigurationError(f"Invalid TOML in {source}: {exc}") from exc

    if not isinstance(document, dict):
        raise GatewayConfigurationError("Gateway authentication must be a TOML document")
    _reject_unknown_keys(document, {"token"}, "authentication document root")
    token = document.get("token")
    if token is None or (isinstance(token, str) and not token.strip()):
        return None
    return _string(document, "token")


def create_gateway_config_files(directory: str | Path = ".") -> tuple[Path, Path]:
    """Create editable gateway TOML files from the packaged templates without overwriting."""

    target_directory = Path(directory).expanduser().resolve()
    if not target_directory.is_dir():
        raise GatewayConfigurationError(
            f"Gateway configuration directory not found: {target_directory}"
        )
    targets = tuple(
        target_directory / name.removesuffix(".template") for name in GATEWAY_TEMPLATE_NAMES
    )
    existing = [target for target in targets if target.exists()]
    if existing:
        raise GatewayConfigurationError(f"Refusing to overwrite existing file: {existing[0]}")
    template_directory = files(__package__).joinpath("templates")
    try:
        contents = tuple(
            template_directory.joinpath(name).read_text(encoding="utf-8")
            for name in GATEWAY_TEMPLATE_NAMES
        )
        for target, content in zip(targets, contents, strict=True):
            target.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise GatewayConfigurationError(
            f"Could not create gateway configuration in {target_directory}: {exc}"
        ) from exc
    return cast(tuple[Path, Path], targets)


def _load_toml(stream: Any) -> dict[str, Any]:
    try:
        toml = import_module("tomllib")
    except ModuleNotFoundError:
        try:
            toml = import_module("tomli")
        except ModuleNotFoundError as exc:
            raise GatewayConfigurationError(
                "TOML support on Python 3.10 requires tomli; "
                "reinstall py-siglent-spd3000 to restore its runtime dependencies"
            ) from exc
    return cast(dict[str, Any], toml.load(stream))


def _table(document: dict[str, Any], name: str, *, required: bool) -> dict[str, Any]:
    value = document.get(name)
    if value is None and not required:
        return {}
    if not isinstance(value, dict):
        qualifier = "required" if value is None else "must be a TOML table"
        raise GatewayConfigurationError(f"[{name}] is {qualifier}")
    return value


def _reject_unknown_keys(table: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise GatewayConfigurationError(f"Unknown key in {location}: {unknown[0]}")


def _string(table: dict[str, Any], name: str, *, default: str | None = None) -> str:
    value = table.get(name, default)
    if not isinstance(value, str) or not value.strip():
        raise GatewayConfigurationError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_string(table: dict[str, Any], name: str) -> str | None:
    value = table.get(name)
    return None if value is None else _string(table, name)


def _port(table: dict[str, Any], name: str, *, default: int) -> int:
    value = table.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise GatewayConfigurationError(f"{name} must be an integer from 1 through 65535")
    return value


def _number(table: dict[str, Any], name: str, *, default: float) -> float:
    value = table.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GatewayConfigurationError(f"{name} must be a real number")
    return float(value)
