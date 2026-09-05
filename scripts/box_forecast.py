"""Rule-based asymmetric core/risk box forecast."""

from __future__ import annotations

import math

from features import current_features, history_bucket
from indicators import forecast_month_range, quantile, stdev
from regime import classify_regime, core_multipliers
from weekly_bars import daily_to_weekly

MIN_CONDITIONAL_SAMPLES = 40


def _path_samples(bars: list[dict], horizon: int) -> list[dict]:
    samples = []
    for index in range(251, len(bars) - horizon):
        close = float(bars[index]["close"])
        future = bars[index + 1:index + 1 + horizon]
        samples.append({
            "low": math.log(min(float(row["low"]) for row in future) / close),
            "high": math.log(max(float(row["high"]) for row in future) / close),
            "bucket": history_bucket(bars, index),
        })
    return samples


def _daily_sigma_floor(bars: list[dict], horizon: int) -> float:
    closes = [float(row["close"]) for row in bars]
    returns = [
        math.log(closes[index] / closes[index - 1])
        for index in range(max(1, len(closes) - 60), len(closes))
    ]
    return 0.85 * stdev(returns) * math.sqrt(horizon)


def _quantile_pair(samples: list[dict], coverage: float, sigma_floor: float) -> tuple[float, float]:
    low = quantile([sample["low"] for sample in samples], 1 - coverage)
    high = quantile([sample["high"] for sample in samples], coverage)
    if low is None or high is None:
        raise ValueError("no path samples for forecast")
    return min(low, -sigma_floor), max(high, sigma_floor)


def _conditional_pair(
    samples: list[dict],
    bucket: str,
    coverage: float,
    sigma_floor: float,
) -> tuple[tuple[float, float], int, bool]:
    matching = [sample for sample in samples if sample["bucket"] == bucket]
    if len(matching) < MIN_CONDITIONAL_SAMPLES:
        return _quantile_pair(samples, coverage, sigma_floor), len(matching), True
    return _quantile_pair(matching, coverage, sigma_floor), len(matching), False


def _range(raw_spot: float, low_log: float, high_log: float) -> dict:
    return {
        "lo": raw_spot * math.exp(low_log),
        "hi": raw_spot * math.exp(high_log),
        "low_log": low_log,
        "high_log": high_log,
    }


def _apply_regime(
    base: tuple[float, float],
    conditional: tuple[float, float],
    regime: dict,
    sigma_floor: float,
    atr_pct: float | None,
    core: bool = False,
) -> tuple[float, float]:
    low = min(base[0], conditional[0])
    high = max(base[1], conditional[1])
    if core:
        down_mult, up_mult = core_multipliers(regime)
    else:
        down_mult, up_mult = regime["down_mult"], regime["up_mult"]
    low *= down_mult
    high *= up_mult
    if regime["danger_down"]:
        low = min(low, base[0], -sigma_floor)
    if regime["danger_up"]:
        high = max(high, base[1], sigma_floor)
    if regime["id"] == "low_support" and atr_pct:
        low = min(low, math.log(max(1 - atr_pct, 0.01)))
    return low, high


def _technical_context(daily_bars: list[dict], timeframe: str, horizon_daily: int, coverage: float) -> dict:
    bars = daily_bars if timeframe == "daily" else daily_to_weekly(daily_bars)
    horizon = horizon_daily if timeframe == "daily" else max(2, math.ceil(horizon_daily / 5))
    return forecast_month_range(
        [float(row["close"]) for row in bars],
        [float(row["high"]) for row in bars],
        [float(row["low"]) for row in bars],
        hist_q=coverage,
        range_pad=0.0,
        timeframe=timeframe,
        horizon_bars=horizon,
    )


def forecast_asymmetric_box(
    daily_bars: list[dict],
    raw_spot: float,
    horizon_daily: int,
    coverage: float,
    range_pad: float,
    timeframe: str = "weekly",
    core_coverage: float = 0.60,
) -> dict:
    """Return baseline, core and risk ranges in current unadjusted-price units."""
    if not 0.50 < core_coverage < coverage < 1.0:
        raise ValueError("coverage must satisfy 0.50 < core < risk < 1.0")
    samples = _path_samples(daily_bars, horizon_daily)
    if len(samples) < 100:
        raise ValueError(f"need >=100 path samples, got {len(samples)}")
    features = current_features(daily_bars)
    regime = classify_regime(features)
    sigma_floor = _daily_sigma_floor(daily_bars, horizon_daily)
    bucket = features["bucket"]

    risk_base = _quantile_pair(samples, coverage, sigma_floor)
    risk_cond, risk_n, risk_fallback = _conditional_pair(
        samples, bucket, coverage, sigma_floor
    )
    risk_logs = _apply_regime(
        risk_base, risk_cond, regime, sigma_floor, features["atr_pct"]
    )

    core_base = _quantile_pair(samples, core_coverage, sigma_floor * 0.65)
    core_cond, core_n, core_fallback = _conditional_pair(
        samples, bucket, core_coverage, sigma_floor * 0.65
    )
    core_logs = _apply_regime(
        core_base,
        core_cond,
        regime,
        sigma_floor * 0.65,
        features["atr_pct"],
        core=True,
    )

    baseline = _range(raw_spot, *risk_base)
    core = _range(raw_spot, *core_logs)
    risk = _range(raw_spot, *risk_logs)
    technical = _technical_context(daily_bars, timeframe, horizon_daily, coverage)
    return {
        **technical,
        "model": "asymmetric",
        "timeframe": timeframe,
        "horizon_bars": horizon_daily if timeframe == "daily" else max(2, math.ceil(horizon_daily / 5)),
        "horizon_daily_bars": horizon_daily,
        "state": regime,
        "position_features": features,
        "sample_info": {
            "all": len(samples),
            "bucket": bucket,
            "conditional": risk_n,
            "risk_fallback": risk_fallback,
            "core_conditional": core_n,
            "core_fallback": core_fallback,
        },
        "baseline_range": baseline,
        "core_range": core,
        "risk_range": risk,
        "predicted_range": {"lo": core["lo"], "hi": core["hi"]},
        "trade_range": {
            "lo": risk["lo"] * (1 - range_pad),
            "hi": risk["hi"] * (1 + range_pad),
            "pad": range_pad,
        },
        "hist_4w": {
            **technical["hist_4w"],
            "hist_q": coverage,
        },
    }
