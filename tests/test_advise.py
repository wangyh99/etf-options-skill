"""Offline tests for expiry pick, strangle scan and yield filter."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from advise_short_strangle import pick_recommendation, scan_strangles  # noqa: E402
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


class TestScanStrangles(unittest.TestCase):
    def test_only_outside_band_and_yield(self):
        # spot 3.0, trade band 2.85–3.15
        chain = [
            _row(2.7, 0.30, 0.020),
            _row(2.8, 0.22, 0.012),
            _row(2.9, 0.14, 0.030),  # put inside band → skip
            _row(3.0, 0.05, 0.05),
            _row(3.1, 0.025, 0.12),  # call inside band → skip
            _row(3.2, 0.010, 0.20),
            _row(3.3, 0.004, 0.30),
        ]
        rows = scan_strangles(chain, spot=3.0, trade_lo=2.85, trade_hi=3.15, min_yield=0.015)
        pairs = {(r["put_k"], r["call_k"]) for r in rows}
        self.assertTrue(pairs)
        for pk, ck in pairs:
            self.assertLessEqual(pk, 2.85)
            self.assertGreaterEqual(ck, 3.15)
            self.assertLess(pk, 3.0)
            self.assertGreater(ck, 3.0)
        self.assertTrue(all(r["yield"] > 0.015 for r in rows))
        self.assertNotIn((2.9, 3.2), pairs)

    def test_empty_when_yield_too_high(self):
        chain = [_row(2.7, 0.01, 0.001), _row(3.4, 0.001, 0.01)]
        rows = scan_strangles(chain, spot=3.0, trade_lo=2.8, trade_hi=3.2, min_yield=0.50)
        self.assertEqual(rows, [])

    def test_pick_recommendation_prefers_higher_yield(self):
        cands = [
            {"put_k": 2.8, "yield": 0.02, "premium_1lot": 100},
            {"put_k": 2.7, "yield": 0.018, "premium_1lot": 80},
        ]
        rec = pick_recommendation(cands, "震荡")
        self.assertEqual(rec["put_k"], 2.8)


if __name__ == "__main__":
    unittest.main()
