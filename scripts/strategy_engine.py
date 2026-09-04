"""Configurable ETF option forecast and dual-strategy engine."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from fetch_option_chain import SYMBOL_META, fetch_chain, list_month_infos, pick_expiries_in_window
from indicators import forecast_month_range
from margin import (
    iron_condor_margin,
    meets_yield_band,
    short_strangle_risk_profile,
)
from weekly_bars import load_bars_3y

SECIDS = {"510050": "1.510050", "510300": "1.510300"}
DISCLAIMER = (
    "仅供研究参考，不构成投资建议。保证金为交易所公式估算，券商可能上浮；"
    "裸卖宽跨认购侧亏损理论上无上限。"
)


def _leg_mid(leg: dict | None) -> float | None:
    if not leg:
        return None
    return leg.get("mid") or leg.get("last")


def _collect_legs(chain: list[dict], side: str) -> list[tuple[float, dict, float]]:
    legs = []
    for row in chain:
        strike = row.get("strike")
        leg = row.get(side)
        mid = _leg_mid(leg)
        if strike is not None and leg and mid and mid > 0:
            legs.append((float(strike), leg, float(mid)))
    return sorted(legs, key=lambda item: item[0])


def horizon_bars_for_dte(dte: int, timeframe: str) -> int:
    if timeframe == "daily":
        return max(5, round(dte * 5 / 7))
    if timeframe == "weekly":
        return max(2, math.ceil(dte / 7))
    raise ValueError("timeframe must be daily or weekly")


def round_forecast(fc: dict) -> dict:
    def r(value: Any, digits: int = 4):
        return None if value is None else round(float(value), digits)

    return {
        "spot": r(fc["spot"]),
        "trend": fc["trend"],
        "timeframe": fc["timeframe"],
        "horizon_bars": fc["horizon_bars"],
        "macd": {**fc["macd"], "dif": r(fc["macd"]["dif"], 5), "dea": r(fc["macd"]["dea"], 5)},
        "rsi14": r(fc["rsi14"], 2),
        "rsi_zone": fc["rsi_zone"],
        "kdj": {**fc["kdj"], "k": r(fc["kdj"]["k"], 2), "d": r(fc["kdj"]["d"], 2), "j": r(fc["kdj"]["j"], 2)},
        "boll": {key: r(value, 3) for key, value in fc["boll"].items()},
        "ann_vol_pct": r(fc["ann_vol_pct"], 2),
        "horizon_sigma_pct": r(fc["horizon_sigma_pct"], 2),
        "hist_quantile": fc["hist_4w"]["hist_q"],
        "hist_up_pct": r(fc["hist_4w"]["up_q"], 2),
        "hist_down_pct": r(fc["hist_4w"]["dn_q"], 2),
        "predicted_range": {key: r(value) for key, value in fc["predicted_range"].items()},
        "trade_range": {
            "lo": r(fc["trade_range"]["lo"]),
            "hi": r(fc["trade_range"]["hi"]),
            "pad": fc["trade_range"]["pad"],
        },
    }


def forecast_for_expiry(bars: list[dict], dte: int, params: dict) -> dict:
    return round_forecast(
        forecast_month_range(
            [bar["close"] for bar in bars],
            [bar["high"] for bar in bars],
            [bar["low"] for bar in bars],
            hist_q=params["quantile"],
            range_pad=params["range_pad"],
            timeframe=params["timeframe"],
            horizon_bars=horizon_bars_for_dte(dte, params["timeframe"]),
        )
    )


def _iron_condor_row(long_put, short_put, short_call, long_call) -> dict | None:
    lpk, lput, lpm = long_put
    spk, sput, spm = short_put
    sck, scall, scm = short_call
    lck, lcall, lcm = long_call
    try:
        metrics = iron_condor_margin(spk, lpk, sck, lck, spm, lpm, scm, lcm)
    except ValueError:
        return None
    credit = metrics["premium"] / 10000
    return {
        "strategy": "iron_condor",
        "label": f"沽{lpk}/{spk} + 购{sck}/{lck}",
        "legs": [
            {"action": "买入", "name": lput.get("name"), "code": lput.get("code"), "strike": lpk, "mid": lpm},
            {"action": "卖出", "name": sput.get("name"), "code": sput.get("code"), "strike": spk, "mid": spm},
            {"action": "卖出", "name": scall.get("name"), "code": scall.get("code"), "strike": sck, "mid": scm},
            {"action": "买入", "name": lcall.get("name"), "code": lcall.get("code"), "strike": lck, "mid": lcm},
        ],
        "long_put_k": lpk,
        "short_put_k": spk,
        "short_call_k": sck,
        "long_call_k": lck,
        "put_k": spk,
        "call_k": sck,
        "premium_1lot": round(metrics["premium"], 2),
        "margin_1lot": round(metrics["margin"], 2),
        "max_profit_1lot": round(metrics["premium"], 2),
        "max_loss_1lot": round(metrics["max_loss"], 2),
        "max_loss_label": f"{metrics['max_loss']:.0f} 元",
        "yield": metrics["yield"],
        "yield_pct": round(metrics["yield"] * 100, 3),
        "be_dn": round(spk - credit, 4),
        "be_up": round(sck + credit, 4),
    }


def scan_iron_condors(
    chain: list[dict],
    spot: float,
    trade_lo: float,
    trade_hi: float,
    min_yield: float = 0.015,
    max_yield: float = 0.022,
    max_wing_steps: int = 6,
) -> list[dict]:
    puts, calls = _collect_legs(chain, "put"), _collect_legs(chain, "call")
    target = (min_yield + max_yield) / 2
    rows = []
    for put_index, short_put in enumerate(puts):
        if not (short_put[0] <= trade_lo and short_put[0] < spot):
            continue
        for call_index, short_call in enumerate(calls):
            if not (short_call[0] >= trade_hi and short_call[0] > spot):
                continue
            for long_put in puts[max(0, put_index - max_wing_steps):put_index]:
                for long_call in calls[call_index + 1:call_index + 1 + max_wing_steps]:
                    row = _iron_condor_row(long_put, short_put, short_call, long_call)
                    if row and meets_yield_band(row["yield"], min_yield, max_yield):
                        rows.append(row)
    return sorted(rows, key=lambda row: (abs(row["yield"] - target), -row["premium_1lot"]))


def scan_short_strangles(
    chain: list[dict],
    spot: float,
    trade_lo: float,
    trade_hi: float,
    min_yield: float = 0.01,
    max_yield: float = 0.03,
) -> list[dict]:
    puts = [leg for leg in _collect_legs(chain, "put") if leg[0] <= trade_lo and leg[0] < spot]
    calls = [leg for leg in _collect_legs(chain, "call") if leg[0] >= trade_hi and leg[0] > spot]
    target = (min_yield + max_yield) / 2
    rows = []
    for pk, put, pm in puts:
        for ck, call, cm in calls:
            risk = short_strangle_risk_profile(cm, pm, spot, ck, pk)
            if not meets_yield_band(risk["yield"], min_yield, max_yield):
                continue
            credit = pm + cm
            rows.append({
                "strategy": "short_strangle",
                "label": f"卖沽{pk} + 卖购{ck}",
                "legs": [
                    {"action": "卖出", "name": put.get("name"), "code": put.get("code"), "strike": pk, "mid": pm},
                    {"action": "卖出", "name": call.get("name"), "code": call.get("code"), "strike": ck, "mid": cm},
                ],
                "put_k": pk,
                "call_k": ck,
                "premium_1lot": round(risk["premium"], 2),
                "margin_1lot": round(risk["combo_margin"], 2),
                "max_profit_1lot": round(risk["max_profit"], 2),
                "max_loss_1lot": None,
                "max_loss_label": risk["max_loss_label"],
                "put_side_loss_at_zero": round(risk["put_side_loss_at_zero"], 2),
                "scenarios": [
                    {**item, "spot": round(item["spot"], 4), "pnl": round(item["pnl"], 2)}
                    for item in risk["scenarios"]
                ],
                "yield": risk["yield"],
                "yield_pct": round(risk["yield"] * 100, 3),
                "be_dn": round(pk - credit, 4),
                "be_up": round(ck + credit, 4),
            })
    return sorted(rows, key=lambda row: (abs(row["yield"] - target), -row["premium_1lot"]))


def pick_recommendation(candidates: list[dict], trend: str, min_yield: float = 0.015, max_yield: float = 0.022) -> dict | None:
    if not candidates:
        return None
    target = (min_yield + max_yield) / 2
    ranked = sorted(candidates, key=lambda row: (abs(row["yield"] - target), -row["premium_1lot"]))
    if "空" not in trend:
        return ranked[0]
    tolerance = max(abs(ranked[0]["yield"] - target), 0.002)
    nearby = [row for row in ranked if abs(row["yield"] - target) <= tolerance]
    return min(nearby, key=lambda row: (row.get("short_put_k", row["put_k"]), -row["premium_1lot"]))


def forecast_report(params: dict) -> dict:
    underlyings, errors = [], []
    for symbol in params["symbols"]:
        try:
            bars, source = load_bars_3y(SECIDS[symbol], params["timeframe"])
            expiries = pick_expiries_in_window(
                list_month_infos(SYMBOL_META[symbol]["cate"]),
                params["dte_min"],
                params["dte_max"],
                params["expiry_count"],
            )
            underlyings.append({
                "symbol": symbol,
                "name": SYMBOL_META[symbol]["name"],
                "bars_from": bars[0]["date"],
                "bars_to": bars[-1]["date"],
                "bars_n": len(bars),
                "bars_source": source,
                "expiries": [
                    {**expiry, "forecast": forecast_for_expiry(bars, expiry["dte"], params)}
                    for expiry in expiries
                ],
            })
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": symbol, "error": str(exc)})
    return {
        "as_of": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "params": params,
        "underlyings": underlyings,
        "errors": errors,
        "disclaimer": DISCLAIMER,
    }


def advice_report(strategy: str, params: dict) -> dict:
    if strategy not in ("iron_condor", "short_strangle"):
        raise ValueError("strategy must be iron_condor or short_strangle")
    report = forecast_report(params)
    for underlying in report["underlyings"]:
        for expiry in underlying["expiries"]:
            try:
                snap = fetch_chain(underlying["symbol"], expiry["month"])
                fc = expiry["forecast"]
                spot = snap["spot"]["last"] or fc["spot"]
                kwargs = {
                    "chain": snap["chain"],
                    "spot": spot,
                    "trade_lo": fc["trade_range"]["lo"],
                    "trade_hi": fc["trade_range"]["hi"],
                    "min_yield": params["min_yield"],
                    "max_yield": params["max_yield"],
                }
                if strategy == "iron_condor":
                    candidates = scan_iron_condors(
                        **kwargs, max_wing_steps=params["max_wing_steps"]
                    )
                else:
                    candidates = scan_short_strangles(**kwargs)
                expiry.update({
                    "spot": spot,
                    "candidates": candidates,
                    "recommended": pick_recommendation(
                        candidates, fc["trend"], params["min_yield"], params["max_yield"]
                    ),
                    "n_candidates": len(candidates),
                })
            except Exception as exc:  # noqa: BLE001
                expiry["error"] = str(exc)
                expiry["candidates"] = []
                expiry["recommended"] = None
    report["strategy"] = strategy
    return report
