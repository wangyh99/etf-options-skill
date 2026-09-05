"""Long-history price-position and trend features for rule-based box forecasts."""

from __future__ import annotations

import math
from typing import Any

from indicators import macd, stdev
from weekly_bars import daily_to_weekly


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def position_at(bars: list[dict], index: int, window: int) -> float | None:
    """Close position in the trailing high-low range; flat ranges map to 0.5."""
    if index < window - 1:
        return None
    rows = bars[index - window + 1:index + 1]
    high = max(float(row["high"]) for row in rows)
    low = min(float(row["low"]) for row in rows)
    if high == low:
        return 0.5
    return (float(bars[index]["close"]) - low) / (high - low)


def moving_average_at(bars: list[dict], index: int, window: int) -> float | None:
    if index < window - 1:
        return None
    return mean([float(row["close"]) for row in bars[index - window + 1:index + 1]])


def true_range_at(bars: list[dict], index: int) -> float:
    row = bars[index]
    if index == 0:
        return float(row["high"]) - float(row["low"])
    prev_close = float(bars[index - 1]["close"])
    return max(
        float(row["high"]) - float(row["low"]),
        abs(float(row["high"]) - prev_close),
        abs(float(row["low"]) - prev_close),
    )


def atr_at(bars: list[dict], index: int, window: int = 20) -> float | None:
    if index < window:
        return None
    return mean([true_range_at(bars, i) for i in range(index - window + 1, index + 1)])


def relative_volume_at(bars: list[dict], index: int, window: int = 20) -> float | None:
    if index < window - 1:
        return None
    values = [bars[i].get("volume") for i in range(index - window + 1, index + 1)]
    if any(value is None for value in values):
        return None
    baseline = mean([float(value) for value in values[:-1]])
    return float(values[-1]) / baseline if baseline else None


def boll_width_percentile(closes: list[float], window: int = 20, lookback: int = 252) -> float | None:
    if len(closes) < window + 10:
        return None
    widths = []
    start = max(window - 1, len(closes) - lookback)
    for index in range(start, len(closes)):
        sample = closes[index - window + 1:index + 1]
        mid = sum(sample) / window
        widths.append((4 * stdev(sample) / mid) if mid else 0.0)
    current = widths[-1]
    return sum(value <= current for value in widths) / len(widths)


def weekly_macd_up(daily_bars: list[dict]) -> bool | None:
    weekly = daily_to_weekly(daily_bars)
    closes = [float(row["close"]) for row in weekly]
    if len(closes) < 40:
        return None
    dif, dea, _hist = macd(closes)
    if dif[-1] is None or dea[-1] is None:
        return None
    return bool(dif[-1] > dea[-1])


def history_bucket(bars: list[dict], index: int) -> str | None:
    """Six coarse buckets: price-position tercile × MA20/MA60 direction."""
    pos = position_at(bars, index, 252)
    ma20 = moving_average_at(bars, index, 20)
    ma60 = moving_average_at(bars, index, 60)
    if pos is None or ma20 is None or ma60 is None:
        return None
    position = "low" if pos < 1 / 3 else "high" if pos > 2 / 3 else "mid"
    trend = "up" if ma20 >= ma60 else "down"
    return f"{position}_{trend}"


def current_features(bars: list[dict]) -> dict[str, Any]:
    if len(bars) < 252:
        raise ValueError(f"need >=252 daily bars for position features, got {len(bars)}")
    index = len(bars) - 1
    close = float(bars[index]["close"])
    atr20 = atr_at(bars, index, 20)
    ma20 = moving_average_at(bars, index, 20)
    ma60 = moving_average_at(bars, index, 60)
    ma250 = moving_average_at(bars, index, 250)
    recent_high60 = max(float(row["high"]) for row in bars[-60:])
    returns = [
        math.log(float(bars[i]["close"]) / float(bars[i - 1]["close"]))
        for i in range(max(1, len(bars) - 60), len(bars))
    ]
    daily_vol = stdev(returns)
    return {
        "close_qfq": close,
        "atr20": atr20,
        "atr_pct": atr20 / close if atr20 and close else None,
        "pos_252": position_at(bars, index, 252),
        "pos_756": position_at(bars, index, 756),
        "pos_1260": position_at(bars, index, 1260),
        "ma20": ma20,
        "ma60": ma60,
        "ma250": ma250,
        "d_ma20_atr": (close - ma20) / atr20 if ma20 and atr20 else None,
        "d_ma60_atr": (close - ma60) / atr20 if ma60 and atr20 else None,
        "d_ma250_atr": (close - ma250) / atr20 if ma250 and atr20 else None,
        "relative_volume20": relative_volume_at(bars, index, 20),
        "weekly_macd_up": weekly_macd_up(bars),
        "boll_width_percentile": boll_width_percentile(
            [float(row["close"]) for row in bars]
        ),
        "near_high_60": close >= recent_high60 * 0.995,
        "daily_vol60": daily_vol,
        "bucket": history_bucket(bars, index),
    }
