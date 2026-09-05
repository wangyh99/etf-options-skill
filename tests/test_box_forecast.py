"""Offline tests for long-position features, regimes and asymmetric boxes."""

from __future__ import annotations

import math
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from box_forecast import forecast_asymmetric_box  # noqa: E402
from features import current_features, position_at  # noqa: E402
from regime import classify_regime  # noqa: E402


def synthetic_bars(count: int = 1500) -> list[dict]:
    bars = []
    start = date(2019, 1, 1)
    for index in range(count):
        close = 2.0 + index * 0.001 + math.sin(index / 18) * 0.035
        bars.append({
            "date": str(start + timedelta(days=index)),
            "open": close * 0.998,
            "high": close * 1.008,
            "low": close * 0.992,
            "close": close,
            "volume": 1_000_000 + (index % 20) * 1000,
        })
    return bars


class TestPositionFeatures(unittest.TestCase):
    def test_position_endpoints_and_flat_range(self):
        bars = [
            {"high": 10.0, "low": 8.0, "close": 8.0},
            {"high": 12.0, "low": 9.0, "close": 12.0},
        ]
        self.assertEqual(position_at(bars, 1, 2), 1.0)
        flat = [{"high": 3.0, "low": 3.0, "close": 3.0}] * 2
        self.assertEqual(position_at(flat, 1, 2), 0.5)

    def test_long_features_are_available(self):
        features = current_features(synthetic_bars())
        self.assertIsNotNone(features["pos_1260"])
        self.assertIsNotNone(features["d_ma250_atr"])
        self.assertGreater(features["atr20"], 0)


class TestRegime(unittest.TestCase):
    def base(self):
        return {
            "pos_252": 0.9,
            "close_qfq": 3.2,
            "ma20": 3.1,
            "ma60": 3.0,
            "weekly_macd_up": True,
            "relative_volume20": 1.2,
            "near_high_60": True,
            "boll_width_percentile": 0.5,
        }

    def test_high_breakout_and_reversion_differ(self):
        breakout = classify_regime(self.base())
        self.assertEqual(breakout["id"], "high_breakout")
        self.assertTrue(breakout["danger_up"])
        weak = self.base()
        weak.update({"ma20": 3.3, "weekly_macd_up": False, "relative_volume20": 0.7})
        reversion = classify_regime(weak)
        self.assertEqual(reversion["id"], "high_reversion")
        self.assertTrue(reversion["danger_down"])

    def test_low_breakdown(self):
        features = self.base()
        features.update({
            "pos_252": 0.1,
            "close_qfq": 2.5,
            "ma20": 2.7,
            "ma60": 2.9,
            "weekly_macd_up": False,
        })
        self.assertEqual(classify_regime(features)["id"], "low_breakdown")


class TestAsymmetricBox(unittest.TestCase):
    def test_three_boxes_and_raw_price_mapping(self):
        result = forecast_asymmetric_box(
            synthetic_bars(),
            raw_spot=3.20,
            horizon_daily=20,
            coverage=0.80,
            range_pad=0.02,
            timeframe="weekly",
            core_coverage=0.60,
        )
        self.assertEqual(result["model"], "asymmetric")
        self.assertIn("state", result)
        self.assertIn("baseline_range", result)
        self.assertIn("core_range", result)
        self.assertIn("risk_range", result)
        self.assertAlmostEqual(
            result["trade_range"]["lo"], result["risk_range"]["lo"] * 0.98
        )
        self.assertAlmostEqual(
            result["trade_range"]["hi"], result["risk_range"]["hi"] * 1.02
        )
        self.assertLess(result["risk_range"]["lo"], 3.20)
        self.assertGreater(result["risk_range"]["hi"], 3.20)

    def test_breakout_upside_not_narrower_than_baseline(self):
        result = forecast_asymmetric_box(
            synthetic_bars(),
            raw_spot=3.20,
            horizon_daily=30,
            coverage=0.90,
            range_pad=0.03,
        )
        if result["state"]["id"] == "high_breakout":
            self.assertGreaterEqual(
                result["risk_range"]["high_log"],
                result["baseline_range"]["high_log"],
            )


if __name__ == "__main__":
    unittest.main()
