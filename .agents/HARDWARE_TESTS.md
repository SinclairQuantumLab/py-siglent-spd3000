# Physical-device validation checklist

This is the ordered acceptance checklist for validating `py-siglent-spd3000` against a physical SPD3303X, SPD3303X-E, or SPD3303C.
Run the sections in order because later sections can energize outputs, overwrite instrument state, or interrupt network connectivity.
Record every unexpected raw response before changing the parser or API.

## Test record

- [ ] Record the date, operator, Git commit, Python version, package installation command, and host operating system.
- [ ] Record the instrument model, serial number, firmware version, and enabled connection method.
- [ ] Record the external DMM, oscilloscope, or electronic-load model and calibration status when it is used for electrical verification.
- [ ] Record the starting IP address, subnet mask, gateway, DHCP state, tracking mode, lock state, CH1/CH2 setpoints, timer programs, waveform-display states, and output states before any write test.
- [ ] Reserve one timer group and one save/recall slot that may be overwritten during the run.

## Required safety gate

- [ ] Disconnect sensitive DUTs before running any write or output test.
- [ ] Either leave every output unloaded or connect only known loads and instruments rated for the planned voltage, current, polarity, and combined tracking-mode voltage or current.
- [ ] Treat CH3 as a fixed-voltage source whose state cannot be queried through the documented SCPI interface.
- [ ] Start with `min_command_interval_ms=100` and `timeout_s=5.0`.
- [ ] Confirm that CH1, CH2, and CH3 are off from the front panel before beginning.
- [ ] Confirm that the front panel remains accessible for emergency output shutdown and network recovery.
- [ ] Do not run series or parallel tracking tests until the external wiring is explicitly verified for that mode.
- [ ] Do not run network-write tests over the network connection being modified.
- [ ] Stop immediately if identity is unexpected, status parsing fails, an output cannot be disabled, or the instrument reports an unexplained error.

## 1. Connection and identity smoke test

- [ ] `CON-01`: Open and close one connection without leaking an exception or leaving the instrument session busy.
- [ ] `CON-02`: Verify that the connection-time `*IDN?` identifies exactly one supported `spd.Model`.
- [ ] `CON-03`: Query `psu.idn` again and verify manufacturer, model, serial number, firmware version, and preserved raw response.
- [ ] `CON-04`: Verify that `psu.capabilities` matches the detected model.
- [ ] `CON-05`: Verify that `psu.settings.timeout` and `psu.settings.min_command_interval` match the requested values.
- [ ] `CON-06`: Repeat connect, identify, and close ten times to expose stale sockets, VISA handles, or VXI-11 sessions.

## 2. Read-only command and parser test

- [ ] `READ-01`: Query `psu.system.version` and record the raw version string.
- [ ] `READ-02`: Query `psu.system.status` and compare its raw word, operating mode, regulation modes, output bits, timer bits, and waveform bits with the front panel.
- [ ] `READ-03`: Query CH1 and CH2 programmed voltage and current values and compare them with the front panel settings.
- [ ] `READ-04`: Query CH1 and CH2 measured voltage and current with the outputs off and confirm plausible near-zero readings.
- [ ] `READ-05`: On SPD3303X/X-E, query CH1 and CH2 measured power and confirm consistency with measured voltage multiplied by measured current within instrument resolution.
- [ ] `READ-06`: After identifying an SPD3303C over USBTMC, confirm that power measurement, timer, waveform, network, and `locked` operations raise `UnsupportedFeatureError` before further device I/O and that its capabilities mark raw socket and VXI-11 unavailable.
- [ ] `READ-07`: On SPD3303X/X-E, query `psu.ipaddr`, `psu.maskaddr`, `psu.gateaddr`, and `psu.dhcp` and compare them with the front panel network settings.
- [ ] `READ-08`: On SPD3303X/X-E, verify that `psu.network.host`, `subnet_mask`, `gateway`, and `dhcp` return the same values as the canonical root properties.
- [ ] `READ-09`: On SPD3303X/X-E, query `psu.locked` and compare it with actual front-panel behavior.
- [ ] `READ-10`: Query `psu.system.error` only after the preceding queries and require the no-error result.
- [ ] `READ-11`: Repeat `idn`, status, setpoint, and measurement queries 100 times at the 100 ms interval and require zero malformed, truncated, stale, or timed-out responses.

## 3. SCPI-shaped source-setting round trip

- [ ] `SET-01`: Save the initial CH1 and CH2 voltage and current settings for cleanup.
- [ ] `SET-02`: Select CH1 through `psu.instrument`, query it back, select CH2, and query it back.
- [ ] `SET-03`: Set CH1 to a low model-aligned voltage and current limit, query both properties, and require exact round-trip values at the model resolution.
- [ ] `SET-04`: Repeat the same voltage and current round trip on CH2.
- [ ] `SET-05`: Repeat one setter using the documented minimum value and one using the documented maximum value while all outputs remain off.
- [ ] `SET-06`: Restore the initial CH1 and CH2 voltage and current settings and query them back.
- [ ] `SET-07`: Query `psu.system.error` and require the no-error result.

## 4. CH1 and CH2 output-state test

- [ ] `OUT-01`: Set both programmable channels to safe test voltage and current limits while their outputs are off.
- [ ] `OUT-02`: Enable CH1 with `psu.output(spd.Channel.CH1, spd.OutputState.ON)` and require `psu.ch1.output is True` and `psu.system.status.ch1.output is True`.
- [ ] `OUT-03`: Verify CH1 voltage with the instrument measurement and an external meter or known load.
- [ ] `OUT-04`: Disable CH1 through `psu.ch1.output = False` and require both status paths to become false.
- [ ] `OUT-05`: Repeat the regular-command and boolean-property checks on CH2.
- [ ] `OUT-06`: Toggle CH1 and CH2 ten times each and require every fresh status query to match the requested state.
- [ ] `OUT-07`: Verify that no output getter is satisfied from a cached write by changing the output at the front panel between two property reads.
- [ ] `OUT-08`: Leave CH1 and CH2 off and query `psu.system.error` for the no-error result.

## 5. CH3 output test

- [ ] `CH3-01`: Confirm that CH3 is unloaded or attached to a correctly rated verification instrument.
- [ ] `CH3-02`: Enable and disable CH3 through `psu.output()` or `psu.ch3.output` and confirm the physical output and front-panel indication.
- [ ] `CH3-03`: Verify that reading `psu.ch3.output` raises `UnsupportedFeatureError` without issuing a query or reporting cached intent as hardware state.
- [ ] `CH3-04`: Leave CH3 off.

## 6. SPD3303X/X-E waveform and timer test

- [ ] `WAVE-01`: Save the initial CH1 and CH2 waveform-display status bits.
- [ ] `WAVE-02`: Enable and disable each waveform display with `psu.output.wave(channel, spd.WaveformState.ON)` and `OFF`, then verify the corresponding `SYSTem:STATus?` bit and front-panel display.
- [ ] `WAVE-03`: Restore the initial waveform-display states.
- [ ] `TIMER-01`: Save all values from the reserved timer group before overwriting it.
- [ ] `TIMER-02`: Write a safe voltage, current, and short duration to the reserved group and require `timer.set(channel, group)` to return the same three values.
- [ ] `TIMER-03`: Start and stop the timer with `psu.timer(channel, spd.TimerState.ON)` and `OFF`, then verify the corresponding status bit and front-panel behavior.
- [ ] `TIMER-04`: With a safe load, verify that the programmed timer step produces the expected voltage, current limit, and duration.
- [ ] `TIMER-05`: Restore the original timer-group values and leave both timers off.
- [ ] `TIMER-06`: Query `psu.system.error` and require the no-error result.

## 7. Tracking-mode test

- [ ] `TRACK-01`: Disconnect all loads and record the initial tracking mode from `psu.system.status.operating_mode`.
- [ ] `TRACK-02`: Set independent mode with `spd.TrackingMode.INDEPENDENT` and verify the decoded status and front panel.
- [ ] `TRACK-03`: After verifying series-safe wiring, set series mode and verify the decoded status, combined output voltage, and channel behavior.
- [ ] `TRACK-04`: Return to independent mode before changing any wiring.
- [ ] `TRACK-05`: After verifying parallel-safe wiring and matched setpoints, set parallel mode and verify the decoded status, combined current behavior, and channel behavior.
- [ ] `TRACK-06`: Restore the initial mode when it is known, otherwise leave the instrument in independent mode.
- [ ] `TRACK-07`: Leave every output off and require a no-error result.

## 8. Front-panel lock test

- [ ] `LOCK-01`: On SPD3303X/X-E, call `psu.lock()`, require `psu.locked is True`, and confirm that front-panel controls are blocked.
- [ ] `LOCK-02`: Call `psu.unlock()`, require `psu.locked is False`, and confirm that front-panel controls work again.
- [ ] `LOCK-03`: On SPD3303C, verify `lock()` and `unlock()` manually because the model does not document `*LOCK?`.
- [ ] `LOCK-04`: Always leave the front panel unlocked.

## 9. Save and recall test

- [ ] `MEM-01`: Obtain explicit approval to overwrite the reserved setup slot because the previous contents cannot be recovered automatically.
- [ ] `MEM-02`: Set recognizable but safe CH1 and CH2 values and save them through canonical `psu.sav(slot)`.
- [ ] `MEM-03`: Change the values, recall through the friendly `psu.recall(slot)` alias, and verify that both channels return to the saved settings.
- [ ] `MEM-04`: Repeat once with `psu.save(slot)` and canonical `psu.rcl(slot)` to verify that both naming paths share behavior.
- [ ] `MEM-05`: Leave every output off and restore the initial working setpoints.

## 10. Raw SCPI and error-queue test

- [ ] `RAW-01`: Require `psu.scpi.query("*IDN?")` to equal `psu.idn.raw` apart from a fresh query.
- [ ] `RAW-02`: Execute a mixed write/query `CommandBatch` and verify ordered result positions and `None` write results.
- [ ] `RAW-03`: Send one deliberately invalid, harmless command and verify that `psu.system.error` returns a nonzero typed error instead of a parsing failure.
- [ ] `RAW-04`: Drain the error queue until the documented no-error entry is returned.
- [ ] `RAW-05`: Re-run identity and status queries to confirm normal operation after the command error.

## 11. Transport parity test

- [ ] `TRANS-01`: On SPD3303X/X-E, run sections 1, 2, and 4 through raw TCP port 5025.
- [ ] `TRANS-02`: On SPD3303X/X-E, run sections 1, 2, and 4 through VXI-11.
- [ ] `TRANS-03`: Run sections 1, 2, and 4 through a USBTMC VISA resource on every supported model.
- [ ] `TRANS-04`: When available, repeat VISA testing with each supported VISA backend and record the backend version.
- [ ] `TRANS-05`: Require identity, parsed values, exceptions, line termination, and close behavior to be equivalent across transports.
- [ ] `TRANS-06`: Repeat the 100-query stability loop at 10 ms and record whether every supported transport remains reliable at the lower end of the vendor recommendation.

## 12. Gateway parity and arbitration test

- [ ] `GATE-01`: Start the gateway over each physical transport already validated directly.
- [ ] `GATE-02`: Connect through `spd.ConnectionType.GATEWAY` and repeat sections 1, 2, 3, and 4.
- [ ] `GATE-03`: Require direct and gateway-backed calls to return equal semantic types and values.
- [ ] `GATE-04`: Trigger a known canonical southbound error and require the client to reconstruct the same exception type with an explicit remote traceback note.
- [ ] `GATE-05`: Verify that a wrong commit hash is rejected while an equal commit from a dirty working tree is accepted.
- [ ] `GATE-06`: Verify token acceptance and rejection independently from commit compatibility.
- [ ] `GATE-07`: Submit distinguishable multi-command batches from at least two clients concurrently and confirm that commands never interleave within a batch.
- [ ] `GATE-08`: Confirm that the physical connection owner enforces one global command interval across client-session transitions.
- [ ] `GATE-09`: Stop the gateway and confirm that the physical connection closes cleanly and can immediately be reopened directly.

## 13. Network-write and recovery test

- [ ] `NET-01`: Run this section last and control the instrument over USBTMC so changing LAN settings cannot strand the active test session.
- [ ] `NET-02`: Record the original DHCP state, IP address, subnet mask, and gateway both through the driver and from the front panel.
- [ ] `NET-03`: Disable DHCP, set an unused test IP address, subnet mask, and gateway, and query each value back.
- [ ] `NET-04`: Connect to the new address through raw TCP and VXI-11 and repeat the identity smoke test.
- [ ] `NET-05`: Restore the original static configuration or re-enable DHCP as originally configured.
- [ ] `NET-06`: Confirm the restored values from USBTMC and reconnect through the restored network address.
- [ ] `NET-07`: Require the no-error result and retain the recorded recovery procedure with the test log.

## 14. Failure and recovery test

- [ ] `FAIL-01`: During a harmless repeated query, disconnect the selected physical link and require the appropriate canonical connection or timeout exception.
- [ ] `FAIL-02`: Restore the link and verify that a new `SPD3000.connect()` session works without restarting Python or the instrument.
- [ ] `FAIL-03`: Stop a gateway during a query and require a gateway exception rather than an instrument exception.
- [ ] `FAIL-04`: Restart the gateway and verify that a new client session can identify the instrument.

## 15. Mandatory cleanup and final acceptance

- [ ] `END-01`: Disable CH1, CH2, and CH3.
- [ ] `END-02`: Stop both timers and restore the saved timer group.
- [ ] `END-03`: Restore waveform-display states or leave them off if the initial state was not recorded.
- [ ] `END-04`: Restore the initial tracking mode or leave independent mode selected.
- [ ] `END-05`: Unlock the front panel.
- [ ] `END-06`: Restore the initial CH1 and CH2 voltage and current settings.
- [ ] `END-07`: Restore and verify the initial network configuration.
- [ ] `END-08`: Drain the error queue and require its no-error entry.
- [ ] `END-09`: Close the driver and verify that another process can immediately open the instrument.
- [ ] `END-10`: Confirm physically that every output is off before reconnecting a DUT.
- [ ] `END-11`: Attach the completed run record, raw failures, and external measurement results to the tested Git commit.

## Automation boundary

All future automated physical-device cases should use the existing `hardware` pytest marker and preserve the test identifiers above in their names or docstrings.
The default hardware run should include only connection, read-only, source-setting, and cleanup checks.
Output, tracking, memory, raw-error, network-write, and forced-failure sections must require separate explicit opt-ins because they can energize terminals, overwrite persistent state, interrupt connectivity, or deliberately cause errors.
Cleanup must run from a fixture finalizer or equivalent `finally` block even when a test fails.
