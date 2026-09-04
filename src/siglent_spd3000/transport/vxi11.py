"""python-vxi11 transport for SPD3303X/X-E LAN control."""

from __future__ import annotations

from typing import Any

from ..exceptions import SPD3000ConnectionError, SPD3000TimeoutError


class VXI11Transport:
    """Physical transport backed by ``python-vxi11``."""

    def __init__(
        self,
        host: str,
        *,
        timeout: float = 5.0,
        instrument: Any | None = None,
    ) -> None:
        self.host = host
        self._closed = False
        try:
            if instrument is None:
                try:
                    import vxi11  # type: ignore[import-untyped]
                except ImportError as exc:
                    raise SPD3000ConnectionError(
                        "python-vxi11 is required but unavailable; "
                        "reinstall py-siglent-spd3000 to restore its runtime dependencies"
                    ) from exc
                self._instrument = vxi11.Instrument(host)
            else:
                self._instrument = instrument
            self._instrument.timeout = int(timeout * 1000)
        except SPD3000ConnectionError:
            raise
        except Exception as exc:
            raise SPD3000ConnectionError(
                f"Could not open VXI-11 instrument {host!r}: {exc}"
            ) from exc

    def write(self, data: bytes) -> None:
        self._ensure_open()
        try:
            self._instrument.write_raw(data)
        except Exception as exc:
            self._raise_io("VXI-11 write", exc)

    def read(self) -> bytes:
        self._ensure_open()
        try:
            data = self._instrument.read_raw()
            return data if isinstance(data, bytes) else str(data).encode("ascii")
        except Exception as exc:
            self._raise_io("VXI-11 read", exc)
        raise AssertionError("unreachable")

    @staticmethod
    def _raise_io(operation: str, exc: Exception) -> None:
        if "timeout" in type(exc).__name__.lower() or "timeout" in str(exc).lower():
            raise SPD3000TimeoutError(f"{operation} timed out: {exc}") from exc
        raise SPD3000ConnectionError(f"{operation} failed: {exc}") from exc

    def _ensure_open(self) -> None:
        if self._closed:
            raise SPD3000ConnectionError("VXI-11 transport is closed")

    def close(self) -> None:
        if not self._closed:
            try:
                self._instrument.close()
            finally:
                self._closed = True

    def __enter__(self) -> VXI11Transport:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
