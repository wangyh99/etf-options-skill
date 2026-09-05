"""Weekly ETF bars with fallbacks (Tencent / Sina daily / East Money)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sina_client import http_get_json, http_get_text

ROOT = Path(__file__).resolve().parents[1]
DAILY_CACHE = ROOT / "data" / "cache"

# Tencent: [date, open, close, high, low, volume]
_TENCENT_WEEK = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},week,,,{limit},qfq"
)
_TENCENT_DAY = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{limit},qfq"
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
_EM_DAILY = (
    "https://{host}/api/qt/stock/kline/get?"
    "secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
    "&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
    "&klt=101&fqt=1&end=20500101&lmt={limit}"
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
        row = {
            "date": str(r[0])[:10],
            "open": float(r[1]),
            "close": float(r[2]),
            "high": float(r[3]),
            "low": float(r[4]),
        }
        if len(r) > 5 and str(r[5]).strip():
            row["volume"] = float(r[5])
        out.append(row)
    return out


def parse_tencent_daily(payload: dict[str, Any], hq: str) -> list[dict]:
    node = (payload.get("data") or {}).get(hq) or {}
    rows = node.get("qfqday") or node.get("day") or []
    output = []
    for r in rows:
        if len(r) < 5:
            continue
        row = {
            "date": str(r[0])[:10],
            "open": float(r[1]),
            "close": float(r[2]),
            "high": float(r[3]),
            "low": float(r[4]),
        }
        if len(r) > 5 and str(r[5]).strip():
            row["volume"] = float(r[5])
        output.append(row)
    return output


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
        bar = {
            "date": last_dt,
            "open": rows[0]["open"],
            "close": rows[-1]["close"],
            "high": max(highs),
            "low": min(lows),
        }
        volumes = [x.get("volume") for x in rows]
        if all(v is not None for v in volumes):
            bar["volume"] = sum(volumes)
        out.append(bar)
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


def fetch_daily_tencent(secid: str, limit: int = 800) -> list[dict]:
    hq = _hq_symbol(secid)
    data = http_get_json(
        _TENCENT_DAY.format(symbol=hq, limit=limit),
        referer=f"https://gu.qq.com/{hq}",
    )
    rows = parse_tencent_daily(data, hq)
    if not rows:
        raise RuntimeError(f"tencent daily empty for {hq}")
    return rows


def fetch_daily_sina(secid: str, limit: int = 800) -> list[dict]:
    hq = _hq_symbol(secid)
    raw = http_get_text(
        _SINA_DAILY.format(symbol=hq, limit=limit),
        referer="https://finance.sina.com.cn/",
    )
    rows = []
    for d in json.loads(raw):
        row = {
            "date": d["day"][:10],
            "open": float(d["open"]),
            "high": float(d["high"]),
            "low": float(d["low"]),
            "close": float(d["close"]),
        }
        if d.get("volume") not in (None, ""):
            row["volume"] = float(d["volume"])
        rows.append(row)
    if not rows:
        raise RuntimeError(f"sina daily empty for {hq}")
    return rows


def fetch_daily_em(secid: str, limit: int = 2800) -> list[dict]:
    """East Money adjusted daily bars (fqt=1)."""
    code = secid.split(".", 1)[1]
    errors = []
    data = None
    for host in ("push2his.eastmoney.com", "33.push2his.eastmoney.com"):
        try:
            data = http_get_json(
                _EM_DAILY.format(host=host, secid=secid, limit=limit),
                referer=f"https://quote.eastmoney.com/sh{code}.html",
            )
            break
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{host}: {exc}")
    if data is None:
        raise RuntimeError(" | ".join(errors))
    klines = (data.get("data") or {}).get("klines") or []
    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        rows.append({
            "date": parts[0],
            "open": float(parts[1]),
            "close": float(parts[2]),
            "high": float(parts[3]),
            "low": float(parts[4]),
            "volume": float(parts[5]),
        })
    if not rows:
        raise RuntimeError(f"eastmoney daily empty for {secid}")
    return rows


def fetch_weekly_sina(secid: str, daily_limit: int = 800) -> list[dict]:
    weekly = daily_to_weekly(fetch_daily_sina(secid, daily_limit))
    if not weekly:
        raise RuntimeError(f"sina weekly empty for {secid}")
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


def load_daily_history(
    secid: str,
    years: int = 10,
    require_adjusted: bool = True,
) -> tuple[list[dict], str]:
    """Return long daily history; adjusted mode only accepts qfq sources."""
    limit = min(4000, max(800, years * 260 + 120))
    cache_path = DAILY_CACHE / f"{secid.replace('.', '_')}_daily_qfq.json"
    cutoff = (datetime.now() - timedelta(days=365 * years + 30)).strftime("%Y-%m-%d")
    cached = []
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cache_age = datetime.now() - datetime.strptime(cached[-1]["date"], "%Y-%m-%d")
            if len(cached) >= 500 and cache_age.days <= 3:
                return [bar for bar in cached if bar["date"] >= cutoff], "cache_qfq"
        except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError):
            cached = []
    errors: list[str] = []
    sources = [
        ("tencent_qfq", fetch_daily_tencent),
        ("eastmoney_qfq", fetch_daily_em),
    ]
    if not require_adjusted:
        sources.append(("sina_unadjusted", fetch_daily_sina))
    for name, fn in sources:
        try:
            bars = fn(secid, limit)
            bars = [b for b in bars if b["date"] >= cutoff]
            if len(bars) < 500:
                errors.append(f"{name}: only {len(bars)} bars")
                continue
            if name.endswith("_qfq"):
                DAILY_CACHE.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps(bars, ensure_ascii=False),
                    encoding="utf-8",
                )
            return bars, name
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
    if require_adjusted and len(cached) >= 500:
        cache_age = datetime.now() - datetime.strptime(cached[-1]["date"], "%Y-%m-%d")
        if cache_age.days <= 10:
            return [bar for bar in cached if bar["date"] >= cutoff], "stale_cache_qfq"
    raise RuntimeError("daily fetch failed: " + " | ".join(errors))


def load_daily_3y(secid: str) -> tuple[list[dict], str]:
    return load_daily_history(secid, years=3, require_adjusted=False)


def load_bars_3y(secid: str, timeframe: str) -> tuple[list[dict], str]:
    if timeframe == "daily":
        return load_daily_3y(secid)
    if timeframe == "weekly":
        return load_weekly_3y(secid)
    raise ValueError("timeframe must be daily or weekly")
