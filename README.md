# OWON XDM1241 Meter Display

![SquatchLab Logo](images/squatchlab-logo-128.png)

Built by SquatchLab.
Professional tools for electronics, repair, reverse engineering, and content creation.

------------------------------------------------------------------------

A local web-based display and OBS overlay application for the **OWON
XDM1241** bench multimeter.

The application connects to the meter over USB serial, reads live
measurements, and serves browser-based views for administration, OBS
overlays, and live graphing.

## Features

-   USB communication with the OWON XDM1241
-   Automatic meter discovery
-   Browser-based administration interface
-   OBS digital meter overlay
-   OBS live graph overlay
-   Manual OWON settings refresh (avoids slowing live updates)
-   Graph reset and configurable graph display ranges
-   Orange-on-black SquatchLab theme inspired by the OWON display
-   HTTP/JSON API for future integrations

Supported measurement modes include:

-   Resistance
-   4-Wire Resistance
-   DC Voltage
-   AC Voltage
-   DC Current
-   AC Current
-   Continuity
-   Diode
-   Capacitance
-   Frequency
-   Period
-   Temperature (PT100)

## Project Structure

``` text
.
├── images/
│   ├── icon.png
│   ├── qr-code-128.png
│   ├── qr-code-256.png
│   ├── squatchcode-logo-128.png
│   ├── squatchcode-logo-1024.png
│   ├── squatchcode-logo-and-name-240x99.png
│   ├── squatchlab-logo-128.png
│   ├── squatchlab-logo-1024.png
│   └── squatchlab-logo-and-name-320x132.png
├── LICENSE
├── owon_xdm1241_obs_app.py
└── README.md
```

## Requirements

-   Python 3.10+
-   OWON XDM1241
-   USB connection
-   Flask
-   pySerial

Install dependencies:

``` bash
pip3 install flask pyserial matplotlib
```

## Running

Launch the application:

``` bash
python3 owon_xdm1241_obs_app.py
```

Or specify a serial port manually:

``` bash
python3 owon_xdm1241_obs_app.py --port /dev/cu.usbserial-2120
```

The application automatically opens the administration page in your
browser.

## Web Interface

Default address:

``` text
http://127.0.0.1:5050
```

  URL             Purpose
  --------------- ----------------------------------
  `/`             Administration and OWON controls
  `/overlay`      OBS digital meter display
  `/graph`        OBS live graph display
  `/api/status`   Live JSON status

## OBS Integration

Create Browser Sources using:

Digital Meter

``` text
http://127.0.0.1:5050/overlay
```

Live Graph

``` text
http://127.0.0.1:5050/graph
```

The overlays are designed with transparent backgrounds so they can be
composited directly into OBS scenes.

## Planned Documentation

Additional documentation will cover:

-   Hardware setup
-   OBS scene examples
-   Supported SCPI commands
-   Custom display themes
-   Stream layouts
-   Troubleshooting
-   Future meter support

## About SquatchLab

SquatchLab develops practical tools for electronics repair, embedded
systems, reverse engineering, hardware restoration, and technical
content creation.

SquatchCode is the software and open-source development division of
SquatchLab, providing source code, downloads, documentation, and
tutorials.

**Website**
Scan the QR code or visit **https://squatchcode.com** for documentation, videos, downloads, and additional SquatchLab projects.

![SquatchCode QR Code](images/qr-code-256.png)


## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
