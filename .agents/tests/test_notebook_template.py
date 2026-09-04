from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _notebook() -> dict[str, Any]:
    source = Path(__file__).resolve().parents[2] / "test_spd300.ipynb.template"
    return json.loads(source.read_text(encoding="utf-8"))


def test_hardware_notebook_template_is_clean_and_well_formed() -> None:
    notebook = _notebook()

    assert notebook["nbformat"] == 4
    assert notebook["cells"]
    for index, cell in enumerate(notebook["cells"]):
        assert cell["cell_type"] in {"markdown", "code"}
        assert cell["source"]
        if cell["cell_type"] == "code":
            assert index > 0
            if notebook["cells"][index - 1]["cell_type"] != "code":
                assert notebook["cells"][index - 1]["cell_type"] == "markdown"
            assert cell["execution_count"] is None
            assert cell["outputs"] == []
            source = "".join(cell["source"]).replace(
                "spd.ConnectionType.<TYPE>", "spd.ConnectionType.SOCKET"
            )
            compile(source, f"notebook-cell-{index}", "exec")


def test_connection_placeholder_is_confined_to_connection_settings_cell() -> None:
    notebook = _notebook()
    placeholder_cells = [
        cell for cell in notebook["cells"] if 'identifier="<IDENTIFIER>"' in "".join(cell["source"])
    ]

    assert len(placeholder_cells) == 1
    assert "connection-settings" in placeholder_cells[0]["metadata"]["tags"]


def test_connection_settings_are_clear_and_connection_specific() -> None:
    notebook = _notebook()
    settings_cells = [
        cell
        for cell in notebook["cells"]
        if "connection-settings" in cell["metadata"].get("tags", [])
    ]

    assert len(settings_cells) == 1
    settings = "".join(settings_cells[0]["source"])
    assert "connection=spd.ConnectionType.<TYPE>,  # e.g., SOCKET, VXI11, VISA, GATEWAY" in settings
    assert 'identifier="<IDENTIFIER>",  # e.g., instrument IP, VISA resource' in settings
    assert "timeout_s=5.0,  # communication timeout in seconds" in settings
    assert "min_command_interval_ms=100.0,  # delay between instrument commands" in settings
    assert "verify_writes_globally=False,  # True adds readback" in settings
    assert "CONNECTION_TYPE =" not in settings
    assert "IDENTIFIER =" not in settings
    assert "TIMEOUT_S =" not in settings
    assert "MIN_COMMAND_INTERVAL_MS =" not in settings
    assert "VISA_BACKEND" not in settings
    assert "GATEWAY_AUTH_FILE" not in settings
    assert '# visa_backend="@py"' in settings
    assert '# token=spd.load_gateway_auth("gateway-auth.toml")' in settings
    assert "raise ValueError" not in settings
    assert "print(psu)" in settings


def test_section_one_places_optional_visa_discovery_after_connection() -> None:
    notebook = _notebook()
    discovery_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "visa-discovery" in cell["metadata"].get("tags", [])
    )
    connection_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "connection-settings" in cell["metadata"].get("tags", [])
    )
    discovery = "".join(notebook["cells"][discovery_index]["source"])
    guide = "".join(notebook["cells"][discovery_index - 1]["source"])

    assert connection_index + 2 == discovery_index
    assert guide.startswith("### 1.1 Optional VISA resource discovery")
    assert "Run this cell only when `ConnectionType.VISA` is selected" in guide
    assert "Copy the power supply resource into `identifier`" in guide
    assert "For VISA only" in discovery
    assert "visa_resource_manager = pyvisa.ResourceManager()  # system VISA backend" in discovery
    assert (
        '# visa_resource_manager = pyvisa.ResourceManager("@py")  # PyVISA-py backend'
        in discovery
    )
    assert "active line searches system VISA" in discovery
    assert ".list_resources()" in discovery
    assert "USB0::0x0483::0x7540::SPD3XGB4150080::INSTR" in discovery
    assert "TCPIP0::192.168.55.122::inst0::INSTR" in discovery
    assert "serial number and IP address will differ" in discovery


def test_section_one_has_a_gateway_specific_connection_example() -> None:
    notebook = _notebook()
    discovery_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "visa-discovery" in cell["metadata"].get("tags", [])
    )
    gateway_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "gateway-connection" in cell["metadata"].get("tags", [])
    )
    guide = "".join(notebook["cells"][gateway_index - 1]["source"])
    example = "".join(notebook["cells"][gateway_index]["source"])

    assert discovery_index + 2 == gateway_index
    assert guide.startswith("### 1.2 Connection through the gateway")
    assert "Close any direct `psu` connection" in guide
    assert "spd3000 gateway serve" in guide
    assert "connection=spd.ConnectionType.GATEWAY" in example
    assert 'identifier="localhost"' in example
    assert 'token=spd.load_gateway_auth("gateway-auth.toml")' in example


def test_gateway_section_has_a_simultaneous_multi_client_read_test() -> None:
    notebook = _notebook()
    gateway_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "gateway-connection" in cell["metadata"].get("tags", [])
    )
    multi_client_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "gateway-multi-client" in cell["metadata"].get("tags", [])
    )
    guide = "".join(notebook["cells"][multi_client_index - 1]["source"])
    example = "".join(notebook["cells"][multi_client_index]["source"])

    assert gateway_index + 2 == multi_client_index
    assert guide.startswith("#### 1.2.1 Multi-client read test")
    assert "read-only test" in guide
    assert "complete, non-interleaved batches" in guide
    assert "ThreadPoolExecutor(max_workers=2)" in example
    assert "Barrier(2)" in example
    assert "start_barrier.wait(timeout=10.0)" in example
    assert example.count("connection=spd.ConnectionType.GATEWAY") == 1
    assert "with client.batch() as responses:" in example
    assert "client.measure.voltage(spd.Channel.CH1)" in example
    assert "client.measure.current(spd.Channel.CH1)" in example
    assert ".voltage =" not in example
    assert ".current =" not in example
    assert ".output =" not in example


def test_notebook_template_is_linked_and_working_copy_is_ignored() -> None:
    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text(encoding="utf-8")
    gitignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "[`test_spd300.ipynb.template`](test_spd300.ipynb.template)" in readme
    assert "test_spd300.ipynb" in gitignore


def test_notebook_demonstrates_manual_scpi_command_discovery() -> None:
    notebook = _notebook()
    discovery_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if cell["cell_type"] == "code" and "SCPI_COMMAND_FROM_MANUAL" in "".join(cell["source"])
    )
    guide = "".join(notebook["cells"][discovery_index - 1]["source"])
    example = "".join(notebook["cells"][discovery_index]["source"])

    assert "Find a Python API from a manual SCPI command" in guide
    assert "without communicating with the instrument" in guide
    assert 'SCPI_COMMAND_FROM_MANUAL = "MEASure:VOLTage? CH1"' in example
    assert "spd.lookup_command(SCPI_COMMAND_FROM_MANUAL)" in example
    assert "for match in matches:" in example
    assert "print(match)" in example


def test_notebook_orders_control_verification_batching_and_diagnostics() -> None:
    notebook = _notebook()
    notebook_text = json.dumps(notebook)
    headings = [
        "".join(cell["source"]).splitlines()[0]
        for cell in notebook["cells"]
        if cell["cell_type"] == "markdown" and "".join(cell["source"]).startswith("## ")
    ]
    sections = {
        "".join(cell["source"]).splitlines()[0]: "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "markdown"
        and "".join(cell["source"]).startswith(("## 6.", "## 7.", "## 8."))
    }

    assert headings[4:12] == [
        "## 5. CH1 and CH2 read-only checks",
        "## 6. Basic CH1 output control",
        "## 7. Write verification",
        "## 8. Batch execution",
        "## 9. Repeated-query stability",
        "## 10. Model-specific read-only checks",
        "## 11. Read-only semantic and raw batches",
        "## 12. Optional error-queue read",
    ]
    assert "Read-only semantic and raw batches" in notebook_text
    assert "with psu.batch() as semantic_responses:" in notebook_text
    assert "batch_identity, batch_status = semantic_responses" in notebook_text
    assert "## 6. Basic CH1 output control" in sections
    assert "## 7. Write verification" in sections
    assert "## 8. Batch execution" in sections
    basic_control_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "".join(cell["source"]).startswith("## 6. Basic CH1 output control")
    )
    basic_control = "".join(notebook["cells"][basic_control_index + 1]["source"])
    assert "psu.batch" not in basic_control
    assert "psu.verify_writes" not in basic_control
    assert basic_control == (
        "psu.ch1.voltage = 1.0\n"
        "psu.ch1.current = 0.1\n"
        "psu.ch1.output = True\n"
        "\n"
        'print(f"CH1 set voltage: {psu.ch1.voltage} V, current: {psu.ch1.current} A, '
        'output: {psu.ch1.output}")'
    )
    output_off = "".join(notebook["cells"][basic_control_index + 2]["source"])
    assert output_off == (
        "psu.ch1.voltage = 0\n"
        "psu.ch1.current = 0\n"
        "psu.ch1.output = False\n"
        "\n"
        'print(f"CH1 set voltage: {psu.ch1.voltage} V, current: {psu.ch1.current} A, '
        'output: {psu.ch1.output}")'
    )
    assert "with psu.verify_writes():" in notebook_text
    assert "psu.ch1.voltage = current_voltage" in notebook_text
    assert "psu.ch1.current = current_limit" in notebook_text
    assert "psu.ch1.output = current_output" in notebook_text
    batch_overview = sections["## 8. Batch execution"]
    assert "ordinary list that stays empty inside the block" in batch_overview
    assert "only explicit user-query results in source order" in batch_overview
    assert "writes and automatic verification readbacks are omitted" in batch_overview
    assert "not rollback" in batch_overview

    batch_examples = {}
    for title in (
        "### 8.1 Context manager and responses",
        "### 8.2 Decorator",
        "### 8.3 Batch with write verification",
    ):
        index = next(
            index
            for index, cell in enumerate(notebook["cells"])
            if "".join(cell["source"]).startswith(title)
        )
        batch_examples[title] = "".join(notebook["cells"][index + 1]["source"])

    context_example = batch_examples["### 8.1 Context manager and responses"]
    assert "with psu.batch() as responses:" in context_example
    assert "print(type(responses))" in context_example
    assert "print(responses)" in context_example
    assert "responses.values" not in context_example
    assert "ch1_voltage, ch1_current_limit, ch1_output = responses" in context_example

    decorator_example = batch_examples["### 8.2 Decorator"]
    assert "@psu.batch" in decorator_example
    assert "def configure_and_read():" in decorator_example
    assert "ch1_set_voltage, ch1_measured_voltage = configure_and_read()" in decorator_example

    verification_example = batch_examples["### 8.3 Batch with write verification"]
    assert "with psu.batch() as responses, psu.verify_writes():" in verification_example
    assert "verified_voltage, verified_current_limit = responses" in verification_example
    verification_heading_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "".join(cell["source"]).startswith("### 8.3 Batch with write verification")
    )
    decorated_verification = "".join(
        notebook["cells"][verification_heading_index + 2]["source"]
    )
    assert decorated_verification.startswith("@psu.batch\ndef configure_and_read():")
    assert "    with psu.verify_writes():" in decorated_verification
    assert "    return psu.ch1.voltage, psu.measure.voltage" in decorated_verification


def test_notebook_stresses_gateway_batch_isolation_with_randomized_clients() -> None:
    notebook = _notebook()
    example_index = next(
        index
        for index, cell in enumerate(notebook["cells"])
        if "gateway-batch-isolation" in cell["metadata"].get("tags", [])
    )
    guide = "".join(notebook["cells"][example_index - 1]["source"])
    example = "".join(notebook["cells"][example_index]["source"])

    assert guide.startswith("### 8.4 Gateway multi-client batch isolation")
    assert "set voltage → set current → query voltage → query current" in guide
    assert "random durations shorter than `psu.settings.min_command_interval`" in guide
    assert "restores its original voltage, current, and output state" in guide
    assert "assert psu.connection_type is spd.ConnectionType.GATEWAY" in example
    assert "Barrier(len(client_cases))" in example
    assert "randomizer.uniform(0.0, psu.settings.min_command_interval * 0.9)" in example
    assert "ThreadPoolExecutor(max_workers=len(scheduled_cases))" in example
    assert "with client.batch() as responses:" in example
    assert "client.ch1.voltage = voltage_v" in example
    assert "client.ch1.current = current_a" in example
    assert "assert read_voltage_v == voltage_v" in example
    assert "assert read_current_a == current_a" in example
    assert "psu.ch1.output = False" in example
    assert "psu.ch1.voltage = original_voltage" in example
    assert "psu.ch1.current = original_current" in example
    assert "psu.ch1.output = original_output" in example


def test_notebook_exercises_public_driver_paths_with_safety_guidance() -> None:
    notebook_text = json.dumps(_notebook())

    for expected in (
        "spd.SPD3000.connect(",
        "spd.lookup_command(",
        "psu.idn",
        "psu.system.status",
        "psu.measure.voltage",
        "psu.measure.current",
        "psu.scpi.execute",
        "psu.network.settings",
        "psu.timer.set",
        "psu.output.wave",
        "with psu.batch(), psu.verify_writes():",
        "with psu.batch():",
        "psu.lock()",
        "psu.close()",
        "finally:",
    ):
        assert expected in notebook_text

    assert "validate_grid_value" not in notebook_text
    assert "from decimal import Decimal" not in notebook_text
    assert "from dataclasses import asdict" not in notebook_text
    assert "from pprint import pprint" in notebook_text
    assert "print(psu.idn); print()" in notebook_text
    assert "print(psu.capabilities)" in notebook_text
    assert "print(psu.settings)" in notebook_text
    assert "print(status)" in notebook_text
    assert "print(psu.system.error)" in notebook_text
    assert "print(psu.network.settings)" in notebook_text
    assert 'print(f\\"Front panel locked: {psu.locked}\\")' in notebook_text
    assert "LOCK_QUERY_RESPONDS = False" in notebook_text
    assert "except (spd.SPD3000TimeoutError, spd.SPD3000ProtocolError)" in notebook_text
    assert "if LOCK_QUERY_RESPONDS:" in notebook_text
    assert "if psu.capabilities.lock_query:" in notebook_text
    assert "asdict(" not in notebook_text
    assert "json.dumps" not in notebook_text
    assert "isolated from sensitive hardware" in notebook_text
    assert "psu.ch1.voltage = 1.0" in notebook_text
    assert "psu.ch1.current = 0.1" in notebook_text
    assert "psu.ch1.output = True" in notebook_text
    assert "CH1 voltage, current, and output writes were verified." in notebook_text
    assert "ENERGIZE_OUTPUT" not in notebook_text
    assert "RUN_CH3_OUTPUT_TEST = False" in notebook_text
    assert "RUN_TIMER_WAVEFORM_TEST = False" in notebook_text
    assert "RUN_FRONT_PANEL_LOCK_TEST = False" in notebook_text
