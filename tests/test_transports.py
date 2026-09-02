from __future__ import annotations

from typing import Any

import pytest

from siglent_spd3000 import SPD3000ConnectionError, SPD3000TimeoutError
from siglent_spd3000.transport import SocketTransport, VisaTransport, VXI11Transport


class FakeSocket:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.writes: list[bytes] = []
        self.timeout: float | None = None
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def sendall(self, data: bytes) -> None:
        self.writes.append(data)

    def recv(self, _size: int) -> bytes:
        return self.chunks.pop(0)

    def close(self) -> None:
        self.closed = True


def test_socket_transport_buffers_partial_and_multiple_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = FakeSocket([b"fir", b"st\nsecond\n"])
    monkeypatch.setattr("socket.create_connection", lambda *_args, **_kwargs: raw)
    transport = SocketTransport("instrument", timeout=2)

    transport.write(b"*IDN?\n")
    assert transport.read() == b"first\n"
    assert transport.read() == b"second\n"
    assert raw.writes == [b"*IDN?\n"]
    assert raw.timeout == 2


def test_socket_transport_reports_early_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = FakeSocket([b""])
    monkeypatch.setattr("socket.create_connection", lambda *_args, **_kwargs: raw)
    transport = SocketTransport("instrument")

    with pytest.raises(SPD3000ConnectionError, match="before LF"):
        transport.read()


class FakeVisaResource:
    def __init__(self) -> None:
        self.timeout = 0
        self.write_termination: str | None = "unused"
        self.read_termination: str | None = None
        self.writes: list[bytes] = []
        self.closed = False

    def write_raw(self, data: bytes) -> None:
        self.writes.append(data)

    def read_raw(self) -> bytes:
        return b"visa\n"

    def close(self) -> None:
        self.closed = True


class FakeVisaManager:
    def __init__(self, resource: FakeVisaResource) -> None:
        self.resource = resource
        self.opened: str | None = None
        self.closed = False

    def open_resource(self, name: str) -> FakeVisaResource:
        self.opened = name
        return self.resource

    def close(self) -> None:
        self.closed = True


def test_visa_transport_uses_raw_io_and_does_not_close_injected_manager() -> None:
    resource = FakeVisaResource()
    manager = FakeVisaManager(resource)
    transport = VisaTransport("USB::TEST", timeout=1.5, resource_manager=manager)

    transport.write(b"Q?\n")
    assert transport.read() == b"visa\n"
    assert resource.timeout == 1500
    assert resource.write_termination is None
    assert resource.read_termination == "\n"
    transport.close()
    assert resource.closed is True
    assert manager.closed is False


class FakeVXI11Instrument:
    def __init__(self, response: bytes | str = b"vxi\n") -> None:
        self.timeout = 0
        self.response = response
        self.writes: list[bytes] = []
        self.closed = False

    def write_raw(self, data: bytes) -> None:
        self.writes.append(data)

    def read_raw(self) -> bytes | str:
        return self.response

    def close(self) -> None:
        self.closed = True


def test_vxi11_transport_uses_separate_raw_write_and_read() -> None:
    instrument = FakeVXI11Instrument("vxi\n")
    transport = VXI11Transport("instrument", timeout=2.0, instrument=instrument)

    transport.write(b"Q?\n")
    assert transport.read() == b"vxi\n"
    assert instrument.writes == [b"Q?\n"]
    assert instrument.timeout == 2000


@pytest.mark.parametrize("transport_class", [VisaTransport, VXI11Transport])
def test_optional_transport_timeout_normalization(transport_class: type[Any]) -> None:
    class TimeoutBackend(FakeVXI11Instrument):
        def read_raw(self) -> bytes:
            raise RuntimeError("backend timeout")

    backend = TimeoutBackend()
    if transport_class is VisaTransport:
        transport: Any = VisaTransport(
            "USB::TEST",
            resource_manager=FakeVisaManager(backend),  # type: ignore[arg-type]
        )
    else:
        transport = VXI11Transport("instrument", instrument=backend)
    with pytest.raises(SPD3000TimeoutError):
        transport.read()
