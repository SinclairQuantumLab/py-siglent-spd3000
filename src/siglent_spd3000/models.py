"""Typed SPD3000 model, capability, and response objects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, IntEnum

from .exceptions import SPD3000ProtocolError, UnknownModelError


class Model(str, Enum):
    """Supported supply models as reported by ``*IDN?``."""

    SPD3303X = "SPD3303X"
    SPD3303X_E = "SPD3303X-E"
    SPD3303C = "SPD3303C"


class ConnectionType(str, Enum):
    """User-facing connection method selected by :meth:`SPD3000.connect`."""

    SOCKET = "socket"
    VXI11 = "vxi11"
    VISA = "visa"
    GATEWAY = "gateway"


class Channel(str, Enum):
    """Physical output channel."""

    CH1 = "CH1"
    CH2 = "CH2"
    CH3 = "CH3"


class OutputState(str, Enum):
    """Argument encoding accepted by ``OUTPut <channel>,<state>``."""

    OFF = "OFF"
    ON = "ON"


class WaveformState(str, Enum):
    """Argument encoding accepted by ``OUTPut:WAVE <channel>,<state>``."""

    OFF = "OFF"
    ON = "ON"


class TimerState(str, Enum):
    """Argument encoding accepted by ``TIMEr <channel>,<state>``."""

    OFF = "OFF"
    ON = "ON"


class TrackingMode(IntEnum):
    """Argument encoding accepted by ``OUTPut:TRACK``."""

    INDEPENDENT = 0
    SERIES = 1
    PARALLEL = 2


class OperatingMode(str, Enum):
    """Operating mode decoded from ``SYSTem:STATus?``."""

    UNKNOWN = "unknown"
    INDEPENDENT = "independent"
    PARALLEL = "parallel"
    SERIES = "series"


class RegulationMode(str, Enum):
    """Constant-voltage or constant-current channel regulation."""

    CV = "CV"
    CC = "CC"


@dataclass(frozen=True)
class Identification:
    """Parsed result of ``*IDN?``."""

    manufacturer: str
    model: Model
    serial_number: str
    firmware_version: str
    raw: str

    def __str__(self) -> str:
        """Return all identification fields in a readable multiline summary."""

        return "\n".join(
            (
                "SIGLENT SPD3000 Series instrument identification",
                f"- Manufacturer: {self.manufacturer}",
                f"- Model: {self.model.value}",
                f"- Serial number: {self.serial_number}",
                f"- Firmware version: {self.firmware_version}",
                f"- Raw response: {self.raw}",
            )
        )


@dataclass(frozen=True)
class Capabilities:
    """Documented model features and programming-resolution information."""

    model: Model
    voltage_resolution: float
    current_resolution: float
    measure_power: bool
    waveform: bool
    timer: bool
    network: bool
    lock_query: bool
    socket: bool
    vxi11: bool
    visa: bool = True

    def __str__(self) -> str:
        """Return model limits and supported features in a readable summary."""

        return "\n".join(
            (
                "SIGLENT SPD3000 Series model capabilities",
                f"- Model: {self.model.value}",
                "- Programming resolution:",
                f"  - Voltage: {self.voltage_resolution:g} V",
                f"  - Current: {self.current_resolution:g} A",
                "- Features:",
                f"  - Power measurement: {_support(self.measure_power)}",
                f"  - Waveform display: {_support(self.waveform)}",
                f"  - Timer: {_support(self.timer)}",
                f"  - Network configuration: {_support(self.network)}",
                f"  - Front-panel lock query: {_support(self.lock_query)}",
                "- Connections:",
                f"  - Raw socket: {_support(self.socket)}",
                f"  - VXI-11: {_support(self.vxi11)}",
                f"  - VISA: {_support(self.visa)}",
            )
        )


@dataclass(frozen=True)
class ChannelStatus:
    """Status fields available for one programmable channel."""

    regulation: RegulationMode
    output: bool
    timer: bool | None
    waveform: bool | None

    def __str__(self) -> str:
        """Return the decoded channel state without querying the instrument."""

        return "\n".join(
            (
                "SIGLENT SPD3000 Series channel status",
                *_channel_status_lines(self, prefix="- "),
            )
        )


@dataclass(frozen=True)
class SystemStatus:
    """Decoded ``SYSTem:STATus?`` bit field.

    Siglent documents output-state bits only for CH1 and CH2. CH3 is therefore
    deliberately absent instead of being inferred from the last write.
    """

    raw: int
    operating_mode: OperatingMode
    ch1: ChannelStatus
    ch2: ChannelStatus

    def __str__(self) -> str:
        """Return the decoded system and channel states in a readable summary."""

        return "\n".join(
            (
                "SIGLENT SPD3000 Series system status",
                f"- Raw status word: 0x{self.raw:04X}",
                f"- Operating mode: {self.operating_mode.value}",
                "- Channels:",
                "  - CH1:",
                *_channel_status_lines(self.ch1, prefix="    - "),
                "  - CH2:",
                *_channel_status_lines(self.ch2, prefix="    - "),
            )
        )


@dataclass(frozen=True)
class SystemError:
    """One entry popped from the instrument error queue."""

    code: int
    message: str

    def __str__(self) -> str:
        """Return the instrument error code and message in a readable summary."""

        return "\n".join(
            (
                "SIGLENT SPD3000 Series system error",
                f"- Code: {self.code}",
                f"- Message: {self.message}",
            )
        )


@dataclass(frozen=True)
class NetworkSettings:
    """One freshly queried snapshot of the instrument network configuration."""

    host: str
    subnet_mask: str
    gateway: str
    dhcp: bool

    def __str__(self) -> str:
        """Return all network settings in a readable multiline summary."""

        return "\n".join(
            (
                "SIGLENT SPD3000 Series network settings",
                f"- IP address: {self.host}",
                f"- Subnet mask: {self.subnet_mask}",
                f"- Gateway: {self.gateway}",
                f"- DHCP: {'enabled' if self.dhcp else 'disabled'}",
            )
        )


def _support(value: bool) -> str:
    return "supported" if value else "not supported"


def _state(value: bool | None) -> str:
    if value is None:
        return "unavailable"
    return "on" if value else "off"


def _channel_status_lines(status: ChannelStatus, *, prefix: str) -> tuple[str, ...]:
    return (
        f"{prefix}Regulation: {status.regulation.value}",
        f"{prefix}Output: {_state(status.output)}",
        f"{prefix}Timer: {_state(status.timer)}",
        f"{prefix}Waveform: {_state(status.waveform)}",
    )


CAPABILITIES: dict[Model, Capabilities] = {
    Model.SPD3303X: Capabilities(
        model=Model.SPD3303X,
        voltage_resolution=0.001,
        current_resolution=0.001,
        measure_power=True,
        waveform=True,
        timer=True,
        network=True,
        lock_query=True,
        socket=True,
        vxi11=True,
    ),
    Model.SPD3303X_E: Capabilities(
        model=Model.SPD3303X_E,
        voltage_resolution=0.01,
        current_resolution=0.01,
        measure_power=True,
        waveform=True,
        timer=True,
        network=True,
        lock_query=True,
        socket=True,
        vxi11=True,
    ),
    Model.SPD3303C: Capabilities(
        model=Model.SPD3303C,
        voltage_resolution=0.01,
        current_resolution=0.01,
        measure_power=False,
        waveform=False,
        timer=False,
        network=False,
        lock_query=False,
        socket=False,
        vxi11=False,
    ),
}


def parse_identification(response: str) -> Identification:
    """Parse and validate a Siglent ``*IDN?`` response."""

    parts = [part.strip() for part in response.strip().split(",")]
    if len(parts) < 4:
        raise SPD3000ProtocolError(f"Malformed *IDN? response: {response!r}")
    model_token = parts[1].upper().replace("_", "-")
    aliases = {
        "SPD3303X": Model.SPD3303X,
        "SPD3303X-E": Model.SPD3303X_E,
        "SPD3303XE": Model.SPD3303X_E,
        "SPD3303C": Model.SPD3303C,
    }
    try:
        model = aliases[model_token]
    except KeyError as exc:
        raise UnknownModelError(f"Unsupported model in *IDN? response: {parts[1]!r}") from exc
    return Identification(parts[0], model, parts[2], ",".join(parts[3:]), response.strip())


def parse_status(response: str, model: Model) -> SystemStatus:
    """Decode the hexadecimal status register documented by Siglent."""

    try:
        raw = int(response.strip(), 0)
    except ValueError as exc:
        raise SPD3000ProtocolError(f"Malformed SYST:STAT? response: {response!r}") from exc
    mode = {
        0b00: OperatingMode.UNKNOWN,
        0b01: OperatingMode.INDEPENDENT,
        0b10: OperatingMode.PARALLEL,
        0b11: OperatingMode.SERIES,
    }[(raw >> 2) & 0b11]
    extended = model is not Model.SPD3303C
    return SystemStatus(
        raw=raw,
        operating_mode=mode,
        ch1=ChannelStatus(
            regulation=RegulationMode.CC if raw & 0b1 else RegulationMode.CV,
            output=bool(raw & (1 << 4)),
            timer=bool(raw & (1 << 6)) if extended else None,
            waveform=bool(raw & (1 << 8)) if extended else None,
        ),
        ch2=ChannelStatus(
            regulation=RegulationMode.CC if raw & (1 << 1) else RegulationMode.CV,
            output=bool(raw & (1 << 5)),
            timer=bool(raw & (1 << 7)) if extended else None,
            waveform=bool(raw & (1 << 9)) if extended else None,
        ),
    )


_ERROR_RE = re.compile(r'^\s*([+-]?\d+)\s*[, ]\s*"?(.*?)"?\s*$')


def parse_system_error(response: str) -> SystemError:
    """Parse common comma- or space-separated ``SYSTem:ERRor?`` responses."""

    match = _ERROR_RE.match(response)
    if match is None:
        raise SPD3000ProtocolError(f"Malformed SYST:ERR? response: {response!r}")
    return SystemError(int(match.group(1)), match.group(2))
