"""Synchronous semantic driver for Siglent SPD3000-series supplies."""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from ipaddress import AddressValueError, IPv4Address, IPv4Network, NetmaskValueError
from typing import overload

from .exceptions import (
    SPD3000ProtocolError,
    SPD3000ValidationError,
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
    SystemError,
    SystemStatus,
    TrackingMode,
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
        self._device._write(f"{self._channel.value}:VOLT {rendered}")

    @property
    def current(self) -> float:
        """Fresh programmed current query in amperes."""

        return _parse_float("CURR?", self._device._query(f"{self._channel.value}:CURR?"))

    @current.setter
    def current(self, value: float) -> None:
        rendered = self._device._setpoint("current", value)
        self._device._write(f"{self._channel.value}:CURR {rendered}")


class FixedChannel:
    """Marker object for fixed-voltage CH3; output control lives under ``output``."""

    channel = Channel.CH3


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


class Instrument:
    """SCPI ``INSTrument`` subtree."""

    def __init__(self, device: SPD3000) -> None:
        self._device = device

    @property
    def channel(self) -> Channel:
        """Fresh query of the currently selected programmable channel."""

        response = self._device._query("INST?").strip().upper()
        try:
            return Channel(response)
        except ValueError as exc:
            raise SPD3000ProtocolError(f"Malformed INST? response: {response!r}") from exc

    @channel.setter
    def channel(self, value: Channel | str) -> None:
        channel = _require_channel(value, programmable=True)
        self._device._write(f"INST {channel.value}")


class Output:
    """SCPI ``OUTPut`` subtree with one documented convenience exception.

    Most of this package follows the vendor SCPI hierarchy literally. Output
    switching is unusually frequent, so this subtree intentionally supports
    both the canonical callable form and per-channel properties::

        psu.output(Channel.CH1, True)
        psu.output("CH1", True)
        psu.output.ch1 = True
        print(psu.output.ch1)

    Both writes emit the same ``OUTP CH1,ON`` command. Reading CH1 or CH2 is a
    fresh, indirect ``SYST:STAT?`` query because Siglent does not document
    ``OUTP?``. CH3 can be written, but its getter raises
    :class:`UnsupportedFeatureError` because no CH3 status bit is documented;
    the driver never presents a cached write as measured hardware state.
    """

    def __init__(self, device: SPD3000) -> None:
        self._device = device

    def __call__(self, channel: Channel | str, state: bool) -> None:
        """Turn a channel output on or off using ``OUTPut <channel>,<state>``."""

        selected = _require_channel(channel)
        enabled = _require_bool("state", state)
        self._device._write(f"OUTP {selected.value},{'ON' if enabled else 'OFF'}")

    def _read(self, channel: Channel) -> bool:
        if channel is Channel.CH3:
            raise UnsupportedFeatureError(
                "Siglent documents no query or SYST:STAT? bit for CH3 output state"
            )
        status = self._device.system.status
        return status.ch1.output if channel is Channel.CH1 else status.ch2.output

    @property
    def ch1(self) -> bool:
        """Fresh CH1 output state derived from ``SYSTem:STATus?``."""

        return self._read(Channel.CH1)

    @ch1.setter
    def ch1(self, state: bool) -> None:
        self(Channel.CH1, state)

    @property
    def ch2(self) -> bool:
        """Fresh CH2 output state derived from ``SYSTem:STATus?``."""

        return self._read(Channel.CH2)

    @ch2.setter
    def ch2(self, state: bool) -> None:
        self(Channel.CH2, state)

    @property
    def ch3(self) -> bool:
        """Raise because no official CH3 output-state query exists."""

        return self._read(Channel.CH3)

    @ch3.setter
    def ch3(self, state: bool) -> None:
        self(Channel.CH3, state)

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
        self._device._write(f"OUTP:TRACK {selected.value}")

    def wave(self, channel: Channel | str, state: bool) -> None:
        """Set X/X-E waveform display state for CH1 or CH2."""

        self._device._require("waveform", "OUTPut:WAVE")
        selected = _require_channel(channel, programmable=True)
        enabled = _require_bool("state", state)
        self._device._write(f"OUTP:WAVE {selected.value},{'ON' if enabled else 'OFF'}")


class Timer:
    """SCPI ``TIMEr`` subtree; calling it controls the timer output state."""

    def __init__(self, device: SPD3000) -> None:
        self._device = device

    def __call__(self, channel: Channel | str, state: bool) -> None:
        self._device._require("timer", "TIMEr")
        selected = _require_channel(channel, programmable=True)
        enabled = _require_bool("state", state)
        self._device._write(f"TIMER {selected.value},{'ON' if enabled else 'OFF'}")

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
            parts = [part.strip() for part in response.split(",")]
            if len(parts) != 3:
                raise SPD3000ProtocolError(f"Malformed TIMER:SET? response: {response!r}")
            return {
                "voltage_v": _parse_float("TIMER:SET? voltage", parts[0]),
                "current_a": _parse_float("TIMER:SET? current", parts[1]),
                "duration_s": _parse_float("TIMER:SET? time", parts[2]),
            }
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
        self._device._write(
            f"TIMER:SET {selected.value},{selected_group},{voltage},{current},{duration}"
        )
        return None


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
    """X/X-E network configuration commands.

    Address properties accept and return canonical dotted IPv4 strings. The
    setter validates locally but deliberately does not change DHCP state as a
    hidden side effect; set ``dhcp = False`` first when assigning static data.
    """

    def __init__(self, device: SPD3000) -> None:
        self._device = device

    def _require(self, command: str) -> None:
        self._device._require("network", command)

    @staticmethod
    def _address(value: str) -> str:
        if not isinstance(value, str):
            raise SPD3000ValidationError("IPv4 address must be a string")
        try:
            return str(IPv4Address(value))
        except AddressValueError as exc:
            raise SPD3000ValidationError(f"Invalid IPv4 address: {value!r}") from exc

    @staticmethod
    def _mask(value: str) -> str:
        if not isinstance(value, str):
            raise SPD3000ValidationError("subnet mask must be a string")
        try:
            return str(IPv4Network(f"0.0.0.0/{value}").netmask)
        except (AddressValueError, NetmaskValueError) as exc:
            raise SPD3000ValidationError(f"Invalid IPv4 subnet mask: {value!r}") from exc

    def _read_address(self, command: str) -> str:
        response = self._device._query(f"{command}?").strip()
        try:
            return str(IPv4Address(response))
        except AddressValueError as exc:
            raise SPD3000ProtocolError(f"Malformed {command}? response: {response!r}") from exc

    @property
    def ip_address(self) -> str:
        self._require("IPaddr?")
        return self._read_address("IPADDR")

    @ip_address.setter
    def ip_address(self, value: str) -> None:
        self._require("IPaddr")
        self._device._write(f"IPADDR {self._address(value)}")

    @property
    def subnet_mask(self) -> str:
        self._require("MASKaddr?")
        response = self._device._query("MASKADDR?").strip()
        try:
            return str(IPv4Network(f"0.0.0.0/{response}").netmask)
        except (AddressValueError, NetmaskValueError) as exc:
            raise SPD3000ProtocolError(f"Malformed MASKADDR? response: {response!r}") from exc

    @subnet_mask.setter
    def subnet_mask(self, value: str) -> None:
        self._require("MASKaddr")
        self._device._write(f"MASKADDR {self._mask(value)}")

    @property
    def gateway_address(self) -> str:
        self._require("GATEaddr?")
        return self._read_address("GATEADDR")

    @gateway_address.setter
    def gateway_address(self, value: str) -> None:
        self._require("GATEaddr")
        self._device._write(f"GATEADDR {self._address(value)}")

    @property
    def dhcp(self) -> bool:
        self._require("DHCP?")
        return _parse_bool("DHCP?", self._device._query("DHCP?"))

    @dhcp.setter
    def dhcp(self, value: bool) -> None:
        self._require("DHCP")
        enabled = _require_bool("dhcp", value)
        self._device._write(f"DHCP {'ON' if enabled else 'OFF'}")


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
        return self._device._executor.execute(batch)


class SPD3000:
    """Semantic SPD3303X/X-E/C driver over an injected command executor."""

    def __init__(self, executor: Executor) -> None:
        self._executor = executor
        try:
            self._session_identity = parse_identification(self._query("*IDN?"))
        except Exception:
            executor.close()
            raise
        self.model = self._session_identity.model
        self.capabilities: Capabilities = CAPABILITIES[self.model]
        self.ch1 = ProgrammableChannel(self, Channel.CH1)
        self.ch2 = ProgrammableChannel(self, Channel.CH2)
        self.ch3 = FixedChannel()
        self.instrument = Instrument(self)
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
        port: int | None = None,
        token: str | None = None,
        visa_backend: str | None = None,
    ) -> SPD3000:
        """Connect through a selected backend while configuring common execution settings.

        ``identifier`` is a hostname or IP address for socket, VXI-11, and
        gateway connections, and a VISA resource string for VISA connections.
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
            return cls._connect_socket(
                target,
                port=cls._connection_port(port, default=5025),
                settings=settings,
            )
        if selected is ConnectionType.VXI11:
            cls._reject_connection_options(
                selected,
                port=port,
                token=token,
                visa_backend=visa_backend,
            )
            return cls._connect_vxi11(target, settings=settings)
        if selected is ConnectionType.VISA:
            cls._reject_connection_options(selected, port=port, token=token)
            return cls._connect_visa(target, backend=visa_backend, settings=settings)

        cls._reject_connection_options(selected, visa_backend=visa_backend)
        return cls._connect_gateway(
            target,
            port=cls._connection_port(port, default=8765),
            token=token,
            settings=settings,
        )

    @staticmethod
    def _connection_port(port: int | None, *, default: int) -> int:
        if port is None:
            return default
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise SPD3000ValidationError("port must be an integer from 1 through 65535")
        return port

    @staticmethod
    def _reject_connection_options(
        connection: ConnectionType,
        *,
        port: int | None = None,
        token: str | None = None,
        visa_backend: str | None = None,
    ) -> None:
        invalid = [
            name
            for name, value in (
                ("port", port),
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
        port: int = 5025,
        settings: ExecutionSettings,
    ) -> SPD3000:
        """Build a driver over an SPD3303X/X-E raw SCPI socket."""

        device = cls(
            DirectExecutor(SocketTransport(host, port=port, timeout=settings.timeout), settings)
        )
        if not device.capabilities.socket:
            device.close()
            raise UnsupportedFeatureError(f"{device.model.value} does not support raw TCP sockets")
        return device

    @classmethod
    def _connect_vxi11(cls, host: str, *, settings: ExecutionSettings) -> SPD3000:
        """Build a driver over an SPD3303X/X-E VXI-11 connection."""

        device = cls(DirectExecutor(VXI11Transport(host, timeout=settings.timeout), settings))
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
        return cls(DirectExecutor(transport, settings))

    @classmethod
    def _connect_gateway(
        cls,
        host: str,
        *,
        port: int = 8765,
        token: str | None = None,
        settings: ExecutionSettings,
    ) -> SPD3000:
        """Build a driver over a persistent gateway session."""

        from .gateway.client import GatewayExecutor

        return cls(GatewayExecutor(host, port=port, token=token, settings=settings))

    @property
    def settings(self) -> ExecutionSettings:
        return self._executor.settings

    @property
    def identity(self) -> Identification:
        """Fresh parsed ``*IDN?`` result."""

        return parse_identification(self._query("*IDN?"))

    @property
    def locked(self) -> bool:
        """Fresh X/X-E front-panel lock state."""

        self._require("lock_query", "*LOCK?")
        return _parse_bool("*LOCK?", self._query("*LOCK?"))

    def save(self, slot: int) -> None:
        self._write(f"*SAV {self._slot(slot)}")

    def recall(self, slot: int) -> None:
        self._write(f"*RCL {self._slot(slot)}")

    def lock(self) -> None:
        self._write("*LOCK")

    def unlock(self) -> None:
        self._write("*UNLOCK")

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

    def _write(self, command: str) -> None:
        self._executor.execute(CommandBatch([Write(command)]))

    def _query(self, command: str) -> str:
        result = self._executor.execute(CommandBatch([Query(command)])).values[0]
        if not isinstance(result, str):
            raise SPD3000ProtocolError(f"Query {command!r} returned no response")
        return result

    def close(self) -> None:
        self._executor.close()

    def __enter__(self) -> SPD3000:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
