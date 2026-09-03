"""Weekly ETF bars with fallbacks (Tencent / Sina daily / East Money)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sina_client import http_get_json, http_get_text

# Tencent: [date, open, close, high, low, volume]
_TENCENT_WEEK = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},week,,,{limit},qfq"
)
_SINA_DAILY = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={limit}"
)
_EM_WEEK = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get?"
    "secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
    "&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
    "&klt=102&fqt=1&end=20500101&lmt={limit}"
)


def _hq_symbol(secid: str) -> str:
    # "1.510050" → sh510050
    market, code = secid.split(".", 1)
    return ("sh" if market == "1" else "sz") + code


def parse_tencent_week(payload: dict[str, Any], hq: str) -> list[dict]:
    node = (payload.get("data") or {}).get(hq) or {}
    rows = node.get("qfqweek") or node.get("week") or []
    out = []
    for r in rows:
        if len(r) < 5:
            continue
        out.append(
            {
                "date": str(r[0])[:10],
                "open": float(r[1]),
                "close": float(r[2]),
                "high": float(r[3]),
                "low": float(r[4]),
            }
        )
    return out


def daily_to_weekly(dailies: list[dict]) -> list[dict]:
    """ISO week: Friday-dated bar from daily OHLC."""
    buckets: dict[str, list[dict]] = {}
    for d in dailies:
        dt = datetime.strptime(d["date"], "%Y-%m-%d")
        iso = dt.isocalendar()
        key = f"{iso.year}-W{iso.week:02d}"
        buckets.setdefault(key, []).append(d)
    out = []
    for key in sorted(buckets):
        rows = buckets[key]
        highs = [x["high"] for x in rows]
        lows = [x["low"] for x in rows]
        last_dt = rows[-1]["date"]
        # label as week Friday if possible
        out.append(
            {
                "date": last_dt,
                "open": rows[0]["open"],
                "close": rows[-1]["close"],
                "high": max(highs),
                "low": min(lows),
            }
        )
    return out


def fetch_weekly_tencent(secid: str, limit: int = 180) -> list[dict]:
    hq = _hq_symbol(secid)
    url = _TENCENT_WEEK.format(symbol=hq, limit=limit)
    data = http_get_json(url, referer=f"https://gu.qq.com/{hq}")
    if data.get("code") not in (0, "0", None) and not (data.get("data") or {}).get(hq):
        raise RuntimeError(f"tencent weekly: {data.get('msg') or data.get('code')}")
    rows = parse_tencent_week(data, hq)
    if not rows:
        raise RuntimeError(f"tencent weekly empty for {hq}")
    return rows


def fetch_weekly_sina(secid: str, daily_limit: int = 800) -> list[dict]:
    hq = _hq_symbol(secid)
    url = _SINA_DAILY.format(symbol=hq, limit=daily_limit)
    raw = http_get_text(url, referer="https://finance.sina.com.cn/")
    dailies = json.loads(raw)
    bars = []
    for d in dailies:
        bars.append(
            {
                "date": d["day"][:10],
                "open": float(d["open"]),
                "high": float(d["high"]),
                "low": float(d["low"]),
                "close": float(d["close"]),
            }
        )
    weekly = daily_to_weekly(bars)
    if not weekly:
        raise RuntimeError(f"sina weekly empty for {hq}")
    return weekly


def fetch_weekly_em(secid: str, limit: int = 180) -> list[dict]:
    url = _EM_WEEK.format(secid=secid, limit=limit)
    code = secid.split(".", 1)[1]
    data = http_get_json(url, referer=f"https://quote.eastmoney.com/sh{code}.html")
    kl = (data.get("data") or {}).get("klines") or []
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
            }
        )
    if not rows:
        raise RuntimeError(f"eastmoney weekly empty for {secid}")
    return rows


def load_weekly_3y(secid: str) -> tuple[list[dict], str]:
    """Return (bars, source_name). Tries Tencent → Sina → East Money."""
    errors: list[str] = []
    for name, fn in (
        ("tencent", fetch_weekly_tencent),
        ("sina_daily", fetch_weekly_sina),
        ("eastmoney", fetch_weekly_em),
    ):
        try:
            bars = fn(secid)
            cutoff = (datetime.now() - timedelta(days=365 * 3 + 14)).strftime("%Y-%m-%d")
            bars = [b for b in bars if b["date"] >= cutoff]
            if len(bars) < 80:
                errors.append(f"{name}: only {len(bars)} bars")
                continue
            return bars, name
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
    raise RuntimeError("weekly fetch failed: " + " | ".join(errors))
