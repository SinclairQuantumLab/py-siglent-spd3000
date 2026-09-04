"""PyVISA transport for USBTMC or VISA-managed LAN resources."""

from __future__ import annotations

from typing import Any

from ..exceptions import SPD3000ConnectionError, SPD3000TimeoutError


class VisaTransport:
    """Physical transport using PyVISA."""

    def __init__(
        self,
        resource: str,
        *,
        backend: str | None = None,
        timeout: float = 5.0,
        resource_manager: Any | None = None,
    ) -> None:
        self.resource_name = resource
        self._owns_manager = resource_manager is None
        self._closed = False
        try:
            if resource_manager is None:
                try:
                    import pyvisa
                except ImportError as exc:
                    raise SPD3000ConnectionError(
                        "PyVISA is required but unavailable; "
                        "reinstall py-siglent-spd3000 to restore its runtime dependencies"
                    ) from exc
                self._manager: Any = (
                    pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()
                )
            else:
                self._manager = resource_manager
            self._resource: Any = self._manager.open_resource(resource)
            self._resource.timeout = int(timeout * 1000)
            self._resource.write_termination = None
            self._resource.read_termination = "\n"
        except SPD3000ConnectionError:
            raise
        except Exception as exc:
            raise SPD3000ConnectionError(
                f"Could not open VISA resource {resource!r}: {exc}"
            ) from exc

    def write(self, data: bytes) -> None:
        self._ensure_open()
        try:
            self._resource.write_raw(data)
        except Exception as exc:
            self._raise_io("VISA write", exc)

    def read(self) -> bytes:
        self._ensure_open()
        try:
            return bytes(self._resource.read_raw())
        except Exception as exc:
            self._raise_io("VISA read", exc)
        raise AssertionError("unreachable")

    @staticmethod
    def _raise_io(operation: str, exc: Exception) -> None:
        if "timeout" in type(exc).__name__.lower() or "timeout" in str(exc).lower():
            raise SPD3000TimeoutError(f"{operation} timed out: {exc}") from exc
        raise SPD3000ConnectionError(f"{operation} failed: {exc}") from exc

    def _ensure_open(self) -> None:
        if self._closed:
            raise SPD3000ConnectionError("VISA transport is closed")

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._resource.close()
        finally:
            if self._owns_manager:
                self._manager.close()
            self._closed = True

    def __enter__(self) -> VisaTransport:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
