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
