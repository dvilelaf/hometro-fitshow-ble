# Reverse engineering plan

## 1. Identify the treadmill

Power the treadmill off, run a scan, power it on, and scan again. The target is
usually the new device with strong RSSI.

```bash
hometro-ble scan --timeout 15 --out captures/scan-off.json
hometro-ble scan --timeout 15 --out captures/scan-on.json
```

Fields worth comparing:

- address or CoreBluetooth UUID
- local name
- advertised service UUIDs
- manufacturer data
- RSSI

## 2. Dump GATT

```bash
hometro-ble gatt ADDRESS --read --out captures/gatt.json
```

Mark each characteristic as:

- readable telemetry/config
- notify/indicate telemetry
- writable command channel
- unknown

## 3. Capture notifications

```bash
hometro-ble notify ADDRESS --out captures/notify-baseline.ndjson
```

Suggested manual script:

```text
00s idle
10s FitShow start
20s speed 1.0
30s speed 1.5
40s speed 2.0
50s stop
```

Use repeated runs. If the same action produces mostly the same packet, the
remaining changing bytes are likely counters, timestamps, or checksums.

## 4. Capture writes

Passive interception of phone-to-treadmill BLE writes is platform-dependent.
Good options:

- Android HCI snoop log, then Wireshark
- Linux host running FitShow-like client code, captured with `btmon`
- nRF Connect or LightBlue manual writes if the app protocol is simple enough

FitShow on iPhone is useful for behavior comparison, but iOS generally does not
make third-party app BLE traffic easy to export.

## 5. Replay carefully

Replay only one variable at a time:

- same characteristic
- same connection state
- one frame
- treadmill empty
- lowest speed

Record:

- payload
- response/no-response
- physical behavior
- any notification changes after the write

## 6. Decode telemetry

Likely telemetry fields to search for:

- speed in km/h as integer tenths, e.g. `25` for `2.5`
- elapsed seconds or minutes/seconds
- distance in meters or hundredths of km
- status byte: idle/running/paused/error/safety-key
- checksum byte at end

Use simple transitions first. For example, change only speed from 1.0 to 1.1 and
look for a byte changing by exactly `1`.
