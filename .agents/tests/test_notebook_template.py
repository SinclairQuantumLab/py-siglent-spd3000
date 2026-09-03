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
            assert index > 0 and notebook["cells"][index - 1]["cell_type"] == "markdown"
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


def test_notebook_template_is_linked_and_working_copy_is_ignored() -> None:
    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text(encoding="utf-8")
    gitignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "[`test_spd300.ipynb.template`](test_spd300.ipynb.template)" in readme
    assert "test_spd300.ipynb" in gitignore


def test_notebook_exercises_public_driver_paths_with_safety_gates() -> None:
    notebook_text = json.dumps(_notebook())

    for expected in (
        "spd.SPD3000.connect(",
        "psu.idn",
        "psu.system.status",
        "psu.measure.voltage",
        "psu.measure.current",
        "psu.scpi.execute",
        "psu.network.settings",
        "psu.timer.set",
        "psu.output.wave",
        "with psu.batch_write, psu.verify:",
        "with psu.batch_write:",
        "psu.lock()",
        "psu.close()",
        "Cancelled before sending any write command",
        "finally:",
    ):
        assert expected in notebook_text

    assert "validate_grid_value" not in notebook_text
    assert "from decimal import Decimal" not in notebook_text
    assert "from dataclasses import asdict" not in notebook_text
    assert "from pprint import pprint" in notebook_text
    assert "print(identity)" in notebook_text
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
    assert "DISABLE {TEST_CHANNEL.value}" in notebook_text
    assert '[1/3] Query SCPI: \\"SYST:STAT?\\"' in notebook_text
    assert '[2/3] Write SCPI: \\"OUTP {TEST_CHANNEL.value},OFF\\"' in notebook_text
    assert "Output-off round trip passed; the channel remains off." in notebook_text
    assert "TEST_VOLTAGE_V" not in notebook_text
    assert "TEST_CURRENT_A" not in notebook_text
    assert "ENERGIZE_OUTPUT" not in notebook_text
    assert "RUN_CH3_OUTPUT_TEST = False" in notebook_text
    assert "RUN_TIMER_WAVEFORM_TEST = False" in notebook_text
    assert "RUN_FRONT_PANEL_LOCK_TEST = False" in notebook_text
