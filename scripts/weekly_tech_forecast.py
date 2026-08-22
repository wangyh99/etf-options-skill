#!/usr/bin/env python3
"""Weekly trend + MACD/RSI/KDJ → 1-month range → short strangle suggestion."""

from __future__ import annotations

import json
import math
import ssl
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_option_chain import fetch_chain  # noqa: E402
from weekly_bars import load_weekly_3y  # noqa: E402

UA = "Mozilla/5.0"
CTX = ssl._create_unverified_context()
MULT = 10000


def http_get(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Referer": "https://finance.eastmoney.com/"}
    )
    with urllib.request.urlopen(req, timeout=30, context=CTX) as resp:
        return resp.read()


def fetch_weekly_em(secid: str, limit: int = 200) -> list[dict]:
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
        f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
        f"&klt=102&fqt=1&end=20500101&lmt={limit}"
    )
    raw = json.loads(http_get(url).decode("utf-8"))
    kl = (raw.get("data") or {}).get("klines") or []
    rows = []
    for line in kl:
        p = line.split(",")
        rows.append(
            {
                "date": p[0],
                "open": float(p[1]),
                "close": float(p[2]),
                "high": float(p[3]),
                "low": float(p[4]),
                "volume": float(p[5]) if p[5] else 0.0,
            }
        )
    return rows


def ema(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    if len(vals) < n:
        return out
    k = 2 / (n + 1)
    s = sum(vals[:n]) / n
    out[n - 1] = s
    for i in range(n, len(vals)):
        s = vals[i] * k + s * (1 - k)
        out[i] = s
    return out


def sma(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    for i in range(n - 1, len(vals)):
        out[i] = sum(vals[i - n + 1 : i + 1]) / n
    return out


def macd(closes: list[float], fast=12, slow=26, signal=9):
    ef, es = ema(closes, fast), ema(closes, slow)
    dif: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        if ef[i] is not None and es[i] is not None:
            dif[i] = ef[i] - es[i]
    dea: list[float | None] = [None] * len(closes)
    valid = [(i, d) for i, d in enumerate(dif) if d is not None]
    if len(valid) >= signal:
        start_i = valid[signal - 1][0]
        seed = sum(d for _, d in valid[:signal]) / signal
        dea[start_i] = seed
        k = 2 / (signal + 1)
        prev = seed
        for i, d in valid[signal:]:
            prev = d * k + prev * (1 - k)
            dea[i] = prev
    hist: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        if dif[i] is not None and dea[i] is not None:
            hist[i] = 2 * (dif[i] - dea[i])
    return dif, dea, hist


def rsi(closes: list[float], n=14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains, losses = [], []
    for i in range(1, n + 1):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0))
        losses.append(max(-ch, 0))
    avg_g, avg_l = sum(gains) / n, sum(losses) / n
    out[n] = 100 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(n + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        g, l = max(ch, 0), max(-ch, 0)
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n
        out[i] = 100 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def kdj(highs, lows, closes, n=9, m1=3, m2=3):
    k_arr: list[float | None] = [None] * len(closes)
    d_arr: list[float | None] = [None] * len(closes)
    j_arr: list[float | None] = [None] * len(closes)
    k_prev, d_prev = 50.0, 50.0
    for i in range(len(closes)):
        if i < n - 1:
            continue
        hh = max(highs[i - n + 1 : i + 1])
        ll = min(lows[i - n + 1 : i + 1])
        rsv = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100
        kv = (m1 - 1) / m1 * k_prev + 1 / m1 * rsv
        dv = (m2 - 1) / m2 * d_prev + 1 / m2 * kv
        jv = 3 * kv - 2 * dv
        k_arr[i], d_arr[i], j_arr[i] = kv, dv, jv
        k_prev, d_prev = kv, dv
    return k_arr, d_arr, j_arr


def quantile(arr: list[float], p: float) -> float | None:
    if not arr:
        return None
    s = sorted(arr)
    idx = min(len(s) - 1, max(0, int(round((len(s) - 1) * p))))
    return s[idx]


def mid(leg):
    if not leg:
        return None
    return leg.get("mid") or leg.get("last")


def analyze_weekly(code: str, name: str, secid: str) -> dict:
    bars, _src = load_weekly_3y(secid)

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    dif, dea, hist = macd(closes)
    rsi14 = rsi(closes, 14)
    kk, dd, jj = kdj(highs, lows, closes)
    ma20 = sma(closes, 20)
    ma60 = sma(closes, 60)

    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    weekly_vol = math.sqrt(var)
    ann_vol = weekly_vol * math.sqrt(52)
    m1_sigma = weekly_vol * math.sqrt(4) * 100

    fwd_up, fwd_dn, fwd_rng = [], [], []
    for i in range(len(closes) - 4):
        hi = max(highs[i + 1 : i + 5])
        lo = min(lows[i + 1 : i + 5])
        fwd_up.append((hi - closes[i]) / closes[i] * 100)
        fwd_dn.append((closes[i] - lo) / closes[i] * 100)
        fwd_rng.append((hi - lo) / closes[i] * 100)

    up60, dn60 = quantile(fwd_up, 0.60), quantile(fwd_dn, 0.60)
    up80, dn80 = quantile(fwd_up, 0.80), quantile(fwd_dn, 0.80)

    i = -1
    spot = closes[i]
    trend = "震荡"
    if ma20[i] and ma60[i]:
        if closes[i] > ma20[i] > ma60[i] and (dif[i] or 0) > (dea[i] or 0):
            trend = "偏多"
        elif closes[i] < ma20[i] < ma60[i] and (dif[i] or 0) < (dea[i] or 0):
            trend = "偏空"
        elif closes[i] > ma20[i]:
            trend = "弱多/反弹"
        elif closes[i] < ma20[i]:
            trend = "弱空/回调"

    macd_sig = "金叉/多头" if dif[i] is not None and dea[i] is not None and dif[i] > dea[i] else "死叉/空头"
    if hist[i] is not None and hist[i - 1] is not None:
        if hist[i] > hist[i - 1] and hist[i] < 0:
            macd_sig += "（绿柱缩短）"
        elif hist[i] < hist[i - 1] and hist[i] > 0:
            macd_sig += "（红柱缩短）"

    rsi_v = rsi14[i]
    if rsi_v is None:
        rsi_zone = "n/a"
    elif rsi_v >= 70:
        rsi_zone = "超买"
    elif rsi_v >= 55:
        rsi_zone = "偏强"
    elif rsi_v <= 30:
        rsi_zone = "超卖"
    elif rsi_v <= 45:
        rsi_zone = "偏弱"
    else:
        rsi_zone = "中性"

    if jj[i] is None:
        kdj_zone = "n/a"
    elif jj[i] >= 80:
        kdj_zone = "超买"
    elif jj[i] <= 20:
        kdj_zone = "超卖"
    elif kk[i] is not None and dd[i] is not None and kk[i] > dd[i]:
        kdj_zone = "金叉偏多"
    else:
        kdj_zone = "死叉偏空"

    bias = 0.0
    if rsi_zone in ("超卖", "偏弱") and kdj_zone in ("超卖", "金叉偏多"):
        bias = 0.35
    elif rsi_zone in ("超买", "偏强") and kdj_zone in ("超买", "死叉偏空"):
        bias = -0.35

    # blend hist percentile with vol sigma
    dn_use = max(dn80 or 0, m1_sigma * 0.85)
    up_use = max(up80 or 0, m1_sigma * 0.85)
    likely_lo = spot * (1 - dn_use / 100)
    likely_hi = spot * (1 + up_use / 100)
    midp = (likely_lo + likely_hi) / 2 * (1 + bias / 100)
    half = (likely_hi - likely_lo) / 2
    likely_lo, likely_hi = midp - half, midp + half

    wide_lo = spot * (1 - max(dn80 or 0, m1_sigma * 1.25) / 100)
    wide_hi = spot * (1 + max(up80 or 0, m1_sigma * 1.25) / 100)

    last52 = bars[-52:] if len(bars) >= 52 else bars
    return {
        "symbol": code,
        "name": name,
        "from": bars[0]["date"],
        "to": bars[-1]["date"],
        "bars_n": len(bars),
        "spot": spot,
        "ma20": round(ma20[i], 4) if ma20[i] else None,
        "ma60": round(ma60[i], 4) if ma60[i] else None,
        "trend": trend,
        "macd": {
            "dif": round(dif[i], 5) if dif[i] is not None else None,
            "dea": round(dea[i], 5) if dea[i] is not None else None,
            "hist": round(hist[i], 5) if hist[i] is not None else None,
            "signal": macd_sig,
        },
        "rsi14": round(rsi_v, 2) if rsi_v is not None else None,
        "rsi_zone": rsi_zone,
        "kdj": {
            "k": round(kk[i], 2) if kk[i] is not None else None,
            "d": round(dd[i], 2) if dd[i] is not None else None,
            "j": round(jj[i], 2) if jj[i] is not None else None,
            "zone": kdj_zone,
        },
        "ann_vol_pct": round(ann_vol * 100, 2),
        "month_1sigma_pct": round(m1_sigma, 2),
        "hist_4w": {
            "n": len(fwd_up),
            "up_p50": round(quantile(fwd_up, 0.5) or 0, 2),
            "up_p60": round(up60 or 0, 2),
            "up_p80": round(up80 or 0, 2),
            "dn_p50": round(quantile(fwd_dn, 0.5) or 0, 2),
            "dn_p60": round(dn60 or 0, 2),
            "dn_p80": round(dn80 or 0, 2),
            "range_p60": round(quantile(fwd_rng, 0.6) or 0, 2),
            "range_p80": round(quantile(fwd_rng, 0.8) or 0, 2),
        },
        "likely_range": {
            "lo": round(likely_lo, 4),
            "hi": round(likely_hi, 4),
            "lo_pct": round((likely_lo / spot - 1) * 100, 2),
            "hi_pct": round((likely_hi / spot - 1) * 100, 2),
        },
        "wide_range": {
            "lo": round(wide_lo, 4),
            "hi": round(wide_hi, 4),
            "lo_pct": round((wide_lo / spot - 1) * 100, 2),
            "hi_pct": round((wide_hi / spot - 1) * 100, 2),
        },
        "year_range": {
            "lo": min(b["low"] for b in last52),
            "hi": max(b["high"] for b in last52),
        },
    }


def nearest_strike(strikes: list[float], target: float, side: str) -> float | None:
    if side == "put":
        cands = [k for k in strikes if k <= target]
        return max(cands) if cands else None
    cands = [k for k in strikes if k >= target]
    return min(cands) if cands else None


def short_strangle_for(tech: dict, month: str = "202609") -> dict:
    snap = fetch_chain(tech["symbol"], month)
    spot = snap["spot"]["last"] or tech["spot"]
    by = {r["strike"]: r for r in snap["chain"]}
    strikes = sorted(by.keys())

    # Place short put near/below likely_lo, short call near/above likely_hi
    # Prefer outside wide_range for "safer", inside for "richer" — recommend outside likely, inside wide
    put_target = tech["likely_range"]["lo"]
    call_target = tech["likely_range"]["hi"]
    # push one more step outside for buffer (~0.5% extra)
    put_target *= 0.995
    call_target *= 1.005

    pk = nearest_strike(strikes, put_target, "put")
    ck = nearest_strike(strikes, call_target, "call")
    # ensure OTM
    if pk is not None and pk >= spot:
        pk = nearest_strike([k for k in strikes if k < spot], spot * 0.97, "put")
    if ck is not None and ck <= spot:
        ck = nearest_strike([k for k in strikes if k > spot], spot * 1.03, "call")

    alts = []
    for label, p_t, c_t in [
        ("贴合月波动(likely)", tech["likely_range"]["lo"] * 0.995, tech["likely_range"]["hi"] * 1.005),
        ("更保守(wide)", tech["wide_range"]["lo"] * 0.99, tech["wide_range"]["hi"] * 1.01),
        ("约±1σ", spot * (1 - tech["month_1sigma_pct"] / 100), spot * (1 + tech["month_1sigma_pct"] / 100)),
    ]:
        p = nearest_strike(strikes, p_t, "put")
        c = nearest_strike(strikes, c_t, "call")
        if p is None or c is None or p >= spot or c <= spot:
            continue
        put, call = by[p].get("put") or {}, by[c].get("call") or {}
        pm, cm = mid(put), mid(call)
        if pm is None or cm is None or pm <= 0 or cm <= 0:
            continue
        prem = pm + cm
        be_dn, be_up = p - prem, c + prem

        def pnl(s, pk=p, ck=c, prem=prem):
            return prem - max(pk - s, 0) - max(s - ck, 0)

        alts.append(
            {
                "style": label,
                "put_k": p,
                "call_k": c,
                "put_name": put.get("name"),
                "call_name": call.get("name"),
                "put_mid": round(pm, 4),
                "call_mid": round(cm, 4),
                "put_iv": None if put.get("iv") is None else round(put["iv"] * 100, 1),
                "call_iv": None if call.get("iv") is None else round(call["iv"] * 100, 1),
                "premium_1lot": round(prem * MULT, 2),
                "premium_bid_1lot": round(((put.get("bid") or 0) + (call.get("bid") or 0)) * MULT, 2),
                "be_dn": round(be_dn, 4),
                "be_up": round(be_up, 4),
                "cushion_dn_pct": round((spot - be_dn) / spot * 100, 2),
                "cushion_up_pct": round((be_up - spot) / spot * 100, 2),
                "put_otm_pct": round((spot - p) / spot * 100, 2),
                "call_otm_pct": round((c - spot) / spot * 100, 2),
                "pnl_m10": round(pnl(spot * 0.9) * MULT, 2),
                "pnl_p10": round(pnl(spot * 1.1) * MULT, 2),
                "covers_likely": p <= tech["likely_range"]["lo"] and c >= tech["likely_range"]["hi"],
                "covers_wide": p <= tech["wide_range"]["lo"] and c >= tech["wide_range"]["hi"],
            }
        )

    # pick best: prefer covers_likely, then max premium among those with cushion >= month_1sigma*0.9
    best = None
    scored = []
    for a in alts:
        score = a["premium_1lot"]
        if a["covers_likely"]:
            score += 200
        if a["covers_wide"]:
            score += 50
        # penalize if cushion < 1sigma
        if a["cushion_dn_pct"] < tech["month_1sigma_pct"] * 0.85:
            score -= 150
        if a["cushion_up_pct"] < tech["month_1sigma_pct"] * 0.85:
            score -= 150
        # prefer balanced wings
        bal = abs(a["put_otm_pct"] - a["call_otm_pct"])
        score -= bal * 5
        scored.append((score, a))
    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][1] if scored else None

    return {
        "expiry": snap["expiry"],
        "dte": snap["dte"],
        "spot": spot,
        "candidates": alts,
        "recommended": best,
    }


def main() -> int:
    specs = [
        ("510050", "上证50ETF", "1.510050"),
        ("510300", "沪深300ETF", "1.510300"),
    ]
    underlyings = []
    for code, name, secid in specs:
        tech = analyze_weekly(code, name, secid)
        opt = short_strangle_for(tech, "202609")
        underlyings.append({**tech, "options": opt})
        print(f"\n=== {code} {name} ===")
        print(f"spot={tech['spot']} trend={tech['trend']} MACD={tech['macd']['signal']}")
        print(f"RSI={tech['rsi14']}({tech['rsi_zone']}) KDJ={tech['kdj']} zone={tech['kdj']['zone']}")
        print(f"annVol={tech['ann_vol_pct']}% 1mσ={tech['month_1sigma_pct']}%")
        print(f"likely {tech['likely_range']} wide {tech['wide_range']}")
        rec = opt.get("recommended")
        if rec:
            print(
                f"REC short {rec['put_k']}/{rec['call_k']} prem={rec['premium_1lot']} "
                f"BE=[{rec['be_dn']},{rec['be_up']}] style={rec['style']}"
            )

    report = {
        "as_of": datetime.now().astimezone().isoformat(timespec="seconds"),
        "horizon": "约1个月（对齐9月期权DTE）",
        "method": "近3年周线：MA趋势+MACD+RSI+KDJ；4周历史分位与周波动折算月σ；在9月链上选卖出宽跨",
        "disclaimer": "仅供研究参考，不构成投资建议。技术指标与历史分位不能预测未来；裸卖认购侧亏损理论上不封顶。",
        "underlyings": underlyings,
    }
    out = ROOT / "data" / "weekly_strangle_reco.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
