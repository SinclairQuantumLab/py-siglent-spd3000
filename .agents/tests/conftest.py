from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable

from siglent_spd3000.execution import (
    BatchResult,
    CommandBatch,
    ExecutionSettings,
    Query,
)


class FakeExecutor:
    def __init__(self, responses: dict[str, Iterable[str]] | None = None) -> None:
        self.settings = ExecutionSettings()
        self.responses = defaultdict(deque)
        for command, values in (responses or {}).items():
            self.responses[command].extend(values)
        self.commands: list[str] = []
        self.batches: list[list[str]] = []
        self.closed = False

    def execute(self, batch: CommandBatch) -> BatchResult:
        self.batches.append([command.text for command in batch.commands])
        values: list[str | None] = []
        for command in batch.commands:
            self.commands.append(command.text)
            if isinstance(command, Query):
                if not self.responses[command.text]:
                    raise AssertionError(f"No fake response for {command.text!r}")
                values.append(self.responses[command.text].popleft())
            else:
                values.append(None)
        return BatchResult(tuple(values))

    def close(self) -> None:
        self.closed = True


def responses_for(model: str, **extra: list[str]) -> dict[str, Iterable[str]]:
    responses: dict[str, Iterable[str]] = {
        "*IDN?": [f"Siglent Technologies,{model},SPD0001,1.0"],
    }
    responses.update(extra)
    return responses
