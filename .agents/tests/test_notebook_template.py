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
            compile("".join(cell["source"]), f"notebook-cell-{index}", "exec")


def test_connection_placeholder_is_confined_to_connection_settings_cell() -> None:
    notebook = _notebook()
    placeholder_cells = [
        cell
        for cell in notebook["cells"]
        if "<REPLACE_WITH_IDENTIFIER>" in "".join(cell["source"])
    ]

    assert len(placeholder_cells) == 1
    assert "connection-settings" in placeholder_cells[0]["metadata"]["tags"]


def test_connection_settings_are_explicit_and_transport_neutral() -> None:
    notebook = _notebook()
    settings_cells = [
        cell
        for cell in notebook["cells"]
        if "connection-settings" in cell["metadata"].get("tags", [])
    ]

    assert len(settings_cells) == 1
    settings = "".join(settings_cells[0]["source"])
    assert "CONNECTION_TYPE: spd.ConnectionType | None = None" in settings
    assert "connection=CONNECTION_TYPE" in settings
    assert "CONNECTION = spd.ConnectionType.SOCKET" not in settings
    assert "IDENTIFIER = \"<REPLACE_WITH_IDENTIFIER>\"" in settings


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
        "psu.network.host",
        "psu.timer.set",
        "psu.output.wave",
        "psu.lock()",
        "psu.close()",
        "Cancelled before sending any write command",
        "finally:",
    ):
        assert expected in notebook_text
    assert "ENERGIZE_OUTPUT = False" in notebook_text
    assert "RUN_CH3_OUTPUT_TEST = False" in notebook_text
    assert "RUN_TIMER_WAVEFORM_TEST = False" in notebook_text
    assert "RUN_FRONT_PANEL_LOCK_TEST = False" in notebook_text
