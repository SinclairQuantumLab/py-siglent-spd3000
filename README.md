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
import siglent_spd3000 as spd
from siglent_spd3000 import SPD3000

with SPD3000.connect("socket", "192.168.1.50") as psu:
    print(psu.idn)  # identify the instrument; SCPI: *IDN?

    psu.ch1.voltage = 5.0  # set CH1 voltage; SCPI: CH1:VOLTage 5.0
    psu.ch1.current = 0.5  # set CH1 current limit; SCPI: CH1:CURRent 0.5
    print(psu.ch1.voltage)  # query CH1 voltage setting; SCPI: CH1:VOLTage?
    print(psu.ch1.current)  # query CH1 current setting; SCPI: CH1:CURRent?

    # Measure the live CH1 output, not its configured settings.
    print(psu.measure.voltage(spd.Channel.CH1))  # SCPI: MEASure:VOLTage? CH1
    print(psu.measure.current(spd.Channel.CH1))  # SCPI: MEASure:CURRent? CH1

    psu.ch1.output = True  # enable CH1 output; SCPI: OUTPut CH1,ON
    print(psu.ch1.output)  # query CH1 state; SCPI: SYSTem:STATus?
```

Every property read performs a fresh hardware query; output state and
measurements are never answered from a write cache. The SPD command set has no
documented `OUTPut?` query, so `psu.ch1.output` reads and decodes
`SYSTem:STATus?`.

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
    psu.output(spd.Channel.CH1, spd.OutputState.ON)
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
and replace `:` with `.`. SCPI arguments remain Python arguments. A trailing `?`
means a read: a query without arguments is normally a property, while a query
with arguments is normally a method call. A value-taking command is normally a
property assignment or method call.

| Manual command | Action and arguments | Python API |
| --- | --- | --- |
| `CH1:VOLTage 5` | Set the CH1 source voltage to 5 V | `psu.ch1.voltage = 5.0` |
| `CH1:VOLTage?` | Read the CH1 voltage setpoint | `setpoint = psu.ch1.voltage` |
| `MEASure:VOLTage? CH1` | Measure voltage; `CH1` selects the channel | `measured = psu.measure.voltage("CH1")` |
| `SYSTem:STATus?` | Read and decode the instrument status word | `status = psu.system.status` |
| `OUTPut:TRACK 1` | Select series tracking mode | `psu.output.track(spd.TrackingMode.SERIES)` |
| `TIMEr:SET CH1,1,3,0.5,2` | Set CH1 timer group 1 to 3 V, 0.5 A, 2 s | `psu.timer.set("CH1", 1, 3.0, 0.5, 2.0)` |
| `TIMEr:SET? CH1,1` | Query CH1 timer group 1 | `timer_step = psu.timer.set("CH1", 1)` |

Arguments determine the final Python shape but keep their SCPI order. Enum
members are recommended for discoverability and type checking; their raw SCPI
values are also accepted where documented. Thus channel arguments accept both
`spd.Channel.CH1` and `"CH1"`, output state accepts both `spd.OutputState.ON`
and `"ON"`, and tracking mode accepts both `spd.TrackingMode.SERIES` and `1`.

There are deliberate quirks:

- IEEE common commands lose the leading `*`:
  `*IDN?` becomes `psu.idn`, `*SAV 1` becomes `psu.save(1)`, `*RCL 1`
  becomes `psu.recall(1)`, and `*LOCK?` becomes `psu.locked`.
- Manual abbreviations such as `MEAS:VOLT?` and `SYST:STAT?` use their expanded
  words in Python: `measure.voltage(channel)` and `system.status`.
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
print(info.python_path)  # measure.voltage(channel)
print(info.access.value)  # read
print(info.unit)  # V
print([model.value for model in info.models])
print(info.source)  # vendor document used for this mapping

measured = psu.measure.voltage(spd.Channel.CH1)  # recommended
measured = psu.measure.voltage("CH1")  # raw SCPI argument is also accepted
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

The regular API follows the instrument's canonical SCPI command and arguments.
Because channel switching is one of the most frequent supply operations, each
channel additionally exposes an intentional boolean convenience property. Both
forms share exactly one write implementation:

```python
psu.output(spd.Channel.CH1, spd.OutputState.ON)  # regular; OUTP CH1,ON
psu.ch1.output = True  # convenience; the same OUTP CH1,ON

status = psu.system.status  # regular; fresh SYST:STAT?
print(status.ch1.output)  # inspect CH1 output bit 4

print(psu.ch1.output)  # convenience; fresh SYST:STAT?, then bit 4
assert psu.ch2.output is False  # convenience; fresh SYST:STAT?, then bit 5
```

Siglent does not document an `OUTPut?` query. CH1/CH2 state is therefore read
indirectly from `SYSTem:STATus?`. The documented status word contains no CH3
output bit, so writing `psu.ch3.output = True` is supported but reading
`psu.ch3.output` raises `UnsupportedFeatureError`. The driver deliberately does
not report the last commanded CH3 value as if it were measured state.

## SCPI-shaped API

```python
psu.instrument.channel = spd.Channel.CH1
psu.ch1.voltage = 3.3
voltage = psu.measure.voltage("CH1")

status = psu.system.status
error = psu.system.error  # pops one error-queue entry

timer_step = {"voltage_v": 3.0, "current_a": 0.5, "duration_s": 2.0}
psu.timer.set("CH1", 1, **timer_step)
timer_step = psu.timer.set("CH1", 1)  # fresh TIMER:SET? query
psu.timer("CH1", True)

psu.network.dhcp = False
psu.network.ip_address = "192.168.1.50"
```

Each channel has timer groups 1 through 5. A group is one timer step containing
voltage, current, and duration; the maximum duration is 10,000 seconds. Passing
only channel and group to `timer.set()` queries that step and returns an ordinary
dictionary. Passing all three values writes it. Positional SCPI order is also
supported: `psu.timer.set("CH1", 1, 3.0, 0.5, 2.0)`.

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

Repository-internal tests live under `.agents/tests/`; pytest discovers them
through the project configuration.

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
