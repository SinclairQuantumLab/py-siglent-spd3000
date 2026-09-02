from __future__ import annotations

import math
from pathlib import Path

import pytest

from siglent_spd3000 import (
    CommandBatch,
    DirectExecutor,
    ExecutionSettings,
    Query,
    SPD3000TimingWarning,
    SPD3000ValidationError,
    Write,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


class FakeTransport:
    def __init__(self, responses: list[bytes] | None = None) -> None:
        self.writes: list[bytes] = []
        self.responses = list(responses or [])
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    def read(self) -> bytes:
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


def test_default_interval_and_outside_range_warning_points_to_caller() -> None:
    assert ExecutionSettings().min_command_interval == 0.1

    with pytest.warns(SPD3000TimingWarning) as caught:
        settings = ExecutionSettings(0.0)
    assert settings.min_command_interval == 0.0
    assert Path(caught[0].filename).resolve() == Path(__file__).resolve()

    with pytest.warns(SPD3000TimingWarning):
        ExecutionSettings(0.101)


@pytest.mark.parametrize("value", [-1.0, math.nan, math.inf, -math.inf])
def test_invalid_interval_is_an_error(value: float) -> None:
    with pytest.raises(SPD3000ValidationError):
        ExecutionSettings(value)


def test_direct_executor_adds_lf_and_separates_query_write_and_read() -> None:
    clock = FakeClock()
    transport = FakeTransport([b"answer\n"])
    executor = DirectExecutor(
        transport,
        ExecutionSettings(0.05),
        clock=clock.monotonic,
        sleeper=clock.sleep,
    )

    result = executor.execute(CommandBatch([Write("A"), Query("B?")]))

    assert transport.writes == [b"A\n", b"B?\n"]
    assert result.values == (None, "answer")
    assert clock.sleeps == [0.05, 0.05]


def test_command_rejects_embedded_terminator_and_non_ascii() -> None:
    with pytest.raises(SPD3000ValidationError):
        Write("OUTP CH1,ON\n")
    with pytest.raises(SPD3000ValidationError):
        Query("측정?")


def test_executor_close_is_idempotent() -> None:
    transport = FakeTransport()
    executor = DirectExecutor(transport)
    executor.close()
    executor.close()
    assert transport.closed is True
