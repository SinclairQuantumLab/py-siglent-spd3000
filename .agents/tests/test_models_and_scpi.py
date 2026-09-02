from __future__ import annotations

import pytest

from siglent_spd3000 import Access, Model, SPD3000ProtocolError, iter_commands, lookup_command
from siglent_spd3000.models import parse_identification, parse_system_error


def test_identification_alias_and_unknown_model() -> None:
    identity = parse_identification("SIGLENT,SPD3303XE,SERIAL,1.2.3")
    assert identity.model is Model.SPD3303X_E

    with pytest.raises(SPD3000ProtocolError):
        parse_identification("SIGLENT,OTHER,SERIAL,1")


def test_system_error_common_formats() -> None:
    assert parse_system_error("0 No Error").message == "No Error"
    assert parse_system_error('-100,"Command error"').code == -100


def test_lookup_accepts_short_query_with_arguments() -> None:
    matches = lookup_command("meas:volt? ch1")
    assert len(matches) == 1
    assert matches[0].python_path == "measure.voltage(channel)"
    assert matches[0].access is Access.READ


def test_common_command_lookup_drops_leading_asterisk() -> None:
    matches = lookup_command("*IDN?")
    assert len(matches) == 1
    assert matches[0].python_path == "idn"


def test_command_registry_filters_model_capabilities() -> None:
    c_paths = {command.python_path for command in iter_commands(Model.SPD3303C)}
    assert "measure.power(channel)" not in c_paths
    assert "ipaddr" not in c_paths
    assert "output(channel, state)" in c_paths


def test_registry_separates_canonical_paths_from_friendly_aliases() -> None:
    ipaddr = lookup_command("IPADDR")[0]
    assert ipaddr.python_path == "ipaddr"
    assert ipaddr.python_aliases == ("network.host",)

    sav = lookup_command("*SAV 1")[0]
    assert sav.python_path == "sav(slot)"
    assert sav.python_aliases == ("save(slot)",)

    output = lookup_command("OUTP")[0]
    assert output.python_path == "output(channel, state)"
    assert output.python_aliases == ("ch1.output", "ch2.output", "ch3.output")
