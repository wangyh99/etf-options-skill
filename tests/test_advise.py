"""Offline tests for expiry pick, iron-condor scan and yield band."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from advise_short_strangle import format_report, pick_recommendation, scan_iron_condors  # noqa: E402
from fetch_option_chain import pick_month_near_dte  # noqa: E402


def _leg(name: str, mid: float, code: str = "1") -> dict:
    return {"name": name, "mid": mid, "code": code, "iv": 0.18, "last": mid}


def _row(strike: float, call_mid: float | None, put_mid: float | None) -> dict:
    return {
        "strike": strike,
        "call": _leg(f"购{strike}", call_mid) if call_mid else None,
        "put": _leg(f"沽{strike}", put_mid) if put_mid else None,
    }


class TestPickMonth(unittest.TestCase):
    def test_closest_to_30(self):
        infos = [
            {"month": "202608", "expiry": "2026-08-26", "dte": 6},
            {"month": "202609", "expiry": "2026-09-23", "dte": 33},
            {"month": "202612", "expiry": "2026-12-23", "dte": 125},
        ]
        picked = pick_month_near_dte(infos, target_dte=30)
        self.assertEqual(picked["month"], "202609")

    def test_skips_too_short_dte(self):
        infos = [
            {"month": "A", "dte": 5, "expiry": "x"},
            {"month": "B", "dte": 40, "expiry": "y"},
        ]
        picked = pick_month_near_dte(infos, target_dte=30, min_dte=15)
        self.assertEqual(picked["month"], "B")


class TestScanIronCondors(unittest.TestCase):
    def _chain(self):
        # Yield = net credit / (put_width + call_width).
        # 沽2.6/2.8 + 购3.2/3.4 → credit 0.007 / width 0.40 = 1.75%
        return [
            _row(2.5, 0.40, 0.009),
            _row(2.6, 0.32, 0.011),
            _row(2.7, 0.24, 0.013),
            _row(2.8, 0.16, 0.015),
            _row(2.9, 0.10, 0.025),  # put inside band → cannot short
            _row(3.0, 0.05, 0.05),
            _row(3.1, 0.020, 0.12),  # call inside band → cannot short
            _row(3.2, 0.010, 0.20),
            _row(3.3, 0.008, 0.28),
            _row(3.4, 0.007, 0.36),
        ]

    def test_only_outside_band_and_yield_band(self):
        rows = scan_iron_condors(self._chain(), spot=3.0, trade_lo=2.85, trade_hi=3.15)
        self.assertTrue(rows)
        for r in rows:
            self.assertLessEqual(r["short_put_k"], 2.85)
            self.assertGreaterEqual(r["short_call_k"], 3.15)
            self.assertLess(r["long_put_k"], r["short_put_k"])
            self.assertGreater(r["long_call_k"], r["short_call_k"])
            self.assertGreaterEqual(r["yield"], 0.015)
            self.assertLessEqual(r["yield"], 0.022)
        keys = {(r["long_put_k"], r["short_put_k"], r["short_call_k"], r["long_call_k"]) for r in rows}
        self.assertIn((2.6, 2.8, 3.2, 3.4), keys)
        self.assertFalse(any(r["short_put_k"] == 2.9 for r in rows))
        self.assertFalse(any(r["short_call_k"] == 3.1 for r in rows))

    def test_empty_when_outside_band_filter(self):
        rows = scan_iron_condors(
            self._chain(), spot=3.0, trade_lo=2.8, trade_hi=3.2, min_yield=0.50, max_yield=0.60
        )
        self.assertEqual(rows, [])

    def test_pick_recommendation_nearest_target(self):
        cands = [
            {"short_put_k": 2.8, "put_k": 2.8, "yield": 0.021, "premium_1lot": 120},
            {"short_put_k": 2.7, "put_k": 2.7, "yield": 0.018, "premium_1lot": 80},
        ]
        rec = pick_recommendation(cands, "震荡")
        self.assertEqual(rec["short_put_k"], 2.7)

    def test_pick_recommendation_bearish_lower_put(self):
        cands = [
            {"short_put_k": 2.8, "put_k": 2.8, "yield": 0.0185, "premium_1lot": 100},
            {"short_put_k": 2.7, "put_k": 2.7, "yield": 0.0182, "premium_1lot": 90},
        ]
        rec = pick_recommendation(cands, "弱空/回调")
        self.assertEqual(rec["short_put_k"], 2.7)


class TestMarkdownReport(unittest.TestCase):
    def test_format_report_is_markdown(self):
        report = {
            "as_of": "2026-08-22T17:00:00+08:00",
            "target_dte": 30,
            "min_yield": 0.015,
            "max_yield": 0.022,
            "range_pad": 0.02,
            "errors": [],
            "underlyings": [
                {
                    "name": "上证50ETF",
                    "symbol": "510050",
                    "spot": 2.99,
                    "expiry": "2026-09-23",
                    "dte": 32,
                    "weekly_from": "2023-08-11",
                    "weekly_to": "2026-08-21",
                    "weekly_n": 156,
                    "weekly_source": "tencent",
                    "forecast": {
                        "trend": "弱空/回调",
                        "macd": {"signal": "死叉/空头"},
                        "rsi14": 46.0,
                        "rsi_zone": "中性",
                        "kdj": {"zone": "超卖"},
                        "boll": {"pct_b": 0.31},
                        "predicted_range": {"lo": 2.87, "hi": 3.11},
                        "trade_range": {"lo": 2.81, "hi": 3.17},
                    },
                    "action": "卖出铁鹰",
                    "recommended": {
                        "long_put_name": "50ETF沽9月2600",
                        "short_put_name": "50ETF沽9月2800",
                        "short_call_name": "50ETF购9月3200",
                        "long_call_name": "50ETF购9月3400",
                        "premium_1lot": 70,
                        "margin_1lot": 4000,
                        "max_loss_1lot": 1930,
                        "yield_pct": 1.75,
                        "be_dn": 2.793,
                        "be_up": 3.207,
                    },
                    "candidates": [
                        {
                            "label": "沽2.6/2.8 + 购3.2/3.4",
                            "put_k": 2.8,
                            "call_k": 3.2,
                            "long_put_k": 2.6,
                            "long_call_k": 3.4,
                            "premium_1lot": 70,
                            "margin_1lot": 4000,
                            "max_loss_1lot": 1930,
                            "yield_pct": 1.75,
                            "be_dn": 2.793,
                            "be_up": 3.207,
                        }
                    ],
                }
            ],
        }
        md = format_report(report)
        self.assertIn("# 铁鹰建议", md)
        self.assertIn("## 上证50ETF（510050）", md)
        self.assertIn("| 结构 | 净权利金 | 保证金 | 最大亏损 | 收益率 | 盈亏平衡 |", md)
        self.assertIn("| 沽2.6/2.8 + 购3.2/3.4 |", md)
        self.assertIn("### 建议", md)
        self.assertIn("1.5%", md)
        self.assertIn("2.2%", md)
