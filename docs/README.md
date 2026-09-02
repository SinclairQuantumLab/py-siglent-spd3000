# Official development references

This directory is the offline, internal-repository reference set used to
implement `py-siglent-spd3000`. The documents remain copyright SIGLENT and are
stored unchanged for engineering traceability. Do not treat their presence in
this repository as a grant to redistribute them publicly.

Hashes are SHA-256. `Retrieved / verified` records when the local file and its
official source were checked, not necessarily the document publication date.

## Instrument manuals and specifications

| Local document | Models | Version | Pages | Retrieved / verified | SHA-256 | Official source | Development use |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| [SPD3303X Quick Start](SPD3303X_QuickStart_E02A.pdf) | SPD3303X, SPD3303X-E | E02A | 44 | 2026-09-02 | `71ba7d35739e131c8093b3904dd3aeb34a5ecfb8d16ce1e3b4d95785727cf6db` | [SIGLENT PDF](https://siglentna.com/wp-content/uploads/dlm_uploads/2022/11/SPD3303X_QuickStart_E02A.pdf) | Primary X/X-E SCPI command reference |
| [SPD3303X Data Sheet](SPD3303X_DataSheet_E03A.pdf) | SPD3303X, SPD3303X-E | E03A | 8 | 2026-09-02 | `5817f9b13935047d451f355fdc1c18b2b7e3a319b8bbdff0ffd91013cc402cee` | [SIGLENT product resources](https://www.siglent.com/na/products-overview/spd3303x-x-e/) | Ranges, resolution, interfaces, accuracy |
| [SPD3000X Series Service Manual](SPD3000X-Series-Service-Manual_E01B.pdf) | SPD3303X, SPD3303X-E | E01B | 48 | 2026-09-02 | `7d1ec68217b8c71f6801a94a52834426ae1affdd0ce67aca7c00ac4ef88fae5e` | [SIGLENT resource center](https://www.siglent.com/na/service-support/resource-center/) | USBTMC/VXI-11 interface verification and servicing context |
| [SPD3303C Quick Start](SPD3303C_QuickStart_E02A.pdf) | SPD3303C | E02A | 33 | 2026-09-02 | `38d05d978f661fc0d01c508528bcb8833524400b61881e7acbb9aee3bd72c667` | [SIGLENT PDF](https://siglent.oss-cn-shenzhen.aliyuncs.com/English_content/Document/DC%20Power%20Supplies/SPD3303C_QuickStart_E02A.pdf) | Primary C SCPI subset, status bits, USBTMC support |
| [SPD3303C Data Sheet](SPD3303C_Datasheet_E02A.pdf) | SPD3303C | E02A | 6 | 2026-09-02 | `a7533dd853c63443e9e7aafbd0a5b75fc109786216f115a1dcd13d6daa418f8e` | [SIGLENT PDF](https://siglent.oss-cn-shenzhen.aliyuncs.com/English_content/Document/DC%20Power%20Supplies/SPD3303C_Datasheet_E02A.pdf) | C ranges, 10 mV/10 mA resolution, USB Device interface |
| [SPD3303C Service Manual](SPD3303C-Service-Manual_E01B.pdf) | SPD3303C | E01B | 30 | 2026-09-02 | `5e4c968199edd468576b18ef348b63e719f6b71a77fbfde8fa16a12ab32ee420` | [SIGLENT PDF](https://siglent.oss-cn-shenzhen.aliyuncs.com/English_content/Document/DC%20Power%20Supplies/SPD3303C-Service-Mannual_E01B.pdf) | C interface and servicing context |

## Official programming notes

| Local document | Pages | Retrieved / verified | SHA-256 | Official source | Development use |
| --- | ---: | --- | --- | --- | --- |
| [SPD programming tips](<SPD programming tips.pdf>) | 3 | 2026-09-02 | `29637ed3abdec74b8652f6cfb3bbe1dd631d2fbb031f29a42a827466346d9e15` | [SIGLENT article](https://siglentna.com/operating-tip/spd-programming-tips/) | LF-only termination, 10-100 ms spacing, delayed query reads |
| [VXI-11 and Python example](<Programming Example_ Using VXI11 (LXI) and Python for LAN control without sockets.pdf>) | 4 | 2026-09-02 | `bbc62fbd26f688779707079d3d20f9cfac54a2f7af89a13f46448a5af6af3c4a` | [SIGLENT article](https://siglentna.com/application-note/programming-example-vxi11-python-lan/) | X/X-E VXI-11 connection reference |
| [Raw socket Python example](<Programming Example_ Controlling an SPD power supply via Sockets over LAN.pdf>) | 3 | 2026-09-02 | `a257a2939eaef274235ab226025182e0b947667a8e786904a082736cb3222b75` | [SIGLENT PDF](https://siglentna.com/application-note/programming-example-controlling-an-spd-power-supply-via-sockets-ov/?pdf=19789) | Raw TCP port 5025 for SPD3303X/X-E |
| [Socket and Telnet port table](<Instrument Socket and Telnet Port Information.pdf>) | 2 | 2026-09-02 | `d91577c37ab6e8e977f02b92b12320da6d4d64bc421e7aa2a8efb82060d14aba` | [SIGLENT PDF](https://siglentna.com/operating-tip/instrument-socket-and-telnet-port-information/?pdf=20244) | Confirms X/X-E port 5025 and no SPD3303C socket support |
| [PyVISA resource discovery example](<Programming Example_ List connected VISA compatible resources using PyVISA.pdf>) | 3 | 2026-09-02 | `bb8cb64f962fd6b889817b68766ca2923c1ad0bd4d2e4fa05d8862b3d7ef1265` | [SIGLENT PDF](https://siglentna.com/application-note/programming-example-list-connected-visa-compatible-resources-using-pyvisa/?pdf=7054) | VISA resource discovery and USB/TCPIP resource forms |
| [Front-panel lock SCPI commands](<SPD Local Front Panel Lock Out SCPI commands.pdf>) | 2 | 2026-09-02 | `e9a6c72ac30ad93783400000fa4fa3202f3e23fc27e85ffc49487fb1f8622465` | [SIGLENT PDF](https://siglentna.com/operating-tip/spd-local-front-panel-lock-out-scpi-commands/?pdf=15906) | `*LOCK`, `*UNLOCK`, and model-specific `*LOCK?` support |

## Live vendor pages not archived as binaries

- [SPD3303X/X-E product and resource page](https://www.siglent.com/na/products-overview/spd3303x-x-e/)
- [SPD3303C product and resource page](https://www.siglent.com/int/products-overview/spd3303c/)
- [DC power supply firmware and software](https://siglentna.com/service-and-support/firmware-software/dc-power-supplies/)

Firmware binaries are intentionally excluded: they are not build inputs and
are hardware-revision-sensitive.

## API interpretation note: canonical and friendly names

SCPI-derived root names own validation and instrument I/O. Modernized names are
thin, developer-friendly aliases:

- IEEE common commands lose the leading `*`:
  - `sav(slot)` -> `save(slot)`
  - `rcl(slot)` -> `recall(slot)`
  - `lock()` and `unlock()` preserve the remaining command names.
  - `locked` is the necessary `*LOCK?` exception because one Python member
    cannot be both a method and a boolean property.
- Root network commands have optional grouped aliases:
  - `ipaddr` -> `network.host`
  - `maskaddr` -> `network.subnet_mask`
  - `gateaddr` -> `network.gateway`
  - `dhcp` -> `network.dhcp`

The complete mapping and rationale are in the project README.

## API interpretation note: `OUTPut`

The driver normally mirrors the canonical SCPI tree. `OUTPut` is the explicit
convenience exception because it is used disproportionately often:

```python
psu.output(Channel.CH1, OutputState.ON)
psu.output("CH1", "ON")
psu.ch1.output = True
print(psu.ch1.output)
```

All three writes above map to `OUTP CH1,ON`. The getter is not an `OUTP?` command;
the manuals document no such query. CH1 and CH2 getters issue a fresh
`SYST:STAT?` and decode bits 4 and 5. No CH3 status bit is documented, so CH3
remains writable but reading `psu.ch3.output` raises
`UnsupportedFeatureError`. The implementation never substitutes cached intent
for hardware state.

The C manual supplies the otherwise omitted `11 = series` interpretation for
status bits 2 and 3. The `OUTP:TRACK` command arguments remain a separate
encoding: `0 = independent`, `1 = series`, and `2 = parallel`.
