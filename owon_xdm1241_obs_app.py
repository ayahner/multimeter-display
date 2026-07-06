#!/usr/bin/env python3
"""
SquatchLab OWON XDM1241 Meter Display

Install:
    pip3 install flask pyserial

Run:
    python3 owon_xdm1241_obs_app.py
"""

from __future__ import annotations

import argparse
import math
import os
import re
import signal
import threading
import time
import webbrowser
from collections import deque
from dataclasses import dataclass
from pathlib import Path
import logging
from typing import Optional

from flask import Flask, jsonify, redirect, render_template_string, request
import serial
from serial.tools import list_ports


DEFAULT_PORT = "auto"
DEFAULT_BAUD = 115200
DEFAULT_WEB_PORT = 5050

APP_DIR = Path.home() / ".owon"
LOG_FILE = APP_DIR / "owon.log"

POLL_SECONDS = 0.25
MODE_POLL_SECONDS = 1.0

GRAPH_WINDOW_SECONDS = 60
GRAPH_MAX_POINTS = int(GRAPH_WINDOW_SECONDS / POLL_SECONDS) + 10
GRAPH_DECIMALS = 3


@dataclass
class MeterMode:
    key: str
    label: str
    command: str
    unit: str
    precision: int = 6
    safety_note: str = ""


MODES: dict[str, MeterMode] = {
    "vdc": MeterMode("vdc", "DC Volts", "CONFigure:VOLTage:DC AUTO", "V", 6),
    "vac": MeterMode("vac", "AC Volts", "CONFigure:VOLTage:AC AUTO", "V", 6),
    "adc": MeterMode("adc", "DC Amps", "CONFigure:CURRent:DC AUTO", "A", 6, "Move leads to the current terminals before measuring current."),
    "aac": MeterMode("aac", "AC Amps", "CONFigure:CURRent:AC AUTO", "A", 6, "Move leads to the current terminals before measuring current."),
    "res": MeterMode("res", "Resistance", "CONFigure:RESistance AUTO", "Ω", 2, "Remove power from the circuit before measuring resistance."),
    "fres": MeterMode("fres", "4-Wire Resistance", "CONFigure:FRESistance AUTO", "Ω", 4, "Use the 4-wire terminals and remove circuit power."),
    "cont": MeterMode("cont", "Continuity", "CONFigure:CONTinuity", "Ω", 2, "Remove power from the circuit before continuity testing."),
    "diode": MeterMode("diode", "Diode", "CONFigure:DIODe", "V", 4, "Remove power from the circuit before diode testing."),
    "cap": MeterMode("cap", "Capacitance", "CONFigure:CAPacitance AUTO", "F", 9, "Discharge capacitors before measuring them."),
    "freq": MeterMode("freq", "Frequency", "CONFigure:FREQuency", "Hz", 3),
    "period": MeterMode("period", "Period", "CONFigure:PERiod", "s", 9),
    "temp_pt100": MeterMode("temp_pt100", "Temperature PT100", "CONFigure:TEMPerature:RTD PT100", "°C", 2),
}


FUNC_ALIASES: list[tuple[str, str]] = [
    ("VOLT:DC", "vdc"), ("VOLTAGE:DC", "vdc"), ("VDC", "vdc"), ("DCV", "vdc"),
    ("VOLT:AC", "vac"), ("VOLTAGE:AC", "vac"), ("VAC", "vac"), ("ACV", "vac"),
    ("CURR:DC", "adc"), ("CURRENT:DC", "adc"), ("ADC", "adc"), ("DCA", "adc"),
    ("CURR:AC", "aac"), ("CURRENT:AC", "aac"), ("AAC", "aac"), ("ACA", "aac"),
    ("FRES", "fres"), ("FRESISTANCE", "fres"),
    ("RES", "res"), ("RESISTANCE", "res"),
    ("CONT", "cont"), ("CONTINUITY", "cont"),
    ("DIOD", "diode"), ("DIODE", "diode"),
    ("CAP", "cap"), ("CAPACITANCE", "cap"),
    ("FREQ", "freq"), ("FREQUENCY", "freq"),
    ("PER", "period"), ("PERIOD", "period"),
    ("TEMP", "temp_pt100"), ("TEMPERATURE", "temp_pt100"),
]


FUNC_NUMERIC_ALIASES: dict[str, str] = {
    "0": "vdc",
    "1": "vac",
    "2": "adc",
    "3": "aac",
    "4": "res",
    "5": "fres",
    "6": "cont",
    "7": "diode",
    "8": "cap",
    "9": "freq",
    "10": "period",
}


RANGE_QUERY_COMMANDS: dict[str, list[str]] = {
    "vdc": ["SENS:VOLT:DC:RANG?", "SENSe:VOLTage:DC:RANGe?", "VOLT:DC:RANG?", "RANGe?"],
    "vac": ["SENS:VOLT:AC:RANG?", "SENSe:VOLTage:AC:RANGe?", "VOLT:AC:RANG?", "RANGe?"],
    "adc": ["SENS:CURR:DC:RANG?", "SENSe:CURRent:DC:RANGe?", "CURR:DC:RANG?", "RANGe?"],
    "aac": ["SENS:CURR:AC:RANG?", "SENSe:CURRent:AC:RANGe?", "CURR:AC:RANG?", "RANGe?"],
    "res": ["SENS:RES:RANG?", "SENSe:RESistance:RANGe?", "RES:RANG?", "RANGe?"],
    "fres": ["SENS:FRES:RANG?", "SENSe:FRESistance:RANGe?", "FRES:RANG?", "RANGe?"],
    "cap": ["SENS:CAP:RANG?", "SENSe:CAPacitance:RANGe?", "CAP:RANG?", "RANGe?"],
    "freq": ["SENS:FREQ:RANG?", "SENSe:FREQuency:RANGe?", "FREQ:RANG?", "RANGe?"],
    "period": ["SENS:PER:RANG?", "SENSe:PERiod:RANGe?", "PER:RANG?", "RANGe?"],
    "diode": ["SENS:DIOD:RANG?", "SENSe:DIODe:RANGe?", "DIOD:RANG?", "RANGe?"],
    "cont": ["SENS:CONT:RANG?", "SENSe:CONTinuity:RANGe?", "CONT:RANG?", "RANGe?"],
}


GRAPH_VIEW_RANGES = {
    "res": [
        ("0_5", "0–5 Ω", 0.0, 5.0),
        ("0_10", "0–10 Ω", 0.0, 10.0),
        ("0_50", "0–50 Ω", 0.0, 50.0),
        ("0_500", "0–500 Ω", 0.0, 500.0),
        ("0_5k", "0–5 kΩ", 0.0, 5_000.0),
        ("0_50k", "0–50 kΩ", 0.0, 50_000.0),
        ("0_500k", "0–500 kΩ", 0.0, 500_000.0),
        ("0_5m", "0–5 MΩ", 0.0, 5_000_000.0),
        ("window", "Window autoscale", None, None),
    ],
    "fres": [
        ("0_5", "0–5 Ω", 0.0, 5.0),
        ("0_10", "0–10 Ω", 0.0, 10.0),
        ("0_50", "0–50 Ω", 0.0, 50.0),
        ("0_500", "0–500 Ω", 0.0, 500.0),
        ("window", "Window autoscale", None, None),
    ],
    "cont": [
        ("0_5", "0–5 Ω", 0.0, 5.0),
        ("0_10", "0–10 Ω", 0.0, 10.0),
        ("0_50", "0–50 Ω", 0.0, 50.0),
        ("window", "Window autoscale", None, None),
    ],
    "diode": [
        ("0_1", "0–1 V", 0.0, 1.0),
        ("0_2", "0–2 V", 0.0, 2.0),
        ("0_5", "0–5 V", 0.0, 5.0),
        ("window", "Window autoscale", None, None),
    ],
    "vdc": [
        ("pm1", "±1 V", -1.0, 1.0),
        ("pm5", "±5 V", -5.0, 5.0),
        ("pm50", "±50 V", -50.0, 50.0),
        ("pm500", "±500 V", -500.0, 500.0),
        ("window", "Window autoscale", None, None),
    ],
    "vac": [
        ("0_1", "0–1 V", 0.0, 1.0),
        ("0_5", "0–5 V", 0.0, 5.0),
        ("0_50", "0–50 V", 0.0, 50.0),
        ("0_500", "0–500 V", 0.0, 500.0),
        ("window", "Window autoscale", None, None),
    ],
    "cap": [
        ("0_1n", "0–1 nF", 0.0, 1e-9),
        ("0_10n", "0–10 nF", 0.0, 10e-9),
        ("0_100n", "0–100 nF", 0.0, 100e-9),
        ("0_1u", "0–1 µF", 0.0, 1e-6),
        ("0_10u", "0–10 µF", 0.0, 10e-6),
        ("0_100u", "0–100 µF", 0.0, 100e-6),
        ("window", "Window autoscale", None, None),
    ],
    "freq": [
        ("0_1k", "0–1 kHz", 0.0, 1_000.0),
        ("0_10k", "0–10 kHz", 0.0, 10_000.0),
        ("0_100k", "0–100 kHz", 0.0, 100_000.0),
        ("window", "Window autoscale", None, None),
    ],
}


def default_graph_view_key(mode_key: str) -> str:
    if mode_key in ("res", "fres", "cont"):
        return "0_10"
    if mode_key == "diode":
        return "0_2"
    if mode_key == "vdc":
        return "pm5"
    if mode_key == "vac":
        return "0_5"
    if mode_key == "cap":
        return "0_1u"
    if mode_key == "freq":
        return "0_1k"
    return "window"


def setup_logging() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("werkzeug").setLevel(logging.ERROR)


def first_number(raw: str) -> Optional[float]:
    m = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", str(raw))
    return float(m.group(0)) if m else None


def range_number_with_suffix(raw: str, base_unit: str) -> Optional[float]:
    text = str(raw).strip()
    val = first_number(text)
    if val is None:
        return None

    upper = text.upper().replace("Ω", "OHM")
    multiplier = 1.0

    if base_unit == "Ω":
        if "KOHM" in upper or re.search(r"\d\s*K\b", upper):
            multiplier = 1_000.0
        elif "MOHM" in upper or re.search(r"\d\s*M\b", upper):
            multiplier = 1_000_000.0
    elif base_unit == "V":
        if "MV" in upper:
            multiplier = 0.001
        elif re.search(r"\d\s*KV\b", upper):
            multiplier = 1_000.0
    elif base_unit == "A":
        if "UA" in upper or "µA" in text:
            multiplier = 0.000001
        elif "MA" in upper:
            multiplier = 0.001
    elif base_unit == "F":
        if "PF" in upper:
            multiplier = 1e-12
        elif "NF" in upper:
            multiplier = 1e-9
        elif "UF" in upper or "µF" in text:
            multiplier = 1e-6
        elif "MF" in upper:
            multiplier = 1e-3

    return val * multiplier


def normalize_function(raw: str) -> Optional[str]:
    if not raw:
        return None
    f = raw.strip().strip('"').upper().replace(" ", "")
    if f in FUNC_NUMERIC_ALIASES:
        return FUNC_NUMERIC_ALIASES[f]
    if ("VOLT" in f or f in ("VDC", "DCV")) and "AC" not in f:
        return "vdc"
    if "VOLT" in f and "AC" in f:
        return "vac"
    if ("CURR" in f or f in ("ADC", "DCA")) and "AC" not in f:
        return "adc"
    if "CURR" in f and "AC" in f:
        return "aac"
    if "FRES" in f:
        return "fres"
    if "RES" in f:
        return "res"
    if "CONT" in f:
        return "cont"
    if "DIOD" in f:
        return "diode"
    if "CAP" in f:
        return "cap"
    if "FREQ" in f:
        return "freq"
    if "PER" in f:
        return "period"
    if "TEMP" in f:
        return "temp_pt100"
    for token, key in FUNC_ALIASES:
        if f == token or token in f:
            return key
    return None


def normalize_speed(raw: str) -> str:
    r = (raw or "").strip().strip('"').upper()
    if r == "F":
        return "FAST"
    if r == "M":
        return "MEDIUM"
    if r == "S":
        return "SLOW"
    if "FAST" in r or "HIGH" in r:
        return "FAST"
    if "MED" in r or "MID" in r:
        return "MEDIUM"
    if "SLOW" in r or "LOW" in r:
        return "SLOW"
    return raw or "UNKNOWN"


def discover_owon_port(baud: int, preferred_port: str = "auto") -> str:
    candidate_ports: list[str] = []

    if preferred_port and preferred_port.lower() != "auto":
        candidate_ports.append(preferred_port)

    for port in list_ports.comports():
        device = port.device or ""
        description = f"{port.description or ''} {port.manufacturer or ''} {port.product or ''}".lower()
        looks_serial = any(token in device for token in ("/dev/cu.usbserial", "/dev/cu.usbmodem", "/dev/ttyUSB", "/dev/ttyACM", "COM"))
        looks_owonish = any(token in description for token in ("owon", "usb serial", "ch340", "ch341", "wch", "cp210", "silicon labs", "ftdi", "prolific"))

        if (looks_serial or looks_owonish) and device not in candidate_ports:
            candidate_ports.append(device)

    for device in candidate_ports:
        try:
            with serial.Serial(device, baud, timeout=0.6, write_timeout=0.6) as test_ser:
                time.sleep(0.25)
                test_ser.reset_input_buffer()
                test_ser.write(b"*IDN?\r\n")
                time.sleep(0.15)
                identity = test_ser.readline().decode(errors="ignore").strip()

            if identity and "OWON" in identity.upper():
                logging.info(f"Auto-discovered OWON meter on {device}: {identity}")
                return device
        except Exception:
            pass

    if preferred_port and preferred_port.lower() != "auto":
        return preferred_port

    raise RuntimeError("Could not auto-detect the OWON meter")


def format_engineering(value: float, unit: str, decimals: int = 3) -> str:
    abs_v = abs(value)
    if unit == "Ω":
        if abs_v >= 1_000_000:
            return f"{value / 1_000_000:.{decimals}f} MΩ"
        if abs_v >= 1_000:
            return f"{value / 1_000:.{decimals}f} kΩ"
        return f"{value:.{decimals}f} Ω"
    if unit == "V":
        if abs_v and abs_v < 1:
            return f"{value * 1000:.{decimals}f} mV"
        return f"{value:.{decimals}f} V"
    if unit == "A":
        if abs_v and abs_v < 0.001:
            return f"{value * 1_000_000:.{decimals}f} µA"
        if abs_v and abs_v < 1:
            return f"{value * 1000:.{decimals}f} mA"
        return f"{value:.{decimals}f} A"
    if unit == "F":
        if abs_v >= 1e-3:
            return f"{value * 1e3:.{decimals}f} mF"
        if abs_v >= 1e-6:
            return f"{value * 1e6:.{decimals}f} µF"
        if abs_v >= 1e-9:
            return f"{value * 1e9:.{decimals}f} nF"
        return f"{value * 1e12:.{decimals}f} pF"
    if unit == "Hz":
        if abs_v >= 1_000_000:
            return f"{value / 1_000_000:.{decimals}f} MHz"
        if abs_v >= 1_000:
            return f"{value / 1_000:.{decimals}f} kHz"
        return f"{value:.{decimals}f} Hz"
    return f"{value:.{decimals}f} {unit}"


def format_value(value: Optional[float], unit: str, precision: int) -> tuple[str, str]:
    if value is None or not math.isfinite(value):
        return "----", unit
    abs_v = abs(value)
    if abs_v >= 1e8:
        return "OL", ""
    if unit == "V":
        if abs_v and abs_v < 1:
            return f"{value * 1000:.3f}", "mV"
        return f"{value:.{min(precision, 6)}f}", "V"
    if unit == "A":
        if abs_v and abs_v < 0.001:
            return f"{value * 1_000_000:.2f}", "µA"
        if abs_v and abs_v < 1:
            return f"{value * 1000:.3f}", "mA"
        return f"{value:.6f}", "A"
    if unit == "Ω":
        if abs_v >= 1_000_000:
            return f"{value / 1_000_000:.3f}", "MΩ"
        if abs_v >= 1_000:
            return f"{value / 1_000:.3f}", "kΩ"
        return f"{value:.2f}", "Ω"
    if unit == "F":
        if abs_v >= 1e-3:
            return f"{value * 1e3:.3f}", "mF"
        if abs_v >= 1e-6:
            return f"{value * 1e6:.3f}", "µF"
        if abs_v >= 1e-9:
            return f"{value * 1e9:.3f}", "nF"
        return f"{value * 1e12:.3f}", "pF"
    if unit == "Hz":
        if abs_v >= 1_000_000:
            return f"{value / 1_000_000:.3f}", "MHz"
        if abs_v >= 1_000:
            return f"{value / 1_000:.3f}", "kHz"
        return f"{value:.3f}", "Hz"
    if unit == "s":
        if abs_v and abs_v < 1e-6:
            return f"{value * 1e9:.3f}", "ns"
        if abs_v and abs_v < 1e-3:
            return f"{value * 1e6:.3f}", "µs"
        if abs_v and abs_v < 1:
            return f"{value * 1e3:.3f}", "ms"
        return f"{value:.6f}", "s"
    return f"{value:.{precision}f}", unit


class OwonMeter:
    def __init__(self, port: str, baud: int):
        self.configured_port = port
        self.port = port
        self.baud = baud
        self.lock = threading.RLock()
        self.ser: Optional[serial.Serial] = None

        self.connected = False
        self.identity = "Not connected"

        self.mode_key = "vdc"
        self.function_raw = ""

        self.speed_raw = ""
        self.speed_label = "UNKNOWN"

        self.range_raw = ""
        self.range_value: Optional[float] = None
        self.range_label = "UNKNOWN"
        self.range_is_auto = True

        self.last_mode_poll = 0.0
        self.value: Optional[float] = None
        self.raw = ""
        self.error = ""
        self.last_updated = 0.0
        self.auto_poll = True

        self.graph_start = time.time()
        self.graph_points: deque[tuple[float, float]] = deque(maxlen=GRAPH_MAX_POINTS)

        self.graph_view_key_by_mode: dict[str, str] = {
            key: default_graph_view_key(key)
            for key in MODES.keys()
        }

    @property
    def mode(self) -> MeterMode:
        return MODES.get(self.mode_key, MODES["vdc"])

    def connect(self) -> None:
        with self.lock:
            if self.ser and self.ser.is_open:
                return
            self.port = discover_owon_port(self.baud, self.configured_port)
            self.ser = serial.Serial(self.port, self.baud, timeout=1)
            time.sleep(1.0)
            self.connected = True
            self.error = ""
            self.identity = self.query("*IDN?") or "Connected"

    def close(self) -> None:
        with self.lock:
            if self.ser:
                self.ser.close()
            self.ser = None
            self.connected = False
            self.identity = "Not connected"

    def write(self, command: str) -> None:
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Serial port is not open")
        self.ser.write((command.strip() + "\r\n").encode("ascii", errors="ignore"))

    def query(self, command: str, delay: float = 0.12) -> str:
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Serial port is not open")
        self.ser.reset_input_buffer()
        self.write(command)
        time.sleep(delay)
        return self.ser.readline().decode(errors="ignore").strip()

    def reset_graph(self, reread_settings: bool = True) -> None:
        with self.lock:
            self.graph_start = time.time()
            self.graph_points.clear()
            if reread_settings:
                self.sync_mode()
                self.sync_speed()
                self.sync_range()

    def sync_speed(self) -> None:
        with self.lock:
            self.connect()
            for cmd in ("SENSe:RATE?", "SENS:RATE?", "RATE?", "SENS:RES:RATE?", "RES:RATE?"):
                try:
                    raw = self.query(cmd, delay=0.08)
                    if raw:
                        self.speed_raw = raw
                        self.speed_label = normalize_speed(raw)
                        return
                except Exception:
                    pass
            self.speed_raw = ""
            self.speed_label = "UNKNOWN"

    def sync_range(self) -> None:
        with self.lock:
            self.connect()
            mode = self.mode
            commands = RANGE_QUERY_COMMANDS.get(self.mode_key, ["RANGe?"])

            self.range_raw = ""
            self.range_value = None
            self.range_label = "UNKNOWN"
            self.range_is_auto = True

            for cmd in commands:
                try:
                    raw = self.query(cmd, delay=0.08)
                    if not raw:
                        continue

                    self.range_raw = raw
                    upper = raw.upper()

                    if "AUTO" in upper:
                        self.range_is_auto = True
                        self.range_value = None
                        self.range_label = "AUTO"
                        return

                    val = range_number_with_suffix(raw, mode.unit)
                    if val is not None and val > 0:
                        self.range_is_auto = False
                        self.range_value = val
                        self.range_label = format_engineering(val, mode.unit, GRAPH_DECIMALS)
                        return
                except Exception:
                    pass

    def sync_mode(self) -> None:
        with self.lock:
            self.connect()
            raw_func = self.query("FUNCtion?", delay=0.08)
            self.function_raw = raw_func
            detected = normalize_function(raw_func)

            if detected and detected != self.mode_key:
                self.mode_key = detected
                self.reset_graph(reread_settings=False)
                self.sync_speed()
                self.sync_range()

            self.last_mode_poll = time.time()

    def set_mode(self, mode_key: str) -> None:
        if mode_key not in MODES:
            raise ValueError(f"Unknown mode: {mode_key}")

        with self.lock:
            self.connect()
            self.write(MODES[mode_key].command)
            time.sleep(0.35)

            self.mode_key = mode_key
            self.value = None
            self.raw = ""
            self.error = ""

            self.reset_graph(reread_settings=False)
            self.sync_mode()
            self.sync_speed()
            self.sync_range()
            self.reset_graph(reread_settings=False)

    def set_graph_view(self, view_key: str) -> None:
        with self.lock:
            options = GRAPH_VIEW_RANGES.get(self.mode_key, [("window", "Window autoscale", None, None)])
            valid_keys = {k for k, _, _, _ in options}

            if view_key not in valid_keys:
                view_key = default_graph_view_key(self.mode_key)

            self.graph_view_key_by_mode[self.mode_key] = view_key
            self.reset_graph(reread_settings=False)

    def poll_once(self) -> None:
        with self.lock:
            try:
                self.connect()

                now = time.time()
                if now - self.last_mode_poll > MODE_POLL_SECONDS:
                    try:
                        self.sync_mode()
                    except Exception:
                        pass

                raw = self.query("MEAS?", delay=0.05)
                self.raw = raw

                if raw:
                    value = float(raw)
                    self.value = value
                    self.last_updated = time.time()
                    self.error = ""

                    if math.isfinite(value) and abs(value) < 1e8:
                        elapsed = time.time() - self.graph_start
                        self.graph_points.append((elapsed, value))

            except Exception as exc:
                self.error = str(exc)
                self.connected = False
                self.value = None
                try:
                    self.close()
                except Exception:
                    pass

    def window_points(self) -> list[tuple[float, float]]:
        if not self.graph_points:
            return []

        newest = self.graph_points[-1][0]
        start = max(0.0, newest - GRAPH_WINDOW_SECONDS)

        return [
            (t, v)
            for t, v in self.graph_points
            if t >= start and math.isfinite(v) and abs(v) < 1e8
        ]

    def window_min_max(self) -> tuple[Optional[float], Optional[float]]:
        pts = self.window_points()
        if not pts:
            return None, None
        vals = [v for _, v in pts]
        return min(vals), max(vals)

    def fallback_graph_bounds(self) -> tuple[float, float]:
        ymin, ymax = self.window_min_max()
        if ymin is None or ymax is None:
            return 0.0, 1.0
        if ymin == ymax:
            pad = max(abs(ymin) * 0.1, 0.1)
            return ymin - pad, ymax + pad
        pad = (ymax - ymin) * 0.2
        return ymin - pad, ymax + pad

    def current_graph_view_option(self) -> tuple[str, str, Optional[float], Optional[float]]:
        options = GRAPH_VIEW_RANGES.get(self.mode_key, [("window", "Window autoscale", None, None)])
        current_key = self.graph_view_key_by_mode.get(self.mode_key, default_graph_view_key(self.mode_key))

        for opt in options:
            if opt[0] == current_key:
                return opt

        return options[0]

    def graph_bounds(self) -> tuple[float, float, str]:
        mode = self.mode

        if not self.range_is_auto and self.range_value is not None and self.range_value > 0:
            r = self.range_value
            if self.mode_key in ("vdc", "adc"):
                return -r, r, f"Meter range: {self.range_label}"
            return 0.0, r, f"Meter range: {self.range_label}"

        key, label, ymin, ymax = self.current_graph_view_option()

        if key != "window" and ymin is not None and ymax is not None:
            return ymin, ymax, f"Auto view: {label}"

        a, b = self.fallback_graph_bounds()
        return a, b, "Auto view: window autoscale"

    def graph_runtime_text(self) -> str:
        runtime = int(time.time() - self.graph_start)
        return f"{runtime // 3600:02d}:{(runtime % 3600) // 60:02d}:{runtime % 60:02d}"

    def snapshot(self) -> dict:
        with self.lock:
            mode = self.mode
            formatted, scaled_unit = format_value(self.value, mode.unit, mode.precision)
            ymin, ymax, graph_display_label = self.graph_bounds()
            win_min, win_max = self.window_min_max()

            options = GRAPH_VIEW_RANGES.get(self.mode_key, [("window", "Window autoscale", None, None)])
            current_graph_key = self.current_graph_view_option()[0]

            return {
                "connected": self.connected,
                "port": self.port,
                "identity": self.identity,

                "mode_key": self.mode_key,
                "mode_label": mode.label,
                "unit": scaled_unit,
                "base_unit": mode.unit,

                "value": self.value,
                "display_value": formatted,
                "raw": self.raw,

                "function_raw": self.function_raw,

                "speed_raw": self.speed_raw,
                "speed_label": self.speed_label,

                "range_raw": self.range_raw,
                "range_value": self.range_value,
                "range_label": self.range_label,
                "range_is_auto": self.range_is_auto,

                "graph_view_key": current_graph_key,
                "graph_view_options": [
                    {"key": k, "label": label}
                    for k, label, _, _ in options
                ],
                "graph_display_label": graph_display_label,

                "error": self.error,
                "last_updated": self.last_updated,
                "age_seconds": time.time() - self.last_updated if self.last_updated else None,
                "safety_note": mode.safety_note,
                "auto_poll": self.auto_poll,

                "graph_points": list(self.graph_points),
                "graph_window_seconds": GRAPH_WINDOW_SECONDS,
                "graph_runtime": self.graph_runtime_text(),
                "graph_y_min": ymin,
                "graph_y_max": ymax,
                "graph_min": win_min,
                "graph_max": win_max,
                "graph_decimals": GRAPH_DECIMALS,
            }


CONTROL_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>SquatchLab OWON XDM1241 Control</title>
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; background:#111; color:#eee; }
    .wrap { max-width: 1100px; margin: 0 auto; padding: 28px; }
    .header { display:flex; align-items:center; gap:16px; margin-bottom: 12px; flex-wrap:wrap; }
    .header img { height: 48px; width: auto; }
    h1 { margin: 0 0 8px; font-size: 30px; }
    .sub { color:#aaa; margin-bottom: 24px; }
    .grid { display:grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    .card { background:#1b1b1b; border:1px solid #333; border-radius: 18px; padding: 22px; box-shadow: 0 12px 36px rgba(0,0,0,.35); }
    .reading { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 76px; letter-spacing:-3px; color:#69ff9a; line-height:1; }
    .unit { font-size: 32px; color:#bafccd; margin-left: 10px; }
    .mode { color:#ddd; font-size: 22px; margin: 14px 0 4px; }
    .raw { color:#888; font-family: monospace; }
    button { border:0; border-radius: 12px; padding: 13px 15px; margin: 6px; background:#2a2a2a; color:#eee; cursor:pointer; font-size:15px; }
    button:hover { background:#3a3a3a; }
    button.active { background:#9b5b00; color:white; }
    .buttons { display:flex; flex-wrap:wrap; margin-left:-6px; }
    .note { margin-top:14px; color:#ffd27d; min-height: 22px; }
    .err { color:#ff7777; white-space:pre-wrap; }
    .danger { background:#5a1b1b; color:#ffd0d0; margin-top:18px; }
    .danger:hover { background:#7a2525; }
    .reset { background:#16405f; color:#d8f0ff; margin-top:18px; }
    .reset:hover { background:#215a85; }
    select { background:#222; color:#eee; border:1px solid #444; border-radius:10px; padding:10px; margin-top:10px; font-size:15px; width:100%; }
    a { color:#79b8ff; }
    code { background:#282828; padding:2px 6px; border-radius:6px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <a href="https://squatchcode.com" target="_blank" rel="noopener noreferrer">
        <img src="/images/squatchlab-logo-and-name-320x132.png" alt="SquatchLab logo">
      </a>
      <div>
        <h1>OWON XDM1241 Control</h1>
      </div>
    </div>
    <div class="sub">
      OBS overlay: <a href="/overlay">/overlay</a> ·
      Graph: <a href="/graph">/graph</a> ·
      JSON: <a href="/api/status">/api/status</a> ·
      Log: <code>~/.owon/owon.log</code>
    </div>

    <div class="grid">
      <div class="card">
        <div><span id="display" class="reading">----</span><span id="unit" class="unit"></span></div>
        <div id="mode" class="mode">---</div>
        <div class="raw">Raw: <span id="raw">---</span></div>
        <div class="raw">Function: <span id="function_raw">---</span></div>
        <div class="raw">Speed: <span id="speed">---</span></div>
        <div class="raw">OWON Range: <span id="range">---</span></div>
        <div class="raw">Graph Display: <span id="graph_display">---</span></div>
        <div class="raw">Port: <span id="port">---</span></div>
        <div class="raw">Device: <span id="identity">---</span></div>
        <div id="note" class="note"></div>
        <div id="error" class="err"></div>
      </div>

      <div class="card">
        <h2>Meter Function</h2>
        <div class="buttons">
          {% for key, mode in modes.items() %}
          <button id="btn-{{key}}" onclick="setMode('{{key}}')">{{mode.label}}</button>
          {% endfor %}
        </div>

        <h2>Graph View</h2>
        <select id="graphView" onchange="setGraphView(this.value)"></select>

        <div class="note">When OWON is auto-ranging, this controls the graph view. When OWON is in a fixed range, Reset Graph / Reread Settings uses the OWON range.</div>
        <button class="reset" onclick="resetGraph()">Reset Graph / Reread Settings</button>
        <button class="danger" onclick="shutdownApp()">Exit App</button>
      </div>
    </div>
  </div>
<script>
async function setMode(mode) {
  await fetch('/api/mode', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({mode})
  });
  await refresh();
}

async function setGraphView(view) {
  await fetch('/api/graph-view', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({view})
  });
  await refresh();
}

async function resetGraph() {
  await fetch('/api/reset-graph', { method: 'POST' });
  await refresh();
}

async function shutdownApp() {
  const ok = confirm('Exit the OWON meter app?');
  if (!ok) return;
  await fetch('/api/shutdown', { method: 'POST' });
  document.body.innerHTML = '<div style="font-family:sans-serif;padding:40px;color:#eee;background:#111;height:100vh"><h1>OWON app exited</h1><p>You can close this window.</p></div>';
}

function updateGraphViewSelect(s) {
  const sel = document.getElementById('graphView');
  const current = sel.value;
  sel.innerHTML = '';

  for (const opt of s.graph_view_options || []) {
    const o = document.createElement('option');
    o.value = opt.key;
    o.textContent = opt.label;
    if (opt.key === s.graph_view_key) o.selected = true;
    sel.appendChild(o);
  }
}

async function refresh() {
  const res = await fetch('/api/status?ts=' + Date.now());
  const s = await res.json();

  document.getElementById('display').textContent = s.display_value;
  document.getElementById('unit').textContent = s.unit;
  document.getElementById('mode').textContent = s.mode_label;
  document.getElementById('raw').textContent = s.raw || '---';
  document.getElementById('function_raw').textContent = s.function_raw || '---';
  document.getElementById('speed').textContent = s.speed_label || '---';
  document.getElementById('range').textContent = (s.range_label || '---') + (s.range_raw ? ' (' + s.range_raw + ')' : '');
  document.getElementById('graph_display').textContent = s.graph_display_label || '---';
  document.getElementById('port').textContent = s.port || '---';
  document.getElementById('identity').textContent = s.identity || '---';
  document.getElementById('note').textContent = s.safety_note || '';
  document.getElementById('error').textContent = s.error ? ('Error: ' + s.error) : '';

  updateGraphViewSelect(s);

  document.querySelectorAll('button').forEach(b => b.classList.remove('active'));
  const active = document.getElementById('btn-' + s.mode_key);
  if (active) active.classList.add('active');
}

setInterval(refresh, 250);
refresh();
</script>
</body>
</html>
"""


OVERLAY_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {
      margin: 0;
      background: rgba(0,0,0,0);
      overflow: hidden;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }
    .box {
      box-sizing: border-box;
      width: 100vw;
      height: 100vh;
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 14px;
      padding: 4px 12px 4px 6px;
      color: #ffb347;
      text-shadow: 0 0 10px rgba(255,179,71,.55);
      background: rgba(0,0,0,.72);
      border: 2px solid rgba(255,179,71,.45);
      border-radius: 12px;
    }
    .value {
      font-family: "DSEG7 Classic", "DSEG7Classic-Regular", "Digital-7", "Segment7", "DS-Digital", ui-monospace, monospace;
      font-size: 96px;
      font-weight: 400;
      line-height: .92;
      letter-spacing: 2px;
      min-width: 420px;
      text-align: right;
      font-variant-numeric: tabular-nums;
      -webkit-text-stroke: 1px rgba(255, 217, 145, .35);
      text-shadow:
        0 0 5px rgba(255,179,71,.9),
        0 0 14px rgba(255,128,0,.65),
        0 0 28px rgba(255,96,0,.35);
    }
    .right { display:flex; flex-direction:column; gap:2px; align-items:flex-start; min-width: 90px; }
    .unit {
      font-family: "DSEG7 Classic", "Digital-7", "Segment7", "DS-Digital", ui-monospace, monospace;
      font-size: 30px;
      color:#ffd7a1;
      line-height: 1;
      text-shadow: 0 0 8px rgba(255,179,71,.7);
    }
    .mode { font-size: 16px; color:#d8b58a; text-transform: uppercase; letter-spacing: 1px; line-height: 1; }
  </style>
</head>
<body>
  <div class="box">
    <div style="display:flex; align-items:center; margin-left:auto; gap:14px;">
      <div id="value" class="value">----</div>
      <div class="right">
        <div id="unit" class="unit"></div>
        <div id="mode" class="mode"></div>
      </div>
    </div>
  </div>
<script>
async function refresh() {
  const res = await fetch('/api/status?ts=' + Date.now());
  const s = await res.json();
  document.getElementById('value').textContent = s.error ? 'ERROR' : s.display_value;
  document.getElementById('unit').textContent = s.error ? '' : s.unit;
  document.getElementById('mode').textContent = s.error ? s.error : s.mode_label;
}
setInterval(refresh, 200);
refresh();
</script>
</body>
</html>
"""


GRAPH_HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>SquatchLab OWON XDM1241 Graph</title>
<style>
html, body {
  margin: 0;
  padding: 0;
  background: #000;
  overflow: hidden;
  color: #ff8a00;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
#wrap {
  width: 100vw;
  height: 100vh;
  box-sizing: border-box;
  padding: 2vh 1.6vw;
  position: relative;
  background: #000;
}
.title {
  text-align: center;
  font-size: clamp(14px, 3.3vh, 34px);
  font-weight: 700;
  height: 6vh;
  line-height: 6vh;
  letter-spacing: 0.08em;
  white-space: nowrap;
}
.top, .logging {
  position: absolute;
  top: 2vh;
  border: 1px solid #ff8a00;
  border-radius: 0.8vh;
  padding: 1vh 1vw;
  font-size: clamp(10px, 1.9vh, 18px);
  line-height: 1.35;
}
.top { left: 1.6vw; }
.logging { right: 1.6vw; }
.chartBox {
  position: absolute;
  left: 1.6vw;
  right: 1.6vw;
  top: 13vh;
  bottom: 20vh;
  border: 1px solid #ff8a00;
  border-radius: 0.8vh;
  padding: 1.2vh 1vw;
  box-sizing: border-box;
}
canvas { width: 100%; height: 100%; }
.bottom {
  position: absolute;
  left: 1.6vw;
  right: 1.6vw;
  bottom: 5vh;
  height: 12vh;
  display: grid;
  grid-template-columns: 1.2fr 1fr 1.35fr 1.1fr 1.1fr 2.2fr;
  gap: 0.6vw;
}
.panel {
  border: 1px solid #ff8a00;
  border-radius: 0.8vh;
  padding: 1.2vh 1vw;
  box-sizing: border-box;
  font-size: clamp(9px, 1.75vh, 17px);
  line-height: 1.3;
  overflow: hidden;
  white-space: nowrap;
}
.big {
  font-size: clamp(12px, 2.6vh, 25px);
  font-weight: 700;
}
.footer {
  position: absolute;
  left: 1.6vw;
  right: 1.6vw;
  bottom: 1.5vh;
  font-size: clamp(8px, 1.4vh, 14px);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
</head>
<body>
<div id="wrap">
  <div class="title">SQUATCHLAB OWON XDM1241 METER GRAPH</div>

  <div class="top">
    MODE<br>
    <span id="mode">UNKNOWN</span><br>
    <span id="unitTop"></span>
  </div>

  <div class="logging">
    GRAPH ●<br>
    <span id="runtime">00:00:00</span>
  </div>

  <div class="chartBox">
    <canvas id="chart"></canvas>
  </div>

  <div class="bottom">
    <div class="panel">METER SPEED<br><span id="speed">UNKNOWN</span></div>
    <div class="panel">RANGE<br><span id="range">UNKNOWN</span></div>
    <div class="panel">LATEST<br><span class="big" id="latest">----</span></div>
    <div class="panel">MIN<br><span class="big" id="min">--</span></div>
    <div class="panel">MAX<br><span class="big" id="max">--</span></div>
    <div class="panel">DISPLAY<br><span id="displayRange">--</span></div>
  </div>

  <div class="footer" id="footer">● CONNECTED</div>
</div>

<script>
const ORANGE = "#ff8a00";
const ORANGE_DIM = "#8a4a00";
const BLACK = "#000000";

const canvas = document.getElementById("chart");
const ctx = canvas.getContext("2d");

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.floor(rect.width * window.devicePixelRatio);
  canvas.height = Math.floor(rect.height * window.devicePixelRatio);
  ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
}

window.addEventListener("resize", resizeCanvas);
resizeCanvas();

function axisLabel(v, decimals) {
  return Number(v).toFixed(decimals);
}

function draw(data) {
  resizeCanvas();

  const rect = canvas.getBoundingClientRect();
  const w = rect.width;
  const h = rect.height;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = BLACK;
  ctx.fillRect(0, 0, w, h);

  const left = Math.max(52, w * 0.095);
  const right = Math.max(12, w * 0.025);
  const top = Math.max(18, h * 0.08);
  const bottom = Math.max(24, h * 0.12);

  const plotW = w - left - right;
  const plotH = h - top - bottom;

  const yMin = data.graph_y_min;
  const yMax = data.graph_y_max;
  const xMax = data.graph_window_seconds;
  const decimals = data.graph_decimals;

  const axisFont = Math.max(9, Math.min(18, h * 0.045));
  const labelFont = Math.max(10, Math.min(18, h * 0.048));

  ctx.strokeStyle = ORANGE_DIM;
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);

  ctx.font = axisFont + "px monospace";
  ctx.fillStyle = ORANGE;
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";

  for (let i = 0; i <= 5; i++) {
    const t = i / 5;
    const yVal = yMin + (yMax - yMin) * (1 - t);
    const y = top + plotH * t;

    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(left + plotW, y);
    ctx.stroke();

    ctx.setLineDash([]);
    ctx.fillText(axisLabel(yVal, decimals), left - 8, y);
    ctx.setLineDash([4, 4]);
  }

  ctx.textAlign = "center";
  ctx.textBaseline = "top";

  for (let i = 0; i <= 6; i++) {
    const t = i / 6;
    const xVal = xMax * t;
    const x = left + plotW * t;

    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + plotH);
    ctx.stroke();

    ctx.setLineDash([]);
    ctx.fillText(Math.round(xVal).toString(), x, top + plotH + 8);
    ctx.setLineDash([4, 4]);
  }

  ctx.setLineDash([]);
  ctx.strokeStyle = ORANGE;
  ctx.lineWidth = 1.5;
  ctx.strokeRect(left, top, plotW, plotH);

  ctx.fillStyle = ORANGE;
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.font = labelFont + "px monospace";
  ctx.fillText(data.mode_label.toUpperCase() + " (" + data.base_unit + ")", left + 14, top + 10);
  ctx.fillText(data.graph_display_label, left + 14, top + 10 + labelFont * 1.35);

  const points = data.graph_points || [];
  if (points.length > 1 && yMax !== yMin) {
    const newest = points[points.length - 1][0];
    const xStart = Math.max(0, newest - xMax);

    ctx.save();
    ctx.beginPath();
    ctx.rect(left, top, plotW, plotH);
    ctx.clip();

    ctx.beginPath();
    ctx.strokeStyle = ORANGE;
    ctx.lineWidth = Math.max(1.5, h * 0.008);

    let started = false;

    for (const p of points) {
      const elapsed = p[0];
      const val = p[1];

      if (val === null || val === undefined) continue;

      const x = left + ((elapsed - xStart) / xMax) * plotW;
      const y = top + (1 - ((val - yMin) / (yMax - yMin))) * plotH;

      if (x < left || x > left + plotW) continue;

      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    }

    ctx.stroke();
    ctx.restore();
  }

  document.getElementById("mode").textContent = data.mode_label;
  document.getElementById("unitTop").textContent = data.base_unit || "";
  document.getElementById("runtime").textContent = data.graph_runtime || "00:00:00";
  document.getElementById("speed").textContent = data.speed_label || "UNKNOWN";
  document.getElementById("range").textContent = data.range_label ? (data.range_label + (data.range_is_auto ? " / AUTO" : "")) : "UNKNOWN";
  document.getElementById("latest").textContent = data.display_value + (data.unit ? " " + data.unit : "");
  document.getElementById("min").textContent = data.graph_min === null ? "--" : Number(data.graph_min).toFixed(data.graph_decimals);
  document.getElementById("max").textContent = data.graph_max === null ? "--" : Number(data.graph_max).toFixed(data.graph_decimals);
  document.getElementById("displayRange").textContent = data.graph_display_label || "--";
  document.getElementById("footer").textContent =
    "● CONNECTED   Port: " + data.port +
    "   |   BAUD: " + data.baud +
    "   |   RAW: " + data.raw;
}

async function refresh() {
  try {
    const res = await fetch('/api/status?ts=' + Date.now(), {cache: 'no-store'});
    const data = await res.json();
    draw(data);
  } catch (e) {
  }
}

setInterval(refresh, 100);
refresh();
</script>
</body>
</html>
"""


def make_app(meter: OwonMeter) -> Flask:
    app = Flask(__name__, static_folder="images", static_url_path="/images")

    @app.route("/")
    def index():
        return render_template_string(CONTROL_HTML, modes=MODES)

    @app.route("/overlay")
    def overlay():
        return render_template_string(OVERLAY_HTML)

    @app.route("/graph")
    def graph():
        return render_template_string(GRAPH_HTML)

    @app.route("/api/status")
    def api_status():
        return jsonify(meter.snapshot())

    @app.route("/api/reset-graph", methods=["POST"])
    def api_reset_graph():
        meter.reset_graph(reread_settings=True)
        return jsonify({"ok": True, **meter.snapshot()})

    @app.route("/api/graph-view", methods=["POST"])
    def api_graph_view():
        payload = request.get_json(silent=True) or {}
        view = str(payload.get("view", "")).strip()
        meter.set_graph_view(view)
        return jsonify({"ok": True, **meter.snapshot()})

    @app.route("/api/mode", methods=["POST"])
    def api_mode():
        payload = request.get_json(silent=True) or {}
        mode = payload.get("mode")

        try:
            meter.set_mode(mode)
            return jsonify({"ok": True, **meter.snapshot()})
        except Exception as exc:
            meter.error = str(exc)
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/api/command", methods=["POST"])
    def api_command():
        payload = request.get_json(silent=True) or {}
        command = str(payload.get("command", "")).strip()

        if not command:
            return jsonify({"ok": False, "error": "Missing command"}), 400

        try:
            with meter.lock:
                meter.connect()
                response = meter.query(command)
            return jsonify({"ok": True, "command": command, "response": response})
        except Exception as exc:
            meter.error = str(exc)
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/api/shutdown", methods=["POST"])
    def api_shutdown():
        try:
            meter.close()
        except Exception:
            pass

        def stop_process():
            time.sleep(0.25)
            os.kill(os.getpid(), signal.SIGTERM)

        threading.Thread(target=stop_process, daemon=True).start()
        return jsonify({"ok": True, "message": "Shutting down"})

    @app.route("/favicon.ico")
    def favicon():
        return redirect("data:,")

    return app


def poll_loop(meter: OwonMeter) -> None:
    while True:
        if meter.auto_poll:
            meter.poll_once()
        time.sleep(POLL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(description="SquatchLab OWON XDM1241 Meter Display")
    parser.add_argument("--port", default=DEFAULT_PORT, help='Serial port, or "auto" to auto-detect the OWON meter')
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=DEFAULT_WEB_PORT)
    args = parser.parse_args()

    setup_logging()

    meter = OwonMeter(args.port, args.baud)
    threading.Thread(target=poll_loop, args=(meter,), daemon=True).start()

    app = make_app(meter)

    control_url = f"http://{args.host}:{args.web_port}"
    overlay_url = f"http://{args.host}:{args.web_port}/overlay"
    graph_url = f"http://{args.host}:{args.web_port}/graph"

    print(f"Control UI: {control_url}")
    print(f"OBS overlay: {overlay_url}")
    print(f"OBS graph: {graph_url}")

    webbrowser.open(control_url)
    app.run(host=args.host, port=args.web_port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
    