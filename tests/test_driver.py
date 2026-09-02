from __future__ import annotations

import pytest

from siglent_spd3000 import (
    SPD3000,
    Channel,
    Model,
    OperatingMode,
    SPD3000ProtocolError,
    SPD3000ValidationError,
    TimerStep,
    TrackingMode,
    UnsupportedFeatureError,
)

from .conftest import FakeExecutor, responses_for


def test_output_callable_and_properties_share_one_write_path() -> None:
    executor = FakeExecutor(responses_for("SPD3303X", **{"SYST:STAT?": ["0x0030", "0x0000"]}))
    psu = SPD3000(executor)

    psu.output(Channel.CH1, True)
    psu.output.ch1 = True
    psu.output.ch2 = False

    assert executor.commands[1:4] == ["OUTP CH1,ON", "OUTP CH1,ON", "OUTP CH2,OFF"]
    assert psu.output.ch1 is True
    assert psu.output.ch2 is False
    assert executor.commands[-2:] == ["SYST:STAT?", "SYST:STAT?"]
    assert "OUTP?" not in executor.commands


def test_ch3_output_is_write_only_and_never_cached() -> None:
    executor = FakeExecutor(responses_for("SPD3303C"))
    psu = SPD3000(executor)

    psu.output.ch3 = True
    assert executor.commands[-1] == "OUTP CH3,ON"

    before = list(executor.commands)
    with pytest.raises(UnsupportedFeatureError, match="no query"):
        _ = psu.output.ch3
    assert executor.commands == before


def test_status_decodes_series_and_extended_x_bits() -> None:
    raw = (0b11 << 2) | 1 | (1 << 5) | (1 << 6) | (1 << 9)
    executor = FakeExecutor(responses_for("SPD3303X", **{"SYST:STAT?": [hex(raw)]}))
    status = SPD3000(executor).system.status

    assert status.operating_mode is OperatingMode.SERIES
    assert status.ch1.regulation.value == "CC"
    assert status.ch1.timer is True
    assert status.ch2.output is True
    assert status.ch2.waveform is True


def test_c_status_has_no_timer_or_waveform_state() -> None:
    executor = FakeExecutor(responses_for("SPD3303C", **{"SYST:STAT?": ["0x14"]}))
    status = SPD3000(executor).system.status

    assert status.operating_mode is OperatingMode.INDEPENDENT
    assert status.ch1.output is True
    assert status.ch1.timer is None
    assert status.ch2.waveform is None


def test_measurement_properties_always_query() -> None:
    executor = FakeExecutor(responses_for("SPD3303X", **{"MEAS:VOLT? CH1": ["1.0", "2.0"]}))
    psu = SPD3000(executor)

    assert psu.measure.ch1.voltage == 1.0
    assert psu.measure.ch1.voltage == 2.0
    assert executor.commands.count("MEAS:VOLT? CH1") == 2


@pytest.mark.parametrize(
    ("model", "valid", "invalid"),
    [
        ("SPD3303X", 1.001, 1.0005),
        ("SPD3303X-E", 1.01, 1.001),
        ("SPD3303C", 1.01, 1.001),
    ],
)
def test_model_resolution_is_enforced_without_rounding(
    model: str, valid: float, invalid: float
) -> None:
    executor = FakeExecutor(responses_for(model))
    psu = SPD3000(executor)

    psu.ch1.voltage = valid
    assert executor.commands[-1] == f"CH1:VOLT {valid}"

    before = list(executor.commands)
    with pytest.raises(SPD3000ValidationError, match="resolution"):
        psu.ch1.voltage = invalid
    assert executor.commands == before


def test_network_uses_validated_strings() -> None:
    executor = FakeExecutor(
        responses_for(
            "SPD3303X",
            **{
                "IPADDR?": ["192.168.001.050", "192.168.1.50"],
                "MASKADDR?": ["255.255.255.0"],
                "DHCP?": ["OFF"],
            },
        )
    )
    psu = SPD3000(executor)

    psu.network.ip_address = "192.168.1.50"
    psu.network.subnet_mask = "255.255.255.0"
    assert executor.commands[-2:] == ["IPADDR 192.168.1.50", "MASKADDR 255.255.255.0"]
    assert psu.network.subnet_mask == "255.255.255.0"
    assert psu.network.dhcp is False

    before = list(executor.commands)
    with pytest.raises(SPD3000ValidationError):
        psu.network.gateway_address = "999.1.1.1"
    assert executor.commands == before

    with pytest.raises(SPD3000ProtocolError):
        _ = psu.network.ip_address


def test_c_unsupported_features_fail_before_io() -> None:
    executor = FakeExecutor(responses_for("SPD3303C"))
    psu = SPD3000(executor)
    baseline = list(executor.commands)

    operations = [
        lambda: psu.measure.ch1.power,
        lambda: psu.network.ip_address,
        lambda: psu.timer(Channel.CH1, True),
        lambda: psu.output.wave(Channel.CH1, True),
        lambda: psu.locked,
    ]
    for operation in operations:
        with pytest.raises(UnsupportedFeatureError):
            operation()
        assert executor.commands == baseline


def test_timer_mapping_and_output_commands() -> None:
    executor = FakeExecutor(responses_for("SPD3303X-E", **{"TIMER:SET? CH1,1": ["3,0.5,2"]}))
    psu = SPD3000(executor)

    psu.timer.set[Channel.CH1, 1] = TimerStep(3.0, 0.5, 2.0)
    psu.timer(Channel.CH1, True)
    psu.output.track(TrackingMode.PARALLEL)

    assert executor.commands[-3:] == [
        "TIMER:SET CH1,1,3,0.5,2",
        "TIMER CH1,ON",
        "OUTP:TRACK 2",
    ]
    assert psu.timer.set[Channel.CH1, 1] == TimerStep(3.0, 0.5, 2.0)


def test_identity_and_system_error_are_fresh_queries() -> None:
    responses = responses_for("SPD3303X", **{"SYST:ERR?": ['-100,"Command error"']})
    responses["*IDN?"] = [
        "Siglent Technologies,SPD3303X,SPD0001,1.0",
        "Siglent Technologies,SPD3303X,SPD0001,1.1",
    ]
    executor = FakeExecutor(responses)
    psu = SPD3000(executor)

    assert psu.model is Model.SPD3303X
    assert psu.identity.firmware_version == "1.1"
    assert psu.system.error.code == -100


def test_context_manager_closes_executor() -> None:
    executor = FakeExecutor(responses_for("SPD3303X"))
    with SPD3000(executor):
        pass
    assert executor.closed is True
