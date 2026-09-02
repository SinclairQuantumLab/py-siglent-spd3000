"""Persistent gateway executor used by the ordinary semantic driver."""

from __future__ import annotations

import socket
import threading
from contextlib import suppress
from typing import Any

from .._commit import UNKNOWN_COMMIT, get_commit
from .._constants import DEFAULT_GATEWAY_PORT
from ..exceptions import GatewayConnectionError, GatewayProtocolError
from ..execution import BatchResult, CommandBatch, ExecutionSettings
from .protocol import (
    MAX_MESSAGE_BYTES,
    decode_message,
    encode_message,
    reconstruct_exception,
    serialize_command,
)


class GatewayExecutor:
    """Execute command batches through one persistent gateway session."""

    def __init__(
        self,
        host: str,
        *,
        port: int = DEFAULT_GATEWAY_PORT,
        token: str | None = None,
        settings: ExecutionSettings | None = None,
    ) -> None:
        self.settings = settings or ExecutionSettings()
        self.host = host
        self.port = port
        self._lock = threading.RLock()
        self._next_id = 1
        self._closed = False
        try:
            self._socket = socket.create_connection((host, port), timeout=self.settings.timeout)
            self._socket.settimeout(self.settings.timeout)
            self._stream = self._socket.makefile("rwb", buffering=0)
        except OSError as exc:
            raise GatewayConnectionError(
                f"Could not connect to gateway {host}:{port}: {exc}"
            ) from exc
        commit = get_commit()
        if commit == UNKNOWN_COMMIT:
            self.close(send_request=False)
            raise GatewayProtocolError("Client Git commit is unavailable")
        try:
            self._request(
                "handshake",
                {
                    "commit": commit,
                    "token": token,
                    "settings": {
                        "min_command_interval": self.settings.min_command_interval,
                        "timeout": self.settings.timeout,
                    },
                },
            )
        except BaseException:
            self.close(send_request=False)
            raise

    def execute(self, batch: CommandBatch) -> BatchResult:
        result = self._request(
            "execute", {"commands": [serialize_command(command) for command in batch.commands]}
        )
        if not isinstance(result, dict) or not isinstance(result.get("values"), list):
            raise GatewayProtocolError("Gateway execute result was malformed")
        values = result["values"]
        if len(values) != len(batch.commands) or not all(
            value is None or isinstance(value, str) for value in values
        ):
            raise GatewayProtocolError("Gateway execute results did not match the batch")
        return BatchResult(tuple(values))

    def ping(self) -> None:
        self._request("ping", {})

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        with self._lock:
            if self._closed:
                raise GatewayConnectionError("Gateway executor is closed")
            request_id = self._next_id
            self._next_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
            try:
                self._stream.write(encode_message(request))
                line = self._stream.readline(MAX_MESSAGE_BYTES + 2)
            except (OSError, ValueError) as exc:
                raise GatewayConnectionError(f"Gateway request failed: {exc}") from exc
            if not line:
                raise GatewayConnectionError("Gateway closed the connection")
            if len(line) > MAX_MESSAGE_BYTES + 1 or not line.endswith(b"\n"):
                raise GatewayProtocolError("Gateway response exceeded limits or lacked LF")
            response = decode_message(line[:-1])
            if response.get("id") != request_id:
                raise GatewayProtocolError("Gateway response ID did not match the request")
            if "error" in response:
                error = response["error"]
                data = error.get("data") if isinstance(error, dict) else None
                raise reconstruct_exception(data)
            if "result" not in response:
                raise GatewayProtocolError("Gateway response had no result or error")
            return response["result"]

    def close(self, *, send_request: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            if send_request:
                with suppress(Exception):
                    self._request("close", {})
            self._closed = True
            try:
                self._stream.close()
            finally:
                self._socket.close()

    def __enter__(self) -> GatewayExecutor:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
