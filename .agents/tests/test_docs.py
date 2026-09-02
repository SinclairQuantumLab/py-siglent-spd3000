from __future__ import annotations

import hashlib
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
    docs = Path(__file__).resolve().parents[1] / "docs"
    if not any(docs.glob("*.pdf")):
        pytest.skip("vendor PDF archive is intentionally repository-only")
    index = (docs / "README.md").read_text(encoding="utf-8")
    assert {path.name for path in docs.glob("*.pdf")} == set(EXPECTED_HASHES)
    for filename, expected in EXPECTED_HASHES.items():
        actual = hashlib.sha256((docs / filename).read_bytes()).hexdigest()
        assert actual == expected
        assert expected in index


def test_output_exception_is_documented_for_users() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    docs = (root / "docs" / "README.md").read_text(encoding="utf-8")
    assert "Intentional `OUTPut` convenience exception" in readme
    assert "API interpretation note: `OUTPut`" in docs


def test_basic_use_shows_scpi_for_each_operation() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    expected = (
        "SCPI: *IDN?",
        "SCPI: CH1:VOLTage 5.0",
        "SCPI: CH1:CURRent 0.5",
        "SCPI: CH1:VOLTage?",
        "SCPI: CH1:CURRent?",
        "SCPI: MEASure:VOLTage? CH1",
        "SCPI: MEASure:CURRent? CH1",
        "SCPI: OUTPut CH1,ON",
        "SCPI: SYSTem:STATus?",
    )
    assert all(command in readme for command in expected)
