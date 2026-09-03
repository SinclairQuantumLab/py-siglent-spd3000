from __future__ import annotations

import socket
import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

import pytest

from siglent_spd3000 import (
    SPD3000,
    CommandBatch,
    ExecutionSettings,
    GatewayAuthenticationError,
    Query,
    SPD3000TimeoutError,
    Write,
)
from siglent_spd3000.execution import BatchResult
from siglent_spd3000.gateway import GatewayExecutor, GatewayServer
from siglent_spd3000.gateway.protocol import decode_message, encode_message
from siglent_spd3000.gateway.server import _PhysicalOwner


class PhysicalExecutor:
    def __init__(self, responses: dict[str, Iterable[str]] | None = None) -> None:
        self.settings = ExecutionSettings(0.01)
        self.responses = defaultdict(deque)
        for command, values in (responses or {}).items():
            self.responses[command].extend(values)
        self.batches: list[list[str]] = []
        self.closed = False
        self.error: Exception | None = None

    def execute(self, batch: CommandBatch) -> BatchResult:
        if self.error is not None:
            raise self.error
        self.batches.append([command.text for command in batch.commands])
        values: list[str | None] = []
        for command in batch.commands:
            if isinstance(command, Query):
                values.append(self.responses[command.text].popleft())
            else:
                values.append(None)
        return BatchResult(tuple(values))

    def close(self) -> None:
        self.closed = True


@contextmanager
def running_server(
    executor: PhysicalExecutor, *, token: str | None = None
) -> Iterator[GatewayServer]:
    server = GatewayServer(executor, port=0, token=token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.close()


def test_gateway_executes_one_persistent_session() -> None:
    physical = PhysicalExecutor({"Q?": ["answer"]})
    with (
        running_server(physical) as server,
        GatewayExecutor(
            "127.0.0.1", port=server.port, settings=ExecutionSettings(0.01)
        ) as executor,
    ):
        result = executor.execute(CommandBatch([Write("A"), Query("Q?")]))
        executor.ping()

    assert result.values == (None, "answer")
    assert physical.batches == [["A", "Q?"]]
    assert physical.closed is True


def test_semantic_verified_batch_reaches_gateway_as_one_batch() -> None:
    physical = PhysicalExecutor(
        {
            "*IDN?": ["Siglent Technologies,SPD3303X,SPD0001,1.0"],
            "CH1:VOLT?": ["5"],
            "CH1:CURR?": ["0.5"],
        }
    )
    with (
        running_server(physical) as server,
        SPD3000(
            GatewayExecutor(
                "127.0.0.1", port=server.port, settings=ExecutionSettings(0.01)
            )
        ) as psu,
        psu.batch(),
        psu.verify_writes(),
    ):
        psu.ch1.voltage = 5.0
        psu.ch1.current = 0.5

    assert physical.batches == [
        ["*IDN?"],
        ["CH1:VOLT 5", "CH1:VOLT?", "CH1:CURR 0.5", "CH1:CURR?"],
    ]


def test_gateway_reconstructs_southbound_exception_and_traceback() -> None:
    physical = PhysicalExecutor()
    physical.error = SPD3000TimeoutError("device timed out")
    physical.error.batch_command_index = 1
    physical.error.batch_command_kind = "query"
    physical.error.batch_command = "VERIFY?"
    with running_server(physical) as server:
        executor = GatewayExecutor("127.0.0.1", port=server.port, settings=ExecutionSettings(0.01))
        try:
            with pytest.raises(SPD3000TimeoutError, match="device timed out") as caught:
                executor.execute(CommandBatch([Query("Q?")]))
            assert "test_gateway.py" in caught.value.remote_traceback
            assert caught.value.batch_command_index == 1
            assert caught.value.batch_command_kind == "query"
            assert caught.value.batch_command == "VERIFY?"
        finally:
            executor.close()


def test_gateway_token_authentication() -> None:
    physical = PhysicalExecutor()
    with (
        running_server(physical, token="correct") as server,
        pytest.raises(GatewayAuthenticationError),
    ):
        GatewayExecutor(
            "127.0.0.1",
            port=server.port,
            token="wrong",
            settings=ExecutionSettings(0.01),
        )


def test_gateway_rejects_non_loopback_without_token() -> None:
    physical = PhysicalExecutor()
    with pytest.raises(GatewayAuthenticationError):
        GatewayServer(physical, host="0.0.0.0", port=0)


def test_gateway_rejects_different_commit() -> None:
    physical = PhysicalExecutor()
    with (
        running_server(physical) as server,
        socket.create_connection(("127.0.0.1", server.port), timeout=2) as connection,
    ):
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "handshake",
            "params": {
                "commit": "0" * 40,
                "token": None,
                "settings": {"min_command_interval": 0.01, "timeout": 1.0},
            },
        }
        connection.sendall(encode_message(request))
        response = decode_message(connection.makefile("rb").readline().rstrip(b"\n"))
    assert response["error"]["data"]["exception_type"] == "GatewayVersionMismatchError"


def test_concurrent_clients_cannot_interleave_batches() -> None:
    class SlowPhysical(PhysicalExecutor):
        def execute(self, batch: CommandBatch) -> BatchResult:
            self.batches.append([])
            active = self.batches[-1]
            for command in batch.commands:
                active.append(command.text)
                time.sleep(0.005)
            return BatchResult(tuple(None for _ in batch.commands))

    physical = SlowPhysical()
    with running_server(physical) as server:
        first = GatewayExecutor("127.0.0.1", port=server.port, settings=ExecutionSettings(0.01))
        second = GatewayExecutor("127.0.0.1", port=server.port, settings=ExecutionSettings(0.01))
        barrier = threading.Barrier(2)

        def run(executor: GatewayExecutor, prefix: str) -> None:
            barrier.wait()
            executor.execute(CommandBatch([Write(f"{prefix}1"), Write(f"{prefix}2")]))

        threads = [
            threading.Thread(target=run, args=(first, "A")),
            threading.Thread(target=run, args=(second, "B")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        first.close()
        second.close()

    assert sorted(physical.batches) == [["A1", "A2"], ["B1", "B2"]]


def test_physical_owner_uses_larger_interval_at_session_transition() -> None:
    class Clock:
        def __init__(self) -> None:
            self.now = 0.0
            self.sleeps: list[float] = []

        def monotonic(self) -> float:
            return self.now

        def sleep(self, delay: float) -> None:
            self.sleeps.append(delay)
            self.now += delay

    clock = Clock()
    physical = PhysicalExecutor()
    owner = _PhysicalOwner(physical, clock=clock.monotonic, sleeper=clock.sleep)
    try:
        owner.execute(CommandBatch([Write("A")]), ExecutionSettings(0.1))
        owner.execute(CommandBatch([Write("B")]), ExecutionSettings(0.01))
        owner.execute(CommandBatch([Write("C")]), ExecutionSettings(0.05))
    finally:
        owner.close()

    assert clock.sleeps == pytest.approx([0.1, 0.05])
