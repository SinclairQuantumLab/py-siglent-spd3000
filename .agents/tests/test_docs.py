from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

# The exact vendor filenames plus SHA-256 values are intentionally indivisible.
# ruff: noqa: E501

EXPECTED_HASHES = {
    "Instrument Socket and Telnet Port Information.pdf": "d91577c37ab6e8e977f02b92b12320da6d4d64bc421e7aa2a8efb82060d14aba",
    "Programming Example_ Controlling an SPD power supply via Sockets over LAN.pdf": "a257a2939eaef274235ab226025182e0b947667a8e786904a082736cb3222b75",
    "Programming Example_ List connected VISA compatible resources using PyVISA.pdf": "bb8cb64f962fd6b889817b68766ca2923c1ad0bd4d2e4fa05d8862b3d7ef1265",
    "Programming Example_ Using VXI11 (LXI) and Python for LAN control without sockets.pdf": "bbc62fbd26f688779707079d3d20f9cfac54a2f7af89a13f46448a5af6af3c4a",
    "SPD Local Front Panel Lock Out SCPI commands.pdf": "e9a6c72ac30ad93783400000fa4fa3202f3e23fc27e85ffc49487fb1f8622465",
    "SPD programming tips.pdf": "29637ed3abdec74b8652f6cfb3bbe1dd631d2fbb031f29a42a827466346d9e15",
    "SPD3000X-Series-Service-Manual_E01B.pdf": "7d1ec68217b8c71f6801a94a52834426ae1affdd0ce67aca7c00ac4ef88fae5e",
    "SPD3303C_Datasheet_E02A.pdf": "a7533dd853c63443e9e7aafbd0a5b75fc109786216f115a1dcd13d6daa418f8e",
    "SPD3303C_QuickStart_E02A.pdf": "38d05d978f661fc0d01c508528bcb8833524400b61881e7acbb9aee3bd72c667",
    "SPD3303C-Service-Manual_E01B.pdf": "5e4c968199edd468576b18ef348b63e719f6b71a77fbfde8fa16a12ab32ee420",
    "SPD3303X_DataSheet_E03A.pdf": "5817f9b13935047d451f355fdc1c18b2b7e3a319b8bbdff0ffd91013cc402cee",
    "SPD3303X_QuickStart_E02A.pdf": "71ba7d35739e131c8093b3904dd3aeb34a5ecfb8d16ce1e3b4d95785727cf6db",
}


def test_official_reference_hashes_and_index() -> None:
    docs = Path(__file__).resolve().parents[2] / "docs"
    if not any(docs.glob("*.pdf")):
        pytest.skip("vendor PDF archive is intentionally repository-only")
    index = (docs / "README.md").read_text(encoding="utf-8")
    assert {path.name for path in docs.glob("*.pdf")} == set(EXPECTED_HASHES)
    for filename, expected in EXPECTED_HASHES.items():
        actual = hashlib.sha256((docs / filename).read_bytes()).hexdigest()
        assert actual == expected
        assert expected in index


def test_output_exception_is_documented_for_users() -> None:
    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text(encoding="utf-8")
    docs = (root / "docs" / "README.md").read_text(encoding="utf-8")
    assert "Intentional `OUTPut` convenience exception" in readme
    assert "API interpretation note: `OUTPut`" in docs
    assert "The mechanically derived name is always the canonical implementation" in readme
    assert "API interpretation note: canonical and friendly names" in docs
    assert "`psu.locked`" in readme


def test_lock_query_capability_is_documented_as_a_runtime_check() -> None:
    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text(encoding="utf-8")
    docs = (root / "docs" / "README.md").read_text(encoding="utf-8")
    checklist = (root / ".agents" / "HARDWARE_TESTS.md").read_text(encoding="utf-8")

    assert "model-level vendor documentation" in readme
    assert "does not define its response token" in docs
    assert "1.01.01.03.11R1" in checklist


def test_basic_use_shows_scpi_for_each_operation() -> None:
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")
    assert "import siglent_spd3000 as spd" in readme
    assert "from siglent_spd3000 import SPD3000" not in readme
    assert "with spd.SPD3000.connect(" in readme
    expected = (
        'SCPI: "*IDN?"',
        'SCPI: "CH1:VOLTage 5.0"',
        'SCPI: "CH1:CURRent 0.5"',
        'SCPI: "CH1:VOLTage?"',
        'SCPI: "CH1:CURRent?"',
        'SCPI: "MEASure:VOLTage? CH1"',
        'SCPI: "MEASure:CURRent? CH1"',
        'SCPI: "OUTPut CH1,ON"',
        'SCPI: "SYSTem:STATus?"',
    )
    assert all(command in readme for command in expected)


def test_hardware_checklist_is_linked_and_has_stable_unique_ids() -> None:
    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text(encoding="utf-8")
    checklist = (root / ".agents" / "HARDWARE_TESTS.md").read_text(encoding="utf-8")
    assert ".agents/HARDWARE_TESTS.md" in readme
    identifiers = re.findall(r"`([A-Z0-9]+-[0-9]+)`:", checklist)
    assert identifiers
    assert len(identifiers) == len(set(identifiers))
    prefixes = {identifier.split("-", 1)[0] for identifier in identifiers}
    assert prefixes == {
        "CH3",
        "CON",
        "END",
        "FAIL",
        "GATE",
        "LOCK",
        "MEM",
        "NET",
        "OUT",
        "RAW",
        "READ",
        "SET",
        "TIMER",
        "TRACK",
        "TRANS",
        "WAVE",
    }


def test_gateway_quick_guide_covers_recommendation_installation_and_use() -> None:
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")
    assert "[gateway server](#gateway-server) is the recommended way" in readme
    assert "git clone <REPOSITORY_URL>" in readme
    assert "git rev-parse HEAD" in readme
    assert "> **NOTE:** `uv` is optional" in readme
    assert "uv sync --extra gateway --no-dev" in readme
    assert "gateway-settings.toml.template" in readme
    assert "gateway-auth.toml.template" in readme
    assert "spd3000 gateway init" in readme
    assert "### Start the gateway" in readme
    assert "### Connect a client" in readme
    assert "### Ports and firewall" in readme
    assert "<GATEWAY_HOST>" in readme
    assert "`localhost` means the gateway accepts clients only from that same computer" in readme
    assert "spd3000 gateway serve" in readme
    assert "--gateway-auth gateway-auth.toml" in readme
    assert 'token = "replace-this-example-with-the-generated-private-token"' in readme
    assert "any non-empty custom string is valid" in readme
    assert "only an example and is not required" in readme
    assert "TCP port 8765" in readme
    assert "TCP 5025" in readme
    assert "connection=spd.ConnectionType.GATEWAY" in readme
    assert "A remotely accessible gateway uses token authentication" in readme


def test_readme_has_table_of_contents_for_major_sections() -> None:
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")
    contents = readme.split("## Installation", 1)[0]
    for anchor in (
        "#installation",
        "#basic-use",
        "#connections",
        "#jupyter-hardware-test-notebook",
        "#from-a-manual-scpi-command-to-python",
        "#intentional-output-convenience-exception",
        "#scpi-shaped-api",
        "#timing",
        "#gateway-server",
        "#model-differences",
        "#development",
    ):
        assert f"]({anchor})" in contents


def test_jupyter_hardware_test_guide_covers_setup_inputs_and_confirmations() -> None:
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")
    guide = readme.split("## Jupyter hardware test notebook", 1)[1].split(
        "## From a manual SCPI command to Python", 1
    )[0]

    for required in (
        "test_spd300.ipynb.template",
        "Copy-Item test_spd300.ipynb.template test_spd300.ipynb",
        "cp -n test_spd300.ipynb.template test_spd300.ipynb",
        "python -m pip install jupyterlab",
        "uv run --with jupyterlab jupyter lab test_spd300.ipynb",
        "spd.ConnectionType.<TYPE>",
        '"<IDENTIFIER>"',
        'visa_backend="@py"',
        'token=spd.load_gateway_auth("gateway-auth.toml")',
        "APPLY CH1",
        "ENERGIZE CH3",
        "OVERWRITE TIMER CH1 5",
        "LOCK FRONT PANEL",
        "READ_ONE_ERROR_QUEUE_ENTRY = True",
        "ENERGIZE_OUTPUT = False",
        ".agents/HARDWARE_TESTS.md",
    ):
        assert required in guide


def test_connection_guide_covers_every_public_connection_type() -> None:
    readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")
    connections = readme.split("## Connections", 1)[1].split(
        "## From a manual SCPI command to Python", 1
    )[0]
    for connection in ("SOCKET", "VXI11", "VISA", "GATEWAY"):
        assert f"spd.ConnectionType.{connection}" in connections
    assert "TCP 5025" in connections
    assert "port 8765" in connections
    assert "USB0::0x0483::0x7540::SPD3XGB4150080::INSTR" in connections
    assert "TCPIP0::192.168.55.122::inst0::INSTR" in connections
    assert "format examples from SIGLENT rather than identifiers for your instrument" in connections
    assert "list_resources()" in connections
    assert '`"localhost"` when the client and gateway run on the same computer' in connections
    assert '`"192.168.50.20:3333"`' in connections
