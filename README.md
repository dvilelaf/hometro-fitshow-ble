# HomeTro / FitShow BLE reverse engineering

Python toolkit for reverse engineering the BLE protocol used by a HomeTro
JF-H-40DA treadmill controlled by FitShow-like OEM apps.

The first goal is evidence collection:

- scan nearby BLE devices
- identify the treadmill advertisement
- list GATT services and characteristics
- monitor notifications while the official app changes treadmill state
- replay candidate commands from Python

The project deliberately keeps protocol assumptions out of the BLE transport
layer. Once real captures show the packet format, decoding and command builders
can be added behind a small protocol API instead of rewriting the tooling.

## Safety

Treat write commands as physical actuator commands. Start with the treadmill
empty, use the safety key, keep one hand near the stop control, and test at the
lowest speed. Prefer `--response` only when the characteristic supports
write-with-response.

## Setup

```bash
cd /home/david/repos/hometro-fitshow-ble
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

On Linux, your user may need Bluetooth permissions. If scanning fails, try:

```bash
bluetoothctl power on
rfkill unblock bluetooth
```

For one-off debugging, running with `sudo -E` may reveal whether the issue is
permissions, but the repo should not require root as a normal workflow.

## CLI workflow

Scan nearby devices:

```bash
hometro-ble scan --timeout 15 --out captures/scan.json
```

Look for names such as `FS-`, `FitShow`, `Treadmill`, `JF`, `HW`, or unnamed
devices with strong RSSI that appear only when the treadmill is powered.

List GATT services and characteristics:

```bash
hometro-ble gatt AA:BB:CC:DD:EE:FF --read --out captures/gatt.json
```

On macOS, the address shown by Bleak is usually a CoreBluetooth UUID rather than
the public BLE MAC address.

Monitor all notification and indication characteristics:

```bash
hometro-ble notify AA:BB:CC:DD:EE:FF --out captures/notify.ndjson
```

Then use FitShow to start, stop, and change speed. Record what you did and when:

```text
18:42:10 app start
18:42:20 speed 1.0 -> 1.5
18:42:30 speed 1.5 -> 2.0
18:42:40 stop
```

Write a candidate command once you know the writable characteristic:

```bash
hometro-ble write AA:BB:CC:DD:EE:FF \
  --char 0000fff2-0000-1000-8000-00805f9b34fb \
  --hex "aa 01 02 ad" \
  --out captures/writes.ndjson
```

Try standard FTMS control commands:

```bash
hometro-ble ftms AA:BB:CC:DD:EE:FF request-control --out captures/ftms.ndjson
hometro-ble ftms AA:BB:CC:DD:EE:FF speed --speed 1.0 --out captures/ftms.ndjson
hometro-ble ftms AA:BB:CC:DD:EE:FF start --out captures/ftms.ndjson
hometro-ble ftms AA:BB:CC:DD:EE:FF stop --out captures/ftms.ndjson
```

Run a short controlled FTMS session. This requests control, sets speed, starts,
monitors telemetry, and sends stop in a `finally` block:

```bash
hometro-ble session AA:BB:CC:DD:EE:FF \
  --speed 1.0 \
  --duration 10 \
  --out captures/session-1kmh.ndjson
```

Run the local web UI:

```bash
hometro-ble web AA:BB:CC:DD:EE:FF --host 127.0.0.1 --port 8000
```

Replay a small file:

```bash
hometro-ble replay AA:BB:CC:DD:EE:FF \
  --char 0000fff2-0000-1000-8000-00805f9b34fb \
  --file captures/replay-start-stop.txt \
  --out captures/replay.ndjson
```

Replay files can be plain hex:

```text
aa 01 02 ad
aa 02 00 ac
```

Or NDJSON:

```json
{"char":"0000fff2-0000-1000-8000-00805f9b34fb","hex":"aa 01 02 ad","delay_ms":500}
```

## Useful tools

- Python: `bleak` for cross-platform BLE GATT scanning, reads, writes, and
  notifications.
- Linux: BlueZ tools (`bluetoothctl`, `btmon`) and Wireshark for host-side HCI
  captures.
- macOS: LightBlue, nRF Connect, and Apple PacketLogger if you have Additional
  Tools for Xcode installed.
- iPhone: nRF Connect and LightBlue for quickly inspecting services,
  characteristics, descriptors, reads, writes, and notifications.
- Android, if available later: it is often the easiest platform for capturing
  app-side BLE traffic because HCI snoop logs can be enabled on many devices.

## Architecture

Current modules:

- `cli.py`: argument parsing and user-facing output only
- `ble_ops.py`: BLE scan/connect/GATT/notify/write orchestration
- `models.py`: serializable records and event types
- `capture.py`: JSON/NDJSON persistence
- `protocol.py`: byte and checksum helpers for protocol hypotheses
- `replay.py`: replay file parsing

The intended next layer is:

- `decoder.py`: parse telemetry packets into speed, time, distance, status
- `commands.py`: build start, stop, and speed command frames
- `devices/hometro_jf_h_40da.py`: model-specific characteristic mapping
- `integrations/`: Home Assistant, Zwift bridge, or a Python API facade

Current higher-level modules:

- `controller.py`: persistent Python API around one treadmill connection
- `web.py`: FastAPI server for HTTP control and server-sent telemetry events
- `web_static/`: no-build browser UI

## FitShow/OEM protocol notes

Many OEM BLE fitness devices expose vendor-specific 128-bit services or common
short UUIDs such as `fff0`, `fff1`, `fff2`, etc. Do not assume these meanings
from UUIDs alone. The reliable path is:

1. identify which characteristic notifies during normal operation
2. identify which characteristic FitShow writes to when changing controls
3. compare packet deltas for simple transitions
4. test checksum hypotheses in `protocol.py`
5. build high-level commands only after repeatable evidence

Keep raw captures private until you have checked whether they contain stable
device identifiers.
