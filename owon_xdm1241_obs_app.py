#!/usr/bin/env python3
"""Entry point for the OWON XDM1241 meter display app."""

from __future__ import annotations

import argparse
import os
import signal
import threading
import time
import webbrowser

from flask import Flask, jsonify, redirect, render_template, request

from owon_meter import (
    APP_DIR,
    DEFAULT_BAUD,
    DEFAULT_PORT,
    DEFAULT_WEB_PORT,
    LOG_FILE,
    MODES,
    OwonMeter,
    POLL_SECONDS,
    setup_logging,
)
def make_app(meter: OwonMeter) -> Flask:
    app = Flask(__name__, static_folder="images", static_url_path="/images")

    @app.route("/")
    def index():
        return render_template("admin.html", modes=MODES)

    @app.route("/overlay")
    def overlay():
        return render_template("overlay.html")

    @app.route("/graph")
    def graph():
        return render_template("graph.html")

    @app.route("/api/status")
    def api_status():
        return jsonify(meter.snapshot())

    @app.route("/api/reset-graph", methods=["POST"])
    def api_reset_graph():
        meter.reset_graph(reread_settings=False)
        return jsonify({"ok": True, **meter.snapshot()})

    @app.route("/api/reread-settings", methods=["POST"])
    def api_reread_settings():
        try:
            meter.reread_settings()
            return jsonify({"ok": True, **meter.snapshot()})
        except Exception as exc:
            meter.error = str(exc)
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.route("/api/graph-view", methods=["POST"])
    def api_graph_view():
        payload = request.get_json(silent=True) or {}
        view = str(payload.get("view", "")).strip()
        meter.set_graph_view(view)
        return jsonify({"ok": True, **meter.snapshot()})

    @app.route("/api/overlay-settings", methods=["POST"])
    def api_overlay_settings():
        payload = request.get_json(silent=True) or {}
        meter.set_overlay_settings(
            auto_decimals=payload.get("auto_decimals"),
            decimals=payload.get("decimals"),
        )
        return jsonify({"ok": True, **meter.snapshot()})

    @app.route("/api/graph-settings", methods=["POST"])
    def api_graph_settings():
        payload = request.get_json(silent=True) or {}
        meter.set_graph_settings(
            range_mode=payload.get("range_mode"),
            range_key=payload.get("range_key"),
            custom_min=payload.get("custom_min"),
            custom_max=payload.get("custom_max"),
            center_on_zero=payload.get("center_on_zero"),
            auto_decimals=payload.get("auto_decimals"),
            decimals=payload.get("decimals"),
            window_seconds=payload.get("window_seconds"),
            visible_seconds=payload.get("visible_seconds"),
        )
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

    webbrowser.open(control_url, new=0, autoraise=True)
    app.run(host=args.host, port=args.web_port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
