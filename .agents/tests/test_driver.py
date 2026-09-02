from __future__ import annotations

import pytest

from siglent_spd3000 import (
    SPD3000,
    Channel,
    ConnectionType,
    ExecutionSettings,
    Model,
    OperatingMode,
    SPD3000ProtocolError,
    SPD3000TimingWarning,
    SPD3000ValidationError,
    TrackingMode,
    UnsupportedFeatureError,
)

from .conftest import FakeExecutor, responses_for


def test_connect_dispatches_and_converts_milliseconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_connect_socket(
        _cls: type[SPD3000],
        host: str,
        *,
        port: int,
        settings: object,
    ) -> object:
        captured.update(host=host, port=port, settings=settings)
        return sentinel

    monkeypatch.setattr(SPD3000, "_connect_socket", classmethod(fake_connect_socket))

    with pytest.warns(SPD3000TimingWarning) as caught:
        result = SPD3000.connect(
            connection="SOCKET",
            identifier=" 192.168.1.50 ",
            timeout_s=7.0,
            min_command_interval_ms=5,
            port=15025,
        )

    assert result is sentinel
    assert captured["host"] == "192.168.1.50"
    assert captured["port"] == 15025
    settings = captured["settings"]
    assert isinstance(settings, ExecutionSettings)
    assert settings.timeout == 7.0
    assert settings.min_command_interval == 0.005
    assert caught[0].filename == __file__


def test_connect_rejects_unknown_method_and_method_specific_options() -> None:
    with pytest.raises(SPD3000ValidationError, match="connection must be one of"):
        SPD3000.connect("ethernet", "192.168.1.50")

    with pytest.raises(SPD3000ValidationError, match="port cannot be used"):
        SPD3000.connect(ConnectionType.VXI11, "192.168.1.50", port=1234)


def test_connect_dispatches_every_supported_connection_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []
    sentinel = object()

    def recorder(name: str):  # type: ignore[no-untyped-def]
        def fake(_cls: type[SPD3000], target: str, **kwargs: object) -> object:
            calls.append((name, target, kwargs))
            return sentinel

        return classmethod(fake)

    for name in ("_connect_socket", "_connect_vxi11", "_connect_visa", "_connect_gateway"):
        monkeypatch.setattr(SPD3000, name, recorder(name))

    assert SPD3000.connect(ConnectionType.SOCKET, "socket-host") is sentinel
    assert SPD3000.connect("vxi11", "vxi11-host") is sentinel
    assert SPD3000.connect(ConnectionType.VISA, "USB0::1::INSTR", visa_backend="@py") is sentinel
    assert SPD3000.connect("gateway", "gateway-host", port=9876, token="secret") is sentinel

    assert [(name, target) for name, target, _kwargs in calls] == [
        ("_connect_socket", "socket-host"),
        ("_connect_vxi11", "vxi11-host"),
        ("_connect_visa", "USB0::1::INSTR"),
        ("_connect_gateway", "gateway-host"),
    ]
    assert calls[0][2]["port"] == 5025
    assert calls[2][2]["backend"] == "@py"
    assert calls[3][2]["port"] == 9876
    assert calls[3][2]["token"] == "secret"
    assert all(isinstance(kwargs["settings"], ExecutionSettings) for _, _, kwargs in calls)


def test_backend_connection_helpers_are_not_public_constructors() -> None:
    for name in ("from_socket", "from_vxi11", "from_visa", "from_gateway"):
        assert not hasattr(SPD3000, name)


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


def test_measurement_methods_keep_channel_as_an_argument_and_always_query() -> None:
    executor = FakeExecutor(
        responses_for(
            "SPD3303X",
            **{
                "MEAS:VOLT? CH1": ["1.0", "2.0"],
                "MEAS:CURR? CH2": ["0.25"],
                "MEAS:POWE? CH1": ["3.5"],
            },
        )
    )
    psu = SPD3000(executor)

    assert psu.measure.voltage(Channel.CH1) == 1.0
    assert psu.measure.voltage("ch1") == 2.0
    assert psu.measure.current(" CH2 ") == 0.25
    assert psu.measure.power(Channel.CH1) == 3.5
    assert executor.commands.count("MEAS:VOLT? CH1") == 2
    assert not hasattr(psu.measure, "ch1")


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
        lambda: psu.measure.power("CH1"),
        lambda: psu.network.ip_address,
        lambda: psu.timer("CH1", True),
        lambda: psu.output.wave("CH1", True),
        lambda: psu.locked,
    ]
    for operation in operations:
        with pytest.raises(UnsupportedFeatureError):
            operation()
        assert executor.commands == baseline


def test_timer_mapping_and_output_commands() -> None:
    executor = FakeExecutor(responses_for("SPD3303X-E", **{"TIMER:SET? CH1,1": ["3,0.5,2"]}))
    psu = SPD3000(executor)

    timer_step = {"voltage_v": 3.0, "current_a": 0.5, "duration_s": 2.0}
    psu.timer.set(Channel.CH1, 1, **timer_step)
    psu.timer.set("ch1", 2, 3.0, 0.5, 2.0)
    psu.timer("ch1", True)
    psu.output.track(TrackingMode.PARALLEL)
    psu.output.track(1)

    assert executor.commands[-5:] == [
        "TIMER:SET CH1,1,3,0.5,2",
        "TIMER:SET CH1,2,3,0.5,2",
        "TIMER CH1,ON",
        "OUTP:TRACK 2",
        "OUTP:TRACK 1",
    ]
    assert psu.timer.set("CH1", 1) == {
        "voltage_v": 3.0,
        "current_a": 0.5,
        "duration_s": 2.0,
    }


def test_channel_strings_are_accepted_consistently() -> None:
    executor = FakeExecutor(responses_for("SPD3303X"))
    psu = SPD3000(executor)

    psu.instrument.channel = "ch2"
    psu.output(" ch1 ", True)
    psu.output.wave("ch2", False)
    psu.timer("CH1", False)

    assert executor.commands[-4:] == [
        "INST CH2",
        "OUTP CH1,ON",
        "OUTP:WAVE CH2,OFF",
        "TIMER CH1,OFF",
    ]


def test_raw_enum_values_are_validated_before_io() -> None:
    executor = FakeExecutor(responses_for("SPD3303X"))
    psu = SPD3000(executor)
    baseline = list(executor.commands)

    for invalid_channel in ("CH4", "", 1):
        with pytest.raises(SPD3000ValidationError, match="channel"):
            psu.measure.voltage(invalid_channel)  # type: ignore[arg-type]
        assert executor.commands == baseline

    for invalid_mode in (True, 3, "1"):
        with pytest.raises(SPD3000ValidationError, match="mode"):
            psu.output.track(invalid_mode)  # type: ignore[arg-type]
        assert executor.commands == baseline

    with pytest.raises(SPD3000ValidationError, match="supplied together"):
        psu.timer.set("CH1", 1, 3.0)
    assert executor.commands == baseline


def test_idn_and_system_error_are_fresh_queries() -> None:
    responses = responses_for("SPD3303X", **{"SYST:ERR?": ['-100,"Command error"']})
    responses["*IDN?"] = [
        "Siglent Technologies,SPD3303X,SPD0001,1.0",
        "Siglent Technologies,SPD3303X,SPD0001,1.1",
    ]
    executor = FakeExecutor(responses)
    psu = SPD3000(executor)

    assert psu.model is Model.SPD3303X
    assert psu.idn.firmware_version == "1.1"
    assert psu.system.error.code == -100


def test_context_manager_closes_executor() -> None:
    executor = FakeExecutor(responses_for("SPD3303X"))
    with SPD3000(executor):
        pass
    assert executor.closed is True
