"""Offline tests for weekly bar parsers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from weekly_bars import daily_to_weekly, parse_tencent_week  # noqa: E402


class TestWeeklyParse(unittest.TestCase):
    def test_tencent_ohlc_order(self):
        payload = {
            "code": 0,
            "data": {
                "sh510050": {
                    "qfqweek": [
                        ["2026-04-10", "2.901", "2.972", "2.989", "2.895", "1"],
                    ]
                }
            },
        }
        rows = parse_tencent_week(payload, "sh510050")
        self.assertEqual(rows[0]["open"], 2.901)
        self.assertEqual(rows[0]["close"], 2.972)
        self.assertEqual(rows[0]["high"], 2.989)
        self.assertEqual(rows[0]["low"], 2.895)

    def test_daily_to_weekly_aggregates(self):
        dailies = [
            {"date": "2026-08-17", "open": 3.0, "high": 3.1, "low": 2.95, "close": 3.05},
            {"date": "2026-08-18", "open": 3.05, "high": 3.2, "low": 3.0, "close": 3.10},
            {"date": "2026-08-19", "open": 3.10, "high": 3.12, "low": 2.90, "close": 2.98},
        ]
        w = daily_to_weekly(dailies)
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0]["open"], 3.0)
        self.assertEqual(w[0]["close"], 2.98)
        self.assertEqual(w[0]["high"], 3.2)
        self.assertEqual(w[0]["low"], 2.90)
