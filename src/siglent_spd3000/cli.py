"""Command-line interface built exclusively on the public driver API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .driver import SPD3000
from .exceptions import GatewayError, SPD3000Error
from .execution import DirectExecutor, ExecutionSettings, Transport
from .gateway import GatewayServer
from .models import Channel, ConnectionType
from .scpi import lookup_command
from .transport import SocketTransport, VisaTransport, VXI11Transport


def _channel(value: str) -> Channel:
    try:
        return Channel(value.upper())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("channel must be CH1, CH2, or CH3") from exc


def _state(value: str) -> bool:
    normalized = value.lower()
    if normalized in {"on", "true", "1"}:
        return True
    if normalized in {"off", "false", "0"}:
        return False
    raise argparse.ArgumentTypeError("state must be on or off")


def _add_connection(parser: argparse.ArgumentParser, *, gateway_allowed: bool = True) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--socket", metavar="HOST")
    group.add_argument("--vxi11", metavar="HOST")
    group.add_argument("--visa", metavar="RESOURCE")
    if gateway_allowed:
        group.add_argument("--gateway", metavar="HOST")
    parser.add_argument("--socket-port", type=int, default=5025)
    parser.add_argument("--gateway-port", type=int, default=8765)
    parser.add_argument("--visa-backend")
    parser.add_argument("--interval", type=float, default=0.100, metavar="SECONDS")
    parser.add_argument("--timeout", type=float, default=5.0, metavar="SECONDS")
    if gateway_allowed:
        parser.add_argument("--token-file", type=Path)


def _token(path: Path | None) -> str | None:
    if path is not None:
        return path.read_text(encoding="utf-8").strip()
    return os.environ.get("SIGLENT_SPD3000_GATEWAY_TOKEN")


def _settings(args: argparse.Namespace) -> ExecutionSettings:
    return ExecutionSettings(args.interval, args.timeout)


def _open_device(args: argparse.Namespace) -> SPD3000:
    if args.socket:
        return SPD3000.connect(
            ConnectionType.SOCKET,
            args.socket,
            port=args.socket_port,
            timeout_s=args.timeout,
            min_command_interval_ms=args.interval * 1000.0,
        )
    if args.vxi11:
        return SPD3000.connect(
            ConnectionType.VXI11,
            args.vxi11,
            timeout_s=args.timeout,
            min_command_interval_ms=args.interval * 1000.0,
        )
    if args.visa:
        return SPD3000.connect(
            ConnectionType.VISA,
            args.visa,
            visa_backend=args.visa_backend,
            timeout_s=args.timeout,
            min_command_interval_ms=args.interval * 1000.0,
        )
    return SPD3000.connect(
        ConnectionType.GATEWAY,
        args.gateway,
        port=args.gateway_port,
        token=_token(args.token_file),
        timeout_s=args.timeout,
        min_command_interval_ms=args.interval * 1000.0,
    )


def _direct_executor(args: argparse.Namespace) -> DirectExecutor:
    settings = _settings(args)
    transport: Transport
    if args.socket:
        transport = SocketTransport(args.socket, port=args.socket_port, timeout=settings.timeout)
    elif args.vxi11:
        transport = VXI11Transport(args.vxi11, timeout=settings.timeout)
    else:
        transport = VisaTransport(args.visa, backend=args.visa_backend, timeout=settings.timeout)
    return DirectExecutor(transport, settings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spd3000")
    subparsers = parser.add_subparsers(dest="command", required=True)

    idn = subparsers.add_parser("idn", help="query instrument identity")
    _add_connection(idn)

    setpoint = subparsers.add_parser("set", help="set a CH1/CH2 source value")
    setpoint.add_argument("quantity", choices=("voltage", "current"))
    setpoint.add_argument("channel", type=_channel, choices=(Channel.CH1, Channel.CH2))
    setpoint.add_argument("value", type=float)
    _add_connection(setpoint)

    measure = subparsers.add_parser("measure", help="query a CH1/CH2 measurement")
    measure.add_argument("quantity", choices=("voltage", "current", "power"))
    measure.add_argument("channel", type=_channel, choices=(Channel.CH1, Channel.CH2))
    _add_connection(measure)

    output = subparsers.add_parser("output", help="turn an output on or off")
    output.add_argument("channel", type=_channel)
    output.add_argument("state", type=_state)
    _add_connection(output)

    status = subparsers.add_parser("status", help="query and decode SYST:STAT?")
    _add_connection(status)

    raw = subparsers.add_parser("raw", help="send an explicit SCPI command")
    raw.add_argument("scpi")
    raw.add_argument("--query", action="store_true")
    _add_connection(raw)

    lookup = subparsers.add_parser("lookup", help="find Python API for a SCPI header")
    lookup.add_argument("scpi")

    gateway = subparsers.add_parser("gateway", help="gateway administration")
    gateway_subparsers = gateway.add_subparsers(dest="gateway_command", required=True)
    serve = gateway_subparsers.add_parser("serve", help="serve one physical connection")
    _add_connection(serve, gateway_allowed=False)
    serve.add_argument("--bind", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--token-file", type=Path)
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "lookup":
        matches = lookup_command(args.scpi)
        for info in matches:
            print(
                f"{info.canonical_scpi}: {info.python_path} "
                f"[{info.access.value}; {', '.join(model.value for model in info.models)}]"
            )
        return 0 if matches else 1

    if args.command == "gateway":
        executor = _direct_executor(args)
        server = GatewayServer(
            executor, host=args.bind, port=args.port, token=_token(args.token_file)
        )
        try:
            print(f"Serving SPD3000 gateway on {args.bind}:{server.port}")
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.close()
        return 0

    with _open_device(args) as psu:
        if args.command == "idn":
            print(psu.identity.raw)
        elif args.command == "set":
            source_channel = psu.ch1 if args.channel is Channel.CH1 else psu.ch2
            setattr(source_channel, args.quantity, args.value)
        elif args.command == "measure":
            measure_channel = psu.measure.ch1 if args.channel is Channel.CH1 else psu.measure.ch2
            print(getattr(measure_channel, args.quantity))
        elif args.command == "output":
            psu.output(args.channel, args.state)
        elif args.command == "status":
            print(json.dumps(asdict(psu.system.status), default=str, sort_keys=True))
        elif args.command == "raw":
            if args.query:
                print(psu.scpi.query(args.scpi))
            else:
                psu.scpi.write(args.scpi)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit status."""

    parser = build_parser()
    try:
        return _run(parser.parse_args(argv))
    except (SPD3000Error, GatewayError, OSError) as exc:
        print(f"spd3000: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
