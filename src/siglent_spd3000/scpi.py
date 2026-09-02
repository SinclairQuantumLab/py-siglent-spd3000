"""Canonical SCPI command registry and discovery helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from .models import Model


class Access(str, Enum):
    """How a documented SCPI header may be used."""

    READ = "read"
    WRITE = "write"
    READ_WRITE = "read-write"


ALL_MODELS = (Model.SPD3303X, Model.SPD3303X_E, Model.SPD3303C)
X_MODELS = (Model.SPD3303X, Model.SPD3303X_E)


@dataclass(frozen=True)
class CommandInfo:
    """Relationship between a documented SCPI command and the Python API."""

    canonical_scpi: str
    python_path: str
    access: Access
    unit: str | None
    models: tuple[Model, ...]
    source: str
    aliases: tuple[str, ...] = ()


def _command(
    canonical: str,
    path: str,
    access: Access,
    *,
    unit: str | None = None,
    models: tuple[Model, ...] = ALL_MODELS,
    source: str = "SPD3303X/SPD3303C Quick Start",
    aliases: tuple[str, ...] = (),
) -> CommandInfo:
    return CommandInfo(canonical, path, access, unit, models, source, aliases)


COMMANDS: tuple[CommandInfo, ...] = (
    _command("*IDN?", "idn", Access.READ),
    _command("*SAV", "save(slot)", Access.WRITE),
    _command("*RCL", "recall(slot)", Access.WRITE),
    _command("INSTRUMENT", "instrument.channel", Access.READ_WRITE, aliases=("INST",)),
    _command(
        "MEASURE:CURRENT?",
        "measure.current(channel)",
        Access.READ,
        unit="A",
        aliases=("MEAS:CURR?",),
    ),
    _command(
        "MEASURE:VOLTAGE?",
        "measure.voltage(channel)",
        Access.READ,
        unit="V",
        aliases=("MEAS:VOLT?",),
    ),
    _command(
        "MEASURE:POWER?",
        "measure.power(channel)",
        Access.READ,
        unit="W",
        models=X_MODELS,
        aliases=("MEAS:POWE?",),
    ),
    _command("CH1:CURRENT", "ch1.current", Access.READ_WRITE, unit="A", aliases=("CH1:CURR",)),
    _command("CH1:VOLTAGE", "ch1.voltage", Access.READ_WRITE, unit="V", aliases=("CH1:VOLT",)),
    _command("CH2:CURRENT", "ch2.current", Access.READ_WRITE, unit="A", aliases=("CH2:CURR",)),
    _command("CH2:VOLTAGE", "ch2.voltage", Access.READ_WRITE, unit="V", aliases=("CH2:VOLT",)),
    _command(
        "OUTPUT", "output(channel, state); ch1/ch2/ch3.output", Access.WRITE, aliases=("OUTP",)
    ),
    _command("OUTPUT:TRACK", "output.track(mode)", Access.WRITE, aliases=("OUTP:TRACK",)),
    _command(
        "OUTPUT:WAVE",
        "output.wave(channel, state)",
        Access.WRITE,
        models=X_MODELS,
        aliases=("OUTP:WAVE",),
    ),
    _command("TIMER", "timer(channel, state)", Access.WRITE, models=X_MODELS),
    _command(
        "TIMER:SET",
        "timer.set(channel, group[, voltage_v, current_a, duration_s])",
        Access.READ_WRITE,
        unit="V,A,s",
        models=X_MODELS,
    ),
    _command("SYSTEM:ERROR?", "system.error", Access.READ, aliases=("SYST:ERR?",)),
    _command("SYSTEM:VERSION?", "system.version", Access.READ, aliases=("SYST:VERS?",)),
    _command("SYSTEM:STATUS?", "system.status", Access.READ, aliases=("SYST:STAT?",)),
    _command("IPADDR", "network.ip_address", Access.READ_WRITE, models=X_MODELS, aliases=("IP",)),
    _command(
        "MASKADDR", "network.subnet_mask", Access.READ_WRITE, models=X_MODELS, aliases=("MASK",)
    ),
    _command(
        "GATEADDR", "network.gateway_address", Access.READ_WRITE, models=X_MODELS, aliases=("GATE",)
    ),
    _command("DHCP", "network.dhcp", Access.READ_WRITE, models=X_MODELS),
    _command(
        "*LOCK", "lock()", Access.WRITE, source="SPD Local Front Panel Lock Out SCPI commands"
    ),
    _command(
        "*UNLOCK", "unlock()", Access.WRITE, source="SPD Local Front Panel Lock Out SCPI commands"
    ),
    _command(
        "*LOCK?",
        "locked",
        Access.READ,
        models=X_MODELS,
        source="SPD Local Front Panel Lock Out SCPI commands",
    ),
)


def _header(command: str) -> str:
    return command.strip().split(maxsplit=1)[0].upper().rstrip("?")


def lookup_command(command: str) -> tuple[CommandInfo, ...]:
    """Find Python API paths for a SCPI header, case-insensitively.

    Arguments and a trailing query marker are ignored, so both
    ``"MEAS:VOLT? CH1"`` and ``"MEASURE:VOLTAGE?"`` resolve.
    """

    wanted = _header(command)
    return tuple(
        info
        for info in COMMANDS
        if wanted in {_header(info.canonical_scpi), *(_header(alias) for alias in info.aliases)}
    )


def iter_commands(model: Model | None = None) -> Iterable[CommandInfo]:
    """Iterate over all commands, optionally filtered by model."""

    return (info for info in COMMANDS if model is None or model in info.models)
