# AGENTS.md

## Current project naming and precedence

The current repository/project/distribution name is:

```text
py-siglent-spd3000
```

Use the Python import package name:

```text
siglent_spd3000
```

The **driver is the core of the project**. The **gateway is an optional/add-on capability** distributed as part of the same project rather than a separate semantic implementation. A natural optional-extra form is:

```bash
pip install py-siglent-spd3000
pip install "py-siglent-spd3000[gateway]"
```

The name `py-siglent-spd3000` was chosen because it makes the Python implementation explicit while remaining broad enough to contain both the instrument driver and the optional gateway. Earlier candidate names such as `siglent-spd3000-driver`, `siglent-spd3000-library`, `siglent-spd3000-api`, and bare `siglent-spd3000` are not the current project name.

### Precedence for the material below

This file joins two prior handoff documents **without shortening either one**.

1. The **SPD3000 Driver + Gateway Architecture Handoff** is the current architecture decision record and takes precedence for architecture where the documents differ.
2. The older **project/research context** remains fully included because it contains the device research, existing-library survey, communication-stack details, references, API ideas, testing ideas, and open questions that remain useful for implementation.
3. The naming decision in this section supersedes older naming references below, especially references to `siglent-spd3000-driver` as the project/package name.
4. In particular, the newer architecture distinguishes a command-level **Executor/Backend** abstraction from lower-level physical **Transport** mechanisms. Where the older research notes place responsibilities such as command spacing directly in `Transport`, follow the newer architecture unless implementation evidence gives a concrete reason to revisit it.
5. Do not reinterpret the same-commit requirement into a stricter source-integrity mechanism. Client and gateway should simply require the same Git commit hash at session establishment. Dirty working trees are allowed; the developer is responsible for understanding local modifications.

---

# SPD3000 Driver + Gateway Architecture Handoff

## Goal

Implement centralized control of Siglent SPD3000-series power supplies while preserving essentially the same Python UX for:

1. direct hardware access, and
2. access through a central gateway process.

The gateway exists primarily because some instruments require controlled command timing and because multiple processes must not independently contend for the same physical instrument connection.

The intended architecture deliberately avoids turning the gateway into a second semantic instrument API.

## Package / Naming

Use one package/project, with conceptually distinct driver and gateway components.

Suggested naming:

- Project/package: `siglent-spd3000-driver`
- Driver: semantic Python instrument driver
- Gateway: centralized remote execution service

Possible packaging:

```bash
pip install siglent-spd3000-driver
pip install "siglent-spd3000-driver[gateway]"
```

`driver` means an instrument driver, not an OS/kernel device driver. It owns the device-specific Python API and translates instrument operations into SCPI.

`gateway` is the authoritative access boundary between clients and the physical instrument. It does not need to understand SPD3000 semantics.

## Core Architecture

```text
                         User / CLI
                             |
                             v
                    SPD3000 Driver
               semantic Python interface
               SCPI generation + parsing
                             |
                       execution request
                    / command batch
                             |
                +------------+------------+
                |                         |
                v                         v
         Direct Executor           Gateway Executor
                |                         |
                |                     RPC/HTTP
                |                         |
                |                         v
                |                     Gateway
                |                  queue / arbiter
                |                  timing enforcement
                |                  batch isolation
                |                         |
                +------------+------------+
                             v
                         Instrument
```

Core rule:

> The driver owns instrument semantics. The gateway owns centralized execution.

Do **not** implement the SPD3000 semantic API a second time in the gateway.

## Why Not a Semantic REST Gateway?

Avoid:

```text
Python driver API
    -> REST semantic API
    -> gateway-side driver
    -> SCPI
```

combined with a client SDK that maps REST back into Python methods.

That duplicates mappings and increases synchronization burden and debugging depth.

Instead, the existing driver remains the **single implementation of SPD3000 semantics**.

For example:

```python
psu.set_voltage(1, 3.3)
psu.measure_voltage(1)
psu.enable_output(1)
```

should execute the same driver code regardless of whether physical execution occurs locally or through the gateway.

Only the execution backend changes.

## Driver Responsibilities

The driver owns all SPD3000-specific knowledge, including:

- semantic Python API
- SCPI command generation
- SCPI response parsing
- device capabilities
- required command sequences
- device-specific execution settings
- validation of those settings
- canonical driver exception hierarchy

Example:

```python
class SPD3000:
    def set_voltage(self, channel, voltage):
        ...

    def measure_voltage(self, channel):
        ...

    def enable_output(self, channel):
        ...
```

Do not duplicate device constraints inside the gateway.

If SPD3000 requires a minimum command interval, the allowed/default value and validation belong to the driver/package:

```python
class ExecutionSettings:
    def __init__(self, min_command_interval=...):
        if min_command_interval < DEVICE_MINIMUM:
            raise ValueError(...)
```

Docstrings/documentation should explain such constraints.

## Executor Abstraction

Prefer `Executor` or `Backend` over `Transport` for the abstraction that executes commands or batches.

`Transport` should refer to lower-level mechanisms such as TCP, serial, USBTMC, or VISA.

Conceptually:

```text
Driver
  |
  v
CommandExecutor
  +-- DirectExecutor
  |      +-- physical transport
  |
  +-- GatewayExecutor
         +-- network connection to gateway
```

Both executors should preserve the same observable driver semantics as far as reasonably possible.

## Command Batches and Non-Interleaving

The gateway should support a batch of commands as one execution request.

Example:

```text
[
    Write("INST CH1"),
    Write("VOLT 3.3"),
    Query("MEAS:VOLT?")
]
```

A batch must execute without another client's batch being interleaved.

Allowed:

```text
A1 A2 A3 B1 B2
```

Not allowed:

```text
A1 B1 A2 B2 A3
```

Prefer terminology such as **serialized batch** or **non-interleaved batch** rather than database-style transaction, because there is generally no rollback.

## Timing and Arbitration

There are two distinct responsibilities.

### Device knowledge

The driver/package knows facts such as:

- minimum allowed command interval
- terminators
- timeouts/defaults
- device quirks

and validates configurable values.

### Physical enforcement

The component that owns the actual hardware connection enforces constraints on the real global command timeline.

Therefore:

```text
Direct mode:
    DirectExecutor enforces timing locally.

Gateway mode:
    Gateway enforces timing across all clients.
```

The gateway does not contain another copy of SPD3000 timing rules. The values come from the same package/driver execution settings.

## Session-Level Execution Settings

Execution settings do not need to accompany every command request.

A gateway connection/session can establish relevant settings once and retain them:

```text
connect
  -> establish execution settings
  -> session
       -> execute(batch)
       -> execute(batch)
       -> execute(batch)
```

The driver/package defines and validates these settings.

The gateway stores whatever session/device execution state is necessary to enforce them.

Do not introduce duplicated gateway-side defaults, allowable ranges, or SPD3000-specific policy definitions.

## Same-Commit Requirement

The driver and gateway are distributed as parts of the same package.

Use a deliberately simple compatibility rule:

> A gateway client and gateway server must report the exact same Git commit hash.

Perform this check when establishing the gateway connection/session.

```text
Client commit:  abc123...
Gateway commit: abc123...

same      -> accept
different -> reject
```

Do not add package-version negotiation, profile hashes, protocol compatibility matrices, etc. unless a real future requirement appears.

Do **not** reject dirty working trees merely because they are dirty. Development from modified working trees must remain convenient. Commit comparison is only a practical guard against accidentally running clearly different revisions.

Commit equality is compatibility checking, not authentication.

If authentication is implemented, it may occur during the same handshake, but keep compatibility checking and authentication conceptually separate.

## Exception Transparency

Preserving exception behavior is one of the most important requirements for making direct and gateway-backed operation feel equivalent.

The package should define a canonical driver exception hierarchy, for example:

```python
class SPD3000Error(Exception):
    ...

class SPD3000TimeoutError(SPD3000Error):
    ...

class SPD3000ConnectionError(SPD3000Error):
    ...

class SPD3000ProtocolError(SPD3000Error):
    ...

class SPD3000CommandError(SPD3000Error):
    ...
```

Exact classes should follow actual driver needs.

### Direct execution

Normalize low-level backend exceptions into canonical driver exceptions where appropriate.

```text
socket/VISA/etc. exception
        -> canonical SPD3000 exception
        -> user
```

### Gateway execution

Relay southbound driver/device exceptions so the client reconstructs and raises the same canonical exception type.

```text
physical I/O
    -> canonical SPD3000 exception
    -> serialize exception information
    -> network
    -> GatewayExecutor
    -> reconstruct same exception class
    -> user
```

Because client and gateway are required to run the same package revision, both sides can rely on having the same driver exception definitions.

Thus this should behave the same in direct and gateway modes:

```python
try:
    psu.measure_voltage(1)
except SPD3000TimeoutError:
    ...
```

Do not serialize arbitrary Python exception objects with pickle. Use an explicit representation sufficient to reconstruct known driver exceptions.

At minimum preserve:

- exception type
- exception arguments/message as needed

Preserve additional structured fields only if the actual exception classes require them.

## Gateway Errors vs Southbound Errors

Do not disguise gateway failures as instrument failures.

Maintain a separate gateway-side exception hierarchy for errors such as:

- `GatewayConnectionError`
- `GatewayAuthenticationError`
- `GatewayVersionMismatchError`
- `GatewayProtocolError`
- `GatewayInternalError`

Names are illustrative.

This lets callers distinguish device failures from gateway/network failures.

## Remote Tracebacks

When a southbound exception or gateway internal error occurs remotely, preserve the remote traceback for debugging.

Do not pretend the remote traceback is a local Python stack. Attach/present it explicitly as a remote traceback, for example through exception notes or an equivalent mechanism.

The exact serialization/display mechanism is an implementation choice.

## What Does Not Need Transparent Relay

Do not over-engineer complete process transparency.

There is no current requirement to relay:

- Python warnings
- arbitrary logging records
- every piece of execution metadata
- arbitrary Python objects
- arbitrary server exceptions

The important transparency targets are:

```text
same driver method call
same return/result semantics
same canonical southbound exception type
```

plus useful remote traceback information.

## Gateway Scope

The gateway should remain intentionally thin.

Primary responsibilities:

- own the physical instrument connection
- receive execution requests
- queue/serialize requests from multiple clients
- execute each command batch without interleaving
- enforce physical command timing on the global device timeline
- return raw execution results
- relay canonical southbound exceptions
- distinguish/report gateway failures
- perform same-commit handshake
- optionally perform authentication

It should **not** independently understand semantic operations such as `set_voltage`, `enable_channel`, or `measure_current`.

The gateway understands execution, not SPD3000 semantics.

## Avoid Premature Genericization

Do not currently create a universal SCPI gateway or generic laboratory-device gateway framework.

The pattern could eventually apply to SCPI/TCP, VISA, serial, non-SCPI string protocols, or more generic request/response devices. Following that abstraction too early would require generic handling of discovery, session lifecycle, transport, framing, binary/textual messages, timing policies, retry/error semantics, protocol quirks, and batch semantics.

That is not justified yet.

The reusable insight is primarily the **gateway/arbitration pattern**, not necessarily a universal reusable implementation.

Implement the SPD3000 gateway concretely first.

Some duplicated code in future device packages is acceptable. A wrong generic abstraction is likely to cost more than a small amount of duplication.

If several future implementations reveal genuinely identical components, extract only those after the repetition is demonstrated.

Possible future reusable primitives might include:

- `SerializedExecutor`
- `MinimumIntervalLimiter`
- `ConnectionOwner`
- `BatchExecutor`

but there is no need to create a separate generic package now.

## Suggested Internal Shape

Illustrative only:

```text
siglent_spd3000/
├── driver.py
├── scpi.py
├── exceptions.py
├── execution.py
├── transport/
│   └── ...
│
├── gateway/
│   ├── client.py
│   ├── server.py
│   ├── protocol.py
│   ├── arbiter.py
│   └── exceptions.py
│
└── cli/
    └── ...
```

Possible conceptual interface:

```python
class Executor(Protocol):
    def execute(self, batch: CommandBatch) -> BatchResult:
        ...
```

with implementations such as:

```python
DirectExecutor(...)
GatewayExecutor(...)
```

The exact sync/async API should be decided based on implementation needs rather than architecture aesthetics.

The gateway server will naturally need concurrency handling, but that does not automatically require the public instrument driver API itself to become async.

## CLI

The CLI should use the same driver API rather than manually constructing gateway HTTP requests.

```text
CLI
 |
 v
SPD3000 driver
 |
 v
selected executor
 +-- DirectExecutor
 +-- GatewayExecutor
```

Therefore commands such as:

```bash
spd3000 set-voltage 1 3.3
spd3000 measure-voltage 1
```

should not need to know the gateway wire protocol.

## Important Design Invariants

1. SPD3000 semantics exist in one place: the driver.
2. Gateway does not duplicate the semantic Python API.
3. Direct and gateway-backed operation use the same driver-facing UX.
4. Device-specific execution settings and validation have one source of truth in the package.
5. The physical connection owner enforces timing on the actual global command stream.
6. A command batch cannot be interleaved with another client's batch.
7. Client and gateway must report the same Git commit at session establishment.
8. Commit equality is not authentication.
9. Canonical southbound exceptions should emerge at the client as the same exception classes in both direct and gateway modes.
10. Gateway/network failures remain distinguishable from instrument failures.
11. Remote tracebacks should remain available for debugging.
12. Do not prematurely generalize this into a universal device-gateway framework.

## Overall Mental Model

```text
Driver = what to do
Executor = where/how to execute it
Gateway = centralized remote executor
```

The objective is not perfect network transparency. It is to make centralized remote control transparent enough that normal user code, return values, and device exceptions behave essentially the same as direct driver use, while guaranteeing safe serialized access to the physical instrument.

---

# AGENTS.md

## Project context

This project is considering a reusable Python library for controlling the **Siglent SPD3303X / SPD3303X-E** programmable DC power supply.

The main goals are:

1. Determine whether an adequate reusable Python library already exists.
2. Understand the SPD3303X communication stack in detail.
3. If building a new library, design it so transport details are cleanly separated from the device-level API.
4. Prefer a small, maintainable, testable lab-instrument driver rather than a large framework unless there is a clear benefit.

The user cares about understanding the protocol stack precisely, not just making a quick script work.

## Existing Python libraries / implementations found

### 1. `spd3303x` / `python-spd3303x`

This is the most directly relevant existing package.

- PyPI: https://pypi.org/project/spd3303x/
- GitHub: https://github.com/geissdoerfer/python-spd3303x

Observed design:

- USB transport:
  - PyVISA / PyVISA-py
  - USBTMC underneath
- LAN transport:
  - `python-vxi11`
  - VXI-11 underneath
- Application command language:
  - SCPI-style ASCII commands

Important implementation details seen in the existing package:

- `write_termination = "\n"`
- `read_termination = "\n"`
- approximately 100 ms delay after write/query operations
- public API mainly covers:
  - set voltage
  - get voltage setpoint
  - measure voltage
  - set current
  - get current setpoint
  - measure current
  - measure power
  - output enable/disable

This package is usable, but its feature surface is relatively small compared with the instrument's available SCPI functionality.

### 2. `rf-bench-drivers-siglent`

PyPI: https://pypi.org/project/rf-bench-drivers-siglent/

Notable because it supports Siglent instruments and uses raw TCP SCPI over Ethernet, including SPD3303X-E testing.

Relevant approach:

- raw TCP socket
- port 5025
- avoids requiring VISA or VXI-11 for LAN usage

Useful as a reference for a simpler dependency-minimized transport design.

### 3. Other wrappers / frameworks

There are also smaller wrappers and broader testbench frameworks such as:

- Swallowtail SPD3303X API
- `psytestbench`

These may be worth inspecting for API ideas, but they are less directly compelling than the two above.

## Physical communication interfaces

SPD3303X / SPD3303X-E remote control primarily uses:

### USB

Physical connector:

- USB Type-B device port on the instrument
- typically USB-A to USB-B cable from PC to instrument

Protocol stack:

```text
Python API
  -> PyVISA / PyVISA-py
  -> USBTMC
  -> USB
  -> SPD3303X
```

The device is not fundamentally a serial COM-port device. It uses **USBTMC**, the USB Test and Measurement Class.

Typical VISA resource style:

```text
USB0::0x0483::0x7540::<serial>::INSTR
```

Exact IDs depend on unit / firmware / VISA enumeration.

### Ethernet / LAN

Physical connector:

- RJ45 Ethernet

There are at least two useful LAN control paths.

#### VXI-11

Protocol stack:

```text
Python API
  -> python-vxi11 or VISA
  -> VXI-11
  -> ONC RPC / TCP/IP
  -> Ethernet
  -> SPD3303X
```

Typical VISA resource form:

```text
TCPIP0::<instrument-ip>::inst0::INSTR
```

#### Raw TCP socket

SPD3303X and SPD3303X-E support SCPI over raw TCP socket on:

```text
TCP port 5025
```

Conceptually:

```text
Python socket
  -> TCP port 5025
  -> SCPI ASCII
  -> SPD3303X
```

Important:

```text
VXI-11 != raw TCP port 5025
```

They are different transports carrying essentially the same instrument command language.

Older Siglent application notes were not always consistent about socket availability, but newer official Siglent material explicitly lists TCP 5025 support for SPD3303X / SPD3303X-E. For maximum backward compatibility, VXI-11 may be a safer baseline, while raw TCP is attractive as a low-dependency transport.

## Command language

The instrument uses an ASCII SCPI-like command set.

Important representative commands include:

```text
*IDN?
*SAV 1
*RCL 1

INST CH1

MEAS:VOLT? CH1
MEAS:CURR? CH1
MEAS:POWE? CH1

CH1:VOLT 5
CH1:VOLT?
CH1:CURR 0.5
CH1:CURR?

OUTP CH1,ON

OUTP:TRACK 0
OUTP:TRACK 1
OUTP:TRACK 2

OUTP:WAVE CH1,ON

TIMER:SET ...
TIMER CH1,ON

SYST:ERR?
SYST:VERS?
SYST:STAT?

IPADDR
MASKADDR
GATEADDR
DHCP
```

Also useful for remote operation:

```text
*LOCK
*UNLOCK
*LOCK?
```

These front-panel lock commands are documented separately by Siglent and are likely worth exposing in a reusable library.

## Important SPD communication quirks

Siglent has an official "SPD Programming Tips" document. These details should be treated as real device constraints rather than accidental hacks.

### Line termination

Use:

```text
LF only: "\n"
```

Avoid extra line-ending characters if possible.

### Command spacing

Siglent recommends approximately:

```text
10 to 100 ms
```

between commands.

### Query behavior

Safer pattern:

```text
write(query-command)
sleep(10-100 ms)
read()
```

rather than assuming arbitrarily fast back-to-back command/query behavior.

The existing `python-spd3303x` package uses roughly 100 ms sleeps, which matches the vendor recommendation.

A reusable driver should probably hide this behavior inside the transport layer so normal device API methods do not need to care about it.

## Useful official references

### Main product / documents

Siglent SPD3303X/X-E product/resources page:

https://www.siglent.com/na/products-overview/spd3303x-x-e/

SPD3303X Quick Start / programming reference:

https://siglentna.com/wp-content/uploads/dlm_uploads/2022/11/SPD3303X_QuickStart_E02A.pdf

Siglent DC power supply document downloads:

https://siglentna.com/resources/documents/dc-power-supplies/

### Programming / communication references

SPD Programming Tips:

https://siglentna.com/operating-tip/spd-programming-tips/

Raw TCP socket Python example:

https://siglentna.com/application-note/programming-example-controlling-an-spd-power-supply-via-sockets-ov/

VXI-11 Python example:

https://siglentna.com/application-note/programming-example-vxi11-python-lan/

PyVISA resource discovery example:

https://siglentna.com/application-note/programming-example-list-connected-visa-compatible-resources-using-pyvisa/

Instrument socket / Telnet port table:

https://siglentna.com/operating-tip/instrument-socket-and-telnet-port-information/

Front-panel lock SCPI commands:

https://siglentna.com/operating-tip/spd-local-front-panel-lock-out-scpi-commands/

Firmware / EasyPower downloads:

https://siglentna.com/service-and-support/firmware-software/dc-power-supplies/

## Recommended architecture if building a new library

The preferred design direction is a thin device API with a clearly separated transport abstraction.

Conceptual structure:

```text
SPD3303X
|
|-- CH1: ProgrammableChannel
|-- CH2: ProgrammableChannel
|-- CH3: FixedChannel
|
|-- save()/recall()
|-- tracking_mode
|-- timer
|-- status
|-- errors
|-- lock_front_panel()
|
`-- Transport
    |-- USBTMCTransport
    |    `-- PyVISA / PyVISA-py
    |
    |-- VXI11Transport
    |    `-- python-vxi11
    |
    `-- SocketTransport
         `-- raw TCP :5025
```

Possible minimal transport protocol:

```python
from typing import Protocol

class Transport(Protocol):
    def write(self, command: str) -> None: ...
    def query(self, command: str) -> str: ...
    def close(self) -> None: ...
```

Transport responsibilities should include:

- LF termination
- command spacing / delay
- timeout handling
- read buffering
- reconnection strategy if desired
- low-level communication errors
- possibly retry policy

Device-layer responsibilities should include:

- channel semantics
- SCPI formatting
- parsing responses
- units / validation
- tracking modes
- timer/list features
- instrument status decoding
- front-panel lock
- save/recall
- clear error reporting

## API style worth considering

Prefer an API where the user does not need to know the transport implementation after connection.

Example:

```python
with SPD3303X.open("TCPIP::192.168.1.50") as psu:
    psu.ch1.voltage = 5.0
    psu.ch1.current_limit = 0.5
    psu.ch1.output = True

    measurement = psu.ch1.measure()
```

Potential alternative explicit constructors:

```python
SPD3303X.from_socket("192.168.1.50")
SPD3303X.from_vxi11("192.168.1.50")
SPD3303X.from_usbtmc(resource)
```

Do not make VISA concepts dominate the public API unless there is a strong reason. The core instrument abstraction is SCPI over interchangeable transports.

## Testing strategy

A transport abstraction enables testing without real hardware.

Example fake transport behavior:

```python
fake = FakeTransport()
psu = SPD3303X(fake)

psu.ch1.voltage = 5.0

assert fake.writes == ["CH1:VOLT 5"]
```

Recommended test layers:

1. SCPI formatting / parsing unit tests
2. status-word decoding tests
3. fake-transport device API tests
4. optional hardware integration tests
5. one integration test per transport if hardware is available

Avoid writing tests that depend on arbitrary sleeps when a fake clock or injected delay policy can be used.

## Open design questions for the next agent

Before implementation, investigate and decide:

1. Whether to:
   - extend/fork `python-spd3303x`, or
   - build a new library with a cleaner transport abstraction.

2. Whether support should target:
   - SPD3303X only,
   - SPD3303X + SPD3303X-E,
   - possibly SPD3303C where command compatibility exists.

3. Whether raw TCP 5025 should be:
   - the preferred LAN backend, or
   - an optional alternative to VXI-11.

4. Whether USB support should use:
   - PyVISA-py only,
   - PyVISA with either NI-VISA or pyvisa-py backend,
   - lower-level USBTMC access directly.

5. Whether to expose:
   - low-level `write()` / `query()` escape hatches,
   - full official command coverage,
   - only a carefully designed high-level API.

6. How to represent measurement results:
   - plain floats,
   - dataclass,
   - optional unit-aware objects.

7. How strict validation should be:
   - instrument limits checked locally,
   - or mostly delegated to the device.

8. Whether to decode `SYST:STAT?` into a typed status object / dataclass.

9. How to model tracking modes:
   - enum preferred over raw integers.

10. Whether timer/list-program functionality is important enough for first release.

## Current recommendation

If the requirement is only basic control, the existing `spd3303x` package is probably adequate.

If the goal is a reusable lab-quality Python driver, a new small package or a substantial refactor/fork is justified because:

- the existing driver exposes only a limited subset of available functionality,
- the transport/device separation can be cleaner,
- raw TCP 5025 support can avoid unnecessary LAN dependencies,
- official SPD quirks can be encapsulated properly,
- testing becomes much easier with an injected transport abstraction.

A good first implementation would likely support:

1. raw TCP 5025
2. USBTMC through PyVISA
3. VXI-11
4. CH1 / CH2 setpoints and measurement
5. CH3 output
6. output state
7. tracking mode
8. status parsing
9. error queue
10. front-panel lock
11. save/recall

Then add timer/list-program functionality after the core API is stable.
