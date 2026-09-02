"""Centralized physical connection owner and JSON-RPC gateway server."""

from __future__ import annotations

import hmac
import ipaddress
import queue
import socketserver
import threading
import time
import traceback
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .._commit import UNKNOWN_COMMIT, get_commit
from .._constants import DEFAULT_GATEWAY_PORT
from ..exceptions import (
    GatewayAuthenticationError,
    GatewayInternalError,
    GatewayProtocolError,
    GatewayVersionMismatchError,
)
from ..execution import BatchResult, CommandBatch, ExecutionSettings, Executor
from .protocol import (
    MAX_BATCH_COMMANDS,
    MAX_MESSAGE_BYTES,
    decode_message,
    deserialize_command,
    encode_message,
    serialize_exception,
)


@dataclass
class _Work:
    batch: CommandBatch
    settings: ExecutionSettings
    done: threading.Event
    result: BatchResult | None = None
    error: BaseException | None = None
    remote_traceback: str = ""


class _PhysicalOwner:
    """Run every physical batch on one worker without interleaving."""

    def __init__(
        self,
        executor: Executor,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._executor = executor
        self._clock = clock
        self._sleeper = sleeper
        self._queue: queue.Queue[_Work | None] = queue.Queue()
        self._previous_interval: float | None = None
        self._last_completed_at: float | None = None
        self._thread = threading.Thread(target=self._run, name="spd3000-owner", daemon=True)
        self._thread.start()

    def execute(self, batch: CommandBatch, settings: ExecutionSettings) -> BatchResult:
        work = _Work(batch, settings, threading.Event())
        self._queue.put(work)
        work.done.wait()
        if work.error is not None:
            work.error.__dict__["gateway_remote_traceback"] = work.remote_traceback
            raise work.error
        if work.result is None:
            raise GatewayInternalError("Physical owner returned no result")
        return work.result

    def _run(self) -> None:
        while True:
            work = self._queue.get()
            if work is None:
                return
            try:
                if self._previous_interval is not None and self._last_completed_at is not None:
                    required = max(self._previous_interval, work.settings.min_command_interval)
                    remaining = required - (self._clock() - self._last_completed_at)
                    if remaining > 0:
                        self._sleeper(remaining)
                self._executor.settings = work.settings
                work.result = self._executor.execute(work.batch)
            except Exception as exc:
                work.error = exc
                work.remote_traceback = traceback.format_exc()
            finally:
                self._previous_interval = work.settings.min_command_interval
                self._last_completed_at = self._clock()
                work.done.set()

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=5)
        self._executor.close()


@dataclass(frozen=True)
class _Session:
    settings: ExecutionSettings


class _ThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class GatewayServer:
    """Thin SPD3000 command-execution gateway.

    The gateway owns no semantic methods. It accepts only raw write/query
    batches, serializes them through one physical owner, and relies on the same
    package revision for validation policy and canonical exceptions.
    """

    def __init__(
        self,
        executor: Executor,
        *,
        host: str = "127.0.0.1",
        port: int = DEFAULT_GATEWAY_PORT,
        token: str | None = None,
    ) -> None:
        if not _is_loopback(host) and not token:
            raise GatewayAuthenticationError("A token is required when binding outside loopback")
        self.host = host
        self.port = port
        self._token = token
        self._commit = get_commit()
        if self._commit == UNKNOWN_COMMIT:
            raise GatewayVersionMismatchError("Gateway Git commit is unavailable")
        self._owner = _PhysicalOwner(executor)
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                outer._handle(self)

        self._server = _ThreadingServer((host, port), Handler)
        self.port = int(self._server.server_address[1])

    def _handle(self, handler: socketserver.StreamRequestHandler) -> None:
        session: _Session | None = None
        while True:
            line = handler.rfile.readline(MAX_MESSAGE_BYTES + 2)
            if not line:
                return
            request_id: Any = None
            close_after = False
            try:
                if len(line) > MAX_MESSAGE_BYTES + 1 or not line.endswith(b"\n"):
                    raise GatewayProtocolError("Request exceeded limits or lacked LF")
                request = decode_message(line[:-1])
                request_id = request.get("id")
                method = request.get("method")
                params = request.get("params", {})
                if not isinstance(method, str) or not isinstance(params, dict):
                    raise GatewayProtocolError("Request method or params were malformed")
                if session is None:
                    if method != "handshake":
                        raise GatewayProtocolError("handshake must be the first request")
                    session = self._handshake(params)
                    result: Any = {"commit": self._commit}
                elif method == "execute":
                    result = self._execute(params, session)
                elif method == "ping":
                    result = {"ok": True}
                elif method == "close":
                    result = {"closed": True}
                    close_after = True
                else:
                    raise GatewayProtocolError(f"Unknown gateway method: {method!r}")
                response = {"jsonrpc": "2.0", "id": request_id, "result": result}
            except BaseException as exc:
                remote_traceback = getattr(exc, "gateway_remote_traceback", traceback.format_exc())
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": str(exc),
                        "data": serialize_exception(exc, remote_traceback),
                    },
                }
            handler.wfile.write(encode_message(response))
            if close_after:
                return

    def _handshake(self, params: dict[str, Any]) -> _Session:
        commit = params.get("commit")
        if commit == UNKNOWN_COMMIT or commit != self._commit:
            raise GatewayVersionMismatchError(
                f"Client commit {commit!r} does not match gateway commit {self._commit!r}"
            )
        supplied = params.get("token")
        if self._token is not None and (
            not isinstance(supplied, str) or not hmac.compare_digest(supplied, self._token)
        ):
            raise GatewayAuthenticationError("Invalid gateway token")
        settings = params.get("settings")
        if not isinstance(settings, dict):
            raise GatewayProtocolError("Handshake settings must be an object")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                execution_settings = ExecutionSettings(
                    min_command_interval=settings["min_command_interval"],
                    timeout=settings["timeout"],
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise GatewayProtocolError(f"Invalid execution settings: {exc}") from exc
        return _Session(execution_settings)

    def _execute(self, params: dict[str, Any], session: _Session) -> dict[str, Any]:
        commands = params.get("commands")
        if not isinstance(commands, list) or not commands:
            raise GatewayProtocolError("execute.commands must be a non-empty list")
        if len(commands) > MAX_BATCH_COMMANDS:
            raise GatewayProtocolError("Batch exceeds 256 commands")
        batch = CommandBatch([deserialize_command(command) for command in commands])
        try:
            result = self._owner.execute(batch, session.settings)
        except BaseException as exc:
            remote_traceback = getattr(exc, "gateway_remote_traceback", traceback.format_exc())
            exc.__dict__["gateway_remote_traceback"] = remote_traceback
            raise
        return {"values": list(result.values)}

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._server.shutdown()

    def close(self) -> None:
        self._server.server_close()
        self._owner.close()

    def __enter__(self) -> GatewayServer:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
