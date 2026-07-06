# OWON XDM1241 Meter Display

![SquatchLab Logo](images/squatchlab-logo-128.png)

Local web app and OBS overlay toolkit for the OWON XDM1241 bench multimeter.

The app connects over USB serial, polls live readings, and serves three browser views:

- Admin control panel
- Transparent digital overlay
- Live graph overlay

## Features

- OWON XDM1241 USB serial integration with auto-discovery
- Browser admin UI with separate sections for Meter Controls, Overlay Settings, and Graph Settings
- Live digital overlay view for OBS
- Live graph view for OBS
- Per-function graph settings and persisted state
- Graph scale modes:
  - Auto Window
  - Fixed Range
  - Manual (explicit min/max)
- Graph time controls:
  - Sample History slider: 0 to 300 seconds, step 5
  - Visible Window slider: 0 to Sample History, step 5
- Graph precision control
- Center on Zero toggle (function-aware)
- Reset Graph and Default Settings actions
- Manual OWON settings refresh endpoint (separate from graph reset)
- JSON API for integrations

## Graph Behavior

- Selected graph range is stored separately per meter function
- Graph range controls do not change hardware range selection
- Positive one-sided ranges are pinned with zero at the bottom
- Center on Zero enforces symmetric negative/positive span
- Zero axis label is always shown whenever zero is inside the visible Y range

## Supported Modes

- DC Voltage
- AC Voltage
- DC Current
- AC Current
- Resistance
- 4-Wire Resistance
- Continuity
- Diode
- Capacitance
- Frequency
- Period
- Temperature (PT100)

## Fixed Range Profiles (Current Defaults)

- DC Voltage: 5V, 10V, 25V, 50V, 500V, 1000V
- AC Voltage: 5V, 50V, 500V, 750V
- Current: 500uA, 5mA, 50mA, 500mA
- Resistance: 500ohm, 5kohm, 50kohm, 500kohm, 5Mohm, 50Mohm
- Capacitance: 50nF, 500nF, 5uF, 50uF, 500uF, 5mF, 50mF

Note: 10V and 25V DC entries are graph convenience ranges.

## Project Structure

```text
.
├── images/
├── templates/
│   ├── admin.html
│   ├── base.html
│   ├── graph.html
│   └── overlay.html
├── LICENSE
├── owon_meter.py
├── owon_xdm1241_obs_app.py
├── README.md
└── ui.py
```

## Requirements

- Python 3.10+
- OWON XDM1241
- USB connection
- Flask
- pySerial

Install dependencies:

```bash
pip3 install flask pyserial
```

## Run

```bash
python3 owon_xdm1241_obs_app.py
```

Optional manual serial port:

```bash
python3 owon_xdm1241_obs_app.py --port /dev/cu.usbserial-2120
```

Optional web port:

```bash
python3 owon_xdm1241_obs_app.py --web-port 5050
```

## Web Endpoints

Default base URL:

```text
http://127.0.0.1:5050
```

- /: Admin UI
- /overlay: OBS digital overlay
- /graph: OBS graph overlay
- /api/status: Live status JSON
- /api/mode: Change function/mode
- /api/overlay-settings: Save overlay settings
- /api/graph-settings: Save graph settings
- /api/reset-graph: Clear graph window
- /api/reread-settings: Refresh OWON mode/range/speed
- /api/command: Send direct command
- /api/shutdown: Stop app

## OBS Integration

Add Browser Sources pointing to:

- Digital overlay: http://127.0.0.1:5050/overlay
- Live graph: http://127.0.0.1:5050/graph

## About SquatchLab

SquatchLab develops practical tools for electronics repair, embedded systems, reverse engineering, and hardware-focused content creation.

SquatchCode is the software and open-source development division of
SquatchLab, providing source code, downloads, documentation, and
tutorials.

Website: https://squatchcode.com

![SquatchCode QR Code](images/qr-code-256.png)

## License

MIT License. See [LICENSE](LICENSE).
