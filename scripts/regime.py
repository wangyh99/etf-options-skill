"""Auditable market-state rules for asymmetric forecast bands."""

from __future__ import annotations


REGIMES = {
    "high_breakout": {
        "label": "高位突破",
        "up_mult": 1.20,
        "down_mult": 1.00,
        "danger_up": True,
        "danger_down": False,
    },
    "high_reversion": {
        "label": "高位回归",
        "up_mult": 0.90,
        "down_mult": 1.20,
        "danger_up": False,
        "danger_down": True,
    },
    "low_support": {
        "label": "低位支撑",
        "up_mult": 1.05,
        "down_mult": 0.90,
        "danger_up": False,
        "danger_down": False,
    },
    "low_breakdown": {
        "label": "低位续跌",
        "up_mult": 0.90,
        "down_mult": 1.25,
        "danger_up": False,
        "danger_down": True,
    },
    "low_vol_squeeze": {
        "label": "低波挤压",
        "up_mult": 1.10,
        "down_mult": 1.10,
        "danger_up": True,
        "danger_down": True,
    },
    "neutral_range": {
        "label": "中位震荡",
        "up_mult": 1.00,
        "down_mult": 1.00,
        "danger_up": False,
        "danger_down": False,
    },
}


def classify_regime(features: dict) -> dict:
    pos = features["pos_252"]
    close = features["close_qfq"]
    ma20, ma60 = features["ma20"], features["ma60"]
    weekly_up = features.get("weekly_macd_up")
    rel_volume = features.get("relative_volume20")
    trend_up = bool(ma20 and ma60 and close > ma20 > ma60)
    trend_down = bool(ma20 and ma60 and close < ma20 < ma60)
    volume_confirms = rel_volume is None or rel_volume >= 1.0
    squeeze = (
        features.get("boll_width_percentile") is not None
        and features["boll_width_percentile"] <= 0.20
    )
    reasons = []

    if pos >= 0.75 and trend_up and weekly_up is True and (
        volume_confirms or features.get("near_high_60")
    ):
        regime_id = "high_breakout"
        reasons.extend(["Pos252处于高位", "均线多头排列", "周线MACD偏多"])
        if rel_volume is not None and rel_volume >= 1.0:
            reasons.append("成交量不弱")
    elif pos >= 0.75:
        regime_id = "high_reversion"
        reasons.append("Pos252处于高位")
        if not trend_up:
            reasons.append("未保持均线多头排列")
        if weekly_up is False:
            reasons.append("周线MACD偏空")
    elif pos <= 0.25 and (
        (not trend_down and weekly_up is True)
        or (ma20 is not None and close >= ma20 and (rel_volume is None or rel_volume <= 1.0))
    ):
        regime_id = "low_support"
        reasons.extend(["Pos252处于低位", "短线止跌或周线转强"])
    elif pos <= 0.25:
        regime_id = "low_breakdown"
        reasons.append("Pos252处于低位")
        if trend_down:
            reasons.append("均线空头排列")
        if weekly_up is False:
            reasons.append("周线MACD偏空")
    elif squeeze:
        regime_id = "low_vol_squeeze"
        reasons.extend(["布林带宽处于近一年低分位", "突破方向尚未确认"])
    else:
        regime_id = "neutral_range"
        reasons.extend(["价格处于年度区间中部", "未触发突破或破位条件"])

    return {"id": regime_id, "reasons": reasons, **REGIMES[regime_id]}


def core_multipliers(regime: dict) -> tuple[float, float]:
    """Core box uses half the risk regime adjustment."""
    return (
        1.0 + (regime["down_mult"] - 1.0) * 0.5,
        1.0 + (regime["up_mult"] - 1.0) * 0.5,
    )
