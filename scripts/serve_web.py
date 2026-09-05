#!/usr/bin/env python3
"""Local Flask control panel for ETF option strategies."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_loader import DEFAULT_CONFIG_PATH, load_config, save_config, validate_strategy_params  # noqa: E402
from report_html import format_fragment  # noqa: E402
from strategy_engine import advice_report, forecast_report  # noqa: E402


def create_app(config_path: str | Path = DEFAULT_CONFIG_PATH) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    app.config["STRATEGY_CONFIG_PATH"] = str(config_path)

    def current_config():
        return load_config(app.config["STRATEGY_CONFIG_PATH"])

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/config")
    def get_config():
        config = current_config()
        return jsonify({"strategy": config["strategy"]})

    @app.post("/api/config")
    def put_config():
        payload = request.get_json(force=True) or {}
        config = current_config()
        config["strategy"] = validate_strategy_params(payload.get("strategy") or payload)
        saved = save_config(config, app.config["STRATEGY_CONFIG_PATH"])
        return jsonify({"ok": True, "strategy": saved["strategy"]})

    @app.post("/api/forecast")
    def forecast():
        params = validate_strategy_params((request.get_json(force=True) or {}).get("params") or {})
        report = forecast_report(params)
        return jsonify({"ok": not bool(report["errors"]), "report": report, "html": format_fragment(report)})

    @app.post("/api/advice")
    def advice():
        payload = request.get_json(force=True) or {}
        params = validate_strategy_params(payload.get("params") or {})
        strategy = payload.get("strategy") or "iron_condor"
        report = advice_report(strategy, params)
        return jsonify({
            "ok": not bool(report["errors"]),
            "report": report,
            "html": format_fragment(report),
        })

    @app.errorhandler(ValueError)
    def bad_request(exc):
        return jsonify({"ok": False, "error": str(exc)}), 400

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify({"ok": False, "error": exc.description}), exc.code

    @app.errorhandler(Exception)
    def internal_error(exc):
        app.logger.exception("request failed")
        return jsonify({"ok": False, "error": str(exc)}), 500

    return app


def main() -> int:
    parser = argparse.ArgumentParser(description="ETF 期权策略本地控制台")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    host = args.host or config["server"]["host"]
    port = args.port or config["server"]["port"]
    create_app(args.config).run(host=host, port=port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
