"""Offline tests for YAML config, HTML, Flask routes and DingTalk signing."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from config_loader import load_config, save_config, validate_strategy_params  # noqa: E402
from dingtalk import build_webhook, send_markdown  # noqa: E402
from report_html import format_html  # noqa: E402
from serve_web import create_app  # noqa: E402


class TestConfig(unittest.TestCase):
    def test_validate_boundaries(self):
        out = validate_strategy_params({
            "quantile": 0.99,
            "timeframe": "daily",
            "range_pad": 0.05,
            "dte_min": 15,
            "dte_max": 60,
            "min_yield": 0.01,
            "max_yield": 0.03,
        })
        self.assertEqual(out["expiry_count"], 2)
        with self.assertRaises(ValueError):
            validate_strategy_params({"quantile": 0.79})

    def test_yaml_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "strategy.yaml"
            config = load_config(Path(tmp) / "missing.yaml")
            config["strategy"]["quantile"] = 0.91
            config["dingtalk"]["secret"] = "SEC-test"
            save_config(config, path)
            loaded = load_config(path)
            self.assertEqual(loaded["strategy"]["quantile"], 0.91)
            self.assertEqual(loaded["dingtalk"]["secret"], "SEC-test")


class TestDingTalk(unittest.TestCase):
    def test_signed_webhook(self):
        url = build_webhook(
            {"access_token": "abc", "secret": "SEC-test"},
            timestamp_ms=123456789,
        )
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(query["access_token"], ["abc"])
        self.assertEqual(query["timestamp"], ["123456789"])
        self.assertIn("sign", query)

    def test_send_payload(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"errcode": 0, "errmsg": "ok"}).encode()

        with patch("urllib.request.urlopen", return_value=Response()) as mocked:
            result = send_markdown("标题", "内容", {"access_token": "abc"})
        self.assertEqual(result["errcode"], 0)
        body = json.loads(mocked.call_args.args[0].data.decode())
        self.assertEqual(body["msgtype"], "markdown")


class TestHtmlAndWeb(unittest.TestCase):
    def test_html_escapes_market_text(self):
        report = {
            "strategy": "iron_condor",
            "underlyings": [],
            "errors": [{"symbol": "x", "error": "<script>alert(1)</script>"}],
            "disclaimer": "test",
        }
        html = format_html(report)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert", html)

    def test_config_routes_do_not_expose_dingtalk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            config = load_config(Path(tmp) / "missing.yaml")
            config["dingtalk"]["access_token"] = "private-token"
            save_config(config, path)
            client = create_app(path).test_client()
            response = client.get("/api/config")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("private-token", response.get_data(as_text=True))
            payload = response.get_json()
            payload["strategy"]["quantile"] = 0.88
            saved = client.post("/api/config", json=payload)
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(load_config(path)["strategy"]["quantile"], 0.88)
            self.assertEqual(load_config(path)["dingtalk"]["access_token"], "private-token")


if __name__ == "__main__":
    unittest.main()
