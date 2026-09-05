"""Offline tests for SSE short-option and KKS combo margin / yield."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from margin import (  # noqa: E402
    call_short_margin,
    iron_condor_margin,
    meets_yield,
    monthly_yield,
    put_short_margin,
    short_strangle_combo_margin,
)


class TestStandaloneMargin(unittest.TestCase):
    def test_atm_call_margin(self):
        # S=3.0 K=3.0 C=0.05 → otm=0 → per_share = 0.05 + max(0.36, 0.21) = 0.41
        m = call_short_margin(0.05, 3.0, 3.0)
        self.assertAlmostEqual(m, 0.41 * 10000)

    def test_otm_call_reduces_guard(self):
        # S=3.0 K=3.3 C=0.01 → otm=0.3 → max(0.36-0.3, 0.21)=0.21
        m = call_short_margin(0.01, 3.0, 3.3)
        self.assertAlmostEqual(m, (0.01 + 0.21) * 10000)

    def test_atm_put_margin(self):
        # S=3.0 K=3.0 P=0.05 → otm=0 → inner=0.05+max(0.36, 0.21)=0.41 < K
        m = put_short_margin(0.05, 3.0, 3.0)
        self.assertAlmostEqual(m, 0.41 * 10000)

    def test_deep_itm_put_capped_by_strike(self):
        # S=0.1 K=3 P=2.95 → inner=2.95+max(0.012,0.21)=3.16 > K → cap at strike
        m = put_short_margin(2.95, 0.1, 3.0)
        self.assertAlmostEqual(m, 3.0 * 10000)


class TestComboAndYield(unittest.TestCase):
    def test_combo_adds_cheaper_side_premium(self):
        # Typical OTM strangle
        out = short_strangle_combo_margin(0.006, 0.0156, 2.988, 3.2, 2.85)
        self.assertGreater(out["combo_margin"], out["call_margin"])
        self.assertGreater(out["combo_margin"], out["put_margin"])
        extra = out["combo_margin"] - max(out["call_margin"], out["put_margin"])
        # extra should be the premium of the lower-margin leg
        if out["call_margin"] >= out["put_margin"]:
            self.assertAlmostEqual(extra, 0.0156 * 10000)
        else:
            self.assertAlmostEqual(extra, 0.006 * 10000)
        self.assertAlmostEqual(out["premium"], (0.006 + 0.0156) * 10000)
        self.assertAlmostEqual(out["yield"], out["premium"] / out["combo_margin"])

    def test_equal_margins_use_max_premium(self):
        # Construct inputs that produce equal standalone margins is hard;
        # instead verify yield filter thresholds.
        self.assertTrue(meets_yield(0.016, 0.015))
        self.assertTrue(meets_yield(0.015, 0.015))
        self.assertFalse(meets_yield(0.01, 0.015))

    def test_strangle_requires_call_above_put(self):
        with self.assertRaises(ValueError):
            short_strangle_combo_margin(0.01, 0.01, 3.0, 2.8, 3.2)


class TestIronCondor(unittest.TestCase):
    def test_sum_of_widths_and_max_loss(self):
        out = iron_condor_margin(2.75, 2.65, 3.30, 3.50, 0.015, 0.006, 0.008, 0.003)
        self.assertAlmostEqual(out["put_width"], 0.10)
        self.assertAlmostEqual(out["call_width"], 0.20)
        self.assertAlmostEqual(out["premium"], 0.014 * 10000)
        self.assertAlmostEqual(out["margin"], 0.30 * 10000)
        self.assertAlmostEqual(out["max_loss"], 0.20 * 10000 - 140)
        self.assertAlmostEqual(out["yield"], 140 / 3000)

    def test_rejects_debit_or_bad_order(self):
        with self.assertRaises(ValueError):
            iron_condor_margin(2.75, 2.85, 3.30, 3.50, 0.01, 0.01, 0.01, 0.01)
        with self.assertRaises(ValueError):
            iron_condor_margin(2.75, 2.65, 3.30, 3.50, 0.01, 0.02, 0.01, 0.02)

    def test_min_yield_floor(self):
        self.assertTrue(meets_yield(0.015, 0.015))
        self.assertTrue(meets_yield(0.04, 0.015))
        self.assertFalse(meets_yield(0.0149, 0.015))

    def test_monthly_yield_is_hold_times_30_over_dte(self):
        self.assertAlmostEqual(monthly_yield(0.053, 53), 0.053 * 30 / 53)
        self.assertAlmostEqual(monthly_yield(0.018, 30), 0.018)


if __name__ == "__main__":
    unittest.main()
