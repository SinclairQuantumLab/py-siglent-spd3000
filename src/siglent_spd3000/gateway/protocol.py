"""Small explicit JSON-RPC representation for gateway execution."""

from __future__ import annotations

import json
from typing import Any

from ..exceptions import (
    CANONICAL_EXCEPTION_TYPES,
    GatewayAuthenticationError,
    GatewayError,
    GatewayInternalError,
    GatewayProtocolError,
    GatewayVersionMismatchError,
    SPD3000Error,
)
from ..execution import Command, Query, Write

JSONRPC_VERSION = "2.0"
MAX_MESSAGE_BYTES = 1024 * 1024
MAX_BATCH_COMMANDS = 256
MAX_COMMAND_BYTES = 4096
HEARTBEAT_METHOD = "heartbeat"
HEARTBEAT_STATES = frozenset(("queued", "executing"))


def encode_message(message: dict[str, Any]) -> bytes:
    """Serialize one newline-delimited JSON-RPC message."""

    try:
        encoded = json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GatewayProtocolError(f"Message is not JSON serializable: {exc}") from exc
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise GatewayProtocolError("Gateway message exceeds 1 MiB")
    return encoded + b"\n"


def decode_message(data: bytes) -> dict[str, Any]:
    """Parse and minimally validate one JSON-RPC object."""

    if len(data) > MAX_MESSAGE_BYTES:
        raise GatewayProtocolError("Gateway message exceeds 1 MiB")
    try:
        message = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GatewayProtocolError(f"Malformed JSON-RPC message: {exc}") from exc
    if not isinstance(message, dict) or message.get("jsonrpc") != JSONRPC_VERSION:
        raise GatewayProtocolError("Expected a JSON-RPC 2.0 object")
    return message


def heartbeat_notification(request_id: object, state: str) -> dict[str, Any]:
    """Build a JSON-RPC notification for one pending execute request."""

    if state not in HEARTBEAT_STATES:
        raise GatewayProtocolError(f"Unknown gateway heartbeat state: {state!r}")
    return {
        "jsonrpc": JSONRPC_VERSION,
        "method": HEARTBEAT_METHOD,
        "params": {"request_id": request_id, "state": state},
    }


def parse_heartbeat_notification(
    message: dict[str, Any], expected_request_id: object
) -> str | None:
    """Return a validated heartbeat state, or ``None`` for a final response."""

    if message.get("method") != HEARTBEAT_METHOD:
        return None
    if "id" in message:
        raise GatewayProtocolError("Gateway heartbeat must be a JSON-RPC notification")
    params = message.get("params")
    if not isinstance(params, dict):
        raise GatewayProtocolError("Gateway heartbeat params must be an object")
    if params.get("request_id") != expected_request_id:
        raise GatewayProtocolError("Gateway heartbeat request ID did not match the request")
    state = params.get("state")
    if not isinstance(state, str) or state not in HEARTBEAT_STATES:
        raise GatewayProtocolError("Gateway heartbeat state was invalid")
    return state


def serialize_command(command: Command) -> dict[str, str]:
    kind = "query" if isinstance(command, Query) else "write"
    if len(command.text.encode("ascii")) > MAX_COMMAND_BYTES:
        raise GatewayProtocolError("SCPI command exceeds 4096 bytes")
    return {"kind": kind, "text": command.text}


def deserialize_command(payload: Any) -> Command:
    if not isinstance(payload, dict):
        raise GatewayProtocolError("Command must be an object")
    kind = payload.get("kind")
    text = payload.get("text")
    if not isinstance(text, str):
        raise GatewayProtocolError("Command text must be a string")
    if len(text.encode("utf-8")) > MAX_COMMAND_BYTES:
        raise GatewayProtocolError("SCPI command exceeds 4096 bytes")
    if kind == "write":
        return Write(text)
    if kind == "query":
        return Query(text)
    raise GatewayProtocolError("Command kind must be 'write' or 'query'")


def serialize_exception(exc: BaseException, remote_traceback: str) -> dict[str, Any]:
    """Serialize only known southbound exceptions and safe gateway errors."""

    if isinstance(exc, SPD3000Error):
        payload: dict[str, Any] = {
            "kind": "southbound",
            "exception_type": type(exc).__name__,
            "args": [_json_safe(arg) for arg in exc.args],
            "remote_traceback": remote_traceback,
        }
        for name in ("batch_command_index", "batch_command_kind", "batch_command"):
            value = getattr(exc, name, None)
            if isinstance(value, (int, str)) and not isinstance(value, bool):
                payload[name] = value
        return payload
    gateway_type = type(exc).__name__ if isinstance(exc, GatewayError) else "GatewayInternalError"
    return {
        "kind": "gateway",
        "exception_type": gateway_type,
        "message": str(exc),
        "remote_traceback": remote_traceback,
    }


def reconstruct_exception(data: Any) -> BaseException:
    """Rebuild an allow-listed exception without deserializing Python objects."""

    if not isinstance(data, dict):
        return GatewayProtocolError("Gateway error lacked structured data")
    remote_traceback = data.get("remote_traceback")
    if data.get("kind") == "southbound":
        exception_type = data.get("exception_type")
        southbound_cls = (
            CANONICAL_EXCEPTION_TYPES.get(exception_type)
            if isinstance(exception_type, str)
            else None
        )
        args = data.get("args", [])
        if southbound_cls is None or not isinstance(args, list):
            exc: BaseException = GatewayProtocolError("Unknown southbound exception type")
        else:
            exc = southbound_cls(*args)
            batch_command_index = data.get("batch_command_index")
            batch_command_kind = data.get("batch_command_kind")
            batch_command = data.get("batch_command")
            if isinstance(batch_command_index, int) and not isinstance(batch_command_index, bool):
                exc.__dict__["batch_command_index"] = batch_command_index
            if batch_command_kind in {"write", "query"}:
                exc.__dict__["batch_command_kind"] = batch_command_kind
            if isinstance(batch_command, str):
                exc.__dict__["batch_command"] = batch_command
    else:
        gateway_classes: dict[str, type[GatewayError]] = {
            "GatewayAuthenticationError": GatewayAuthenticationError,
            "GatewayVersionMismatchError": GatewayVersionMismatchError,
            "GatewayProtocolError": GatewayProtocolError,
            "GatewayInternalError": GatewayInternalError,
        }
        gateway_cls = gateway_classes.get(str(data.get("exception_type")), GatewayInternalError)
        exc = gateway_cls(str(data.get("message", "Gateway request failed")))
    if isinstance(remote_traceback, str) and remote_traceback:
        exc.__dict__["remote_traceback"] = remote_traceback
        add_note = getattr(exc, "add_note", None)
        if callable(add_note):
            add_note(f"Remote traceback:\n{remote_traceback}")
    return exc


def _json_safe(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)
