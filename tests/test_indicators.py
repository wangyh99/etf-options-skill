"""Offline tests for MACD / KDJ / RSI / BOLL and range expansion."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from indicators import (  # noqa: E402
    boll_last,
    expand_range,
    forecast_month_range,
    kdj,
    macd,
    rsi,
    sma,
)


class TestSmaRsiMacd(unittest.TestCase):
    def test_sma_known(self):
        vals = [1, 2, 3, 4, 5]
        out = sma(vals, 3)
        self.assertIsNone(out[1])
        self.assertAlmostEqual(out[2], 2.0)
        self.assertAlmostEqual(out[4], 4.0)

    def test_rsi_flat_is_neutralish(self):
        closes = [10.0] * 20
        # constant series: after seed, gains=losses=0 → RSI=100 by convention
        series = rsi(closes, 14)
        self.assertIsNotNone(series[-1])
        self.assertGreaterEqual(series[-1], 50)

    def test_rsi_uptrend_high(self):
        closes = [float(i) for i in range(1, 40)]
        v = rsi(closes, 14)[-1]
        self.assertIsNotNone(v)
        self.assertGreater(v, 70)

    def test_macd_uptrend_positive_dif(self):
        closes = [100 + i * 0.5 for i in range(80)]
        dif, dea, hist = macd(closes)
        self.assertIsNotNone(dif[-1])
        self.assertGreater(dif[-1], 0)
        self.assertIsNotNone(hist[-1])


class TestKdjBoll(unittest.TestCase):
    def test_kdj_overbought_on_highs(self):
        highs = [10 + i for i in range(30)]
        lows = [9 + i for i in range(30)]
        closes = [10 + i for i in range(30)]
        _k, _d, j = kdj(highs, lows, closes)
        self.assertIsNotNone(j[-1])
        self.assertGreater(j[-1], 80)

    def test_boll_contains_price_on_gentle_series(self):
        closes = [100 + math.sin(i / 3) * 2 for i in range(40)]
        last = boll_last(closes, 20, 2.0)
        self.assertIsNotNone(last["mid"])
        self.assertLess(last["lower"], closes[-1])
        self.assertGreater(last["upper"], closes[-1])
        self.assertGreater(last["pct_b"], 0)
        self.assertLess(last["pct_b"], 1)


class TestRange(unittest.TestCase):
    def test_expand_range_two_percent(self):
        lo, hi = expand_range(2.87, 3.11, 0.02)
        self.assertAlmostEqual(lo, 2.87 * 0.98)
        self.assertAlmostEqual(hi, 3.11 * 1.02)
        self.assertLess(lo, 2.87)
        self.assertGreater(hi, 3.11)

    def test_expand_range_zero_and_one_percent(self):
        lo, hi = expand_range(3.0, 4.0, 0.0)
        self.assertEqual((lo, hi), (3.0, 4.0))
        lo, hi = expand_range(3.0, 4.0, 0.01)
        self.assertAlmostEqual(lo, 2.97)
        self.assertAlmostEqual(hi, 4.04)

    def test_expand_rejects_bad(self):
        with self.assertRaises(ValueError):
            expand_range(3, 2, 0.02)

    def test_forecast_month_range_shape(self):
        closes, highs, lows = [], [], []
        px = 3.0
        for i in range(120):
            px = px * (1 + 0.002 * math.sin(i / 5) + (0.001 if i % 7 else -0.0005))
            closes.append(px)
            highs.append(px * 1.01)
            lows.append(px * 0.99)
        fc = forecast_month_range(closes, highs, lows)
        self.assertIn(fc["trend"], {
            "偏多", "偏空", "弱多/反弹", "弱空/回调", "震荡",
            "弱空/靠近布林下轨", "弱多/靠近布林上轨",
        })
        pred = fc["predicted_range"]
        trade = fc["trade_range"]
        self.assertLess(pred["lo"], pred["hi"])
        self.assertAlmostEqual(trade["lo"], pred["lo"] * 0.98, places=6)
        self.assertAlmostEqual(trade["hi"], pred["hi"] * 1.02, places=6)
        self.assertLess(trade["lo"], closes[-1])
        self.assertGreater(trade["hi"], closes[-1])

    def test_configurable_quantile_pad_and_daily_horizon(self):
        closes, highs, lows = [], [], []
        for i in range(180):
            px = 3.0 + math.sin(i / 10) * 0.08 + i * 0.0005
            closes.append(px)
            highs.append(px * 1.006)
            lows.append(px * 0.994)
        fc = forecast_month_range(
            closes,
            highs,
            lows,
            hist_q=0.95,
            range_pad=0.05,
            timeframe="daily",
            horizon_bars=30,
        )
        self.assertEqual(fc["timeframe"], "daily")
        self.assertEqual(fc["horizon_bars"], 30)
        self.assertEqual(fc["hist_4w"]["hist_q"], 0.95)
        self.assertAlmostEqual(
            fc["trade_range"]["lo"], fc["predicted_range"]["lo"] * 0.95
        )


if __name__ == "__main__":
    unittest.main()
