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
import json
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
SETTINGS_FILE = APP_DIR / "settings.json"

POLL_SECONDS = 0.25
MODE_POLL_SECONDS = 1.0

GRAPH_WINDOW_SECONDS = 60
GRAPH_MAX_POINTS = int(GRAPH_WINDOW_SECONDS / POLL_SECONDS) + 10
GRAPH_DECIMALS = 3
OVERLOAD_THRESHOLD = 1e8


def _is_valid_measurement(value: Optional[float]) -> bool:
    return value is not None and math.isfinite(value) and abs(value) < OVERLOAD_THRESHOLD


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

GRAPH_MODE_CONFIG: dict[str, dict[str, object]] = {
    "vdc": {
        "default_view": "pm5",
        "default_center_on_zero": False,
        "zero_bottom_default": True,
        "allow_center_on_zero": True,
        "ranges": [
            {"key": "pm5", "label": "5 V", "min": 0.0, "max": 5.0},
            {"key": "pm10", "label": "10 V", "min": 0.0, "max": 10.0},
            {"key": "pm25", "label": "25 V", "min": 0.0, "max": 25.0},
            {"key": "pm50", "label": "50 V", "min": 0.0, "max": 50.0},
            {"key": "pm500", "label": "500 V", "min": 0.0, "max": 500.0},
            {"key": "pm1000", "label": "1000 V", "min": 0.0, "max": 1000.0},
        ],
    },
    "vac": {
        "default_view": "pm5",
        "default_center_on_zero": False,
        "zero_bottom_default": True,
        "allow_center_on_zero": False,
        "ranges": [
            {"key": "pm5", "label": "5 V", "min": 0.0, "max": 5.0},
            {"key": "pm50", "label": "50 V", "min": 0.0, "max": 50.0},
            {"key": "pm500", "label": "500 V", "min": 0.0, "max": 500.0},
            {"key": "pm750", "label": "750 V", "min": 0.0, "max": 750.0},
        ],
    },
    "adc": {
        "default_view": "pm0_0005",
        "default_center_on_zero": False,
        "zero_bottom_default": True,
        "allow_center_on_zero": True,
        "ranges": [
            {"key": "pm0_0005", "label": "500 µA", "min": 0.0, "max": 0.0005},
            {"key": "pm0_005", "label": "5 mA", "min": 0.0, "max": 0.005},
            {"key": "pm0_05", "label": "50 mA", "min": 0.0, "max": 0.05},
            {"key": "pm0_5", "label": "500 mA", "min": 0.0, "max": 0.5},
        ],
    },
    "aac": {
        "default_view": "pm0_0005",
        "default_center_on_zero": False,
        "zero_bottom_default": True,
        "allow_center_on_zero": False,
        "ranges": [
            {"key": "pm0_0005", "label": "500 µA", "min": 0.0, "max": 0.0005},
            {"key": "pm0_005", "label": "5 mA", "min": 0.0, "max": 0.005},
            {"key": "pm0_05", "label": "50 mA", "min": 0.0, "max": 0.05},
            {"key": "pm0_5", "label": "500 mA", "min": 0.0, "max": 0.5},
        ],
    },
    "res": {
        "default_view": "0_500",
        "default_center_on_zero": False,
        "zero_bottom_default": True,
        "allow_center_on_zero": False,
        "ranges": [
            {"key": "0_500", "label": "0–500 Ω", "min": 0.0, "max": 500.0},
            {"key": "0_5k", "label": "0–5 kΩ", "min": 0.0, "max": 5_000.0},
            {"key": "0_50k", "label": "0–50 kΩ", "min": 0.0, "max": 50_000.0},
            {"key": "0_500k", "label": "0–500 kΩ", "min": 0.0, "max": 500_000.0},
            {"key": "0_5m", "label": "0–5 MΩ", "min": 0.0, "max": 5_000_000.0},
            {"key": "0_50m", "label": "0–50 MΩ", "min": 0.0, "max": 50_000_000.0},
        ],
    },
    "fres": {
        "default_view": "0_500",
        "default_center_on_zero": False,
        "zero_bottom_default": True,
        "allow_center_on_zero": False,
        "ranges": [
            {"key": "0_500", "label": "0–500 Ω", "min": 0.0, "max": 500.0},
            {"key": "0_5k", "label": "0–5 kΩ", "min": 0.0, "max": 5_000.0},
            {"key": "0_50k", "label": "0–50 kΩ", "min": 0.0, "max": 50_000.0},
        ],
    },
    "cont": {
        "default_view": "0_10",
        "default_center_on_zero": False,
        "zero_bottom_default": True,
        "allow_center_on_zero": False,
        "ranges": [
            {"key": "0_10", "label": "0–10 Ω", "min": 0.0, "max": 10.0},
            {"key": "0_50", "label": "0–50 Ω", "min": 0.0, "max": 50.0},
        ],
    },
    "diode": {
        "default_view": "0_2",
        "default_center_on_zero": False,
        "zero_bottom_default": True,
        "allow_center_on_zero": False,
        "ranges": [
            {"key": "0_1", "label": "0–1 V", "min": 0.0, "max": 1.0},
            {"key": "0_2", "label": "0–2 V", "min": 0.0, "max": 2.0},
            {"key": "0_5", "label": "0–5 V", "min": 0.0, "max": 5.0},
        ],
    },
    "cap": {
        "default_view": "0_50n",
        "default_center_on_zero": False,
        "zero_bottom_default": True,
        "allow_center_on_zero": False,
        "ranges": [
            {"key": "0_50n", "label": "0–50 nF", "min": 0.0, "max": 50e-9},
            {"key": "0_500n", "label": "0–500 nF", "min": 0.0, "max": 500e-9},
            {"key": "0_5u", "label": "0–5 µF", "min": 0.0, "max": 5e-6},
            {"key": "0_50u", "label": "0–50 µF", "min": 0.0, "max": 50e-6},
            {"key": "0_500u", "label": "0–500 µF", "min": 0.0, "max": 500e-6},
            {"key": "0_5m", "label": "0–5 mF", "min": 0.0, "max": 5e-3},
            {"key": "0_50m", "label": "0–50 mF", "min": 0.0, "max": 50e-3},
        ],
    },
    "freq": {
        "default_view": "0_1k",
        "default_center_on_zero": False,
        "zero_bottom_default": True,
        "allow_center_on_zero": True,
        "ranges": [
            {"key": "0_1k", "label": "0–1 kHz", "min": 0.0, "max": 1_000.0},
            {"key": "0_10k", "label": "0–10 kHz", "min": 0.0, "max": 10_000.0},
            {"key": "0_100k", "label": "0–100 kHz", "min": 0.0, "max": 100_000.0},
        ],
    },
    "period": {
        "default_view": "window",
        "default_center_on_zero": False,
        "zero_bottom_default": True,
        "allow_center_on_zero": True,
        "ranges": [],
    },
    "temp_pt100": {
        "default_view": "window",
        "default_center_on_zero": False,
        "zero_bottom_default": True,
        "allow_center_on_zero": True,
        "ranges": [],
    },
}


def graph_mode_config(mode_key: str) -> dict[str, object]:
    return GRAPH_MODE_CONFIG.get(mode_key, {
        "default_view": "window",
        "default_center_on_zero": False,
        "zero_bottom_default": False,
        "allow_center_on_zero": True,
        "ranges": [],
    })


def graph_view_options(mode_key: str) -> list[tuple[str, str, Optional[float], Optional[float]]]:
    config = graph_mode_config(mode_key)
    options: list[tuple[str, str, Optional[float], Optional[float]]] = []
    for entry in config["ranges"]:
        options.append((entry["key"], entry["label"], entry["min"], entry["max"]))
    options.append(("window", "Auto Window", None, None))
    return options


def default_graph_view_key(mode_key: str) -> str:
    return graph_mode_config(mode_key)["default_view"]


def default_graph_center_on_zero(mode_key: str) -> bool:
    return bool(graph_mode_config(mode_key).get("default_center_on_zero", False))


def default_graph_zero_bottom(mode_key: str) -> bool:
    return bool(graph_mode_config(mode_key).get("zero_bottom_default", False))


def graph_range_option(mode_key: str, key: str) -> tuple[str, str, Optional[float], Optional[float]]:
    for option in graph_view_options(mode_key):
        if option[0] == key:
            return option
    return graph_view_options(mode_key)[0]


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


def format_value(value: Optional[float], unit: str, precision: int, decimals: Optional[int] = None) -> tuple[str, str]:
    if value is None or not math.isfinite(value):
        return "----", unit

    digits = int(decimals) if decimals is not None else min(max(precision, 0), 6)
    digits = max(0, min(9, digits))
    abs_v = abs(value)

    if abs_v >= OVERLOAD_THRESHOLD:
        return "OL", ""
    if unit == "V":
        if abs_v and abs_v < 1:
            return f"{value * 1000:.{digits}f}", "mV"
        return f"{value:.{digits}f}", "V"
    if unit == "A":
        if abs_v and abs_v < 0.001:
            return f"{value * 1_000_000:.{digits}f}", "µA"
        if abs_v and abs_v < 1:
            return f"{value * 1000:.{digits}f}", "mA"
        return f"{value:.{digits}f}", "A"
    if unit == "Ω":
        if abs_v >= 1_000_000:
            return f"{value / 1_000_000:.{digits}f}", "MΩ"
        if abs_v >= 1_000:
            return f"{value / 1_000:.{digits}f}", "kΩ"
        return f"{value:.{digits}f}", "Ω"
    if unit == "F":
        if abs_v >= 1e-3:
            return f"{value * 1e3:.{digits}f}", "mF"
        if abs_v >= 1e-6:
            return f"{value * 1e6:.{digits}f}", "µF"
        if abs_v >= 1e-9:
            return f"{value * 1e9:.{digits}f}", "nF"
        return f"{value * 1e12:.{digits}f}", "pF"
    if unit == "Hz":
        if abs_v >= 1_000_000:
            return f"{value / 1_000_000:.{digits}f}", "MHz"
        if abs_v >= 1_000:
            return f"{value / 1_000:.{digits}f}", "kHz"
        return f"{value:.{digits}f}", "Hz"
    if unit == "s":
        if abs_v and abs_v < 1e-6:
            return f"{value * 1e9:.{digits}f}", "ns"
        if abs_v and abs_v < 1e-3:
            return f"{value * 1e6:.{digits}f}", "µs"
        if abs_v and abs_v < 1:
            return f"{value * 1e3:.{digits}f}", "ms"
        return f"{value:.{digits}f}", "s"
    return f"{value:.{digits}f}", unit


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
        self.graph_window_seconds = GRAPH_WINDOW_SECONDS
        self.graph_visible_seconds = 30
        self.graph_points: deque[tuple[float, float]] = deque(maxlen=GRAPH_MAX_POINTS)

        self.graph_range_mode_by_mode: dict[str, str] = {key: "auto" for key in MODES.keys()}
        self.graph_range_key_by_mode: dict[str, str] = {
            key: default_graph_view_key(key)
            for key in MODES.keys()
        }
        self.graph_center_on_zero_by_mode: dict[str, bool] = {
            key: default_graph_center_on_zero(key)
            for key in MODES.keys()
        }
        self.graph_custom_min_by_mode: dict[str, float] = {key: 0.0 for key in MODES.keys()}
        self.graph_custom_max_by_mode: dict[str, float] = {key: 100_000.0 for key in MODES.keys()}
        self.overlay_auto_decimals = True
        self.overlay_decimals = 3
        self.graph_auto_decimals = True
        self.graph_decimals = 3

        self.settings_file = SETTINGS_FILE
        self._reset_graph_points()
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self._load_settings()

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

    def _reset_graph_points(self) -> None:
        self.graph_points = deque(maxlen=max(20, int(self.graph_window_seconds / POLL_SECONDS) + 10))

    def reset_graph(self, reread_settings: bool = True) -> None:
        with self.lock:
            self.graph_start = time.time()
            self._reset_graph_points()
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
            valid_keys = {k for k, _, _, _ in graph_view_options(self.mode_key) if k != "window"}
            if view_key not in valid_keys:
                view_key = default_graph_view_key(self.mode_key)

            self.graph_range_mode_by_mode[self.mode_key] = "fixed"
            self.graph_range_key_by_mode[self.mode_key] = view_key
            self.reset_graph(reread_settings=False)

    def _load_settings(self) -> None:
        with self.lock:
            try:
                if self.settings_file.exists():
                    with self.settings_file.open("r", encoding="utf-8") as handle:
                        payload = json.load(handle)
                else:
                    payload = {}
            except Exception:
                payload = {}

            self.overlay_auto_decimals = bool(payload.get("overlay_auto_decimals", True))
            try:
                self.overlay_decimals = max(0, min(9, int(payload.get("overlay_decimals", 3))))
            except (TypeError, ValueError):
                self.overlay_decimals = 3

            self.graph_auto_decimals = bool(payload.get("graph_auto_decimals", True))
            try:
                self.graph_decimals = max(0, min(9, int(payload.get("graph_decimals", 3))))
            except (TypeError, ValueError):
                self.graph_decimals = 3

            range_mode_maps = payload.get("graph_range_mode_by_mode", {}) or {}
            for key in list(self.graph_range_mode_by_mode.keys()):
                raw_mode = str(range_mode_maps.get(key, payload.get("graph_range_mode", "auto"))).strip().lower()
                self.graph_range_mode_by_mode[key] = raw_mode if raw_mode in {"auto", "fixed", "manual"} else "auto"

            range_key_maps = payload.get("graph_range_key_by_mode", {}) or payload.get("graph_view_key_by_mode", {}) or {}
            for key in list(self.graph_range_key_by_mode.keys()):
                valid_keys = {k for k, _, _, _ in graph_view_options(key) if k != "window"}
                saved = range_key_maps.get(key, default_graph_view_key(key))
                self.graph_range_key_by_mode[key] = saved if saved in valid_keys else default_graph_view_key(key)

            saved_range_key = payload.get("graph_range_key")
            valid_keys = {k for k, _, _, _ in graph_view_options(self.mode_key) if k != "window"}
            if isinstance(saved_range_key, str) and saved_range_key in valid_keys:
                self.graph_range_key_by_mode[self.mode_key] = saved_range_key

            center_map = payload.get("graph_center_on_zero_by_mode", {}) or {}
            for key in list(self.graph_center_on_zero_by_mode.keys()):
                self.graph_center_on_zero_by_mode[key] = bool(center_map.get(key, default_graph_center_on_zero(key)))

            custom_min_map = payload.get("graph_custom_min_by_mode", {}) or {}
            custom_max_map = payload.get("graph_custom_max_by_mode", {}) or {}
            for key in list(self.graph_custom_min_by_mode.keys()):
                self.graph_custom_min_by_mode[key] = self._load_float(custom_min_map.get(key), 0.0)
                self.graph_custom_max_by_mode[key] = self._load_float(custom_max_map.get(key), 100000.0)

            if payload.get("graph_custom_min") is not None:
                self.graph_custom_min_by_mode[self.mode_key] = self._load_float(payload.get("graph_custom_min"), 0.0)
            if payload.get("graph_custom_max") is not None:
                self.graph_custom_max_by_mode[self.mode_key] = self._load_float(payload.get("graph_custom_max"), 100000.0)

            try:
                self.graph_window_seconds = max(0, min(300, int(payload.get("graph_window_seconds", GRAPH_WINDOW_SECONDS))))
            except (TypeError, ValueError):
                self.graph_window_seconds = GRAPH_WINDOW_SECONDS

            try:
                self.graph_visible_seconds = max(0, min(self.graph_window_seconds, int(payload.get("graph_visible_seconds", 30))))
            except (TypeError, ValueError):
                self.graph_visible_seconds = 30

            self._reset_graph_points()
            self._save_settings()

    def _save_settings(self) -> None:
        try:
            payload = {
                "overlay_auto_decimals": self.overlay_auto_decimals,
                "overlay_decimals": self.overlay_decimals,
                "graph_auto_decimals": self.graph_auto_decimals,
                "graph_decimals": self.graph_decimals,
                "graph_range_mode_by_mode": self.graph_range_mode_by_mode,
                "graph_range_key_by_mode": self.graph_range_key_by_mode,
                "graph_center_on_zero_by_mode": self.graph_center_on_zero_by_mode,
                "graph_custom_min_by_mode": self.graph_custom_min_by_mode,
                "graph_custom_max_by_mode": self.graph_custom_max_by_mode,
                "graph_range_mode": self.graph_range_mode_by_mode.get(self.mode_key, "auto"),
                "graph_range_key": self.graph_range_key_by_mode.get(self.mode_key, default_graph_view_key(self.mode_key)),
                "graph_custom_min": self.graph_custom_min_by_mode.get(self.mode_key, 0.0),
                "graph_custom_max": self.graph_custom_max_by_mode.get(self.mode_key, 100000.0),
                "graph_window_seconds": self.graph_window_seconds,
                "graph_visible_seconds": self.graph_visible_seconds,
            }
            with self.settings_file.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        except Exception:
            pass

    def _load_float(self, value: Optional[object], default: float) -> float:
        try:
            return float(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    def set_overlay_settings(self, auto_decimals: Optional[bool] = None, decimals: Optional[int] = None) -> None:
        with self.lock:
            if auto_decimals is not None:
                self.overlay_auto_decimals = bool(auto_decimals)
            if decimals is not None:
                try:
                    self.overlay_decimals = max(0, min(9, int(decimals)))
                except (TypeError, ValueError):
                    pass
            self._save_settings()

    def set_graph_window_seconds(self, seconds: Optional[int] = None) -> None:
        with self.lock:
            try:
                value = max(0, min(300, int(seconds))) if seconds is not None else self.graph_window_seconds
            except (TypeError, ValueError):
                value = self.graph_window_seconds

            if value == self.graph_window_seconds:
                return

            self.graph_window_seconds = value
            if self.graph_visible_seconds > self.graph_window_seconds:
                self.graph_visible_seconds = self.graph_window_seconds
            self.reset_graph(reread_settings=False)
            self._save_settings()

    def set_graph_settings(
        self,
        range_mode: Optional[str] = None,
        range_key: Optional[str] = None,
        custom_min: Optional[float] = None,
        custom_max: Optional[float] = None,
        center_on_zero: Optional[bool] = None,
        auto_decimals: Optional[bool] = None,
        decimals: Optional[int] = None,
        window_seconds: Optional[int] = None,
        visible_seconds: Optional[int] = None,
    ) -> None:
        with self.lock:
            if range_mode in {"auto", "fixed", "manual"}:
                self.graph_range_mode_by_mode[self.mode_key] = range_mode

            if range_key is not None:
                valid_keys = {k for k, _, _, _ in graph_view_options(self.mode_key) if k != "window"}
                if range_key in valid_keys:
                    self.graph_range_key_by_mode[self.mode_key] = range_key
                else:
                    self.graph_range_key_by_mode[self.mode_key] = default_graph_view_key(self.mode_key)

            if custom_min is not None:
                self.graph_custom_min_by_mode[self.mode_key] = self._load_float(custom_min, 0.0)

            if custom_max is not None:
                self.graph_custom_max_by_mode[self.mode_key] = self._load_float(custom_max, 100_000.0)

            if center_on_zero is not None:
                allow_center = bool(graph_mode_config(self.mode_key).get("allow_center_on_zero", True))
                self.graph_center_on_zero_by_mode[self.mode_key] = bool(center_on_zero) and allow_center

            if auto_decimals is not None:
                self.graph_auto_decimals = bool(auto_decimals)
            if decimals is not None:
                try:
                    self.graph_decimals = max(0, min(9, int(decimals)))
                except (TypeError, ValueError):
                    pass

            if window_seconds is not None:
                self.set_graph_window_seconds(window_seconds)

            if visible_seconds is not None:
                try:
                    value = int(visible_seconds)
                    self.graph_visible_seconds = max(0, min(self.graph_window_seconds, value))
                except (TypeError, ValueError):
                    self.graph_visible_seconds = 30

            # Keep manual bounds sane even if user enters reversed values.
            lo = self.graph_custom_min_by_mode.get(self.mode_key, 0.0)
            hi = self.graph_custom_max_by_mode.get(self.mode_key, 100_000.0)
            if hi <= lo:
                self.graph_custom_max_by_mode[self.mode_key] = lo + 1.0

            self._save_settings()

    def reread_settings(self) -> None:
        with self.lock:
            self.connect()
            self.sync_mode()
            self.sync_speed()
            self.sync_range()

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

                    if _is_valid_measurement(value):
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
        start = max(0.0, newest - self.graph_window_seconds)

        return [
            (t, v)
            for t, v in self.graph_points
            if t >= start and _is_valid_measurement(v)
        ]

    def visible_points(self) -> list[tuple[float, float]]:
        if not self.graph_points:
            return []

        newest = self.graph_points[-1][0]
        start = max(0.0, newest - self.graph_visible_seconds)

        return [
            (t, v)
            for t, v in self.graph_points
            if t >= start and _is_valid_measurement(v)
        ]

    def window_min_max(self) -> tuple[Optional[float], Optional[float]]:
        pts = self.window_points()
        if not pts:
            return None, None
        vals = [v for _, v in pts]
        decimals = self.graph_decimals if not self.graph_auto_decimals else max(0, min(9, self.mode.precision))
        adjusted = [round(v, decimals) for v in vals]
        return min(adjusted), max(adjusted)

    def visible_min_max(self) -> tuple[Optional[float], Optional[float]]:
        pts = self.visible_points()
        if not pts:
            return None, None
        vals = [v for _, v in pts]
        decimals = self.graph_decimals if not self.graph_auto_decimals else max(0, min(9, self.mode.precision))
        adjusted = [round(v, decimals) for v in vals]
        return min(adjusted), max(adjusted)

    def fallback_graph_bounds(self) -> tuple[float, float]:
        ymin, ymax = self.visible_min_max()
        if ymin is None or ymax is None:
            return 0.0, 1.0

        # Keep one-sided measurements anchored to zero so autoscale does not
        # introduce misleading negative (or positive) space.
        if ymin >= 0 and ymax > 0:
            if ymin == ymax:
                pad = max(abs(ymax) * 0.1, 0.1)
                return 0.0, ymax + pad
            pad = (ymax - ymin) * 0.2
            return 0.0, ymax + pad

        if ymax <= 0 and ymin < 0:
            if ymin == ymax:
                pad = max(abs(ymin) * 0.1, 0.1)
                return ymin - pad, 0.0
            pad = (ymax - ymin) * 0.2
            return ymin - pad, 0.0

        if ymin == ymax:
            pad = max(abs(ymin) * 0.1, 0.1)
            return ymin - pad, ymax + pad
        pad = (ymax - ymin) * 0.2
        return ymin - pad, ymax + pad

    def current_graph_view_option(self) -> tuple[str, str, Optional[float], Optional[float]]:
        options = graph_view_options(self.mode_key)
        valid_keys = {k for k, _, _, _ in options}

        current_key = self.graph_range_key_by_mode.get(self.mode_key, default_graph_view_key(self.mode_key))
        if current_key not in valid_keys:
            current_key = default_graph_view_key(self.mode_key)

        for opt in options:
            if opt[0] == current_key:
                return opt

        return options[0]

    def graph_bounds(self) -> tuple[float, float, str]:
        range_mode = self.graph_range_mode_by_mode.get(self.mode_key, "auto")
        center_on_zero = self.graph_center_on_zero_by_mode.get(self.mode_key, False)

        def apply_positive_one_sided_zero_bottom(ymin: float, ymax: float) -> tuple[float, float]:
            if not center_on_zero and ymax > 0 and ymin >= 0:
                return 0.0, ymax
            return ymin, ymax

        if range_mode == "manual":
            custom_min = self.graph_custom_min_by_mode.get(self.mode_key)
            custom_max = self.graph_custom_max_by_mode.get(self.mode_key)
            if custom_min is not None and custom_max is not None and custom_max > custom_min:
                if center_on_zero:
                    span = max(abs(custom_min), abs(custom_max), 1e-12)
                    return -span, span, f"Manual centered: {custom_min} to {custom_max}"
                ymin, ymax = apply_positive_one_sided_zero_bottom(custom_min, custom_max)
                return ymin, ymax, f"Manual: {custom_min} to {custom_max}"
            a, b = self.fallback_graph_bounds()
            if center_on_zero:
                span = max(abs(a), abs(b), 1e-12)
                return -span, span, "Manual range invalid (centered)"
            ymin, ymax = apply_positive_one_sided_zero_bottom(a, b)
            return ymin, ymax, "Manual range invalid"

        if range_mode == "fixed":
            _, label, ymin, ymax = self.current_graph_view_option()
            if ymin is not None and ymax is not None:
                if center_on_zero:
                    span = max(abs(ymax), abs(ymin))
                    span = max(span, 1e-12)
                    return -span, span, f"Preset centered: {label}"
                zero_bottom = default_graph_zero_bottom(self.mode_key)
                if zero_bottom and ymin < 0 <= ymax:
                    return 0.0, ymax, f"Preset: {label}"
                ymin, ymax = apply_positive_one_sided_zero_bottom(ymin, ymax)
                return ymin, ymax, f"Preset: {label}"

        a, b = self.fallback_graph_bounds()
        if center_on_zero:
            span = max(abs(a), abs(b), 1e-12)
            return -span, span, "Auto view: window autoscale (centered)"
        ymin, ymax = apply_positive_one_sided_zero_bottom(a, b)
        return ymin, ymax, "Auto view: window autoscale"

    def graph_runtime_text(self) -> str:
        runtime = int(time.time() - self.graph_start)
        return f"{runtime // 3600:02d}:{(runtime % 3600) // 60:02d}:{runtime % 60:02d}"

    def snapshot(self) -> dict:
        with self.lock:
            mode = self.mode
            overlay_decimals = self.overlay_decimals if not self.overlay_auto_decimals else max(0, min(9, mode.precision))
            graph_decimals = self.graph_decimals if not self.graph_auto_decimals else max(0, min(9, mode.precision))
            formatted, scaled_unit = format_value(self.value, mode.unit, mode.precision, decimals=overlay_decimals)
            graph_formatted, graph_scaled_unit = format_value(self.value, mode.unit, mode.precision, decimals=graph_decimals)
            ymin, ymax, graph_display_label = self.graph_bounds()
            win_min, win_max = self.window_min_max()

            options = [opt for opt in graph_view_options(self.mode_key) if opt[0] != "window"]
            current_graph_key = self.current_graph_view_option()[0]

            # prepare graph points rounded to graph_decimals for display and autoscale consistency
            graph_points_out: list[tuple[float, float]] = []
            try:
                for t, v in list(self.graph_points):
                    if _is_valid_measurement(v):
                        adj = round(v, graph_decimals)
                        graph_points_out.append((t, adj))
            except Exception:
                graph_points_out = list(self.graph_points)

            return {
                "connected": self.connected,
                "port": self.port,
                "identity": self.identity,

                "mode_key": self.mode_key,
                "mode_label": mode.label,
                "unit": scaled_unit,
                "base_unit": mode.unit,

                "value": self.value if _is_valid_measurement(self.value) else None,
                "display_value": formatted,
                "graph_display_value": graph_formatted,
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

                "graph_points": graph_points_out,
                "graph_window_seconds": self.graph_window_seconds,
                "graph_visible_seconds": self.graph_visible_seconds,
                "graph_runtime": self.graph_runtime_text(),
                "graph_y_min": ymin,
                "graph_y_max": ymax,
                "graph_min": win_min,
                "graph_max": win_max,
                "graph_decimals": graph_decimals,
                "overlay_auto_decimals": self.overlay_auto_decimals,
                "overlay_decimals": self.overlay_decimals,
                "graph_auto_decimals": self.graph_auto_decimals,
                "graph_decimals_setting": self.graph_decimals,
                "graph_range_mode": self.graph_range_mode_by_mode.get(self.mode_key, "auto"),
                "graph_range_key": self.graph_range_key_by_mode.get(self.mode_key, default_graph_view_key(self.mode_key)),
                "graph_custom_min": self.graph_custom_min_by_mode.get(self.mode_key, 0.0),
                "graph_custom_max": self.graph_custom_max_by_mode.get(self.mode_key, 100000.0),
                "graph_center_on_zero": self.graph_center_on_zero_by_mode.get(self.mode_key, False),
                "graph_center_on_zero_allowed": bool(graph_mode_config(self.mode_key).get("allow_center_on_zero", True)),
            }

