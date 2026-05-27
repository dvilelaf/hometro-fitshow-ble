# Findings

## Device

Initial scan identified the treadmill as:

- name: `FS-0099C3`
- address: `66:99:D4:F6:7B:30`
- model string: `FS-BT-D2`
- manufacturer string: `FITSHOW`
- services: Heart Rate `180d`, Fitness Machine `1826`, vendor service `fff0`

The treadmill appears to accept one BLE central at a time. FitShow could not
discover/connect while the Python monitor was connected, and worked again after
the monitor disconnected.

## GATT

Important characteristics:

- FTMS Treadmill Data: `00002acd-0000-1000-8000-00805f9b34fb`, notify
- FTMS Fitness Machine Status: `00002ada-0000-1000-8000-00805f9b34fb`, notify
- FTMS Control Point: `00002ad9-0000-1000-8000-00805f9b34fb`, write + indicate
- FitShow vendor notify: `0000fff1-0000-1000-8000-00805f9b34fb`
- FitShow vendor write: `0000fff2-0000-1000-8000-00805f9b34fb`

Full dump: `captures/gatt-fs-0099c3.json`.

## Physical control capture

Capture file: `captures/notify-physical-4-6-stop.ndjson`.

Manual sequence:

- start from treadmill controls
- speed reached `4.00 km/h`
- speed reached `6.00 km/h`
- stop from treadmill controls

Observed FTMS Treadmill Data examples:

```text
84 04 90 01 01 00 00 00 00 ff ff ff 04 00  speed=4.00km/h distance=1m
84 04 58 02 16 00 00 01 00 ff ff ff 17 00  speed=6.00km/h distance=22m
84 04 00 00 00 00 00 00 00 ff ff ff 00 00  speed=0.00km/h distance=0m
```

The first speed field is FTMS instantaneous speed in hundredths of km/h:

- `90 01` = `0x0190` = 400 = `4.00 km/h`
- `58 02` = `0x0258` = 600 = `6.00 km/h`

Distance is present as a 24-bit little-endian value in meters.

## FitShow vendor notify frames

The vendor notify characteristic mirrors the same state in a compact frame:

```text
02 51 00 51 03                                      idle
02 51 02 03 50 03                                   countdown 3
02 51 03 28 00 04 00 01 00 00 00 01 00 00 00 7e 03 running 4.0
02 51 03 3c 00 17 00 16 00 0f 00 1b 00 00 00 7b 03 running 6.0
02 51 04 38 00 29 00 34 00 25 00 39 00 00 00 6c 03 stopping 5.6
```

Frame format observed so far:

- byte 0: `02` STX
- byte 1: command/channel, usually `51`
- byte 2: state: `00` idle, `02` countdown, `03` running, `04` stopping
- bytes before final `03`: payload plus checksum
- checksum: XOR of bytes after STX up to the byte before checksum
- final byte: `03` ETX

For running/stopping frames, bytes 3-4 appear to be speed in tenths of km/h:

- `28 00` = 40 = `4.0 km/h`
- `3c 00` = 60 = `6.0 km/h`
- `38 00` = 56 = `5.6 km/h`

The next fields appear to include elapsed seconds and distance meters, but need
more captures before treating every field as stable.

## FTMS control point

Control point characteristic:

```text
00002ad9-0000-1000-8000-00805f9b34fb
```

The treadmill accepts standard FTMS control point commands. Capture file:
`captures/ftms-control-test.ndjson`.

Observed responses:

```text
00        request control      -> 80 00 01 success
02 64 00  set speed 1.00 km/h -> 80 02 01 success
07        start/resume         -> 80 07 01 success
08 01     stop                 -> 80 08 01 success
```

FTMS target speed uses hundredths of km/h, little endian:

- `02 64 00` = set target speed to `1.00 km/h`

This means basic open-source control can likely use FTMS first, with the FitShow
vendor protocol as a compatibility/diagnostic layer.

Physical behavior was confirmed: after setting target speed to `1.00 km/h`, the
standard FTMS `start/resume` command made the belt move, and `stop` stopped it.

The FTMS pause procedure behaves like a controlled stop rather than a full
workout pause. In a targeted test at `1.0 km/h`, `pause` ramped the belt down to
zero and reset the telemetry counters when idle. Sending FTMS `start/resume`
afterwards restarted the belt and recovered the previous target speed, but the
session counters restarted.
