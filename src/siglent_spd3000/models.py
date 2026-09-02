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


class Channel(str, Enum):
    """Physical output channel."""

    CH1 = "CH1"
    CH2 = "CH2"
    CH3 = "CH3"


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


@dataclass(frozen=True)
class Capabilities:
    """Model-specific feature and programming-resolution information."""

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


@dataclass(frozen=True)
class TimerStep:
    """One ``TIMEr:SET`` entry; values use volts, amperes, and seconds."""

    voltage: float
    current: float
    time: float


@dataclass(frozen=True)
class ChannelStatus:
    """Status fields available for one programmable channel."""

    regulation: RegulationMode
    output: bool
    timer: bool | None
    waveform: bool | None


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


@dataclass(frozen=True)
class SystemError:
    """One entry popped from the instrument error queue."""

    code: int
    message: str


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
