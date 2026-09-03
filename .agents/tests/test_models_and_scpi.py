from __future__ import annotations

import pytest

from siglent_spd3000 import (
    Access,
    Capabilities,
    ChannelStatus,
    Model,
    NetworkSettings,
    OperatingMode,
    RegulationMode,
    SPD3000ProtocolError,
    SystemStatus,
    iter_commands,
    lookup_command,
)
from siglent_spd3000.models import parse_identification, parse_system_error


def test_identification_alias_and_unknown_model() -> None:
    identity = parse_identification("SIGLENT,SPD3303XE,SERIAL,1.2.3")
    assert identity.model is Model.SPD3303X_E
    assert str(identity) == (
        "SIGLENT SPD3000 Series instrument identification\n"
        "- Manufacturer: SIGLENT\n"
        "- Model: SPD3303X-E\n"
        "- Serial number: SERIAL\n"
        "- Firmware version: 1.2.3\n"
        "- Raw response: SIGLENT,SPD3303XE,SERIAL,1.2.3"
    )

    with pytest.raises(SPD3000ProtocolError):
        parse_identification("SIGLENT,OTHER,SERIAL,1")


def test_system_error_common_formats() -> None:
    no_error = parse_system_error("0 No Error")
    command_error = parse_system_error('-100,"Command error"')

    assert no_error.message == "No Error"
    assert command_error.code == -100
    assert str(command_error) == (
        "SIGLENT SPD3000 Series system error\n"
        "- Code: -100\n"
        "- Message: Command error"
    )


def test_network_settings_have_a_grouped_human_readable_summary() -> None:
    settings = NetworkSettings(
        host="192.168.1.50",
        subnet_mask="255.255.255.0",
        gateway="192.168.1.1",
        dhcp=False,
    )

    assert str(settings) == (
        "SIGLENT SPD3000 Series network settings\n"
        "- IP address: 192.168.1.50\n"
        "- Subnet mask: 255.255.255.0\n"
        "- Gateway: 192.168.1.1\n"
        "- DHCP: disabled"
    )


def test_capabilities_have_a_grouped_human_readable_summary() -> None:
    capabilities = Capabilities(
        model=Model.SPD3303X_E,
        voltage_resolution=0.01,
        current_resolution=0.01,
        measure_power=True,
        waveform=True,
        timer=True,
        network=False,
        lock_query=False,
        socket=True,
        vxi11=False,
    )

    assert str(capabilities) == (
        "SIGLENT SPD3000 Series model capabilities\n"
        "- Model: SPD3303X-E\n"
        "- Programming resolution:\n"
        "  - Voltage: 0.01 V\n"
        "  - Current: 0.01 A\n"
        "- Features:\n"
        "  - Power measurement: supported\n"
        "  - Waveform display: supported\n"
        "  - Timer: supported\n"
        "  - Network configuration: not supported\n"
        "  - Front-panel lock query: not supported\n"
        "- Connections:\n"
        "  - Raw socket: supported\n"
        "  - VXI-11: not supported\n"
        "  - VISA: supported"
    )


def test_channel_status_formats_optional_fields_without_instrument_io() -> None:
    status = ChannelStatus(
        regulation=RegulationMode.CV,
        output=True,
        timer=False,
        waveform=None,
    )

    assert str(status) == (
        "SIGLENT SPD3000 Series channel status\n"
        "- Regulation: CV\n"
        "- Output: on\n"
        "- Timer: off\n"
        "- Waveform: unavailable"
    )


def test_system_status_groups_both_channel_statuses() -> None:
    status = SystemStatus(
        raw=0x235,
        operating_mode=OperatingMode.SERIES,
        ch1=ChannelStatus(RegulationMode.CC, True, False, None),
        ch2=ChannelStatus(RegulationMode.CV, False, True, True),
    )

    assert str(status) == (
        "SIGLENT SPD3000 Series system status\n"
        "- Raw status word: 0x0235\n"
        "- Operating mode: series\n"
        "- Channels:\n"
        "  - CH1:\n"
        "    - Regulation: CC\n"
        "    - Output: on\n"
        "    - Timer: off\n"
        "    - Waveform: unavailable\n"
        "  - CH2:\n"
        "    - Regulation: CV\n"
        "    - Output: off\n"
        "    - Timer: on\n"
        "    - Waveform: on"
    )


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


def test_command_info_has_a_grouped_human_readable_summary() -> None:
    command = lookup_command("MEAS:VOLT? CH1")[0]

    assert str(command) == (
        "SIGLENT SPD3000 Series SCPI command\n"
        "- SCPI command: MEASURE:VOLTAGE?\n"
        "- Python API: measure.voltage(channel)\n"
        "- Access: read\n"
        "- Unit: V\n"
        "- Models:\n"
        "  - SPD3303X\n"
        "  - SPD3303X-E\n"
        "  - SPD3303C\n"
        "- Documentation source: SPD3303X/SPD3303C Quick Start\n"
        "- Friendly Python aliases:\n"
        "  - none\n"
        "- Accepted SCPI aliases:\n"
        "  - MEAS:VOLT?"
    )
