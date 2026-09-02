"""Public exception and warning hierarchy."""

from __future__ import annotations


class SPD3000Error(Exception):
    """Base class for driver and instrument failures."""


class SPD3000TimeoutError(SPD3000Error, TimeoutError):
    """An instrument operation exceeded its configured timeout."""


class SPD3000ConnectionError(SPD3000Error, ConnectionError):
    """The physical instrument connection failed."""


class SPD3000ProtocolError(SPD3000Error):
    """The instrument returned malformed or unexpected data."""


class SPD3000CommandError(SPD3000Error):
    """The instrument rejected or could not execute a command."""


class SPD3000ValidationError(SPD3000Error, ValueError):
    """A value is invalid for the selected SPD3000 model."""


class UnsupportedFeatureError(SPD3000Error, NotImplementedError):
    """The connected model does not implement the requested feature."""


class UnknownModelError(SPD3000ProtocolError):
    """The ``*IDN?`` response does not identify a supported model."""


class SPD3000TimingWarning(UserWarning):
    """A command interval is outside Siglent's recommended 10-100 ms range."""


class GatewayError(Exception):
    """Base class for gateway/network failures, distinct from device failures."""


class GatewayConnectionError(GatewayError, ConnectionError):
    """The gateway connection failed."""


class GatewayConfigurationError(GatewayError, ValueError):
    """The gateway settings file is missing or invalid."""


class GatewayAuthenticationError(GatewayError):
    """The gateway rejected the pre-shared token."""


class GatewayVersionMismatchError(GatewayError):
    """Client and gateway Git commits do not match."""


class GatewayProtocolError(GatewayError):
    """A malformed or unsupported gateway message was received."""


class GatewayInternalError(GatewayError):
    """The gateway failed outside the canonical driver exception boundary."""


CANONICAL_EXCEPTION_TYPES: dict[str, type[SPD3000Error]] = {
    cls.__name__: cls
    for cls in (
        SPD3000Error,
        SPD3000TimeoutError,
        SPD3000ConnectionError,
        SPD3000ProtocolError,
        SPD3000CommandError,
        SPD3000ValidationError,
        UnsupportedFeatureError,
        UnknownModelError,
    )
}
