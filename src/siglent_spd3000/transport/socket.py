"""Raw TCP transport for SPD3303X/X-E port 5025."""

from __future__ import annotations

import socket

from .._constants import DEFAULT_SCPI_PORT
from ..exceptions import SPD3000ConnectionError, SPD3000ProtocolError, SPD3000TimeoutError


class SocketTransport:
    """A buffered TCP byte stream with LF-delimited reads."""

    def __init__(
        self,
        host: str,
        *,
        port: int = DEFAULT_SCPI_PORT,
        timeout: float = 5.0,
        max_response_bytes: int = 1024 * 1024,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.max_response_bytes = max_response_bytes
        self._buffer = bytearray()
        self._closed = False
        try:
            self._socket = socket.create_connection((host, port), timeout=timeout)
            self._socket.settimeout(timeout)
        except TimeoutError as exc:
            raise SPD3000TimeoutError(f"Timed out connecting to {host}:{port}") from exc
        except OSError as exc:
            raise SPD3000ConnectionError(f"Could not connect to {host}:{port}: {exc}") from exc

    def write(self, data: bytes) -> None:
        self._ensure_open()
        try:
            self._socket.sendall(data)
        except TimeoutError as exc:
            raise SPD3000TimeoutError("Timed out writing to the instrument") from exc
        except OSError as exc:
            raise SPD3000ConnectionError(f"Socket write failed: {exc}") from exc

    def read(self) -> bytes:
        self._ensure_open()
        while True:
            marker = self._buffer.find(b"\n")
            if marker >= 0:
                result = bytes(self._buffer[: marker + 1])
                del self._buffer[: marker + 1]
                return result
            if len(self._buffer) >= self.max_response_bytes:
                raise SPD3000ProtocolError("Instrument response exceeded the configured limit")
            try:
                chunk = self._socket.recv(min(4096, self.max_response_bytes - len(self._buffer)))
            except TimeoutError as exc:
                if self._buffer:
                    detail = (
                        f" after receiving {len(self._buffer)} byte(s) without LF termination"
                    )
                else:
                    detail = " without receiving any bytes"
                raise SPD3000TimeoutError(
                    f"Timed out reading from the instrument{detail}"
                ) from exc
            except OSError as exc:
                raise SPD3000ConnectionError(f"Socket read failed: {exc}") from exc
            if not chunk:
                raise SPD3000ConnectionError("Instrument closed the socket before LF termination")
            self._buffer.extend(chunk)

    def _ensure_open(self) -> None:
        if self._closed:
            raise SPD3000ConnectionError("Socket transport is closed")

    def close(self) -> None:
        if not self._closed:
            try:
                self._socket.close()
            finally:
                self._closed = True

    def __enter__(self) -> SocketTransport:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
