"""Offline tests for dual strategy scanning and report formatting."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from advise_short_strangle import format_report  # noqa: E402
from fetch_option_chain import pick_expiries_in_window, pick_month_near_dte  # noqa: E402
from strategy_engine import (  # noqa: E402
    horizon_bars_for_dte,
    pick_recommendation,
    scan_iron_condors,
    scan_short_strangles,
)


def _leg(name: str, mid: float) -> dict:
    return {"name": name, "mid": mid, "last": mid, "code": name, "iv": 0.18}


def _row(strike: float, call_mid: float, put_mid: float) -> dict:
    return {
        "strike": strike,
        "call": _leg(f"购{strike}", call_mid),
        "put": _leg(f"沽{strike}", put_mid),
    }


def chain_fixture() -> list[dict]:
    return [
        _row(2.5, 0.40, 0.009),
        _row(2.6, 0.32, 0.011),
        _row(2.7, 0.24, 0.013),
        _row(2.8, 0.16, 0.015),
        _row(2.9, 0.10, 0.025),
        _row(3.0, 0.05, 0.05),
        _row(3.1, 0.020, 0.12),
        _row(3.2, 0.010, 0.20),
        _row(3.3, 0.008, 0.28),
        _row(3.4, 0.007, 0.36),
    ]


class TestExpirySelection(unittest.TestCase):
    def test_closest_to_30_compatibility(self):
        infos = [
            {"month": "202608", "expiry": "2026-08-26", "dte": 6},
            {"month": "202609", "expiry": "2026-09-23", "dte": 33},
        ]
        self.assertEqual(pick_month_near_dte(infos, 30)["month"], "202609")

    def test_two_expiries_in_window(self):
        infos = [
            {"month": "A", "expiry": "a", "dte": 10},
            {"month": "B", "expiry": "b", "dte": 40},
            {"month": "C", "expiry": "c", "dte": 20},
            {"month": "D", "expiry": "d", "dte": 70},
        ]
        self.assertEqual(
            [x["month"] for x in pick_expiries_in_window(infos, 15, 60, 2)],
            ["C", "B"],
        )

    def test_requires_two_expiries(self):
        with self.assertRaises(ValueError):
            pick_expiries_in_window([{"month": "A", "dte": 30}], 15, 60, 2)

    def test_horizon_tracks_dte(self):
        self.assertEqual(horizon_bars_for_dte(28, "weekly"), 4)
        self.assertEqual(horizon_bars_for_dte(28, "daily"), 20)


class TestDualStrategyScan(unittest.TestCase):
    def test_iron_condor_is_bounded_and_outside_band(self):
        rows = scan_iron_condors(
            chain_fixture(), 3.0, 2.85, 3.15, min_yield=0.015, max_yield=0.022
        )
        self.assertTrue(rows)
        for row in rows:
            self.assertLessEqual(row["short_put_k"], 2.85)
            self.assertGreaterEqual(row["short_call_k"], 3.15)
            self.assertIsInstance(row["max_loss_1lot"], float)
            self.assertGreaterEqual(row["yield"] + 1e-12, 0.015)
            self.assertLessEqual(row["yield"], 0.022 + 1e-12)

    def test_short_strangle_marks_unbounded_loss(self):
        rows = scan_short_strangles(
            chain_fixture(), 3.0, 2.85, 3.15, min_yield=0.01, max_yield=0.20
        )
        self.assertTrue(rows)
        row = rows[0]
        self.assertIsNone(row["max_loss_1lot"])
        self.assertIn("无限", row["max_loss_label"])
        self.assertEqual(len(row["scenarios"]), 4)
        self.assertGreater(row["put_side_loss_at_zero"], 0)

    def test_recommendation_nearest_midpoint(self):
        candidates = [
            {"put_k": 2.8, "yield": 0.021, "premium_1lot": 120},
            {"put_k": 2.7, "yield": 0.018, "premium_1lot": 80},
        ]
        self.assertEqual(pick_recommendation(candidates, "震荡")["put_k"], 2.7)


class TestMarkdownReport(unittest.TestCase):
    def test_strategy_only_hides_forecast(self):
        report = {
            "as_of": "2026-09-04T01:00:00+08:00",
            "strategy": "short_strangle",
            "params": {
                "timeframe": "weekly",
                "quantile": 0.80,
                "range_pad": 0.02,
                "min_yield": 0.01,
                "max_yield": 0.03,
            },
            "errors": [],
            "disclaimer": "仅供研究参考，不构成投资建议。",
            "underlyings": [{
                "name": "上证50ETF",
                "symbol": "510050",
                "expiries": [{
                    "expiry": "2026-09-23",
                    "dte": 19,
                    "forecast": {
                        "predicted_range": {"lo": 2.8, "hi": 3.2},
                        "trade_range": {"lo": 2.7, "hi": 3.3},
                        "trend": "震荡",
                        "hist_quantile": 0.8,
                        "hist_down_pct": 5,
                        "hist_up_pct": 5,
                    },
                    "recommended": {
                        "label": "卖沽2.7 + 卖购3.3",
                        "premium_1lot": 100,
                        "margin_1lot": 3000,
                        "yield_pct": 2,
                        "be_dn": 2.69,
                        "be_up": 3.31,
                        "max_loss_label": "理论无限（认购侧）",
                        "put_side_loss_at_zero": 26900,
                    },
                }],
            }],
        }
        text = format_report(report, strategy_only=True)
        self.assertIn("# 卖出宽跨策略建议", text)
        self.assertIn("最大亏损：**理论无限", text)
        self.assertNotIn("预测区间：", text)


if __name__ == "__main__":
    unittest.main()
