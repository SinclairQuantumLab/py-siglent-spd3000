# py-siglent-spd3000

A synchronous Python driver and optional centralized gateway for Siglent SPD3303X, SPD3303X-E, and SPD3303C programmable DC power supplies.
Connecting through the [gateway server](#gateway-server) is the recommended way to share a supply because one server owns the physical connection, runs client requests one at a time, and enforces the required command spacing; simple one-process scripts can still connect directly through the same Python API.

## Table of contents

- [Installation](#installation)
  - [Install from a Git checkout](#install-from-a-git-checkout)
  - [Install a published build](#install-a-published-build)
- [Basic use](#basic-use)
- [Connections](#connections)
  - [VISA resource identifiers](#visa-resource-identifiers)
- [Jupyter hardware test notebook](#jupyter-hardware-test-notebook)
- [From a manual SCPI command to Python](#from-a-manual-scpi-command-to-python)
  - [1. Guess the Python path from the SCPI command line](#1-guess-the-python-path-from-the-scpi-command-line)
  - [2. Confirm the mapping with the helper](#2-confirm-the-mapping-with-the-helper)
  - [Intentional `OUTPut` convenience exception](#intentional-output-convenience-exception)
- [SCPI-shaped API](#scpi-shaped-api)
- [Batching](#batching)
- [Write verification](#write-verification)
- [Timing](#timing)
- [Gateway server](#gateway-server)
  - [Install](#install)
  - [Create the configuration files](#create-the-configuration-files)
  - [Start the gateway](#start-the-gateway)
  - [Connect a client](#connect-a-client)
  - [Ports and firewall](#ports-and-firewall)
- [Model differences](#model-differences)
- [Development](#development)

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
On the gateway computer and each computer that will connect to it, install the gateway extra:

```bash
python -m pip install -e ".[gateway]"
```

Use `python -m pip install -e ".[driver]"` on a computer that connects directly through USBTMC/VISA or VXI-11 without running or using the gateway.
Compare the output of `git rev-parse HEAD` on every computer before starting the gateway; all hashes must be identical.
Do not copy an editable source tree without its `.git` directory because the package would be unable to identify its commit and the gateway handshake would fail.
Uncommitted local changes are allowed, but the person running them remains responsible for knowing that those changes are not represented by the commit hash.

> **NOTE:** `uv` is optional and does not replace Git or the same-commit requirement.
> After cloning and checking out the selected commit, run `uv sync --extra gateway --no-dev` on the gateway computer and its clients, or `uv sync --extra driver --no-dev` on a computer that only connects directly.
> Run project commands through that environment by prefixing them with `uv run`, for example `uv run spd3000 --help`.

### Install a published build

When installing from a package index, install the exact same published version on the gateway computer and every client computer.
Replace `<VERSION>` with one specific release number:

```bash
# Gateway computer
python -m pip install "py-siglent-spd3000[gateway]==<VERSION>"

# Gateway client computer
python -m pip install "py-siglent-spd3000[gateway]==<VERSION>"
```

A built wheel contains its source commit, so Git is not required at runtime when every computer installs the same build.
The base package remains standard-library-only, while the `driver` extra installs direct USBTMC/VISA and VXI-11 support and the `gateway` extra installs the gateway's physical-connection dependencies plus a TOML compatibility parser for Python 3.10.
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
    print(psu)  # cached model, serial number, connection, and local open/closed state; no SCPI query
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
See [Batching](#batching) when related commands must execute without another gateway client's commands appearing between them.
See [Write verification](#write-verification) when a setting must be queried and checked after it is written.
Every instrument-state property read performs a fresh hardware query; output state and measurements are never answered from a write cache.
`str(psu)` instead summarizes the identity cached during connection, the normalized connection destination, the local open/closed state, and the instance's timeout, command interval, and global write-verification setting without issuing another command.
The reported `open` state means that `close()` has not been called; it is not an active reachability probe.
Public identification, capability, execution-setting, network-setting, status, error, SCPI-command information, and gateway-setting objects also provide readable multiline `str()` output; formatting an already obtained object performs no I/O.
The SPD command set has no documented `OUTPut?` query, so special `psu.ch<CH_NUM>.output` properties are implemented by querying and decoding `SYSTem:STATus?`.
For a guided end-to-end check against a real instrument, use the [Jupyter hardware test notebook](#jupyter-hardware-test-notebook); it starts with read-only checks and gates state-changing tests behind explicit user input.

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

## Connections

`SPD3000.connect(connection, identifier, ...)` separates the connection method from the address or resource that identifies its destination.
Enum members such as `spd.ConnectionType.SOCKET` are recommended, while their lowercase string values remain accepted for short scripts.

| `connection` | Physical and protocol path | `identifier` | Supported models and installation |
| --- | --- | --- | --- |
| `spd.ConnectionType.SOCKET` or `"socket"` | Ethernet using raw SCPI over TCP 5025 | Power supply hostname or IP address, such as `"192.168.1.50"` | SPD3303X/X-E; base package |
| `spd.ConnectionType.VXI11` or `"vxi11"` | Ethernet using VXI-11 directly through `python-vxi11` | Power supply hostname or IP address | SPD3303X/X-E; `driver` extra |
| `spd.ConnectionType.VISA` or `"visa"` | USBTMC over USB, or a VISA-managed Ethernet connection such as VXI-11 | Complete VISA resource reported on that computer, such as `"USB0::0x0483::0x7540::SPD3XGB4150080::INSTR"` or `"TCPIP0::192.168.55.122::inst0::INSTR"` | All models over USB; SPD3303X/X-E over Ethernet when supported by the selected VISA backend; `driver` extra |
| `spd.ConnectionType.GATEWAY` or `"gateway"` | This package's gateway protocol over TCP, with the gateway owning the physical connection | `"localhost"` when the client and gateway run on the same computer; otherwise the gateway computer's hostname or IP address, such as `"192.168.50.20"`; append a non-default port as in `"192.168.50.20:3333"`; never use the power supply address | All supported models through a suitably connected gateway; `gateway` extra |

Ordinary raw socket connections always use the instrument's documented TCP port 5025, while gateway connections use port 8765 by default.
See [Gateway server](#gateway-server) for gateway configuration, authentication, and firewall requirements.

### VISA resource identifiers

A VISA `identifier` should be copied from the resources enumerated by the VISA backend on the computer that will control the instrument.
Do not construct it from the operating-system name or copy another computer's resource blindly, because the backend, interface number, and instrument serial number can change the exact value.
After installing the `driver` extra and connecting the instrument, PyVISA-py resources can be listed with:

```bash
python -c "import pyvisa; print(*pyvisa.ResourceManager('@py').list_resources(), sep='\n')"
```

The official SIGLENT example scan returns these complete resource strings:

- USBTMC power supply: `USB0::0x0483::0x7540::SPD3XGB4150080::INSTR`
- Ethernet instrument: `TCPIP0::192.168.55.122::inst0::INSTR`

These are format examples from SIGLENT rather than identifiers for your instrument, so replace the entire string with the resource returned on the target computer.
Use `visa_backend="@py"` with PyVISA-py, or omit `visa_backend` to let PyVISA select an installed system backend such as NI-VISA:

```python
import siglent_spd3000 as spd

VISA_RESOURCE = "USB0::0x0483::0x7540::SPD3XGB4150080::INSTR"  # example only; replace it

with spd.SPD3000.connect(
    spd.ConnectionType.VISA,
    VISA_RESOURCE,
    visa_backend="@py",
) as psu:
    print(psu.idn)
```

The VISA resource grammar is generally portable, but driver installation and USB device permissions remain operating-system-specific.
The [official SIGLENT PyVISA discovery example](docs/Programming%20Example_%20List%20connected%20VISA%20compatible%20resources%20using%20PyVISA.pdf) provides additional resource-discovery context.

## Jupyter hardware test notebook

[`test_spd300.ipynb.template`](test_spd300.ipynb.template) is the quickest guided check of this driver against a real SPD3000 Series power supply.
Its annotated cells exercise the connection and representative instrument operations while reporting each step, making a firmware, transport, or individual-command failure easier to locate.
The notebook itself explains the required connection inputs and safety confirmations; potentially state-changing tests remain opt-in and show their planned values first.

Copy the template so connection details and saved outputs remain in the ignored working copy rather than entering Git history.
If `test_spd300.ipynb` already exists, open that file and skip the copy command so its connection values and test record are not overwritten.

```console
cp test_spd300.ipynb.template test_spd300.ipynb
```

Open `test_spd300.ipynb` in Visual Studio Code, use **Select Kernel** to choose the environment where this project is installed, and follow the notebook from top to bottom.

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
  - `psu.network.settings` queries all four values and returns one printable `NetworkSettings` snapshot.

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

### Intentional `OUTPut` convenience exception

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
print(psu.network.settings)  # four fresh network queries; formatting performs no I/O

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

## Batching

Ordinary setters execute immediately and do not perform an implicit readback.
The SPD3000 requires deliberate spacing between commands, and a gateway may be serving multiple clients through the same physical connection.
Batching is therefore a first-class feature: it keeps one logical sequence non-interleaved while the physical connection owner continues to enforce the required command interval.
Use it for related setpoint changes, configuration sequences, or groups of measurements that must remain together.

Use `psu.batch()` to collect semantic writes and queries and execute them as one non-interleaved batch.
A write-only batch needs no separate API:

```python
with psu.batch():
    psu.ch1.voltage = 5.0
    psu.ch1.current = 0.5
```

Use `as responses` to receive the parsed results of user-issued queries in source order:

```python
with psu.batch() as responses:
    psu.ch1.voltage
    psu.measure.current(spd.Channel.CH1)

voltage, measured_current = responses
```

`responses` contains only explicit user-query results; writes and automatic verification readbacks are omitted.
Results are unavailable inside the block and become ordinary parsed Python values when it exits successfully.
If the block raises, its collected operations are discarded without being sent.
Execution and response-parsing failures are raised when the block exits.

`@psu.batch` is a convenience wrapper around the same `psu.batch()` context and unwraps Deferred values in the decorated function's returned built-in containers:

```python
@psu.batch
def configure_and_read():
    psu.ch1.voltage = 5.0
    return psu.ch1.voltage, psu.measure.voltage(spd.Channel.CH1)

ch1_set_voltage, ch1_measured_voltage = configure_and_read()
print(ch1_set_voltage)  # float
print(ch1_measured_voltage)  # float
```

Batching guarantees ordering and non-interleaving, not rollback: writes completed before a later command fails may remain applied.
Raw `psu.scpi.query()` can also be collected inside `psu.batch()` or an `@psu.batch` function.

## Write verification

Most SPD3000 setting commands return no value, so a successfully transmitted write does not by itself prove that the instrument accepted the requested state.
Write verification appends the documented query, parses its response, and compares it with the requested value.
This costs additional commands and time, and a few writes have no corresponding query, so verification remains an explicit choice rather than an implicit setter behavior.

Write verification is disabled by default.
Pass `verify_writes_globally=True` to the constructor or `connect()` to verify every supported semantic write:

```python
with spd.SPD3000.connect(
    spd.ConnectionType.SOCKET,
    "192.168.1.50",
    verify_writes_globally=True,
) as psu:
    psu.ch1.voltage = 5.0

    psu.verify_writes_globally = False
    psu.ch1.current = 0.5
```

`psu.verify_writes_globally` is an ordinary bool property that can be read or changed at any time.
Here, globally means all subsequent writes made through that `psu` instance rather than every driver instance in the process.
Use `psu.verify_writes()` to force verification on within one scope, or pass `False` to force it off temporarily:

```python
with psu.verify_writes():
    psu.ch1.voltage = 5.0

with psu.verify_writes(False):
    psu.ch1.current = 0.5
```

Without `psu.batch()`, each verified setter executes its own non-interleaved write/query pair.
The two contexts compose, so several verified settings can travel as one write batch:

```python
with psu.batch(), psu.verify_writes():
    psu.ch1.voltage = 5.0
    psu.ch1.current = 0.5
    psu.ch1.output = True
```

If a write fails, its original driver or gateway exception is preserved.
If the write succeeds but its readback fails, is malformed, differs from the requested value, or does not exist, the driver raises `SPD3000VerificationError`.
The exception exposes `command`, `query`, `expected`, and `actual`; the original readback exception is available as `__cause__`.

```python
try:
    with psu.verify_writes():
        psu.ch3.output = True
except spd.SPD3000VerificationError as exc:
    print(exc.command)   # "OUTP CH3,ON" was sent
    print(exc.query)     # None: Siglent documents no CH3 output-state query
```

Verification errors never imply rollback.
In particular, an unqueryable setting such as CH3 output is applied first and then reported as unverifiable, and writes completed before a later batch failure may remain applied.
The already-assembled `psu.scpi.execute()` escape hatch cannot be nested inside a batch or verification scope because it owns a separate immediate batch.

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
The gateway computer is the computer physically connected to the supply or able to reach it over the network, and client computers send the ordinary `SPD3000` operations to that gateway.

### Install

Follow [Installation](#installation) on the gateway computer and every client computer.
Install the `gateway` extra on all of them and verify that every installation reports the same Git commit.

### Create the configuration files

The source repository and installed package include two safe-to-commit templates:

- `gateway-settings.toml.template` describes the gateway listener and its physical instrument connection.
- `gateway-auth.toml.template` contains the shape of the separate authentication file.

On the gateway computer, run the following command to create editable copies in the current directory:

```bash
spd3000 gateway init
```

The command creates `gateway-settings.toml` and `gateway-auth.toml` from those templates and refuses to overwrite existing files.
Edit `gateway-settings.toml` for the gateway computer and its power supply.
For a typical network-connected SPD3303X/X-E, use settings like these:

```toml
[gateway]
bind = "192.168.50.20" # IP address of the computer that runs this gateway server
port = 8765

[instrument]
connection = "socket"
identifier = "192.168.50.30" # IP address of the power supply
timeout_s = 5.0
min_command_interval_ms = 100.0
```

`connection = "socket"` uses the documented Siglent raw-SCPI port 5025, and the official network commands provide no port-setting operation, so it is intentionally fixed inside the driver rather than exposed in this file.
Use `connection = "vxi11"` with the instrument hostname for VXI-11, or `connection = "visa"` with a VISA resource in `identifier` for USBTMC and SPD3303C.

For access from another computer, also edit the generated `gateway-auth.toml`.
The token has no special format: any non-empty custom string is valid.
Because anyone who knows this string can access the gateway, a long, random, hard-to-guess value is strongly recommended rather than a short manually chosen value.
The following Python command is one convenient way to generate a recommended token, but it is only an example and is not required:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The completed authentication file has this form:

```toml
token = "replace-this-example-with-the-generated-private-token"
```

Copy the completed `gateway-auth.toml` securely to every authorized client computer.
The real `gateway-settings.toml` and `gateway-auth.toml` files are excluded from Git; commit only their `.template` files.

### Start the gateway

Run this command from the directory containing both TOML files:

```bash
spd3000 gateway serve
```

Use `--config <SETTINGS_PATH>` and `--auth <AUTH_PATH>` only when the files have different names or locations.
If `--auth` is omitted, the server looks for `gateway-auth.toml` beside the settings file.
The command keeps running until it is stopped.

> **NOTE:** When installed with `uv`, run `uv run spd3000 gateway serve` instead.

### Connect a client

`<GATEWAY_HOST>` below means the IP address or hostname of the gateway computer, such as `192.168.50.20`; replace the whole placeholder, including the angle brackets.
On a client computer containing its copy of `gateway-auth.toml`, test the connection with:

```bash
spd3000 idn --gateway <GATEWAY_HOST> --gateway-auth gateway-auth.toml
```

When the server uses a non-default gateway port, append it to the same identifier:

```bash
spd3000 idn --gateway 192.168.50.20:3333 --gateway-auth gateway-auth.toml
```

The equivalent Python connection is:

```python
import siglent_spd3000 as spd

GATEWAY_ENDPOINT = "192.168.50.20"  # append ":3333" when using a non-default port

with spd.SPD3000.connect(
    connection=spd.ConnectionType.GATEWAY,
    identifier=GATEWAY_ENDPOINT,
    token=spd.load_gateway_auth("gateway-auth.toml"),
) as psu:
    print(psu.idn)
    psu.ch1.voltage = 5.0
```

For a local-only setup, set `gateway.bind = "localhost"` and either leave the generated token empty or remove `gateway-auth.toml`.
`localhost` means the gateway accepts clients only from that same computer, so no token is required.

### Ports and firewall

The gateway listens on TCP port 8765 by default; it does not use the common web ports 80 or 443.
Remote clients require an inbound firewall rule for TCP 8765 on the gateway computer, preferably restricted to the trusted client IP addresses.
The gateway computer must also be allowed to reach an SPD3303X/X-E at TCP 5025 when `connection = "socket"` is used.
If you change `gateway.port`, use the same value in the firewall rule and append it to the client identifier, for example `--gateway 192.168.50.20:3333` or `identifier="192.168.50.20:3333"`.
A remotely accessible gateway uses token authentication, but the protocol is not encrypted, so use it only on a trusted network or carry it through a VPN, SSH tunnel, or TLS proxy.

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
| `*LOCK?` | Documented; verify on the target firmware and connection | Documented; verify on the target firmware and connection | No |

Unsupported model features raise `UnsupportedFeatureError` before any command is sent.
Values outside documented limits or off the model's programming grid raise `SPD3000ValidationError`; the driver never silently rounds them.
`psu.capabilities` describes model-level vendor documentation rather than probing every command at connection time.
An unanswered documented query still raises `SPD3000TimeoutError`; the hardware notebook handles the known `*LOCK?` case as an optional runtime check without hiding timeouts from normal application code.

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
Use the [Jupyter hardware test notebook](#jupyter-hardware-test-notebook) for a guided interactive check or the ordered [physical-device acceptance procedure](.agents/HARDWARE_TESTS.md) for the complete manual test campaign.
