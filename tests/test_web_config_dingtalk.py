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
        self.assertNotIn("max_yield", out)
        self.assertEqual(validate_strategy_params({"range_pad": 0.0})["range_pad"], 0.0)
        self.assertEqual(validate_strategy_params({"range_pad": 0.01})["range_pad"], 0.01)
        with self.assertRaises(ValueError):
            validate_strategy_params({"quantile": 0.79})
        with self.assertRaises(ValueError):
            validate_strategy_params({"range_pad": -0.01})
        with self.assertRaises(ValueError):
            validate_strategy_params({"range_pad": 0.06})

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

    def test_unknown_path_stays_404(self):
        client = create_app().test_client()
        for path in ("/favicon.ico", "/nope"):
            response = client.get(path)
            self.assertEqual(response.status_code, 404)
            self.assertFalse(response.get_json()["ok"])

    def test_html_renders_asymmetric_boxes(self):
        forecast = {
            "model": "asymmetric",
            "state": {"label": "高位突破", "reasons": ["均线多头"]},
            "position_features": {
                "pos_252": 0.9,
                "pos_756": 0.8,
                "d_ma250_atr": 2.1,
                "atr_pct": 0.01,
            },
            "core_range": {"lo": 2.9, "hi": 3.1},
            "risk_range": {"lo": 2.7, "hi": 3.3},
            "baseline_range": {"lo": 2.8, "hi": 3.2},
            "trade_range": {"lo": 2.65, "hi": 3.35, "pad": 0.02},
            "hist_quantile": 0.9,
            "sample_info": {
                "bucket": "high_up",
                "conditional": 100,
                "all": 1000,
                "risk_fallback": False,
            },
            "timeframe": "weekly",
        }
        report = {
            "strategy": "forecast",
            "errors": [],
            "disclaimer": "test",
            "underlyings": [{
                "name": "上证50ETF",
                "symbol": "510050",
                "bars_from": "2016-01-01",
                "bars_to": "2026-01-01",
                "bars_n": 2400,
                "bars_source": "eastmoney_qfq",
                "expiries": [{
                    "expiry": "2026-09-23",
                    "dte": 19,
                    "forecast": forecast,
                    "recommended": None,
                }],
            }],
        }
        html = format_html(report)
        self.assertNotIn("核心箱体", html)
        self.assertIn("风险箱体", html)
        self.assertIn("无条件基线", html)
        self.assertIn("高位突破", html)

    def test_html_wait_shows_lowest_yield_reference_only(self):
        report = {
            "strategy": "iron_condor",
            "errors": [],
            "disclaimer": "test",
            "underlyings": [{
                "name": "上证50ETF",
                "symbol": "510050",
                "bars_from": "2016-01-01",
                "bars_to": "2026-01-01",
                "bars_n": 2400,
                "bars_source": "eastmoney_qfq",
                "expiries": [{
                    "expiry": "2026-09-23",
                    "dte": 19,
                    "forecast": {
                        "model": "baseline",
                        "predicted_range": {"lo": 2.8, "hi": 3.2},
                        "trade_range": {"lo": 2.7, "hi": 3.3},
                        "trend": "震荡",
                        "timeframe": "weekly",
                        "horizon_bars": 4,
                        "hist_quantile": 0.8,
                        "hist_down_pct": 5,
                        "hist_up_pct": 5,
                        "horizon_sigma_pct": 3,
                    },
                    "recommended": None,
                    "reference": {
                        "label": "沽2.5/2.6 + 购3.4/3.5",
                        "put_k": 2.6,
                        "call_k": 3.4,
                        "premium_1lot": 80,
                        "margin_1lot": 4000,
                        "yield_pct": 0.8,
                        "hold_yield_pct": 0.45,
                        "be_dn": 2.59,
                        "be_up": 3.41,
                        "max_loss_label": "920 元",
                        "legs": [
                            {"action": "买入", "option_type": "认沽", "strike": 2.5},
                            {"action": "卖出", "option_type": "认沽", "strike": 2.6},
                            {"action": "卖出", "option_type": "认购", "strike": 3.4},
                            {"action": "买入", "option_type": "认购", "strike": 3.5},
                        ],
                        "reference_context": {
                            "reason": "strike_coverage",
                            "trade_lo": 2.4,
                            "trade_hi": 3.6,
                            "put_deviation_pct": 8.33,
                            "call_deviation_pct": -5.56,
                            "put_inward_gap_pct": 8.33,
                            "call_inward_gap_pct": 5.56,
                            "max_inward_gap_pct": 8.33,
                            "risk_level": "高",
                            "yield_meets_min": True,
                            "min_yield_pct": 0.5,
                            "buyback_stop_1lot": 160,
                            "stop_loss_1lot": 80,
                        },
                    },
                }],
            }],
        }
        html = format_html(report)
        self.assertIn("action-wait", html)
        self.assertIn("观望", html)
        self.assertIn("recommendation dim", html)
        self.assertIn("月均收益率", html)
        self.assertIn("持有到期 0.45%", html)
        self.assertIn("最终扫描带最近可用档位", html)
        self.assertIn("买入</mark> 认沽 2.5", html)
        self.assertIn("卖出</mark> 认购 3.4", html)
        self.assertIn("并非收益率不足", html)
        self.assertIn("认沽端偏差", html)
        self.assertIn("8.33%", html)
        self.assertIn("初始净权利金的 2 倍", html)

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
            self.assertIn(payload["strategy"]["box_model"], ("baseline", "asymmetric"))
            payload["strategy"]["quantile"] = 0.88
            saved = client.post("/api/config", json=payload)
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(load_config(path)["strategy"]["quantile"], 0.88)
            self.assertEqual(load_config(path)["dingtalk"]["access_token"], "private-token")


if __name__ == "__main__":
    unittest.main()
