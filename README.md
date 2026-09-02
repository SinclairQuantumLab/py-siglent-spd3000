# py-siglent-spd3000

A synchronous Python driver and optional centralized gateway for Siglent
SPD3303X, SPD3303X-E, and SPD3303C programmable DC power supplies.

The semantic driver is the single source of instrument behavior. Direct and
gateway-backed connections expose the same Python API; only the command
executor changes.

## Installation

```bash
python -m pip install py-siglent-spd3000
python -m pip install "py-siglent-spd3000[driver]"
python -m pip install "py-siglent-spd3000[gateway]"
```

The base installation has no runtime dependencies outside the Python standard
library and supports raw TCP for SPD3303X/X-E plus the gateway protocol. The
`driver` extra adds every supported physical backend (PyVISA/PyVISA-py USBTMC
and VXI-11). The `gateway` extra adds the same backends because a gateway server
can own any supported physical connection. These are the project's only two
extras. SPD3303C exposes USB Device/USBTMC only and therefore needs one of them.

> **NOTE:** `uv` is entirely optional. Contributors who prefer it can replace
> the development setup below with `uv sync --extra driver --extra gateway
> --dev` and prefix the check commands with `uv run`.

## Basic use

```python
from siglent_spd3000 import SPD3000

with SPD3000.from_socket("192.168.1.50") as psu:
    psu.ch1.voltage = 5.0
    psu.ch1.current = 0.5
    print(psu.measure.ch1.voltage)
    print(psu.measure.ch1.current)
    psu.output.ch1 = True
```

Equivalent constructors are `from_vxi11()`, `from_visa()`, and
`from_gateway()`. Every property read performs a fresh hardware query; output
state and measurements are never answered from a write cache.

For more involved programs, keep the main class directly available and access
additional public types through the package namespace:

```python
import siglent_spd3000 as spd
from siglent_spd3000 import SPD3000

with SPD3000.from_socket("192.168.1.50") as psu:
    psu.output(spd.Channel.CH1, True)
    psu.output.track(spd.TrackingMode.INDEPENDENT)
```

## Intentional `OUTPut` convenience exception

The public API otherwise follows the instrument's canonical SCPI tree as
closely as practical. `OUTPut` is intentionally exceptional because channel
switching is one of the most frequent supply operations. The callable and
per-channel property forms are both supported and share exactly one write
implementation:

```python
psu.output(Channel.CH1, True)  # OUTP CH1,ON
psu.output.ch1 = True  # the same OUTP CH1,ON

print(psu.output.ch1)  # fresh SYST:STAT?, bit 4
assert psu.output.ch2 is False  # fresh SYST:STAT?, bit 5
```

Siglent does not document an `OUTPut?` query. CH1/CH2 state is therefore read
indirectly from `SYSTem:STATus?`. The documented status word contains no CH3
output bit, so writing `psu.output.ch3 = True` is supported but reading
`psu.output.ch3` raises `UnsupportedFeatureError`. The driver deliberately does
not report the last commanded CH3 value as if it were measured state.

## SCPI-shaped API

```python
from siglent_spd3000 import TimerStep

psu.instrument.channel = Channel.CH1
psu.ch1.voltage = 3.3
voltage = psu.measure.ch1.voltage

status = psu.system.status
error = psu.system.error  # pops one error-queue entry

psu.timer(Channel.CH1, True)
psu.timer.set[Channel.CH1, 1] = TimerStep(voltage=3.0, current=0.5, time=2.0)

psu.network.dhcp = False
psu.network.ip_address = "192.168.1.50"
```

Network properties accept and return ordinary dotted IPv4 strings. They are
validated and normalized internally. Setting a static address does not
silently disable DHCP.

Use `lookup_command("MEAS:VOLT?")` to discover the corresponding Python path,
or use `psu.scpi.write()`, `query()`, and `execute()` as an explicit low-level
escape hatch.

## Timing

Siglent recommends LF-only termination and a delay of 10-100 ms between most
commands and between a query write and read. The driver defaults to 100 ms:

```python
from siglent_spd3000 import ExecutionSettings

settings = ExecutionSettings(min_command_interval=0.100, timeout=5.0)
```

Finite, non-negative intervals outside 10-100 ms are allowed but emit
`SPD3000TimingWarning` at the caller. Negative, NaN, and infinite values are
rejected. The owner of the physical connection enforces timing globally, so
gateway clients cannot interleave command batches.

## Gateway

The gateway relays command batches, not semantic operations. Client and server
must report the exact same Git commit. Dirty working trees are allowed; commit
matching is compatibility checking and is not authentication.

```bash
spd3000 gateway serve --socket 192.168.1.50
spd3000 idn --gateway 127.0.0.1
```

The default bind is `127.0.0.1:8765`. A non-loopback bind requires a pre-shared
token from `--token-file` or `SIGLENT_SPD3000_GATEWAY_TOKEN`. The protocol does
not provide encryption; use a VPN, SSH tunnel, or TLS proxy for untrusted
networks.

## Model differences

| Feature | SPD3303X | SPD3303X-E | SPD3303C |
| --- | --- | --- | --- |
| Programming resolution | 1 mV / 1 mA | 10 mV / 10 mA | 10 mV / 10 mA |
| Measure power | Yes | Yes | No |
| Timer / waveform display | Yes | Yes | No remote command |
| Network configuration | Yes | Yes | No |
| Raw socket / VXI-11 | Yes | Yes | No |
| USBTMC through VISA | Yes | Yes | Yes |
| `*LOCK` / `*UNLOCK` | Yes | Yes | Yes |
| `*LOCK?` | Yes | Yes | No |

Unsupported model features raise `UnsupportedFeatureError` before any command
is sent. Values outside documented limits or off the model's programming grid
raise `SPD3000ValidationError`; the driver never silently rounds them.

## Development

```bash
python -m venv .venv
# Activate .venv using the command for your shell, then:
python -m pip install --upgrade pip
python -m pip install -e ".[driver,gateway]"
python -m pip install pytest pytest-cov ruff mypy
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m pytest --cov=siglent_spd3000
python -m pip wheel . --no-deps --wheel-dir dist
```

Official vendor manuals and application notes used during development are
indexed in [`docs/README.md`](docs/README.md), including source URLs and file
hashes. Hardware tests are opt-in and are not run without an attached supply.
