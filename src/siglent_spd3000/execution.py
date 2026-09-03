"""Command-level execution and physical timing enforcement."""

from __future__ import annotations

import math
import threading
import time
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, cast

from .exceptions import (
    SPD3000ConnectionError,
    SPD3000DeferredResultError,
    SPD3000Error,
    SPD3000ProtocolError,
    SPD3000TimeoutError,
    SPD3000TimingWarning,
    SPD3000ValidationError,
)

_T = TypeVar("_T")
_PENDING = object()


def _validated_command(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise SPD3000ValidationError("SCPI command must be a non-empty string")
    if "\n" in text or "\r" in text:
        raise SPD3000ValidationError("SCPI command must not contain a line terminator")
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise SPD3000ValidationError("SCPI command must contain ASCII characters only") from exc
    return text


@dataclass(frozen=True)
class Write:
    """A SCPI command that does not read a response."""

    text: str

    def __post_init__(self) -> None:
        _validated_command(self.text)


@dataclass(frozen=True)
class Query:
    """A SCPI command followed by a delayed response read."""

    text: str

    def __post_init__(self) -> None:
        _validated_command(self.text)


Command = Write | Query


@dataclass(frozen=True)
class CommandBatch:
    """A non-interleaved sequence of writes and queries."""

    commands: tuple[Command, ...]

    def __init__(self, commands: Sequence[Command]) -> None:
        if not commands:
            raise SPD3000ValidationError("A command batch must not be empty")
        object.__setattr__(self, "commands", tuple(commands))


@dataclass(frozen=True)
class BatchResult:
    """Results aligned with a command batch; writes produce ``None``."""

    values: tuple[str | None, ...]


class Deferred(Generic[_T]):
    """A typed query result populated when its collecting batch exits.

    Accessing :attr:`value` before successful batch completion raises
    :class:`SPD3000DeferredResultError`. Query or parsing failures are retained
    and re-raised if the result is inspected after the context exception was
    caught.
    """

    def __init__(self, command: str) -> None:
        self.command = command
        self._value: object = _PENDING
        self._error: BaseException | None = None

    @property
    def done(self) -> bool:
        """Whether the batch has resolved, failed, or cancelled this result."""

        return self._value is not _PENDING or self._error is not None

    @property
    def value(self) -> _T:
        """Return the resolved value or raise its pending/stored error."""

        if self._error is not None:
            raise self._error
        if self._value is _PENDING:
            raise SPD3000DeferredResultError(
                f"Query {self.command!r} is pending until its batch execution completes"
            )
        return cast(_T, self._value)

    def result(self) -> _T:
        """Method-form alias for :attr:`value`."""

        return self.value

    def _resolve(self, value: _T) -> None:
        self._value = value

    def _reject(self, error: BaseException) -> None:
        self._error = error

    def _cancel(self) -> None:
        self._error = SPD3000DeferredResultError(
            f"Query {self.command!r} was cancelled because its batch function did not complete"
        )

    def __repr__(self) -> str:
        if self._error is not None:
            state = f"failed={type(self._error).__name__}"
        elif self._value is _PENDING:
            state = "pending"
        else:
            state = f"value={self._value!r}"
        return f"Deferred(command={self.command!r}, {state})"


@dataclass(frozen=True, init=False)
class ExecutionSettings:
    """Timing and timeout settings shared by direct and gateway execution.

    Siglent recommends 10-100 ms between commands and between a query write
    and its read. The default is the conservative upper bound of 100 ms.
    Non-negative values outside that recommendation remain usable and emit
    :class:`SPD3000TimingWarning`; physically meaningless values are errors.
    """

    min_command_interval: float
    timeout: float

    def __init__(
        self,
        min_command_interval: float = 0.100,
        timeout: float = 5.0,
        *,
        _warning_stacklevel: int = 2,
    ) -> None:
        interval = _finite_number("min_command_interval", min_command_interval)
        timeout_value = _finite_number("timeout", timeout)
        if interval < 0:
            raise SPD3000ValidationError("min_command_interval must be non-negative")
        if timeout_value <= 0:
            raise SPD3000ValidationError("timeout must be greater than zero")
        if not 0.010 <= interval <= 0.100:
            warnings.warn(
                "min_command_interval is outside Siglent's recommended 10-100 ms range",
                SPD3000TimingWarning,
                stacklevel=_warning_stacklevel,
            )
        object.__setattr__(self, "min_command_interval", interval)
        object.__setattr__(self, "timeout", timeout_value)

    def __str__(self) -> str:
        """Return command timing and timeout values in user-facing units."""

        return "\n".join(
            (
                "SIGLENT SPD3000 Series command execution settings",
                f"- Minimum command interval: {self.min_command_interval * 1000:.15g} ms",
                f"- Timeout: {self.timeout:.15g} s",
            )
        )


def _finite_number(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SPD3000ValidationError(f"{name} must be a real number")
    result = float(value)
    if not math.isfinite(result):
        raise SPD3000ValidationError(f"{name} must be finite")
    return result


class Executor(Protocol):
    """Command-level boundary used by the semantic driver."""

    settings: ExecutionSettings

    def execute(self, batch: CommandBatch) -> BatchResult: ...

    def close(self) -> None: ...


class Transport(Protocol):
    """Byte-oriented physical transport owned by a direct executor."""

    def write(self, data: bytes) -> None: ...

    def read(self) -> bytes: ...

    def close(self) -> None: ...


class DirectExecutor:
    """Serialize a physical transport and enforce global command timing."""

    def __init__(
        self,
        transport: Transport,
        settings: ExecutionSettings | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.transport = transport
        self.settings = settings or ExecutionSettings()
        self._clock = clock
        self._sleeper = sleeper
        self._last_write_at: float | None = None
        self._lock = threading.RLock()
        self._closed = False

    def execute(self, batch: CommandBatch) -> BatchResult:
        with self._lock:
            if self._closed:
                raise SPD3000ConnectionError("Executor is closed")
            values: list[str | None] = []
            for command_index, command in enumerate(batch.commands):
                try:
                    self._wait_before_write()
                    self.transport.write(command.text.encode("ascii") + b"\n")
                    self._last_write_at = self._clock()
                    if isinstance(command, Query):
                        self._sleeper(self.settings.min_command_interval)
                        values.append(self._decode(self.transport.read()))
                    else:
                        values.append(None)
                except SPD3000Error as exc:
                    _annotate_execution_error(exc, command_index, command)
                    raise
                except TimeoutError as exc:
                    timeout_error = SPD3000TimeoutError(str(exc))
                    _annotate_execution_error(timeout_error, command_index, command)
                    raise timeout_error from exc
                except OSError as exc:
                    connection_error = SPD3000ConnectionError(str(exc))
                    _annotate_execution_error(connection_error, command_index, command)
                    raise connection_error from exc
            return BatchResult(tuple(values))

    def _wait_before_write(self) -> None:
        if self._last_write_at is None:
            return
        remaining = self.settings.min_command_interval - (self._clock() - self._last_write_at)
        if remaining > 0:
            self._sleeper(remaining)

    @staticmethod
    def _decode(data: bytes) -> str:
        try:
            return data.decode("ascii").rstrip("\r\n")
        except UnicodeDecodeError as exc:
            raise SPD3000ProtocolError("Instrument response was not ASCII") from exc

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self.transport.close()
                self._closed = True

    def __enter__(self) -> DirectExecutor:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _annotate_execution_error(exc: SPD3000Error, index: int, command: Command) -> None:
    """Attach allow-listed batch position metadata for higher-level error handling."""

    exc.__dict__["batch_command_index"] = index
    exc.__dict__["batch_command_kind"] = "query" if isinstance(command, Query) else "write"
    exc.__dict__["batch_command"] = command.text
