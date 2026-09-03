"""Synchronous semantic driver for Siglent SPD3000-series supplies."""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from ipaddress import AddressValueError, IPv4Address, IPv4Network, NetmaskValueError
from types import TracebackType
from typing import overload

from ._constants import DEFAULT_GATEWAY_PORT, DEFAULT_SCPI_PORT
from .exceptions import (
    SPD3000Error,
    SPD3000ProtocolError,
    SPD3000ValidationError,
    SPD3000VerificationError,
    UnsupportedFeatureError,
)
from .execution import (
    BatchResult,
    Command,
    CommandBatch,
    DirectExecutor,
    ExecutionSettings,
    Executor,
    Query,
    Write,
)
from .models import (
    CAPABILITIES,
    Capabilities,
    Channel,
    ConnectionType,
    Identification,
    NetworkSettings,
    OutputState,
    SystemError,
    SystemStatus,
    TimerState,
    TrackingMode,
    WaveformState,
    parse_identification,
    parse_status,
    parse_system_error,
)
from .transport import SocketTransport, VisaTransport, VXI11Transport


def _require_channel(value: Channel | str, *, programmable: bool = False) -> Channel:
    if isinstance(value, Channel):
        channel = value
    elif isinstance(value, str):
        try:
            channel = Channel(value.strip().upper())
        except ValueError as exc:
            raise SPD3000ValidationError("channel must be CH1, CH2, or CH3") from exc
    else:
        raise SPD3000ValidationError("channel must be a Channel enum value or string")
    if programmable and channel is Channel.CH3:
        raise SPD3000ValidationError("CH3 has no programmable voltage or current")
    return channel


def _require_timer_group(group: int) -> int:
    if isinstance(group, bool) or not isinstance(group, int) or not 1 <= group <= 5:
        raise SPD3000ValidationError("timer group must be an integer from 1 through 5")
    return group


def _require_bool(name: str, value: bool) -> bool:
    if type(value) is not bool:
        raise SPD3000ValidationError(f"{name} must be bool")
    return value


def _require_output_state(value: OutputState | str) -> OutputState:
    if isinstance(value, OutputState):
        return value
    if isinstance(value, str):
        try:
            return OutputState(value.strip().upper())
        except ValueError:
            pass
    raise SPD3000ValidationError("state must be OutputState.ON, OutputState.OFF, 'ON', or 'OFF'")


def _require_waveform_state(value: WaveformState | str) -> WaveformState:
    if isinstance(value, WaveformState):
        return value
    if isinstance(value, str):
        try:
            return WaveformState(value.strip().upper())
        except ValueError:
            pass
    raise SPD3000ValidationError(
        "state must be WaveformState.ON, WaveformState.OFF, 'ON', or 'OFF'"
    )


def _require_timer_state(value: TimerState | str) -> TimerState:
    if isinstance(value, TimerState):
        return value
    if isinstance(value, str):
        try:
            return TimerState(value.strip().upper())
        except ValueError:
            pass
    raise SPD3000ValidationError("state must be TimerState.ON, TimerState.OFF, 'ON', or 'OFF'")


def _require_ipv4_address(value: str) -> str:
    if not isinstance(value, str):
        raise SPD3000ValidationError("IPv4 address must be a string")
    try:
        return str(IPv4Address(value))
    except AddressValueError as exc:
        raise SPD3000ValidationError(f"Invalid IPv4 address: {value!r}") from exc


def _require_subnet_mask(value: str) -> str:
    if not isinstance(value, str):
        raise SPD3000ValidationError("subnet mask must be a string")
    try:
        return str(IPv4Network(f"0.0.0.0/{value}").netmask)
    except (AddressValueError, NetmaskValueError) as exc:
        raise SPD3000ValidationError(f"Invalid IPv4 subnet mask: {value!r}") from exc


def _parse_ipv4_address(command: str, response: str) -> str:
    value = response.strip()
    try:
        return str(IPv4Address(value))
    except AddressValueError as exc:
        raise SPD3000ProtocolError(f"Malformed {command} response: {value!r}") from exc


def _parse_subnet_mask(response: str) -> str:
    value = response.strip()
    try:
        return str(IPv4Network(f"0.0.0.0/{value}").netmask)
    except (AddressValueError, NetmaskValueError) as exc:
        raise SPD3000ProtocolError(f"Malformed MASKADDR? response: {value!r}") from exc


def _format_number(
    name: str,
    value: float,
    *,
    minimum: Decimal,
    maximum: Decimal,
    resolution: Decimal | None = None,
) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise SPD3000ValidationError(f"{name} must be a real number")
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as exc:
        raise SPD3000ValidationError(f"{name} must be a real number") from exc
    if not decimal.is_finite():
        raise SPD3000ValidationError(f"{name} must be finite")
    if not minimum <= decimal <= maximum:
        raise SPD3000ValidationError(f"{name} must be between {minimum} and {maximum}")
    if resolution is not None and decimal % resolution != 0:
        raise SPD3000ValidationError(f"{name} must align to the {resolution} resolution")
    rendered = format(decimal.normalize(), "f")
    return "0" if rendered == "-0" else rendered


def _parse_float(command: str, response: str) -> float:
    try:
        result = float(response.strip())
    except ValueError as exc:
        raise SPD3000ProtocolError(f"Malformed {command} response: {response!r}") from exc
    if not math.isfinite(result):
        raise SPD3000ProtocolError(f"Non-finite {command} response: {response!r}")
    return result


def _parse_bool(command: str, response: str) -> bool:
    normalized = response.strip().upper()
    if normalized in {"1", "ON", "TRUE"}:
        return True
    if normalized in {"0", "OFF", "FALSE"}:
        return False
    raise SPD3000ProtocolError(f"Malformed {command} response: {response!r}")


def _parse_dhcp(response: str) -> bool:
    normalized = response.strip()
    if normalized.upper().startswith("DHCP:"):
        normalized = normalized.split(":", 1)[1]
    return _parse_bool("DHCP?", normalized)


def _parse_timer_step(response: str) -> dict[str, float]:
    parts = [part.strip() for part in response.split(",")]
    if len(parts) != 3:
        raise SPD3000ProtocolError(f"Malformed TIMER:SET? response: {response!r}")
    return {
        "voltage_v": _parse_float("TIMER:SET? voltage", parts[0]),
        "current_a": _parse_float("TIMER:SET? current", parts[1]),
        "duration_s": _parse_float("TIMER:SET? time", parts[2]),
    }


@dataclass(frozen=True)
class _Verification:
    query: str | None
    expected: object
    parser: Callable[[str], object] | None
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class _PendingWrite:
    command: str
    verification: _Verification | None


class _BatchContext:
    """Reusable ``with psu.batch:`` context manager."""

    def __init__(self, device: SPD3000) -> None:
        self._device = device

    def __enter__(self) -> SPD3000:
        self._device._begin_batch()
        return self._device

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self._device._end_batch(execute=exc_type is None)


class _VerifyContext:
    """Reusable ``with psu.verify:`` context manager."""

    def __init__(self, device: SPD3000) -> None:
        self._device = device

    def __enter__(self) -> SPD3000:
        self._device._begin_verify()
        return self._device

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self._device._end_verify()


class ProgrammableChannel:
    """SCPI ``CH1`` or ``CH2`` source subtree."""

    def __init__(self, device: SPD3000, channel: Channel) -> None:
        self._device = device
        self._channel = _require_channel(channel, programmable=True)

    @property
    def voltage(self) -> float:
        """Fresh programmed voltage query in volts."""

        return _parse_float("VOLT?", self._device._query(f"{self._channel.value}:VOLT?"))

    @voltage.setter
    def voltage(self, value: float) -> None:
        rendered = self._device._setpoint("voltage", value)
        query = f"{self._channel.value}:VOLT?"
        self._device._write(
            f"{self._channel.value}:VOLT {rendered}",
            verification=_Verification(
                query,
                float(rendered),
                lambda response: _parse_float(query, response),
            ),
        )

    @property
    def current(self) -> float:
        """Fresh programmed current query in amperes."""

        return _parse_float("CURR?", self._device._query(f"{self._channel.value}:CURR?"))

    @current.setter
    def current(self, value: float) -> None:
        rendered = self._device._setpoint("current", value)
        query = f"{self._channel.value}:CURR?"
        self._device._write(
            f"{self._channel.value}:CURR {rendered}",
            verification=_Verification(
                query,
                float(rendered),
                lambda response: _parse_float(query, response),
            ),
        )

    @property
    def output(self) -> bool:
        """Fresh output state derived indirectly from ``SYSTem:STATus?``."""

        return self._device.output._read(self._channel)

    @output.setter
    def output(self, state: bool) -> None:
        enabled = _require_bool("output", state)
        self._device.output(self._channel, OutputState.ON if enabled else OutputState.OFF)


class FixedChannel:
    """Fixed-voltage CH3 with write-only convenience output control."""

    channel = Channel.CH3

    def __init__(self, device: SPD3000) -> None:
        self._device = device

    @property
    def output(self) -> bool:
        """Raise because Siglent documents no CH3 output-state query or status bit."""

        return self._device.output._read(self.channel)

    @output.setter
    def output(self, state: bool) -> None:
        enabled = _require_bool("output", state)
        self._device.output(self.channel, OutputState.ON if enabled else OutputState.OFF)


class Measure:
    """SCPI ``MEASure`` subtree; SCPI arguments remain Python arguments."""

    def __init__(self, device: SPD3000) -> None:
        self._device = device

    def voltage(self, channel: Channel | str) -> float:
        """Query ``MEASure:VOLTage? <channel>`` and return volts."""

        selected = _require_channel(channel, programmable=True)
        response = self._device._query(f"MEAS:VOLT? {selected.value}")
        return _parse_float("MEAS:VOLT?", response)

    def current(self, channel: Channel | str) -> float:
        """Query ``MEASure:CURRent? <channel>`` and return amperes."""

        selected = _require_channel(channel, programmable=True)
        response = self._device._query(f"MEAS:CURR? {selected.value}")
        return _parse_float("MEAS:CURR?", response)

    def power(self, channel: Channel | str) -> float:
        """Query ``MEASure:POWer? <channel>``; unavailable on SPD3303C."""

        self._device._require("measure_power", "MEASure:POWer")
        selected = _require_channel(channel, programmable=True)
        response = self._device._query(f"MEAS:POWE? {selected.value}")
        return _parse_float("MEAS:POWE?", response)


class Output:
    """SCPI ``OUTPut`` subtree with one documented convenience exception.

    Most of this package follows the vendor SCPI hierarchy literally. Output
    switching is unusually frequent, so channel objects additionally provide
    boolean convenience properties::

        psu.output(Channel.CH1, OutputState.ON)
        psu.output("CH1", "ON")
        psu.ch1.output = True
        print(psu.ch1.output)

    All three writes emit the same ``OUTP CH1,ON`` command. Reading CH1 or CH2 is a
    fresh, indirect ``SYST:STAT?`` query because Siglent does not document
    ``OUTP?``. CH3 can be written, but its getter raises
    :class:`UnsupportedFeatureError` because no CH3 status bit is documented;
    the driver never presents a cached write as measured hardware state.
    """

    def __init__(self, device: SPD3000) -> None:
        self._device = device

    def __call__(self, channel: Channel | str, state: OutputState | str) -> None:
        """Turn a channel output on or off using ``OUTPut <channel>,<state>``."""

        selected = _require_channel(channel)
        selected_state = _require_output_state(state)
        command = f"OUTP {selected.value},{selected_state.value}"
        expected = selected_state is OutputState.ON
        if selected is Channel.CH3:
            verification = _Verification(
                query=None,
                expected=expected,
                parser=None,
                unavailable_reason=(
                    "Siglent documents no query or SYST:STAT? bit for CH3 output state"
                ),
            )
        else:
            verification = _Verification(
                query="SYST:STAT?",
                expected=expected,
                parser=lambda response: self._status_output(response, selected),
            )
        self._device._write(command, verification=verification)

    def _read(self, channel: Channel) -> bool:
        if channel is Channel.CH3:
            raise UnsupportedFeatureError(
                "Siglent documents no query or SYST:STAT? bit for CH3 output state"
            )
        status = self._device.system.status
        return status.ch1.output if channel is Channel.CH1 else status.ch2.output

    def _status_output(self, response: str, channel: Channel) -> bool:
        status = parse_status(response, self._device.model)
        return status.ch1.output if channel is Channel.CH1 else status.ch2.output

    def track(self, mode: TrackingMode | int) -> None:
        """Set ``OUTPut:TRACK`` from the recommended enum or raw integer 0-2."""

        if isinstance(mode, bool) or not isinstance(mode, (TrackingMode, int)):
            raise SPD3000ValidationError("mode must be a TrackingMode or integer 0, 1, or 2")
        try:
            selected = TrackingMode(mode)
        except ValueError as exc:
            raise SPD3000ValidationError(
                "mode must be a TrackingMode or integer 0, 1, or 2"
            ) from exc
        expected = {
            TrackingMode.INDEPENDENT: "independent",
            TrackingMode.SERIES: "series",
            TrackingMode.PARALLEL: "parallel",
        }[selected]
        self._device._write(
            f"OUTP:TRACK {selected.value}",
            verification=_Verification(
                "SYST:STAT?",
                expected,
                lambda response: parse_status(response, self._device.model).operating_mode.value,
            ),
        )

    def wave(self, channel: Channel | str, state: WaveformState | str) -> None:
        """Set ``OUTPut:WAVE`` using its state enum or raw ``ON``/``OFF`` token."""

        self._device._require("waveform", "OUTPut:WAVE")
        selected = _require_channel(channel, programmable=True)
        selected_state = _require_waveform_state(state)
        expected = selected_state is WaveformState.ON
        self._device._write(
            f"OUTP:WAVE {selected.value},{selected_state.value}",
            verification=_Verification(
                "SYST:STAT?",
                expected,
                lambda response: self._status_waveform(response, selected),
            ),
        )

    def _status_waveform(self, response: str, channel: Channel) -> bool | None:
        status = parse_status(response, self._device.model)
        return status.ch1.waveform if channel is Channel.CH1 else status.ch2.waveform


class Timer:
    """SCPI ``TIMEr`` subtree; calling it controls the timer output state."""

    def __init__(self, device: SPD3000) -> None:
        self._device = device

    def __call__(self, channel: Channel | str, state: TimerState | str) -> None:
        """Set ``TIMEr`` using its state enum or raw ``ON``/``OFF`` token."""

        self._device._require("timer", "TIMEr")
        selected = _require_channel(channel, programmable=True)
        selected_state = _require_timer_state(state)
        expected = selected_state is TimerState.ON
        self._device._write(
            f"TIMER {selected.value},{selected_state.value}",
            verification=_Verification(
                "SYST:STAT?",
                expected,
                lambda response: self._status_timer(response, selected),
            ),
        )

    @overload
    def set(self, channel: Channel | str, group: int) -> dict[str, float]: ...

    @overload
    def set(
        self,
        channel: Channel | str,
        group: int,
        voltage_v: float,
        current_a: float,
        duration_s: float,
    ) -> None: ...

    def set(
        self,
        channel: Channel | str,
        group: int,
        voltage_v: float | None = None,
        current_a: float | None = None,
        duration_s: float | None = None,
    ) -> dict[str, float] | None:
        """Query or write one of the five ``TIMEr:SET`` groups.

        With only ``channel`` and ``group``, issue ``TIMEr:SET?`` and return a
        built-in dictionary. Supplying voltage, current, and duration issues
        ``TIMEr:SET``. The three write values may be positional or keyword
        arguments, including an ordinary ``**timer_step`` dictionary.
        """

        self._device._require("timer", "TIMEr:SET")
        selected = _require_channel(channel, programmable=True)
        selected_group = _require_timer_group(group)
        values = (voltage_v, current_a, duration_s)
        if all(value is None for value in values):
            response = self._device._query(f"TIMER:SET? {selected.value},{selected_group}")
            return _parse_timer_step(response)
        if any(value is None for value in values):
            raise SPD3000ValidationError(
                "voltage_v, current_a, and duration_s must be supplied together"
            )

        assert voltage_v is not None and current_a is not None and duration_s is not None
        voltage = self._device._setpoint("voltage", voltage_v)
        current = self._device._setpoint("current", current_a)
        duration = _format_number(
            "duration_s", duration_s, minimum=Decimal("0"), maximum=Decimal("10000")
        )
        command = f"TIMER:SET {selected.value},{selected_group},{voltage},{current},{duration}"
        self._device._write(
            command,
            verification=_Verification(
                f"TIMER:SET? {selected.value},{selected_group}",
                {
                    "voltage_v": float(voltage),
                    "current_a": float(current),
                    "duration_s": float(duration),
                },
                _parse_timer_step,
            ),
        )
        return None

    def _status_timer(self, response: str, channel: Channel) -> bool | None:
        status = parse_status(response, self._device.model)
        return status.ch1.timer if channel is Channel.CH1 else status.ch2.timer


class System:
    """SCPI ``SYSTem`` query subtree."""

    def __init__(self, device: SPD3000) -> None:
        self._device = device

    @property
    def error(self) -> SystemError:
        """Pop and return one fresh entry from ``SYSTem:ERRor?``."""

        return parse_system_error(self._device._query("SYST:ERR?"))

    @property
    def version(self) -> str:
        """Fresh instrument software version."""

        return self._device._query("SYST:VERS?").strip()

    @property
    def status(self) -> SystemStatus:
        """Fresh decoded instrument status, including CH1/CH2 output state."""

        return parse_status(self._device._query("SYST:STAT?"), self._device.model)


class Network:
    """Developer-friendly aliases for X/X-E root network commands.

    The SCPI-derived ``SPD3000.ipaddr``, ``maskaddr``, ``gateaddr``, and
    ``dhcp`` properties own validation and I/O. These grouped properties only
    delegate to them and introduce no second implementation. ``settings`` is
    an additive snapshot convenience that performs all four queries.
    """

    def __init__(self, device: SPD3000) -> None:
        self._device = device

    @property
    def settings(self) -> NetworkSettings:
        """Fresh snapshot built from the four documented network queries."""

        return NetworkSettings(
            host=self.host,
            subnet_mask=self.subnet_mask,
            gateway=self.gateway,
            dhcp=self.dhcp,
        )

    @property
    def host(self) -> str:
        """Friendly alias for :attr:`SPD3000.ipaddr`."""

        return self._device.ipaddr

    @host.setter
    def host(self, value: str) -> None:
        self._device.ipaddr = value

    @property
    def subnet_mask(self) -> str:
        """Friendly alias for :attr:`SPD3000.maskaddr`."""

        return self._device.maskaddr

    @subnet_mask.setter
    def subnet_mask(self, value: str) -> None:
        self._device.maskaddr = value

    @property
    def gateway(self) -> str:
        """Friendly alias for :attr:`SPD3000.gateaddr`."""

        return self._device.gateaddr

    @gateway.setter
    def gateway(self, value: str) -> None:
        self._device.gateaddr = value

    @property
    def dhcp(self) -> bool:
        """Grouped alias for :attr:`SPD3000.dhcp`."""

        return self._device.dhcp

    @dhcp.setter
    def dhcp(self, value: bool) -> None:
        self._device.dhcp = value


class RawSCPI:
    """Explicit low-level escape hatch that still uses the configured executor."""

    def __init__(self, device: SPD3000) -> None:
        self._device = device

    def write(self, command: str) -> None:
        self._device._write(command)

    def query(self, command: str) -> str:
        return self._device._query(command)

    def execute(self, commands: Sequence[Command] | CommandBatch) -> BatchResult:
        batch = commands if isinstance(commands, CommandBatch) else CommandBatch(commands)
        return self._device._execute_raw_batch(batch)


class SPD3000:
    """Semantic SPD3303X/X-E/C driver over an injected command executor.

    ``batch`` collects semantic writes for one non-interleaved execution.
    ``verify`` adds supported readbacks and raises
    :class:`SPD3000VerificationError` when a completed write cannot be verified.
    The reusable context managers compose as ``with psu.batch, psu.verify:``.
    """

    def __init__(self, executor: Executor) -> None:
        self._executor = executor
        self._connection_type: ConnectionType | None = None
        self._connection_identifier: str | None = None
        self._closed = False
        self._operation_lock = threading.RLock()
        self._batch_active = False
        self._pending_writes: list[_PendingWrite] = []
        self._verify_depth = 0
        self.batch = _BatchContext(self)
        self.verify = _VerifyContext(self)
        try:
            self._session_identity = parse_identification(self._query("*IDN?"))
        except Exception:
            executor.close()
            raise
        self.model = self._session_identity.model
        self.capabilities: Capabilities = CAPABILITIES[self.model]
        self.ch1 = ProgrammableChannel(self, Channel.CH1)
        self.ch2 = ProgrammableChannel(self, Channel.CH2)
        self.ch3 = FixedChannel(self)
        self.measure = Measure(self)
        self.output = Output(self)
        self.timer = Timer(self)
        self.system = System(self)
        self.network = Network(self)
        self.scpi = RawSCPI(self)

    @classmethod
    def connect(
        cls,
        connection: ConnectionType | str,
        identifier: str,
        *,
        timeout_s: float = 5.0,
        min_command_interval_ms: float = 100.0,
        token: str | None = None,
        visa_backend: str | None = None,
    ) -> SPD3000:
        """Connect through a selected backend while configuring common execution settings.

        ``identifier`` is a hostname or IP address for socket and VXI-11, a
        ``host[:port]`` endpoint for gateway connections, and a VISA resource
        string for VISA connections.
        Method-specific options are rejected when supplied to another method.
        """

        if isinstance(connection, ConnectionType):
            selected = connection
        elif isinstance(connection, str):
            try:
                selected = ConnectionType(connection.strip().lower())
            except ValueError as exc:
                choices = ", ".join(item.value for item in ConnectionType)
                raise SPD3000ValidationError(f"connection must be one of: {choices}") from exc
        else:
            raise SPD3000ValidationError("connection must be a ConnectionType or string")

        if not isinstance(identifier, str) or not identifier.strip():
            raise SPD3000ValidationError("identifier must be a non-empty string")
        target = identifier.strip()

        if isinstance(min_command_interval_ms, bool) or not isinstance(
            min_command_interval_ms, (int, float)
        ):
            raise SPD3000ValidationError("min_command_interval_ms must be a real number")
        settings = ExecutionSettings(
            min_command_interval=float(min_command_interval_ms) / 1000.0,
            timeout=timeout_s,
            _warning_stacklevel=3,
        )

        if selected is ConnectionType.SOCKET:
            cls._reject_connection_options(selected, token=token, visa_backend=visa_backend)
            return cls._connect_socket(target, settings=settings)
        if selected is ConnectionType.VXI11:
            cls._reject_connection_options(selected, token=token, visa_backend=visa_backend)
            return cls._connect_vxi11(target, settings=settings)
        if selected is ConnectionType.VISA:
            cls._reject_connection_options(selected, token=token)
            return cls._connect_visa(target, backend=visa_backend, settings=settings)

        cls._reject_connection_options(selected, visa_backend=visa_backend)
        host, gateway_port = cls._gateway_endpoint(target)
        return cls._connect_gateway(
            host,
            port=gateway_port,
            token=token,
            settings=settings,
        )

    @staticmethod
    def _gateway_endpoint(identifier: str) -> tuple[str, int]:
        host = identifier
        raw_port: str | None = None
        if identifier.startswith("["):
            closing_bracket = identifier.find("]")
            if closing_bracket < 0:
                raise SPD3000ValidationError("gateway IPv6 identifier is missing closing ']'")
            host = identifier[1:closing_bracket]
            suffix = identifier[closing_bracket + 1 :]
            if suffix:
                if not suffix.startswith(":"):
                    raise SPD3000ValidationError(
                        "gateway identifier must be HOST, HOST:PORT, [IPv6], or [IPv6]:PORT"
                    )
                raw_port = suffix[1:]
        elif identifier.count(":") == 1:
            host, raw_port = identifier.split(":", 1)
        elif ":" in identifier:
            raise SPD3000ValidationError(
                "gateway IPv6 identifiers must use '[IPv6]' or '[IPv6]:PORT'"
            )
        if not host or host != host.strip() or any(character.isspace() for character in host):
            raise SPD3000ValidationError("gateway identifier must contain a valid host")
        if raw_port is None:
            return host, DEFAULT_GATEWAY_PORT
        if not raw_port.isascii() or not raw_port.isdigit():
            raise SPD3000ValidationError("gateway port must be an integer from 1 through 65535")
        port = int(raw_port)
        if not 1 <= port <= 65535:
            raise SPD3000ValidationError("gateway port must be an integer from 1 through 65535")
        return host, port

    @staticmethod
    def _reject_connection_options(
        connection: ConnectionType,
        *,
        token: str | None = None,
        visa_backend: str | None = None,
    ) -> None:
        invalid = [
            name
            for name, value in (
                ("token", token),
                ("visa_backend", visa_backend),
            )
            if value is not None
        ]
        if invalid:
            names = ", ".join(invalid)
            raise SPD3000ValidationError(
                f"{names} cannot be used with connection={connection.value!r}"
            )

    @classmethod
    def _connect_socket(
        cls,
        host: str,
        *,
        settings: ExecutionSettings,
    ) -> SPD3000:
        """Build a driver over an SPD3303X/X-E raw SCPI socket."""

        device = cls(
            DirectExecutor(
                SocketTransport(host, port=DEFAULT_SCPI_PORT, timeout=settings.timeout), settings
            )
        )
        device._set_connection_metadata(ConnectionType.SOCKET, f"{host}:{DEFAULT_SCPI_PORT}")
        if not device.capabilities.socket:
            device.close()
            raise UnsupportedFeatureError(f"{device.model.value} does not support raw TCP sockets")
        return device

    @classmethod
    def _connect_vxi11(cls, host: str, *, settings: ExecutionSettings) -> SPD3000:
        """Build a driver over an SPD3303X/X-E VXI-11 connection."""

        device = cls(DirectExecutor(VXI11Transport(host, timeout=settings.timeout), settings))
        device._set_connection_metadata(ConnectionType.VXI11, host)
        if not device.capabilities.vxi11:
            device.close()
            raise UnsupportedFeatureError(f"{device.model.value} does not support VXI-11")
        return device

    @classmethod
    def _connect_visa(
        cls,
        resource: str,
        *,
        backend: str | None = None,
        settings: ExecutionSettings,
    ) -> SPD3000:
        """Build a driver over a PyVISA resource."""

        transport = VisaTransport(resource, backend=backend, timeout=settings.timeout)
        device = cls(DirectExecutor(transport, settings))
        device._set_connection_metadata(ConnectionType.VISA, resource)
        return device

    @classmethod
    def _connect_gateway(
        cls,
        host: str,
        *,
        port: int = DEFAULT_GATEWAY_PORT,
        token: str | None = None,
        settings: ExecutionSettings,
    ) -> SPD3000:
        """Build a driver over a persistent gateway session."""

        from .gateway.client import GatewayExecutor

        endpoint = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        device = cls(GatewayExecutor(host, port=port, token=token, settings=settings))
        device._set_connection_metadata(ConnectionType.GATEWAY, endpoint)
        return device

    def _set_connection_metadata(
        self, connection_type: ConnectionType, identifier: str
    ) -> None:
        self._connection_type = connection_type
        self._connection_identifier = identifier

    @property
    def connection_type(self) -> ConnectionType | None:
        """Selected public connection type, or ``None`` for an injected executor."""

        return self._connection_type

    @property
    def connection_identifier(self) -> str | None:
        """Normalized connection destination, or ``None`` for an injected executor."""

        return self._connection_identifier

    @property
    def is_open(self) -> bool:
        """Whether this driver session has not been closed.

        This local lifecycle state does not probe whether a remote peer or
        instrument remains reachable.
        """

        return not self._closed

    @property
    def settings(self) -> ExecutionSettings:
        return self._executor.settings

    @property
    def idn(self) -> Identification:
        """Fresh parsed ``*IDN?`` result."""

        return parse_identification(self._query("*IDN?"))

    @property
    def instrument(self) -> Channel:
        """Fresh ``INSTrument?`` result identifying the selected channel."""

        response = self._query("INST?").strip().upper()
        try:
            return Channel(response)
        except ValueError as exc:
            raise SPD3000ProtocolError(f"Malformed INST? response: {response!r}") from exc

    @instrument.setter
    def instrument(self, value: Channel | str) -> None:
        channel = _require_channel(value, programmable=True)
        self._write(
            f"INST {channel.value}",
            verification=_Verification(
                "INST?",
                channel,
                lambda response: _require_channel(response, programmable=True),
            ),
        )

    @property
    def ipaddr(self) -> str:
        """Fresh canonical ``IPaddr?`` query result."""

        self._require("network", "IPaddr?")
        return _parse_ipv4_address("IPADDR?", self._query("IPADDR?"))

    @ipaddr.setter
    def ipaddr(self, value: str) -> None:
        self._require("network", "IPaddr")
        expected = _require_ipv4_address(value)
        self._write(
            f"IPADDR {expected}",
            verification=_Verification(
                "IPADDR?",
                expected,
                lambda response: _parse_ipv4_address("IPADDR?", response),
            ),
        )

    @property
    def maskaddr(self) -> str:
        """Fresh canonical ``MASKaddr?`` query result."""

        self._require("network", "MASKaddr?")
        return _parse_subnet_mask(self._query("MASKADDR?"))

    @maskaddr.setter
    def maskaddr(self, value: str) -> None:
        self._require("network", "MASKaddr")
        expected = _require_subnet_mask(value)
        self._write(
            f"MASKADDR {expected}",
            verification=_Verification("MASKADDR?", expected, _parse_subnet_mask),
        )

    @property
    def gateaddr(self) -> str:
        """Fresh canonical ``GATEaddr?`` query result."""

        self._require("network", "GATEaddr?")
        return _parse_ipv4_address("GATEADDR?", self._query("GATEADDR?"))

    @gateaddr.setter
    def gateaddr(self, value: str) -> None:
        self._require("network", "GATEaddr")
        expected = _require_ipv4_address(value)
        self._write(
            f"GATEADDR {expected}",
            verification=_Verification(
                "GATEADDR?",
                expected,
                lambda response: _parse_ipv4_address("GATEADDR?", response),
            ),
        )

    @property
    def dhcp(self) -> bool:
        """Fresh boolean state parsed from the documented ``DHCP:<ON|OFF>`` response."""

        self._require("network", "DHCP?")
        return _parse_dhcp(self._query("DHCP?"))

    @dhcp.setter
    def dhcp(self, value: bool) -> None:
        self._require("network", "DHCP")
        enabled = _require_bool("dhcp", value)
        self._write(
            f"DHCP {'ON' if enabled else 'OFF'}",
            verification=_Verification("DHCP?", enabled, _parse_dhcp),
        )

    @property
    def locked(self) -> bool:
        """Fresh ``*LOCK?`` state; named differently because ``lock()`` is callable."""

        self._require("lock_query", "*LOCK?")
        return _parse_bool("*LOCK?", self._query("*LOCK?"))

    def sav(self, slot: int) -> None:
        """Execute canonical ``*SAV <slot>``."""

        self._write(
            f"*SAV {self._slot(slot)}",
            unavailable_reason="Siglent documents no query that confirms a saved setup slot",
        )

    def rcl(self, slot: int) -> None:
        """Execute canonical ``*RCL <slot>``."""

        self._write(
            f"*RCL {self._slot(slot)}",
            unavailable_reason=(
                "Siglent documents no single query that confirms the complete recalled setup"
            ),
        )

    def save(self, slot: int) -> None:
        """Developer-friendly alias for :meth:`sav`."""

        self.sav(slot)

    def recall(self, slot: int) -> None:
        """Developer-friendly alias for :meth:`rcl`."""

        self.rcl(slot)

    def lock(self) -> None:
        if self.capabilities.lock_query:
            verification = _Verification(
                "*LOCK?", True, lambda response: _parse_bool("*LOCK?", response)
            )
            self._write("*LOCK", verification=verification)
        else:
            self._write(
                "*LOCK",
                unavailable_reason=f"{self.model.value} does not document *LOCK?",
            )

    def unlock(self) -> None:
        if self.capabilities.lock_query:
            verification = _Verification(
                "*LOCK?", False, lambda response: _parse_bool("*LOCK?", response)
            )
            self._write("*UNLOCK", verification=verification)
        else:
            self._write(
                "*UNLOCK",
                unavailable_reason=f"{self.model.value} does not document *LOCK?",
            )

    @staticmethod
    def _slot(slot: int) -> int:
        if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 5:
            raise SPD3000ValidationError("memory slot must be an integer from 1 through 5")
        return slot

    def _setpoint(self, quantity: str, value: float) -> str:
        if quantity == "voltage":
            resolution = Decimal(str(self.capabilities.voltage_resolution))
            maximum = Decimal("32")
        elif quantity == "current":
            resolution = Decimal(str(self.capabilities.current_resolution))
            maximum = Decimal("3.2")
        else:
            raise AssertionError(f"unknown setpoint quantity: {quantity}")
        return _format_number(
            quantity,
            value,
            minimum=Decimal("0"),
            maximum=maximum,
            resolution=resolution,
        )

    def _require(self, capability: str, command: str) -> None:
        if not bool(getattr(self.capabilities, capability)):
            raise UnsupportedFeatureError(f"{command} is not supported by {self.model.value}")

    def _write(
        self,
        command: str,
        *,
        verification: _Verification | None = None,
        unavailable_reason: str | None = None,
    ) -> None:
        with self._operation_lock:
            if self._verify_depth:
                selected_verification = verification or _Verification(
                    query=None,
                    expected=None,
                    parser=None,
                    unavailable_reason=(
                        unavailable_reason
                        or "No automatic verification is defined for this write operation"
                    ),
                )
            else:
                selected_verification = None
            pending = _PendingWrite(command, selected_verification)
            if self._batch_active:
                self._pending_writes.append(pending)
                return
            self._execute_pending_writes([pending])

    def _query(self, command: str) -> str:
        with self._operation_lock:
            if self._batch_active:
                raise SPD3000ValidationError(
                    "Queries cannot return values while with psu.batch is collecting writes"
                )
            result = self._executor.execute(CommandBatch([Query(command)])).values[0]
            if not isinstance(result, str):
                raise SPD3000ProtocolError(f"Query {command!r} returned no response")
            return result

    def _begin_batch(self) -> None:
        self._operation_lock.acquire()
        if self._batch_active:
            self._operation_lock.release()
            raise SPD3000ValidationError("Nested psu.batch contexts are not supported")
        self._batch_active = True
        self._pending_writes = []

    def _end_batch(self, *, execute: bool) -> None:
        try:
            pending = self._pending_writes
            self._pending_writes = []
            self._batch_active = False
            if execute and pending:
                self._execute_pending_writes(pending)
        finally:
            self._operation_lock.release()

    def _begin_verify(self) -> None:
        self._operation_lock.acquire()
        self._verify_depth += 1

    def _end_verify(self) -> None:
        try:
            if self._verify_depth <= 0:
                raise RuntimeError("psu.verify context exited without entering")
            self._verify_depth -= 1
        finally:
            self._operation_lock.release()

    def _execute_pending_writes(self, pending: Sequence[_PendingWrite]) -> None:
        commands: list[Command] = []
        verification_indexes: list[tuple[_PendingWrite, int | None]] = []
        for operation in pending:
            commands.append(Write(operation.command))
            verification = operation.verification
            if verification is None:
                continue
            query_index: int | None = None
            if verification.query is not None:
                query_index = len(commands)
                commands.append(Query(verification.query))
            verification_indexes.append((operation, query_index))

        try:
            result = self._executor.execute(CommandBatch(commands))
        except SPD3000Error as exc:
            failed_index = getattr(exc, "batch_command_index", None)
            failed_verification = next(
                (
                    operation
                    for operation, query_index in verification_indexes
                    if query_index == failed_index
                ),
                None,
            )
            if failed_verification is None:
                raise
            verification = failed_verification.verification
            assert verification is not None and verification.query is not None
            raise SPD3000VerificationError(
                (
                    f"Verification query {verification.query!r} failed after "
                    f"{failed_verification.command!r}: {exc}"
                ),
                command=failed_verification.command,
                query=verification.query,
                expected=verification.expected,
            ) from exc

        for operation, query_index in verification_indexes:
            verification = operation.verification
            assert verification is not None
            if query_index is None:
                raise SPD3000VerificationError(
                    (
                        f"Verification is unavailable after {operation.command!r}: "
                        f"{verification.unavailable_reason}"
                    ),
                    command=operation.command,
                    query=None,
                    expected=verification.expected,
                )
            response = result.values[query_index]
            if not isinstance(response, str):
                raise SPD3000VerificationError(
                    f"Verification query {verification.query!r} returned no response",
                    command=operation.command,
                    query=verification.query,
                    expected=verification.expected,
                )
            assert verification.parser is not None
            try:
                actual = verification.parser(response)
            except SPD3000Error as exc:
                raise SPD3000VerificationError(
                    (
                        f"Verification query {verification.query!r} returned an unusable "
                        f"response after {operation.command!r}: {exc}"
                    ),
                    command=operation.command,
                    query=verification.query,
                    expected=verification.expected,
                    actual=response,
                ) from exc
            if actual != verification.expected:
                raise SPD3000VerificationError(
                    (
                        f"Verification failed after {operation.command!r}: "
                        f"{verification.query!r} returned {actual!r}, "
                        f"expected {verification.expected!r}"
                    ),
                    command=operation.command,
                    query=verification.query,
                    expected=verification.expected,
                    actual=actual,
                )

    def _execute_raw_batch(self, batch: CommandBatch) -> BatchResult:
        with self._operation_lock:
            if self._batch_active:
                raise SPD3000ValidationError(
                    "psu.scpi.execute() cannot run inside a collecting psu.batch context"
                )
            if self._verify_depth:
                raise SPD3000ValidationError(
                    "psu.verify cannot infer expected values for psu.scpi.execute()"
                )
            return self._executor.execute(batch)

    def close(self) -> None:
        with self._operation_lock:
            if self._closed:
                return
            try:
                self._executor.close()
            finally:
                self._closed = True

    def __str__(self) -> str:
        """Return a concise identity and connection summary without instrument I/O."""

        identity = self._session_identity
        connection_type = (
            self._connection_type.value
            if self._connection_type is not None
            else "injected executor"
        )
        connection_identifier = self._connection_identifier or type(self._executor).__name__
        state = "open" if self.is_open else "closed"
        return "\n".join(
            (
                "SIGLENT SPD3000 Series power supply driver instance",
                f"- Model: {identity.model.value}",
                f"- Serial number: {identity.serial_number}",
                "- Connection:",
                f"  - Type: {connection_type}",
                f"  - Identifier: {connection_identifier}",
                f"  - State: {state}",
            )
        )

    def __enter__(self) -> SPD3000:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
