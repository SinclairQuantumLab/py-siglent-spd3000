# py-siglent-spd3000

A synchronous Python driver and optional centralized gateway for Siglent SPD3303X, SPD3303X-E, and SPD3303C programmable DC power supplies.
Connecting through the [gateway server](#gateway-server) is the recommended way to share a supply because one server owns the physical connection, runs client requests one at a time, and enforces the required command spacing; simple one-process scripts can still connect directly through the same Python API.

## Installation

Python 3.10 or newer is required.
Gateway connections also require the gateway computer and every client computer to run code built from the exact same Git commit.

### Install from a Git checkout

Install Python and Git on every computer, then run the following commands on the gateway computer and on each client computer.
Replace `<REPOSITORY_URL>` with this repository's URL and `<COMMIT_HASH>` with the same agreed commit on every computer; do not type the angle brackets.

```bash
git clone <REPOSITORY_URL>
cd py-siglent-spd3000
git checkout <COMMIT_HASH>
git rev-parse HEAD
python -m venv .venv
```

Activate the environment with `.venv\Scripts\Activate.ps1` in Windows PowerShell or `source .venv/bin/activate` on Linux and macOS.
On the gateway computer, install the gateway extra:

```bash
python -m pip install -e ".[gateway]"
```

On a computer that only connects to the gateway, install the base package:

```bash
python -m pip install -e .
```

Use `python -m pip install -e ".[driver]"` instead if that client computer must also connect directly through USBTMC/VISA or VXI-11.
Compare the output of `git rev-parse HEAD` on every computer before starting the gateway; all hashes must be identical.
Do not copy an editable source tree without its `.git` directory because the package would be unable to identify its commit and the gateway handshake would fail.
Uncommitted local changes are allowed, but the person running them remains responsible for knowing that those changes are not represented by the commit hash.

> **NOTE:** `uv` is optional and does not replace Git or the same-commit requirement.
> After cloning and checking out the selected commit, run `uv sync --extra gateway --no-dev` on the gateway computer, `uv sync --no-dev` on a client-only computer, or `uv sync --extra driver --no-dev` on a computer that also connects directly.
> Run project commands through that environment by prefixing them with `uv run`, for example `uv run spd3000 --help`.

### Install a published build

When installing from a package index, install the exact same published version on the gateway computer and every client computer.
Replace `<VERSION>` with one specific release number:

```bash
# Gateway computer
python -m pip install "py-siglent-spd3000[gateway]==<VERSION>"

# Client-only computer
python -m pip install "py-siglent-spd3000==<VERSION>"
```

A built wheel contains its source commit, so Git is not required at runtime when every computer installs the same build.
The base package supports raw TCP and gateway clients, while the `driver` and `gateway` extras install PyVISA/PyVISA-py USBTMC and VXI-11 support.
These are the project's only two extras.
SPD3303C supports USBTMC only and therefore requires one of these extras on the computer physically connected to it.

## Basic use

Below is the basic use of this driver library, including:

- importing the package,
- connecting to the power supply,
- querying and setting voltage and current values,
- measuring actual voltage and current, and
- querying and setting channel output status.

```python
import siglent_spd3000 as spd

with spd.SPD3000.connect("socket", "192.168.1.50") as psu:
    print(psu.idn)  # identify the instrument; SCPI: "*IDN?"

    psu.ch1.voltage = 5.0  # set CH1 voltage; SCPI: "CH1:VOLTage 5.0"
    psu.ch1.current = 0.5  # set CH1 current limit; SCPI: "CH1:CURRent 0.5"
    print(psu.ch1.voltage)  # query CH1 voltage setting; SCPI: "CH1:VOLTage?"
    print(psu.ch1.current)  # query CH1 current setting; SCPI: "CH1:CURRent?"

    # Measure the live CH1 output, not its configured settings.
    print(psu.measure.voltage(spd.Channel.CH1))  # SCPI: "MEASure:VOLTage? CH1"
    print(psu.measure.current(spd.Channel.CH1))  # SCPI: "MEASure:CURRent? CH1"

    psu.ch1.output = True  # enable CH1 output; SCPI: "OUTPut CH1,ON"
    print(psu.ch1.output)  # query CH1 output; SCPI: "SYSTem:STATus?" -> bit #4
```

See [From a manual SCPI command to Python](#from-a-manual-scpi-command-to-python) to find and use the commands and corresponding library methods.
Every property read performs a fresh hardware query; output state and measurements are never answered from a write cache.
The SPD command set has no documented `OUTPut?` query, so special `psu.ch<CH_NUM>.output` properties are implemented by querying and decoding `SYSTem:STATus?`.

For more involved programs, the same package namespace provides connection types, enums, and execution settings.
The unified `connect()` factory accepts common execution settings directly:

```python
import siglent_spd3000 as spd

with spd.SPD3000.connect(
    connection=spd.ConnectionType.SOCKET,
    identifier="192.168.1.50",
    timeout_s=5.0,
    min_command_interval_ms=50,
) as psu:
    psu.output(spd.Channel.CH1, spd.OutputState.ON)
    psu.output.track(spd.TrackingMode.INDEPENDENT)
```

`connection` also accepts the strings `"socket"`, `"vxi11"`, `"visa"`, and `"gateway"`.

## From a manual SCPI command to Python

Start with the command entry in the applicable [official manual](docs/README.md).
Read its action, arguments, return format, supported channels, and model notes; the Python API preserves those device semantics and validates documented model limitations before I/O.

### 1. Guess the Python path from the SCPI command line

As a first approximation, expand abbreviated SCPI headers, make them lowercase, and replace `:` with `.`.
SCPI arguments remain Python arguments.
A trailing `?` means a read: a query without arguments is normally a property, while a query with arguments is normally a method call.
A value-taking command is normally a property assignment or method call.

| Manual command | Action and arguments | Python API |
| --- | --- | --- |
| `CH1:VOLTage 5` | Set the CH1 source voltage to 5 V | `psu.ch1.voltage = 5.0` |
| `CH1:VOLTage?` | Read the CH1 voltage setpoint | `setpoint = psu.ch1.voltage` |
| `MEASure:VOLTage? CH1` | Measure voltage; `CH1` selects the channel | `measured = psu.measure.voltage("CH1")` |
| `SYSTem:STATus?` | Read and decode the instrument status word | `status = psu.system.status` |
| `OUTPut:TRACK 1` | Select series tracking mode | `psu.output.track(spd.TrackingMode.SERIES)` |
| `TIMEr:SET CH1,1,3,0.5,2` | Set CH1 timer group 1 to 3 V, 0.5 A, 2 s | `psu.timer.set("CH1", 1, 3.0, 0.5, 2.0)` |
| `TIMEr:SET? CH1,1` | Query CH1 timer group 1 | `timer_step = psu.timer.set("CH1", 1)` |

Arguments determine the final Python shape but keep their SCPI order.
Enum members are recommended for discoverability and type checking; their raw SCPI values are also accepted where documented.
Thus channel arguments accept both `spd.Channel.CH1` and `"CH1"`, output state accepts both `spd.OutputState.ON` and `"ON"`, timer state accepts both `spd.TimerState.ON` and `"ON"`, waveform state accepts both `spd.WaveformState.ON` and `"ON"`, and tracking mode accepts both `spd.TrackingMode.SERIES` and `1`.

The mechanically derived name is always the canonical implementation.
Friendly names are additive aliases which delegate to it; they do not contain separate validation or I/O logic:

- IEEE common commands lose the leading `*`:
  - Identification: `*IDN?` maps directly to `psu.idn`.
  - Stored setups:
    - `*SAV 1` maps to canonical `psu.sav(1)`; `psu.save(1)` is its readable alias.
    - `*RCL 1` maps to canonical `psu.rcl(1)`; `psu.recall(1)` is its readable alias.
  - Front-panel locking:
    - `*LOCK` and `*UNLOCK` map directly to `psu.lock()` and `psu.unlock()`.
    - `*LOCK?` maps exceptionally to `psu.locked`.
      Python cannot expose `lock` as both a callable method and a boolean property.
- Network settings keep their SCPI-derived root properties and also provide grouped aliases under `psu.network`:
  - `psu.ipaddr` -> `psu.network.host`
  - `psu.maskaddr` -> `psu.network.subnet_mask`
  - `psu.gateaddr` -> `psu.network.gateway`
  - `psu.dhcp` -> `psu.network.dhcp`

Commands which already map cleanly need no alias; for example, `INSTrument CH1` maps directly to `psu.instrument = "CH1"`.

The remaining behavior and naming rules are:

- Manual abbreviations such as `MEAS:VOLT?` and `SYST:STAT?` use their expanded words in Python: `measure.voltage(channel)` and `system.status`.
- Method arguments preserve documented SCPI tokens through enums such as `OutputState`, `TimerState`, and `WaveformState`; Python `bool` is deliberately rejected in those positions.
- Boolean properties such as `dhcp`, `locked`, and `ch1.output` instead expose ordinary `bool` values because the property itself represents a binary state.
- `OUTPut` keeps canonical `output(channel, state)` and adds channel convenience properties because it is used frequently; see [Intentional `OUTPut` convenience exception](#intentional-output-convenience-exception).
- A query is not necessarily a plain string in Python.
  For example, `*IDN?`, `SYST:STAT?`, and `SYST:ERR?` return parsed typed objects.

### 2. Confirm the mapping with the helper

Pass either the manual's long form or the abbreviated command line to `lookup_command()`.
Matching is case-insensitive, and command arguments and the trailing `?` are ignored:

```python
matches = spd.lookup_command("MEAS:VOLT? CH1")
info = matches[0]

print(info.canonical_scpi)  # MEASURE:VOLTAGE?
print(info.python_path)  # canonical: measure.voltage(channel)
print(info.python_aliases)  # additional friendly paths, if any
print(info.access.value)  # read
print(info.unit)  # V
print([model.value for model in info.models])
print(info.source)  # vendor document used for this mapping

measured = psu.measure.voltage(spd.Channel.CH1)  # recommended
measured = psu.measure.voltage("CH1")  # raw SCPI argument is also accepted
```

The helper returns a tuple because a header can have multiple mappings.
It does not generate executable code or interpret the supplied arguments; use the manual's argument description to select the channel, enum, index, or value.
An empty tuple means that no semantic mapping is registered.
`spd.iter_commands(psu.model)` lists every registered command for the connected model.

If a firmware-specific command is not registered, the explicit escape hatch is `psu.scpi.write("COMMAND ...")` or `psu.scpi.query("COMMAND?")`.
Raw access still uses the configured executor, timing, and gateway serialization, but bypasses the semantic driver's model checks and response parsing.

## Intentional `OUTPut` convenience exception

The regular API follows the instrument's canonical SCPI command and arguments.
Because channel switching is one of the most frequent supply operations, each channel additionally exposes an intentional boolean convenience property.
Both forms share exactly one write implementation:

```python
psu.output(spd.Channel.CH1, spd.OutputState.ON)  # regular; SCPI: "OUTPut CH1,ON"
psu.ch1.output = True  # convenience; SCPI: "OUTPut CH1,ON"

status = psu.system.status  # regular; SCPI: "SYSTem:STATus?"
print(status.ch1.output)  # inspect bit #4

print(psu.ch1.output)  # convenience; SCPI: "SYSTem:STATus?" -> bit #4
assert psu.ch2.output is False  # convenience; SCPI: "SYSTem:STATus?" -> bit #5
```

Siglent does not document an `OUTPut?` query.
CH1/CH2 state is therefore read indirectly from `SYSTem:STATus?`.
The documented status word contains no CH3 output bit, so writing `psu.ch3.output = True` is supported but reading `psu.ch3.output` raises `UnsupportedFeatureError`.
The driver deliberately does not report the last commanded CH3 value as if it were measured state.

## SCPI-shaped API

```python
psu.instrument = spd.Channel.CH1
psu.ch1.voltage = 3.3
voltage = psu.measure.voltage("CH1")

status = psu.system.status
error = psu.system.error  # pops one error-queue entry

timer_step = {"voltage_v": 3.0, "current_a": 0.5, "duration_s": 2.0}
psu.timer.set("CH1", 1, **timer_step)
timer_step = psu.timer.set("CH1", 1)  # fresh TIMER:SET? query
psu.timer("CH1", spd.TimerState.ON)
psu.output.wave("CH1", spd.WaveformState.ON)

psu.dhcp = False
psu.ipaddr = "192.168.1.50"

# Friendly aliases delegate to the canonical root properties above.
psu.network.dhcp = False
psu.network.host = "192.168.1.50"

psu.sav(1)
psu.save(1)  # friendly alias for the same *SAV 1 command
```

Each channel has timer groups 1 through 5.
A group is one timer step containing voltage, current, and duration; the maximum duration is 10,000 seconds.
Passing only channel and group to `timer.set()` queries that step and returns an ordinary dictionary.
Passing all three values writes it.
Positional SCPI order is also supported: `psu.timer.set("CH1", 1, 3.0, 0.5, 2.0)`.

Canonical and grouped network properties accept and return ordinary dotted IPv4 strings.
They are validated and normalized by the canonical root properties.
Setting a static address does not silently disable DHCP.

Use `lookup_command("MEAS:VOLT?")` to discover the corresponding Python path, or use `psu.scpi.write()`, `query()`, and `execute()` as an explicit low-level escape hatch.

## Timing

Siglent recommends LF-only termination and a delay of 10-100 ms between most commands and between a query write and read.
The driver defaults to 100 ms:

```python
settings = spd.ExecutionSettings(min_command_interval=0.100, timeout=5.0)
```

Most callers can pass these values to `spd.SPD3000.connect()` as shown in Basic use.
`ExecutionSettings` remains useful for custom executors and gateway internals; its interval is expressed in seconds.

Finite, non-negative intervals outside 10-100 ms are allowed but emit `SPD3000TimingWarning` at the caller.
Negative, NaN, and infinite values are rejected.
The owner of the physical connection enforces timing globally, so gateway clients cannot interleave command batches.

## Gateway server

Run one gateway server for each power supply that will be shared.
The gateway computer is the computer that can reach the physical instrument, while a client is any program or computer that sends driver operations through that gateway.
Client code still uses the ordinary `SPD3000` API.

### Install

Follow [Installation](#installation) on every participating computer.
The gateway computer needs the `gateway` extra, client-only computers need the base package, and every checkout or installed build must report the same commit hash.

### Identify the addresses

- `<INSTRUMENT_HOST>` is the power supply's IP address or hostname, for example `192.168.50.30`.
- `<GATEWAY_HOST>` is the IP address or hostname of the computer running this gateway server, for example `192.168.50.20`.
- `<TOKEN_FILE>` is a UTF-8 text file containing the same private secret on the gateway computer and each remote client, for example `gateway-token.txt`.
- `localhost` means “this same computer” and is correct only when the gateway server and client run on one computer.

Replace every `<...>` placeholder in the commands below with the value for your setup; do not type the angle brackets.
Do not commit the token file to Git.
The following command prints a suitable random secret; save that one line in the token file on the gateway computer and in a separate token file on each client computer:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Start the gateway

On the gateway computer, select how that computer reaches the instrument:

- `--socket <INSTRUMENT_HOST>` uses raw TCP on an SPD3303X/X-E.
- `--vxi11 <INSTRUMENT_HOST>` uses VXI-11 on an SPD3303X/X-E.
- `--visa <VISA_RESOURCE>` uses a VISA resource and is the supported path for an SPD3303C.

For a typical two-computer setup using raw TCP, start the server with:

```bash
spd3000 gateway serve --socket <INSTRUMENT_HOST> --bind <GATEWAY_HOST> --token-file <TOKEN_FILE>
```

For example, if the supply is `192.168.50.30` and the gateway computer is `192.168.50.20`:

```bash
spd3000 gateway serve --socket 192.168.50.30 --bind 192.168.50.20 --token-file gateway-token.txt
```

The default gateway port is `8765`, and the command keeps running until it is stopped.

### Connect a client

On a different client computer, address the gateway computer rather than the power supply:

```bash
spd3000 idn --gateway <GATEWAY_HOST> --token-file <TOKEN_FILE>
```

The equivalent Python connection is:

```python
from pathlib import Path

import siglent_spd3000 as spd

GATEWAY_HOST = "192.168.50.20"  # IP address or hostname of the gateway computer
GATEWAY_TOKEN = Path("gateway-token.txt").read_text(encoding="utf-8").strip()

with spd.SPD3000.connect(
    connection=spd.ConnectionType.GATEWAY,
    identifier=GATEWAY_HOST,
    token=GATEWAY_TOKEN,
) as psu:
    print(psu.idn)
    psu.ch1.voltage = 5.0
```

When the client runs on the gateway computer itself, the shorter local-only setup is:

```bash
spd3000 gateway serve --socket <INSTRUMENT_HOST>
spd3000 idn --gateway localhost
```

The local-only form listens only on the gateway computer and does not require a token.
A server that accepts other computers is rejected unless a token is configured.
The gateway protocol is not encrypted, so use it only on a trusted network or carry it through a VPN, SSH tunnel, or TLS proxy.

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

Unsupported model features raise `UnsupportedFeatureError` before any command is sent.
Values outside documented limits or off the model's programming grid raise `SPD3000ValidationError`; the driver never silently rounds them.

## Development

Repository-internal tests live under `.agents/tests/`; pytest discovers them through the project configuration.

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

Official vendor manuals and application notes used during development are indexed in [`docs/README.md`](docs/README.md), including source URLs and file hashes.
Hardware tests are opt-in and are not run without an attached supply.
The ordered physical-device acceptance procedure is maintained in [`.agents/HARDWARE_TESTS.md`](.agents/HARDWARE_TESTS.md).
