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
    """A SCPI command's canonical Python path and any additive friendly aliases.

    ``aliases`` contains accepted SCPI abbreviations, while ``python_aliases``
    contains Python paths which delegate to ``python_path``.
    """

    canonical_scpi: str
    python_path: str
    access: Access
    unit: str | None
    models: tuple[Model, ...]
    source: str
    python_aliases: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()

    def __str__(self) -> str:
        """Return command syntax, availability, and aliases as a readable summary."""

        lines = [
            "SIGLENT SPD3000 Series SCPI command",
            f"- SCPI command: {self.canonical_scpi}",
            f"- Python API: {self.python_path}",
            f"- Access: {self.access.value}",
            f"- Unit: {self.unit or 'none'}",
            "- Models:",
            *(f"  - {model.value}" for model in self.models),
            f"- Documentation source: {self.source}",
            "- Friendly Python aliases:",
            *(_list_values(self.python_aliases)),
            "- Accepted SCPI aliases:",
            *(_list_values(self.aliases)),
        ]
        return "\n".join(lines)


def _list_values(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"  - {value}" for value in values) or ("  - none",)


def _command(
    canonical: str,
    path: str,
    access: Access,
    *,
    unit: str | None = None,
    models: tuple[Model, ...] = ALL_MODELS,
    source: str = "SPD3303X/SPD3303C Quick Start",
    python_aliases: tuple[str, ...] = (),
    aliases: tuple[str, ...] = (),
) -> CommandInfo:
    return CommandInfo(canonical, path, access, unit, models, source, python_aliases, aliases)


COMMANDS: tuple[CommandInfo, ...] = (
    _command("*IDN?", "idn", Access.READ),
    _command("*SAV", "sav(slot)", Access.WRITE, python_aliases=("save(slot)",)),
    _command("*RCL", "rcl(slot)", Access.WRITE, python_aliases=("recall(slot)",)),
    _command("INSTRUMENT", "instrument", Access.READ_WRITE, aliases=("INST",)),
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
        "OUTPUT",
        "output(channel, state)",
        Access.WRITE,
        python_aliases=("ch1.output", "ch2.output", "ch3.output"),
        aliases=("OUTP",),
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
    _command(
        "IPADDR",
        "ipaddr",
        Access.READ_WRITE,
        models=X_MODELS,
        python_aliases=("network.host",),
        aliases=("IP",),
    ),
    _command(
        "MASKADDR",
        "maskaddr",
        Access.READ_WRITE,
        models=X_MODELS,
        python_aliases=("network.subnet_mask",),
        aliases=("MASK",),
    ),
    _command(
        "GATEADDR",
        "gateaddr",
        Access.READ_WRITE,
        models=X_MODELS,
        python_aliases=("network.gateway",),
        aliases=("GATE",),
    ),
    _command(
        "DHCP",
        "dhcp",
        Access.READ_WRITE,
        models=X_MODELS,
        python_aliases=("network.dhcp",),
    ),
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
