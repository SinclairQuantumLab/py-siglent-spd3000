from __future__ import annotations

import pytest

import siglent_spd3000 as spd
from siglent_spd3000 import (
    SPD3000,
    Channel,
    ConnectionType,
    Deferred,
    ExecutionSettings,
    Model,
    OperatingMode,
    OutputState,
    SPD3000DeferredResultError,
    SPD3000ProtocolError,
    SPD3000TimeoutError,
    SPD3000TimingWarning,
    SPD3000ValidationError,
    SPD3000VerificationError,
    TimerState,
    TrackingMode,
    UnsupportedFeatureError,
    WaveformState,
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
        settings: object,
        verify_writes_globally: bool,
    ) -> object:
        captured.update(
            host=host,
            settings=settings,
            verify_writes_globally=verify_writes_globally,
        )
        return sentinel

    monkeypatch.setattr(SPD3000, "_connect_socket", classmethod(fake_connect_socket))

    with pytest.warns(SPD3000TimingWarning) as caught:
        result = SPD3000.connect(
            connection="SOCKET",
            identifier=" 192.168.1.50 ",
            timeout_s=7.0,
            min_command_interval_ms=5,
            verify_writes_globally=True,
        )

    assert result is sentinel
    assert captured["host"] == "192.168.1.50"
    settings = captured["settings"]
    assert isinstance(settings, ExecutionSettings)
    assert settings.timeout == 7.0
    assert settings.min_command_interval == 0.005
    assert captured["verify_writes_globally"] is True
    assert caught[0].filename == __file__


def test_connect_rejects_unknown_method_and_method_specific_options() -> None:
    with pytest.raises(SPD3000ValidationError, match="connection must be one of"):
        SPD3000.connect("ethernet", "192.168.1.50")

    with pytest.raises(SPD3000ValidationError, match="token cannot be used"):
        SPD3000.connect(ConnectionType.VXI11, "192.168.1.50", token="secret")

    with pytest.raises(TypeError, match="unexpected keyword argument 'port'"):
        SPD3000.connect(ConnectionType.SOCKET, "192.168.1.50", port=5025)  # type: ignore[call-arg]

    with pytest.raises(
        SPD3000ValidationError, match="verify_writes_globally must be a bool"
    ):
        SPD3000.connect(
            ConnectionType.SOCKET,
            "192.168.1.50",
            verify_writes_globally=1,  # type: ignore[arg-type]
        )


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
    assert SPD3000.connect("gateway", "gateway-host:9876", token="secret") is sentinel

    assert [(name, target) for name, target, _kwargs in calls] == [
        ("_connect_socket", "socket-host"),
        ("_connect_vxi11", "vxi11-host"),
        ("_connect_visa", "USB0::1::INSTR"),
        ("_connect_gateway", "gateway-host"),
    ]
    assert "port" not in calls[0][2]
    assert calls[2][2]["backend"] == "@py"
    assert calls[3][2]["port"] == 9876
    assert calls[3][2]["token"] == "secret"
    assert all(isinstance(kwargs["settings"], ExecutionSettings) for _, _, kwargs in calls)
    assert all(kwargs["verify_writes_globally"] is False for _, _, kwargs in calls)


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("gateway.local", ("gateway.local", 8765)),
        ("gateway.local:3333", ("gateway.local", 3333)),
        ("[::1]", ("::1", 8765)),
        ("[::1]:3333", ("::1", 3333)),
    ],
)
def test_gateway_identifier_parses_optional_port(
    identifier: str, expected: tuple[str, int]
) -> None:
    assert SPD3000._gateway_endpoint(identifier) == expected


@pytest.mark.parametrize(
    "identifier",
    (
        ":3333",
        "gateway.local:",
        "gateway.local:0",
        "gateway.local:65536",
        "gateway host:3333",
        "::1",
        "[::1",
    ),
)
def test_gateway_identifier_rejects_invalid_endpoints(identifier: str) -> None:
    with pytest.raises(SPD3000ValidationError):
        SPD3000._gateway_endpoint(identifier)


def test_backend_connection_helpers_are_not_public_constructors() -> None:
    for name in ("from_socket", "from_vxi11", "from_visa", "from_gateway"):
        assert not hasattr(SPD3000, name)


def test_string_summary_uses_cached_identity_and_local_connection_state() -> None:
    executor = FakeExecutor(responses_for("SPD3303X"))
    executor.settings = ExecutionSettings(min_command_interval=0.025, timeout=7.5)
    psu = SPD3000(executor, verify_writes_globally=True)
    psu._set_connection_metadata(ConnectionType.SOCKET, "192.168.1.50:5025")

    assert str(psu) == (
        "SIGLENT SPD3000 Series power supply driver instance\n"
        "- Model: SPD3303X\n"
        "- Serial number: SPD0001\n"
        "- Connection:\n"
        "  - Type: socket\n"
        "  - Identifier: 192.168.1.50:5025\n"
        "  - State: open\n"
        "- Execution settings:\n"
        "  - Timeout: 7.5 s\n"
        "  - Minimum command interval: 25 ms\n"
        "  - Verify writes globally: enabled"
    )
    assert psu.connection_type is ConnectionType.SOCKET
    assert psu.connection_identifier == "192.168.1.50:5025"
    assert psu.is_open is True
    assert executor.commands == ["*IDN?"]

    psu.close()

    assert "  - State: closed\n" in str(psu)
    assert "  - Verify writes globally: enabled" in str(psu)
    assert psu.is_open is False
    assert executor.commands == ["*IDN?"]


def test_string_summary_names_an_injected_executor() -> None:
    executor = FakeExecutor(responses_for("SPD3303C"))
    psu = SPD3000(executor)

    assert str(psu) == (
        "SIGLENT SPD3000 Series power supply driver instance\n"
        "- Model: SPD3303C\n"
        "- Serial number: SPD0001\n"
        "- Connection:\n"
        "  - Type: injected executor\n"
        "  - Identifier: FakeExecutor\n"
        "  - State: open\n"
        "- Execution settings:\n"
        "  - Timeout: 5 s\n"
        "  - Minimum command interval: 100 ms\n"
        "  - Verify writes globally: disabled"
    )
    assert psu.connection_type is None
    assert psu.connection_identifier is None


def test_output_command_and_channel_convenience_share_one_write_path() -> None:
    executor = FakeExecutor(responses_for("SPD3303X", **{"SYST:STAT?": ["0x0030", "0x0000"]}))
    psu = SPD3000(executor)

    psu.output(Channel.CH1, OutputState.ON)
    psu.output("CH1", "on")
    psu.ch1.output = True
    psu.ch2.output = False

    assert executor.commands[1:5] == [
        "OUTP CH1,ON",
        "OUTP CH1,ON",
        "OUTP CH1,ON",
        "OUTP CH2,OFF",
    ]
    assert psu.ch1.output is True
    assert psu.ch2.output is False
    assert executor.commands[-2:] == ["SYST:STAT?", "SYST:STAT?"]
    assert "OUTP?" not in executor.commands
    assert not hasattr(psu.output, "ch1")


def test_ch3_output_is_write_only_and_never_cached() -> None:
    executor = FakeExecutor(responses_for("SPD3303C"))
    psu = SPD3000(executor)

    psu.ch3.output = True
    assert executor.commands[-1] == "OUTP CH3,ON"

    before = list(executor.commands)
    with pytest.raises(UnsupportedFeatureError, match="no query"):
        _ = psu.ch3.output
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
                "IPADDR?": ["192.168.1.50", "192.168.001.050"],
                "MASKADDR?": ["255.255.255.0"],
                "GATEADDR?": ["192.168.1.1"],
                "DHCP?": ["DHCP:OFF"],
            },
        )
    )
    psu = SPD3000(executor)

    psu.ipaddr = "192.168.1.50"
    psu.network.subnet_mask = "255.255.255.0"
    psu.network.gateway = "192.168.1.1"
    psu.dhcp = False
    assert executor.commands[-4:] == [
        "IPADDR 192.168.1.50",
        "MASKADDR 255.255.255.0",
        "GATEADDR 192.168.1.1",
        "DHCP OFF",
    ]
    assert psu.network.host == "192.168.1.50"
    assert psu.maskaddr == "255.255.255.0"
    assert psu.network.gateway == "192.168.1.1"
    assert psu.network.dhcp is False

    before = list(executor.commands)
    with pytest.raises(SPD3000ValidationError):
        psu.network.gateway = "999.1.1.1"
    assert executor.commands == before

    with pytest.raises(SPD3000ProtocolError):
        _ = psu.ipaddr


def test_network_settings_returns_one_typed_snapshot_from_four_queries() -> None:
    executor = FakeExecutor(
        responses_for(
            "SPD3303X",
            **{
                "IPADDR?": ["192.168.1.50"],
                "MASKADDR?": ["255.255.255.0"],
                "GATEADDR?": ["192.168.1.1"],
                "DHCP?": ["DHCP:OFF"],
            },
        )
    )
    psu = SPD3000(executor)

    settings = psu.network.settings

    assert settings.host == "192.168.1.50"
    assert settings.subnet_mask == "255.255.255.0"
    assert settings.gateway == "192.168.1.1"
    assert settings.dhcp is False
    assert executor.commands[-4:] == ["IPADDR?", "MASKADDR?", "GATEADDR?", "DHCP?"]


def test_canonical_and_friendly_memory_names_share_implementation() -> None:
    executor = FakeExecutor(responses_for("SPD3303X"))
    psu = SPD3000(executor)

    psu.sav(1)
    psu.save(2)
    psu.rcl(3)
    psu.recall(4)

    assert executor.commands[-4:] == ["*SAV 1", "*SAV 2", "*RCL 3", "*RCL 4"]


def test_c_unsupported_features_fail_before_io() -> None:
    executor = FakeExecutor(responses_for("SPD3303C"))
    psu = SPD3000(executor)
    baseline = list(executor.commands)

    operations = [
        lambda: psu.measure.power("CH1"),
        lambda: psu.ipaddr,
        lambda: psu.network.host,
        lambda: psu.network.settings,
        lambda: psu.timer("CH1", TimerState.ON),
        lambda: psu.output.wave("CH1", WaveformState.ON),
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
    psu.timer("ch1", TimerState.ON)
    psu.output.wave(Channel.CH2, WaveformState.ON)
    psu.output.track(TrackingMode.PARALLEL)
    psu.output.track(1)

    assert executor.commands[-6:] == [
        "TIMER:SET CH1,1,3,0.5,2",
        "TIMER:SET CH1,2,3,0.5,2",
        "TIMER CH1,ON",
        "OUTP:WAVE CH2,ON",
        "OUTP:TRACK 2",
        "OUTP:TRACK 1",
    ]
    assert psu.timer.set("CH1", 1) == {
        "voltage_v": 3.0,
        "current_a": 0.5,
        "duration_s": 2.0,
    }


def test_channel_strings_are_accepted_consistently() -> None:
    executor = FakeExecutor(responses_for("SPD3303X", **{"INST?": ["CH1"]}))
    psu = SPD3000(executor)

    psu.instrument = "ch2"
    psu.output(" ch1 ", "on")
    psu.output.wave("ch2", "off")
    psu.timer("CH1", "off")
    selected = psu.instrument

    assert executor.commands[-5:] == [
        "INST CH2",
        "OUTP CH1,ON",
        "OUTP:WAVE CH2,OFF",
        "TIMER CH1,OFF",
        "INST?",
    ]
    assert selected is Channel.CH1


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

    for invalid_state in (True, False, 1, "enabled"):
        with pytest.raises(SPD3000ValidationError, match="state"):
            psu.output(Channel.CH1, invalid_state)  # type: ignore[arg-type]
        assert executor.commands == baseline

    for operation in (
        lambda: psu.output.wave(Channel.CH1, False),  # type: ignore[arg-type]
        lambda: psu.timer(Channel.CH1, True),  # type: ignore[arg-type]
    ):
        with pytest.raises(SPD3000ValidationError, match="state"):
            operation()
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


def test_batch_context_collects_semantic_writes_and_executes_once_on_exit() -> None:
    executor = FakeExecutor(responses_for("SPD3303X"))
    psu = SPD3000(executor)

    with psu.batch() as responses:
        psu.ch1.voltage = 5.0
        psu.ch1.current = 0.5
        psu.ch1.output = True
        assert executor.commands == ["*IDN?"]
        assert isinstance(responses, list)
        assert responses == []

    assert executor.batches[-1] == ["CH1:VOLT 5", "CH1:CURR 0.5", "OUTP CH1,ON"]
    assert responses == []


def test_batch_context_returns_parsed_user_queries_in_source_order() -> None:
    executor = FakeExecutor(
        responses_for(
            "SPD3303X",
            **{
                "CH1:VOLT?": ["5"],
                "MEAS:CURR? CH1": ["0.125"],
                "SYST:STAT?": ["0x10"],
            },
        )
    )
    psu = SPD3000(executor)

    with psu.batch() as responses:
        _ = psu.ch1.voltage
        _ = psu.measure.current(Channel.CH1)
        _ = psu.ch1.output

    assert isinstance(responses, list)
    assert responses == [5.0, 0.125, True]
    voltage, current, output = responses
    assert (voltage, current, output) == (5.0, 0.125, True)


def test_batch_discards_pending_operations_when_body_raises() -> None:
    executor = FakeExecutor(responses_for("SPD3303X", **{"CH1:VOLT?": ["5"]}))
    psu = SPD3000(executor)

    captured: list[Deferred[float]] = []

    @psu.batch
    def fail() -> None:
        psu.ch1.voltage = 5.0
        voltage = psu.ch1.voltage
        assert isinstance(voltage, Deferred)
        captured.append(voltage)
        raise RuntimeError("stop")

    with pytest.raises(RuntimeError, match="stop"):
        fail()

    assert executor.commands == ["*IDN?"]
    assert captured[0].done is True
    with pytest.raises(SPD3000DeferredResultError, match="cancelled"):
        _ = captured[0].value


def test_batch_context_leaves_response_list_empty_when_body_raises() -> None:
    executor = FakeExecutor(responses_for("SPD3303X", **{"CH1:VOLT?": ["5"]}))
    psu = SPD3000(executor)

    with pytest.raises(RuntimeError, match="stop"), psu.batch() as responses:
        _ = psu.ch1.voltage
        raise RuntimeError("stop")

    assert executor.commands == ["*IDN?"]
    assert responses == []


def test_batch_context_leaves_response_list_empty_when_query_parsing_fails() -> None:
    executor = FakeExecutor(responses_for("SPD3303X", **{"CH1:VOLT?": ["invalid"]}))
    psu = SPD3000(executor)

    with (
        pytest.raises(SPD3000ProtocolError, match="Malformed VOLT"),
        psu.batch() as responses,
    ):
        _ = psu.ch1.voltage

    assert responses == []


def test_batch_decorator_executes_mixed_operations_and_unwraps_return_value() -> None:
    executor = FakeExecutor(
        responses_for(
            "SPD3303X",
            **{
                "CH1:VOLT?": ["5"],
                "MEAS:CURR? CH1": ["0.125"],
                "SYST:STAT?": ["0x10", "0x10"],
            },
        )
    )
    psu = SPD3000(executor)

    @psu.batch
    def configure_and_read() -> dict[str, object]:
        psu.ch1.voltage = 5.0
        voltage = psu.ch1.voltage
        current = psu.measure.current(Channel.CH1)
        output = psu.ch1.output
        raw = psu.scpi.query("SYST:STAT?")
        assert all(isinstance(value, Deferred) for value in (voltage, current, output, raw))
        assert executor.commands == ["*IDN?"]
        with pytest.raises(SPD3000DeferredResultError, match="pending"):
            _ = voltage.value
        return {
            "voltage": voltage,
            "nested": [current, (output, raw)],
        }

    returned = configure_and_read()
    assert executor.batches[-1] == [
        "CH1:VOLT 5",
        "CH1:VOLT?",
        "MEAS:CURR? CH1",
        "SYST:STAT?",
        "SYST:STAT?",
    ]
    assert returned == {"voltage": 5.0, "nested": [0.125, (True, "0x10")]}


def test_batch_rejects_nested_decorated_and_context_calls() -> None:
    executor = FakeExecutor(responses_for("SPD3303X"))
    psu = SPD3000(executor)

    @psu.batch
    def inner() -> object:
        return psu.idn

    @psu.batch
    def outer() -> object:
        return inner()

    with pytest.raises(SPD3000ValidationError, match="Nested"):
        outer()

    with pytest.raises(
        SPD3000ValidationError, match="Nested"
    ), psu.batch(), psu.batch():
        pass


def test_batch_decorator_unwraps_structured_and_multi_query_results() -> None:
    executor = FakeExecutor(
        responses_for(
            "SPD3303X",
            **{
                "*IDN?": [
                    "Siglent Technologies,SPD3303X,SPD0001,1.0",
                    "Siglent Technologies,SPD3303X,SPD0002,2.0",
                ],
                "TIMER:SET? CH1,2": ["3,0.5,2"],
                "SYST:ERR?": ['-100,"Command error"'],
                "IPADDR?": ["192.168.1.50"],
                "MASKADDR?": ["255.255.255.0"],
                "GATEADDR?": ["192.168.1.1"],
                "DHCP?": ["DHCP:OFF"],
            },
        )
    )
    psu = SPD3000(executor)

    @psu.batch
    def read_all() -> tuple[object, object, object, object]:
        return (
            psu.idn,
            psu.timer.set(Channel.CH1, 2),
            psu.system.error,
            psu.network.settings,
        )

    identity, timer_step, system_error, network = read_all()
    assert identity.serial_number == "SPD0002"
    assert timer_step == {"voltage_v": 3.0, "current_a": 0.5, "duration_s": 2.0}
    assert system_error.code == -100
    assert network.host == "192.168.1.50"
    assert network.dhcp is False


def test_batch_query_parse_failure_raises_on_exit_and_remains_on_deferred() -> None:
    executor = FakeExecutor(responses_for("SPD3303X", **{"CH1:VOLT?": ["not-a-number"]}))
    psu = SPD3000(executor)

    captured: list[Deferred[float]] = []

    @psu.batch
    def read_voltage() -> object:
        voltage = psu.ch1.voltage
        assert isinstance(voltage, Deferred)
        captured.append(voltage)
        return voltage

    with pytest.raises(SPD3000ProtocolError, match="Malformed VOLT"):
        read_voltage()

    assert captured[0].done is True
    with pytest.raises(SPD3000ProtocolError, match="Malformed VOLT"):
        _ = captured[0].value


def test_batch_decorator_queries_compose_with_write_verification_queries() -> None:
    executor = FakeExecutor(responses_for("SPD3303X", **{"CH1:VOLT?": ["5", "5"]}))
    psu = SPD3000(executor)

    @psu.batch
    def configure_and_read() -> object:
        with psu.verify_writes():
            psu.ch1.voltage = 5.0
        return psu.ch1.voltage

    voltage = configure_and_read()
    assert executor.batches[-1] == ["CH1:VOLT 5", "CH1:VOLT?", "CH1:VOLT?"]
    assert voltage == 5.0


def test_verify_writes_executes_each_setter_as_its_own_write_query_batch() -> None:
    executor = FakeExecutor(
        responses_for(
            "SPD3303X",
            **{
                "CH1:VOLT?": ["5"],
                "CH1:CURR?": ["0.5"],
            },
        )
    )
    psu = SPD3000(executor)

    with psu.verify_writes():
        psu.ch1.voltage = 5.0
        psu.ch1.current = 0.5

    assert executor.batches[-2:] == [
        ["CH1:VOLT 5", "CH1:VOLT?"],
        ["CH1:CURR 0.5", "CH1:CURR?"],
    ]


def test_verify_writes_globally_is_a_settable_bool_property() -> None:
    executor = FakeExecutor(
        responses_for(
            "SPD3303X",
            **{
                "CH1:VOLT?": ["5", "4"],
            },
        )
    )
    psu = SPD3000(executor, verify_writes_globally=True)

    assert psu.verify_writes_globally is True
    psu.ch1.voltage = 5.0

    psu.verify_writes_globally = False
    assert psu.verify_writes_globally is False
    psu.ch1.current = 0.5

    with psu.verify_writes():
        psu.ch1.voltage = 4.0

    assert psu.verify_writes_globally is False
    assert executor.batches[-3:] == [
        ["CH1:VOLT 5", "CH1:VOLT?"],
        ["CH1:CURR 0.5"],
        ["CH1:VOLT 4", "CH1:VOLT?"],
    ]

    with pytest.raises(
        SPD3000ValidationError, match="verify_writes_globally must be a bool"
    ):
        psu.verify_writes_globally = 1  # type: ignore[assignment]
    with pytest.raises(SPD3000ValidationError, match="enabled must be a bool"):
        psu.verify_writes(1)  # type: ignore[arg-type]


def test_verify_writes_override_is_captured_per_setter_inside_batch() -> None:
    executor = FakeExecutor(responses_for("SPD3303X", **{"CH1:VOLT?": ["5"]}))
    psu = SPD3000(executor)

    psu.verify_writes_globally = True
    with psu.batch(), psu.verify_writes(False):
        psu.ch1.current = 0.5
        with psu.verify_writes():
            psu.ch1.voltage = 5.0
        psu.ch2.current = 0.5

    assert executor.batches[-1] == [
        "CH1:CURR 0.5",
        "CH1:VOLT 5",
        "CH1:VOLT?",
        "CH2:CURR 0.5",
    ]
    assert psu.verify_writes_globally is True


def test_batch_and_verify_writes_compose_into_one_non_interleaved_batch() -> None:
    executor = FakeExecutor(
        responses_for(
            "SPD3303X",
            **{
                "CH1:VOLT?": ["5"],
                "CH1:CURR?": ["0.5"],
                "SYST:STAT?": ["0x10"],
                "MEAS:VOLT? CH1": ["4.9"],
            },
        )
    )
    psu = SPD3000(executor)

    with psu.batch() as responses, psu.verify_writes():
        psu.ch1.voltage = 5.0
        psu.ch1.current = 0.5
        psu.ch1.output = True
        _ = psu.measure.voltage(Channel.CH1)

    assert executor.batches[-1] == [
        "CH1:VOLT 5",
        "CH1:VOLT?",
        "CH1:CURR 0.5",
        "CH1:CURR?",
        "OUTP CH1,ON",
        "SYST:STAT?",
        "MEAS:VOLT? CH1",
    ]
    assert responses == [4.9]


def test_verify_mismatch_raises_structured_verification_error_after_write() -> None:
    executor = FakeExecutor(responses_for("SPD3303X", **{"CH1:VOLT?": ["4.9"]}))
    psu = SPD3000(executor)

    with pytest.raises(
        SPD3000VerificationError, match=r"expected 5\.0"
    ) as caught, psu.verify_writes():
        psu.ch1.voltage = 5.0

    assert caught.value.command == "CH1:VOLT 5"
    assert caught.value.query == "CH1:VOLT?"
    assert caught.value.expected == 5.0
    assert caught.value.actual == 4.9
    assert executor.commands[-2:] == ["CH1:VOLT 5", "CH1:VOLT?"]


def test_verify_wraps_a_failed_readback_but_not_a_failed_write() -> None:
    class FailingExecutor(FakeExecutor):
        def __init__(self, *, failed_index: int) -> None:
            super().__init__(responses_for("SPD3303X"))
            self.failed_index = failed_index

        def execute(self, batch: spd.CommandBatch) -> spd.BatchResult:
            if any(command.text == "CH1:VOLT?" for command in batch.commands):
                self.batches.append([command.text for command in batch.commands])
                self.commands.extend(
                    command.text for command in batch.commands[: self.failed_index + 1]
                )
                error = SPD3000TimeoutError("timed out")
                error.batch_command_index = self.failed_index
                error.batch_command_kind = (
                    "query" if isinstance(batch.commands[self.failed_index], spd.Query) else "write"
                )
                error.batch_command = batch.commands[self.failed_index].text
                raise error
            return super().execute(batch)

    query_failure = FailingExecutor(failed_index=1)
    query_psu = SPD3000(query_failure)
    with pytest.raises(SPD3000VerificationError) as caught, query_psu.verify_writes():
        query_psu.ch1.voltage = 5.0
    assert isinstance(caught.value.__cause__, SPD3000TimeoutError)
    assert caught.value.command == "CH1:VOLT 5"
    assert caught.value.query == "CH1:VOLT?"

    write_failure = FailingExecutor(failed_index=0)
    with pytest.raises(SPD3000TimeoutError), SPD3000(write_failure).verify_writes() as psu:
        psu.ch1.voltage = 5.0


def test_verify_reports_unqueryable_state_only_after_sending_the_write() -> None:
    executor = FakeExecutor(responses_for("SPD3303X"))
    psu = SPD3000(executor)

    with pytest.raises(
        SPD3000VerificationError, match="no query"
    ) as caught, psu.verify_writes():
        psu.ch3.output = True

    assert executor.commands[-1] == "OUTP CH3,ON"
    assert caught.value.command == "OUTP CH3,ON"
    assert caught.value.query is None
    assert caught.value.expected is True
    assert caught.value.actual is None


def test_verify_supports_the_remaining_semantic_write_commands() -> None:
    executor = FakeExecutor(
        responses_for(
            "SPD3303X",
            **{
                "INST?": ["CH2"],
                "SYST:STAT?": ["0x0c", "0x204", "0x44"],
                "TIMER:SET? CH1,1": ["3,0.5,2"],
                "IPADDR?": ["192.168.1.50"],
                "MASKADDR?": ["255.255.255.0"],
                "GATEADDR?": ["192.168.1.1"],
                "DHCP?": ["DHCP:OFF"],
                "*LOCK?": ["LOCK", "UNLOCK"],
            },
        )
    )
    psu = SPD3000(executor)

    with psu.verify_writes():
        psu.instrument = Channel.CH2
        psu.output.track(TrackingMode.SERIES)
        psu.output.wave(Channel.CH2, WaveformState.ON)
        psu.timer(Channel.CH1, TimerState.ON)
        psu.timer.set(Channel.CH1, 1, 3.0, 0.5, 2.0)
        psu.ipaddr = "192.168.1.50"
        psu.maskaddr = "255.255.255.0"
        psu.gateaddr = "192.168.1.1"
        psu.dhcp = False
        psu.lock()
        psu.unlock()

    assert executor.batches[-1] == ["*UNLOCK", "*LOCK?"]


def test_lock_query_accepts_device_words_and_numeric_forms() -> None:
    executor = FakeExecutor(
        responses_for(
            "SPD3303X",
            **{"*LOCK?": ["LOCK", "UNLOCK", "1", "0"]},
        )
    )
    psu = SPD3000(executor)

    assert psu.locked is True
    assert psu.locked is False
    assert psu.locked is True
    assert psu.locked is False


def test_verify_reports_memory_and_raw_writes_as_unverifiable_after_execution() -> None:
    executor = FakeExecutor(responses_for("SPD3303X"))
    psu = SPD3000(executor)

    with pytest.raises(
        SPD3000VerificationError, match="saved setup slot"
    ), psu.verify_writes():
        psu.save(1)
    assert executor.commands[-1] == "*SAV 1"

    with pytest.raises(
        SPD3000VerificationError, match="No automatic"
    ), psu.verify_writes():
        psu.scpi.write("CUSTOM 1")
    assert executor.commands[-1] == "CUSTOM 1"
