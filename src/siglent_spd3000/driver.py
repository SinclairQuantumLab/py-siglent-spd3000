"""Synchronous semantic driver for Siglent SPD3000-series supplies."""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from ipaddress import AddressValueError, IPv4Address, IPv4Network, NetmaskValueError

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
    Identification,
    SystemError,
    SystemStatus,
    TimerStep,
    TrackingMode,
    parse_identification,
    parse_status,
    parse_system_error,
)
from .transport import SocketTransport, VisaTransport, VXI11Transport


def _require_channel(value: Channel, *, programmable: bool = False) -> Channel:
    if not isinstance(value, Channel):
        raise SPD3000ValidationError("channel must be a Channel enum value")
    if programmable and value is Channel.CH3:
        raise SPD3000ValidationError("CH3 has no programmable voltage or current")
    return value


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


class MeasurementChannel:
    """One channel under the SCPI ``MEASure`` query subtree."""

    def __init__(self, device: SPD3000, channel: Channel) -> None:
        self._device = device
        self._channel = _require_channel(channel, programmable=True)

    @property
    def voltage(self) -> float:
        """Fresh measured voltage in volts."""

        response = self._device._query(f"MEAS:VOLT? {self._channel.value}")
        return _parse_float("MEAS:VOLT?", response)

    @property
    def current(self) -> float:
        """Fresh measured current in amperes."""

        response = self._device._query(f"MEAS:CURR? {self._channel.value}")
        return _parse_float("MEAS:CURR?", response)

    @property
    def power(self) -> float:
        """Fresh measured power in watts; unavailable on SPD3303C."""

        self._device._require("measure_power", "MEASure:POWer")
        response = self._device._query(f"MEAS:POWE? {self._channel.value}")
        return _parse_float("MEAS:POWE?", response)


class Measure:
    """SCPI ``MEASure`` subtree."""

    def __init__(self, device: SPD3000) -> None:
        self.ch1 = MeasurementChannel(device, Channel.CH1)
        self.ch2 = MeasurementChannel(device, Channel.CH2)


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
    def channel(self, value: Channel) -> None:
        channel = _require_channel(value, programmable=True)
        self._device._write(f"INST {channel.value}")


class Output:
    """SCPI ``OUTPut`` subtree with one documented convenience exception.

    Most of this package follows the vendor SCPI hierarchy literally. Output
    switching is unusually frequent, so this subtree intentionally supports
    both the canonical callable form and per-channel properties::

        psu.output(Channel.CH1, True)
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

    def __call__(self, channel: Channel, state: bool) -> None:
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

    def track(self, mode: TrackingMode) -> None:
        """Select independent, series, or parallel ``OUTPut:TRACK`` mode."""

        if not isinstance(mode, TrackingMode):
            raise SPD3000ValidationError("mode must be a TrackingMode enum value")
        self._device._write(f"OUTP:TRACK {mode.value}")

    def wave(self, channel: Channel, state: bool) -> None:
        """Set X/X-E waveform display state for CH1 or CH2."""

        self._device._require("waveform", "OUTPut:WAVE")
        selected = _require_channel(channel, programmable=True)
        enabled = _require_bool("state", state)
        self._device._write(f"OUTP:WAVE {selected.value},{'ON' if enabled else 'OFF'}")


class TimerSet:
    """Mapping-like ``TIMEr:SET`` query/write subtree indexed by channel and group."""

    def __init__(self, device: SPD3000) -> None:
        self._device = device

    @staticmethod
    def _key(key: tuple[Channel, int]) -> tuple[Channel, int]:
        if not isinstance(key, tuple) or len(key) != 2:
            raise SPD3000ValidationError("timer.set key must be (Channel, group)")
        channel = _require_channel(key[0], programmable=True)
        group = key[1]
        if isinstance(group, bool) or not isinstance(group, int) or not 1 <= group <= 5:
            raise SPD3000ValidationError("timer group must be an integer from 1 through 5")
        return channel, group

    def __getitem__(self, key: tuple[Channel, int]) -> TimerStep:
        self._device._require("timer", "TIMEr:SET?")
        channel, group = self._key(key)
        response = self._device._query(f"TIMER:SET? {channel.value},{group}")
        parts = [part.strip() for part in response.split(",")]
        if len(parts) != 3:
            raise SPD3000ProtocolError(f"Malformed TIMER:SET? response: {response!r}")
        return TimerStep(
            voltage=_parse_float("TIMER:SET? voltage", parts[0]),
            current=_parse_float("TIMER:SET? current", parts[1]),
            time=_parse_float("TIMER:SET? time", parts[2]),
        )

    def __setitem__(self, key: tuple[Channel, int], value: TimerStep) -> None:
        self._device._require("timer", "TIMEr:SET")
        channel, group = self._key(key)
        if not isinstance(value, TimerStep):
            raise SPD3000ValidationError("timer value must be TimerStep")
        voltage = self._device._setpoint("voltage", value.voltage)
        current = self._device._setpoint("current", value.current)
        duration = _format_number(
            "time", value.time, minimum=Decimal("0"), maximum=Decimal("10000")
        )
        self._device._write(f"TIMER:SET {channel.value},{group},{voltage},{current},{duration}")


class Timer:
    """SCPI ``TIMEr`` subtree; calling it controls the timer output state."""

    def __init__(self, device: SPD3000) -> None:
        self._device = device
        self.set = TimerSet(device)

    def __call__(self, channel: Channel, state: bool) -> None:
        self._device._require("timer", "TIMEr")
        selected = _require_channel(channel, programmable=True)
        enabled = _require_bool("state", state)
        self._device._write(f"TIMER {selected.value},{'ON' if enabled else 'OFF'}")


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
    def from_socket(
        cls,
        host: str,
        *,
        port: int = 5025,
        settings: ExecutionSettings | None = None,
    ) -> SPD3000:
        """Connect to an SPD3303X/X-E raw SCPI socket on port 5025."""

        active = settings or ExecutionSettings()
        device = cls(
            DirectExecutor(SocketTransport(host, port=port, timeout=active.timeout), active)
        )
        if not device.capabilities.socket:
            device.close()
            raise UnsupportedFeatureError(f"{device.model.value} does not support raw TCP sockets")
        return device

    @classmethod
    def from_vxi11(cls, host: str, *, settings: ExecutionSettings | None = None) -> SPD3000:
        """Connect to an SPD3303X/X-E with VXI-11."""

        active = settings or ExecutionSettings()
        device = cls(DirectExecutor(VXI11Transport(host, timeout=active.timeout), active))
        if not device.capabilities.vxi11:
            device.close()
            raise UnsupportedFeatureError(f"{device.model.value} does not support VXI-11")
        return device

    @classmethod
    def from_visa(
        cls,
        resource: str,
        *,
        backend: str | None = None,
        settings: ExecutionSettings | None = None,
    ) -> SPD3000:
        """Connect to any supported model through a PyVISA resource."""

        active = settings or ExecutionSettings()
        transport = VisaTransport(resource, backend=backend, timeout=active.timeout)
        return cls(DirectExecutor(transport, active))

    @classmethod
    def from_gateway(
        cls,
        host: str,
        *,
        port: int = 8765,
        token: str | None = None,
        settings: ExecutionSettings | None = None,
    ) -> SPD3000:
        """Use the same semantic driver through a persistent gateway session."""

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
