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

Already have a command from a SIGLENT manual? See
[From a manual SCPI command to Python](#from-a-manual-scpi-command-to-python).

```python
from siglent_spd3000 import SPD3000

with SPD3000.connect("socket", "192.168.1.50") as psu:
    psu.ch1.voltage = 5.0
    psu.ch1.current = 0.5
    print(psu.measure.ch1.voltage)
    print(psu.measure.ch1.current)
    psu.output.ch1 = True
```

Every property read performs a fresh hardware query; output state and
measurements are never answered from a write cache.

For more involved programs, keep the main class directly available and access
additional public types through the package namespace. The unified `connect()`
factory accepts common execution settings directly:

```python
import siglent_spd3000 as spd
from siglent_spd3000 import SPD3000

with SPD3000.connect(
    connection=spd.ConnectionType.SOCKET,
    identifier="192.168.1.50",
    timeout_s=5.0,
    min_command_interval_ms=50,
) as psu:
    psu.output(spd.Channel.CH1, True)
    psu.output.track(spd.TrackingMode.INDEPENDENT)
```

`connection` also accepts the strings `"socket"`, `"vxi11"`, `"visa"`, and
`"gateway"`.

## From a manual SCPI command to Python

Start with the command entry in the applicable [official manual](docs/README.md).
Read its action, arguments, return format, supported channels, and model notes;
the Python API preserves those device semantics and validates documented model
limitations before I/O.

### 1. Guess the Python path from the SCPI command line

As a first approximation, expand abbreviated SCPI headers, make them lowercase,
and replace `:` with `.`. A trailing `?` means a read, which is normally a
property access; a value-taking command is normally a property assignment or a
method call.

| Manual command | Action and arguments | Python API |
| --- | --- | --- |
| `CH1:VOLTage 5` | Set the CH1 source voltage to 5 V | `psu.ch1.voltage = 5.0` |
| `CH1:VOLTage?` | Read the CH1 voltage setpoint | `setpoint = psu.ch1.voltage` |
| `MEASure:VOLTage? CH1` | Measure voltage; `CH1` selects the channel | `measured = psu.measure.ch1.voltage` |
| `SYSTem:STATus?` | Read and decode the instrument status word | `status = psu.system.status` |
| `OUTPut:TRACK 1` | Select series tracking mode | `psu.output.track(spd.TrackingMode.SERIES)` |
| `TIMEr:SET CH1,1,3,0.5,2` | Set CH1 timer group 1 to 3 V, 0.5 A, 2 s | `psu.timer.set[spd.Channel.CH1, 1] = spd.TimerStep(3.0, 0.5, 2.0)` |

Arguments determine the final Python shape. A channel argument commonly becomes
a channel subtree, a single value commonly becomes an assignment, and an action
with several arguments commonly becomes a method call or a typed value such as
`TimerStep`.

There are deliberate quirks:

- IEEE common commands lose the leading `*` and use a descriptive root member:
  `*IDN?` becomes `psu.identity`, `*SAV 1` becomes `psu.save(1)`, `*RCL 1`
  becomes `psu.recall(1)`, and `*LOCK?` becomes `psu.locked`.
- Manual abbreviations such as `MEAS:VOLT?` and `SYST:STAT?` use their expanded
  words in Python: `measure.voltage` and `system.status`.
- Network commands are grouped under `psu.network`, so `IPADDR` maps to
  `psu.network.ip_address` even though the SCPI header has no `NETWork` prefix.
- `OUTPut` has an intentional convenience API because it is used frequently;
  see [Intentional `OUTPut` convenience exception](#intentional-output-convenience-exception).
- A query is not necessarily a plain string in Python. For example, `*IDN?`,
  `SYST:STAT?`, and `SYST:ERR?` return parsed typed objects.

### 2. Confirm the mapping with the helper

Pass either the manual's long form or the abbreviated command line to
`lookup_command()`. Matching is case-insensitive, and command arguments and the
trailing `?` are ignored:

```python
matches = spd.lookup_command("MEAS:VOLT? CH1")
info = matches[0]

print(info.canonical_scpi)  # MEASURE:VOLTAGE?
print(info.python_path)  # measure.ch1.voltage / measure.ch2.voltage
print(info.access.value)  # read
print(info.unit)  # V
print([model.value for model in info.models])
print(info.source)  # vendor document used for this mapping

measured = psu.measure.ch1.voltage
```

The helper returns a tuple because a header can have multiple mappings. It does
not generate executable code or interpret the supplied arguments; use the
manual's argument description to select the channel, enum, index, or value.
An empty tuple means that no semantic mapping is registered.
`spd.iter_commands(psu.model)` lists every registered command for the connected
model.

If a firmware-specific command is not registered, the explicit escape hatch is
`psu.scpi.write("COMMAND ...")` or `psu.scpi.query("COMMAND?")`. Raw access still
uses the configured executor, timing, and gateway serialization, but bypasses
the semantic driver's model checks and response parsing.

## Intentional `OUTPut` convenience exception

The public API otherwise follows the instrument's canonical SCPI tree as
closely as practical. `OUTPut` is intentionally exceptional because channel
switching is one of the most frequent supply operations. The callable and
per-channel property forms are both supported and share exactly one write
implementation:

```python
psu.output(spd.Channel.CH1, True)  # OUTP CH1,ON
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
psu.instrument.channel = spd.Channel.CH1
psu.ch1.voltage = 3.3
voltage = psu.measure.ch1.voltage

status = psu.system.status
error = psu.system.error  # pops one error-queue entry

psu.timer(spd.Channel.CH1, True)
psu.timer.set[spd.Channel.CH1, 1] = spd.TimerStep(voltage=3.0, current=0.5, time=2.0)

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
settings = spd.ExecutionSettings(min_command_interval=0.100, timeout=5.0)
```

Most callers can pass these values to `SPD3000.connect()` as shown in Basic
use. `ExecutionSettings` remains useful for custom executors and gateway
internals; its interval is expressed in seconds.

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
