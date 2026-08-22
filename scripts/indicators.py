"""Weekly technicals: MACD, KDJ (JDK), RSI, BOLL."""

from __future__ import annotations

import math


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


def stdev(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    mean = sum(vals) / len(vals)
    var = sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)
    return math.sqrt(var)


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
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


def rsi(closes: list[float], n: int = 14) -> list[float | None]:
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


def kdj(highs: list[float], lows: list[float], closes: list[float], n: int = 9, m1: int = 3, m2: int = 3):
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


def boll(closes: list[float], n: int = 20, k: float = 2.0):
    """Return (mid, upper, lower) series. Sample stdev, period n, k sigma."""
    mid = sma(closes, n)
    upper: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        sd = stdev(closes[i - n + 1 : i + 1])
        m = mid[i]
        if m is None:
            continue
        upper[i] = m + k * sd
        lower[i] = m - k * sd
    return mid, upper, lower


def boll_last(closes: list[float], n: int = 20, k: float = 2.0) -> dict:
    mid, upper, lower = boll(closes, n, k)
    i = -1
    m, u, lo = mid[i], upper[i], lower[i]
    if m is None or u is None or lo is None or u == lo:
        return {"mid": m, "upper": u, "lower": lo, "pct_b": None, "width_pct": None}
    pct_b = (closes[i] - lo) / (u - lo)
    width_pct = (u - lo) / m * 100 if m else None
    return {
        "mid": m,
        "upper": u,
        "lower": lo,
        "pct_b": pct_b,
        "width_pct": width_pct,
    }


def quantile(arr: list[float], p: float) -> float | None:
    if not arr:
        return None
    s = sorted(arr)
    idx = min(len(s) - 1, max(0, int(round((len(s) - 1) * p))))
    return s[idx]


def classify_rsi(rsi_v: float | None) -> str:
    if rsi_v is None:
        return "n/a"
    if rsi_v >= 70:
        return "超买"
    if rsi_v >= 55:
        return "偏强"
    if rsi_v <= 30:
        return "超卖"
    if rsi_v <= 45:
        return "偏弱"
    return "中性"


def classify_kdj(k: float | None, d: float | None, j: float | None) -> str:
    if j is None:
        return "n/a"
    if j >= 80:
        return "超买"
    if j <= 20:
        return "超卖"
    if k is not None and d is not None and k > d:
        return "金叉偏多"
    return "死叉偏空"


def classify_macd(dif: float | None, dea: float | None, hist: float | None, prev_hist: float | None) -> str:
    if dif is None or dea is None:
        return "n/a"
    sig = "金叉/多头" if dif > dea else "死叉/空头"
    if hist is not None and prev_hist is not None:
        if hist > prev_hist and hist < 0:
            sig += "（绿柱缩短）"
        elif hist < prev_hist and hist > 0:
            sig += "（红柱缩短）"
    return sig


def classify_trend(close: float, ma20: float | None, ma60: float | None, dif: float | None, dea: float | None, pct_b: float | None) -> str:
    if ma20 is None:
        return "震荡"
    macd_up = dif is not None and dea is not None and dif > dea
    if ma60 is not None and close > ma20 > ma60 and macd_up:
        return "偏多"
    if ma60 is not None and close < ma20 < ma60 and not macd_up:
        return "偏空"
    if pct_b is not None and pct_b < 0.2:
        return "弱空/靠近布林下轨"
    if pct_b is not None and pct_b > 0.8:
        return "弱多/靠近布林上轨"
    if close > ma20:
        return "弱多/反弹"
    if close < ma20:
        return "弱空/回调"
    return "震荡"


def expand_range(lo: float, hi: float, pad: float = 0.02) -> tuple[float, float]:
    """Widen a price band by pad on each side (default +2% / -2%)."""
    if lo <= 0 or hi <= 0 or hi < lo:
        raise ValueError("invalid range")
    return lo * (1 - pad), hi * (1 + pad)


# Historical 4-week one-sided move quantile used for the predicted band.
HIST_RANGE_Q = 0.80


def forecast_month_range(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    hist_q: float = HIST_RANGE_Q,
) -> dict:
    """Blend 3y weekly hist 4-week range (default P80), vol, MACD/RSI/KDJ/BOLL into a 1-month band."""
    if len(closes) < 80:
        raise ValueError(f"need >=80 weekly bars, got {len(closes)}")

    dif, dea, hist = macd(closes)
    rsi14 = rsi(closes)
    kk, dd, jj = kdj(highs, lows, closes)
    ma20 = sma(closes, 20)
    ma60 = sma(closes, 60)
    bl = boll_last(closes)

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

    up_q, dn_q = quantile(fwd_up, hist_q), quantile(fwd_dn, hist_q)
    up80, dn80 = quantile(fwd_up, 0.80), quantile(fwd_dn, 0.80)

    i = -1
    spot = closes[i]
    rsi_v = rsi14[i]
    rsi_zone = classify_rsi(rsi_v)
    kdj_zone = classify_kdj(kk[i], dd[i], jj[i])
    macd_sig = classify_macd(dif[i], dea[i], hist[i], hist[i - 1] if len(hist) > 1 else None)
    trend = classify_trend(spot, ma20[i], ma60[i], dif[i], dea[i], bl.get("pct_b"))

    bias = 0.0
    if rsi_zone in ("超卖", "偏弱") and kdj_zone in ("超卖", "金叉偏多"):
        bias += 0.35
    elif rsi_zone in ("超买", "偏强") and kdj_zone in ("超买", "死叉偏空"):
        bias -= 0.35
    pct_b = bl.get("pct_b")
    if pct_b is not None:
        if pct_b < 0.2:
            bias += 0.25
        elif pct_b > 0.8:
            bias -= 0.25

    # Scale weekly BOLL(20) half-width to a ~4-week horizon
    boll_half = 0.0
    if bl.get("width_pct"):
        boll_half = bl["width_pct"] / 2 * math.sqrt(4 / 20)

    dn_use = max(dn_q or 0, m1_sigma * 0.85, boll_half * 0.8)
    up_use = max(up_q or 0, m1_sigma * 0.85, boll_half * 0.8)
    likely_lo = spot * (1 - dn_use / 100)
    likely_hi = spot * (1 + up_use / 100)
    midp = (likely_lo + likely_hi) / 2 * (1 + bias / 100)
    half = (likely_hi - likely_lo) / 2
    likely_lo, likely_hi = midp - half, midp + half

    exp_lo, exp_hi = expand_range(likely_lo, likely_hi, 0.02)

    return {
        "spot": spot,
        "ma20": ma20[i],
        "ma60": ma60[i],
        "trend": trend,
        "macd": {"dif": dif[i], "dea": dea[i], "hist": hist[i], "signal": macd_sig},
        "rsi14": rsi_v,
        "rsi_zone": rsi_zone,
        "kdj": {"k": kk[i], "d": dd[i], "j": jj[i], "zone": kdj_zone},
        "boll": bl,
        "ann_vol_pct": ann_vol * 100,
        "month_1sigma_pct": m1_sigma,
        "hist_4w": {
            "n": len(fwd_up),
            "hist_q": hist_q,
            "up_q": up_q,
            "dn_q": dn_q,
            "up_p80": up80,
            "dn_p80": dn80,
            "range_p80": quantile(fwd_rng, 0.8),
        },
        "predicted_range": {"lo": likely_lo, "hi": likely_hi},
        "trade_range": {"lo": exp_lo, "hi": exp_hi, "pad": 0.02},
    }
