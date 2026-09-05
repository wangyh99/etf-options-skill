"""Configurable ETF option forecast and dual-strategy engine."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from box_forecast import forecast_asymmetric_box
from fetch_option_chain import (
    SYMBOL_META,
    fetch_chain,
    list_month_infos,
    pick_expiries_in_window,
    underlying_spot,
)
from indicators import forecast_month_range
from margin import (
    iron_condor_margin,
    meets_yield,
    monthly_yield,
    short_strangle_risk_profile,
)
from weekly_bars import daily_to_weekly, load_daily_history

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

    output = {
        "spot": r(fc["spot"]),
        "model": fc.get("model", "baseline"),
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
    if fc.get("state"):
        output["state"] = {
            **fc["state"],
            "reasons": list(fc["state"].get("reasons") or []),
        }
    if fc.get("position_features"):
        output["position_features"] = {
            key: r(value, 3) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
            for key, value in fc["position_features"].items()
        }
    for key in ("baseline_range", "core_range", "risk_range"):
        if fc.get(key):
            output[key] = {
                item: r(value, 5) for item, value in fc[key].items()
            }
    if fc.get("sample_info"):
        output["sample_info"] = dict(fc["sample_info"])
    output["horizon_daily_bars"] = fc.get("horizon_daily_bars")
    return output


def forecast_for_expiry(
    daily_bars: list[dict],
    dte: int,
    params: dict,
    raw_spot: float | None = None,
) -> dict:
    if params.get("box_model", "asymmetric") == "asymmetric":
        fc = forecast_asymmetric_box(
            daily_bars,
            raw_spot or float(daily_bars[-1]["close"]),
            horizon_bars_for_dte(dte, "daily"),
            params["quantile"],
            params["range_pad"],
            timeframe=params["timeframe"],
            core_coverage=params.get("core_quantile", 0.60),
        )
    else:
        bars = daily_bars if params["timeframe"] == "daily" else daily_to_weekly(daily_bars)
        fc = forecast_month_range(
            [bar["close"] for bar in bars],
            [bar["high"] for bar in bars],
            [bar["low"] for bar in bars],
            hist_q=params["quantile"],
            range_pad=params["range_pad"],
            timeframe=params["timeframe"],
            horizon_bars=horizon_bars_for_dte(dte, params["timeframe"]),
        )
        factor = (raw_spot or fc["spot"]) / fc["spot"]
        for name in ("predicted_range", "trade_range"):
            fc[name]["lo"] *= factor
            fc[name]["hi"] *= factor
        fc["spot"] = raw_spot or fc["spot"]
        fc["model"] = "baseline"
        fc["baseline_range"] = {
            "lo": fc["predicted_range"]["lo"],
            "hi": fc["predicted_range"]["hi"],
        }
        fc["core_range"] = dict(fc["predicted_range"])
        fc["risk_range"] = dict(fc["predicted_range"])
    return round_forecast(fc)


def _with_monthly_yield(row: dict, dte: int) -> dict:
    hold = float(row["hold_yield"])
    monthly = monthly_yield(hold, dte)
    row["dte"] = dte
    row["hold_yield_pct"] = round(hold * 100, 3)
    row["yield"] = monthly
    row["yield_pct"] = round(monthly * 100, 3)
    return row


def _iron_condor_row(long_put, short_put, short_call, long_call, dte: int) -> dict | None:
    lpk, lput, lpm = long_put
    spk, sput, spm = short_put
    sck, scall, scm = short_call
    lck, lcall, lcm = long_call
    try:
        metrics = iron_condor_margin(spk, lpk, sck, lck, spm, lpm, scm, lcm)
    except ValueError:
        return None
    credit = metrics["premium"] / 10000
    row = {
        "strategy": "iron_condor",
        "label": f"沽{lpk}/{spk} + 购{sck}/{lck}",
        "legs": [
            {"action": "买入", "option_type": "认沽", "name": lput.get("name"), "code": lput.get("code"), "strike": lpk, "mid": lpm},
            {"action": "卖出", "option_type": "认沽", "name": sput.get("name"), "code": sput.get("code"), "strike": spk, "mid": spm},
            {"action": "卖出", "option_type": "认购", "name": scall.get("name"), "code": scall.get("code"), "strike": sck, "mid": scm},
            {"action": "买入", "option_type": "认购", "name": lcall.get("name"), "code": lcall.get("code"), "strike": lck, "mid": lcm},
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
        "hold_yield": metrics["yield"],
        "be_dn": round(spk - credit, 4),
        "be_up": round(sck + credit, 4),
    }
    return _with_monthly_yield(row, dte)


def scan_iron_condors(
    chain: list[dict],
    spot: float,
    trade_lo: float,
    trade_hi: float,
    dte: int,
    min_yield: float = 0.015,
    max_wing_steps: int = 6,
    yield_filter: bool = True,
) -> list[dict]:
    puts, calls = _collect_legs(chain, "put"), _collect_legs(chain, "call")
    rows = []
    for put_index, short_put in enumerate(puts):
        if not (short_put[0] <= trade_lo and short_put[0] < spot):
            continue
        for call_index, short_call in enumerate(calls):
            if not (short_call[0] >= trade_hi and short_call[0] > spot):
                continue
            for long_put in puts[max(0, put_index - max_wing_steps):put_index]:
                for long_call in calls[call_index + 1:call_index + 1 + max_wing_steps]:
                    row = _iron_condor_row(long_put, short_put, short_call, long_call, dte)
                    if row and (not yield_filter or meets_yield(row["yield"], min_yield)):
                        row["trade_lo"] = trade_lo
                        row["trade_hi"] = trade_hi
                        rows.append(row)
    return sorted(rows, key=_selection_key)


def scan_short_strangles(
    chain: list[dict],
    spot: float,
    trade_lo: float,
    trade_hi: float,
    dte: int,
    min_yield: float = 0.01,
    yield_filter: bool = True,
) -> list[dict]:
    puts = [leg for leg in _collect_legs(chain, "put") if leg[0] <= trade_lo and leg[0] < spot]
    calls = [leg for leg in _collect_legs(chain, "call") if leg[0] >= trade_hi and leg[0] > spot]
    rows = []
    for pk, put, pm in puts:
        for ck, call, cm in calls:
            row = _short_strangle_row((pk, put, pm), (ck, call, cm), spot, dte)
            if yield_filter and not meets_yield(row["yield"], min_yield):
                continue
            row["trade_lo"] = trade_lo
            row["trade_hi"] = trade_hi
            rows.append(row)
    return sorted(rows, key=_selection_key)


def _short_strangle_row(short_put, short_call, spot: float, dte: int) -> dict:
    pk, put, pm = short_put
    ck, call, cm = short_call
    risk = short_strangle_risk_profile(cm, pm, spot, ck, pk)
    credit = pm + cm
    row = {
        "strategy": "short_strangle",
        "label": f"卖沽{pk} + 卖购{ck}",
        "legs": [
            {"action": "卖出", "option_type": "认沽", "name": put.get("name"), "code": put.get("code"), "strike": pk, "mid": pm},
            {"action": "卖出", "option_type": "认购", "name": call.get("name"), "code": call.get("code"), "strike": ck, "mid": cm},
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
        "hold_yield": risk["yield"],
        "be_dn": round(pk - credit, 4),
        "be_up": round(ck + credit, 4),
    }
    return _with_monthly_yield(row, dte)


def reference_nearest_trade_band(
    strategy: str,
    chain: list[dict],
    spot: float,
    trade_lo: float,
    trade_hi: float,
    min_yield: float = 0.015,
    dte: int = 30,
) -> dict | None:
    """Build a fallback from market strikes nearest the final scan-band edges."""
    puts = [leg for leg in _collect_legs(chain, "put") if leg[0] < spot]
    calls = [leg for leg in _collect_legs(chain, "call") if leg[0] > spot]
    if not puts or not calls:
        return None
    short_put_pool = puts[1:] if strategy == "iron_condor" else puts
    short_call_pool = calls[:-1] if strategy == "iron_condor" else calls
    if not short_put_pool or not short_call_pool:
        return None
    short_put = min(short_put_pool, key=lambda leg: (abs(leg[0] - trade_lo), leg[0]))
    short_call = min(short_call_pool, key=lambda leg: (abs(leg[0] - trade_hi), -leg[0]))
    if strategy == "short_strangle":
        row = _short_strangle_row(short_put, short_call, spot, dte)
    else:
        lower_puts = [leg for leg in puts if leg[0] < short_put[0]]
        higher_calls = [leg for leg in calls if leg[0] > short_call[0]]
        if not lower_puts or not higher_calls:
            return None
        long_put = max(lower_puts, key=lambda leg: leg[0])
        long_call = min(higher_calls, key=lambda leg: leg[0])
        row = _iron_condor_row(long_put, short_put, short_call, long_call, dte)
        if row is None:
            return None

    put_deviation_pct = (row["put_k"] / trade_lo - 1) * 100
    call_deviation_pct = (row["call_k"] / trade_hi - 1) * 100
    put_inward_gap_pct = max(put_deviation_pct, 0.0)
    call_inward_gap_pct = max(-call_deviation_pct, 0.0)
    max_inward_gap_pct = max(put_inward_gap_pct, call_inward_gap_pct)
    if max_inward_gap_pct > 0.005:
        reason = "strike_coverage"
    elif not meets_yield(row["yield"], min_yield):
        reason = "yield_below_min"
    else:
        reason = "structure_unavailable"
    row["reference_context"] = {
        "reason": reason,
        "trade_lo": round(trade_lo, 4),
        "trade_hi": round(trade_hi, 4),
        "put_deviation_pct": round(put_deviation_pct, 2),
        "call_deviation_pct": round(call_deviation_pct, 2),
        "put_inward_gap_pct": round(put_inward_gap_pct, 2),
        "call_inward_gap_pct": round(call_inward_gap_pct, 2),
        "max_inward_gap_pct": round(max_inward_gap_pct, 2),
        "risk_level": "高" if max_inward_gap_pct >= 5 else "中" if max_inward_gap_pct >= 2 else "低",
        "yield_meets_min": meets_yield(row["yield"], min_yield),
        "min_yield_pct": round(min_yield * 100, 2),
        "buyback_stop_1lot": round(row["premium_1lot"] * 2, 2),
        "stop_loss_1lot": round(row["premium_1lot"], 2),
    }
    return row


def _band_distance(row: dict, trade_lo: float | None = None, trade_hi: float | None = None) -> float:
    lo = trade_lo if trade_lo is not None else row.get("trade_lo")
    hi = trade_hi if trade_hi is not None else row.get("trade_hi")
    if lo is None or hi is None:
        return 0.0
    put_k = float(row.get("short_put_k", row["put_k"]))
    call_k = float(row.get("short_call_k", row["call_k"]))
    return abs(put_k - lo) + abs(call_k - hi)


def _selection_key(row: dict) -> tuple:
    """Prefer shorts nearest the scan-band edges, then lower defined risk, then lower yield."""
    defined_loss = row.get("max_loss_1lot")
    if defined_loss is None:
        defined_loss = float("inf")
    return (_band_distance(row), defined_loss, row["yield"])


def pick_recommendation(
    candidates: list[dict],
    trend: str | None = None,
    min_yield: float = 0.015,
    trade_lo: float | None = None,
    trade_hi: float | None = None,
) -> dict | None:
    qualified = [row for row in candidates if meets_yield(row["yield"], min_yield)]
    if not qualified:
        return None
    if trade_lo is not None and trade_hi is not None:
        for row in qualified:
            row["trade_lo"] = trade_lo
            row["trade_hi"] = trade_hi
    return min(qualified, key=_selection_key)


def forecast_report(params: dict) -> dict:
    underlyings, errors = [], []
    for symbol in params["symbols"]:
        try:
            bars, source = load_daily_history(
                SECIDS[symbol], params.get("history_years", 10)
            )
            raw_spot = underlying_spot(SYMBOL_META[symbol]["hq"])["last"]
            if raw_spot is None:
                raise RuntimeError(f"no spot for {symbol}")
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
                    {
                        **expiry,
                        "forecast": forecast_for_expiry(
                            bars, expiry["dte"], params, raw_spot
                        ),
                    }
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
                    "dte": expiry["dte"],
                    "yield_filter": False,
                }
                if strategy == "iron_condor":
                    usable = scan_iron_condors(
                        **kwargs, max_wing_steps=params["max_wing_steps"]
                    )
                else:
                    usable = scan_short_strangles(**kwargs)
                candidates = [
                    row for row in usable
                    if meets_yield(row["yield"], params["min_yield"])
                ]
                recommended = pick_recommendation(
                    candidates,
                    fc["trend"],
                    params["min_yield"],
                    fc["trade_range"]["lo"],
                    fc["trade_range"]["hi"],
                )
                expiry.update({
                    "spot": spot,
                    "candidates": candidates,
                    "n_candidates": len(candidates),
                    "n_usable": len(usable),
                    "recommended": recommended,
                    "reference": None if recommended else reference_nearest_trade_band(
                        strategy,
                        snap["chain"],
                        spot,
                        fc["trade_range"]["lo"],
                        fc["trade_range"]["hi"],
                        params["min_yield"],
                        expiry["dte"],
                    ),
                })
            except Exception as exc:  # noqa: BLE001
                expiry["error"] = str(exc)
                expiry["candidates"] = []
                expiry["recommended"] = None
                expiry["reference"] = None
    report["strategy"] = strategy
    return report
