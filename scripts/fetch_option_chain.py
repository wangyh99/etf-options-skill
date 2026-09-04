"""Fetch A-share SSE ETF option chains from Sina Finance."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from iv import implied_vol
from sina_client import http_get_text, openapi, parse_hq_vars

ROOT = Path(__file__).resolve().parents[1]

SYMBOL_META = {
    "510050": {"cate": "50ETF", "name": "上证50ETF", "hq": "sh510050"},
    "510300": {"cate": "300ETF", "name": "沪深300ETF", "hq": "sh510300"},
}

CON_OP_FIELDS = [
    "买量",
    "买价",
    "最新价",
    "卖价",
    "卖量",
    "持仓量",
    "涨幅",
    "行权价",
    "昨收价",
    "开盘价",
    "涨停价",
    "跌停价",
]


def _f(x: str | None, default: float | None = None) -> float | None:
    if x is None or x == "":
        return default
    try:
        return float(x)
    except ValueError:
        return default


def _i(x: str | None, default: int | None = None) -> int | None:
    v = _f(x)
    return int(v) if v is not None else default


def list_months(cate: str) -> list[str]:
    data = openapi(
        "StockOptionService.getStockName",
        {"exchange": "null", "cate": cate, "date": "", "source": "web"},
    )
    months = data["result"]["data"]["contractMonth"]
    # First entry is often duplicated current month — unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for m in months:
        key = m.replace("-", "")
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def expire_info(cate: str, yyyymm: str) -> tuple[str, int]:
    data = openapi(
        "StockOptionService.getRemainderDay",
        {
            "exchange": "null",
            "cate": cate,
            "date": f"{yyyymm[:4]}-{yyyymm[4:]}",
            "date2": yyyymm,
            "source": "web",
        },
    )
    d = data["result"]["data"]
    return d["expireDay"], int(d["remainderDays"])


def option_codes(underlying: str, yyyymm: str) -> tuple[list[str], list[str]]:
    yymm = yyyymm[-4:]
    url = f"https://hq.sinajs.cn/list=OP_UP_{underlying}{yymm},OP_DOWN_{underlying}{yymm}"
    text = http_get_text(url, encoding="gbk")
    vars_ = parse_hq_vars(text)
    up = [x[7:] for x in vars_.get(f"OP_UP_{underlying}{yymm}", []) if x.startswith("CON_OP_")]
    down = [
        x[7:] for x in vars_.get(f"OP_DOWN_{underlying}{yymm}", []) if x.startswith("CON_OP_")
    ]
    return up, down


def batch_hq(symbols: list[str], prefix: str = "CON_OP_") -> dict[str, list[str]]:
    """Fetch many hq symbols; keys without prefix in return if prefix used in request."""
    out: dict[str, list[str]] = {}
    chunk = 40
    for i in range(0, len(symbols), chunk):
        part = symbols[i : i + chunk]
        joined = ",".join(f"{prefix}{s}" if not s.startswith(prefix) else s for s in part)
        # normalize: if symbols already full names
        names = []
        for s in part:
            if s.startswith("CON_OP_") or s.startswith("CON_SO_") or s.startswith("sh"):
                names.append(s)
            else:
                names.append(f"{prefix}{s}")
        url = "https://hq.sinajs.cn/list=" + ",".join(names)
        text = http_get_text(url, encoding="gbk")
        out.update(parse_hq_vars(text))
    return out


def parse_con_op(code: str, fields: list[str]) -> dict[str, Any]:
    d = {CON_OP_FIELDS[i]: fields[i] if i < len(fields) else "" for i in range(len(CON_OP_FIELDS))}
    # Trailing extras beyond 成交额 (index 42)
    cp = None
    expiry = None
    dte = None
    if len(fields) > 45:
        cp = fields[45] if fields[45] in ("C", "P") else None
    if len(fields) > 46:
        expiry = fields[46] or None
    if len(fields) > 47:
        dte = _i(fields[47])
    if cp is None:
        name = fields[37] if len(fields) > 37 else ""
        if "购" in name:
            cp = "C"
        elif "沽" in name:
            cp = "P"

    bid = _f(d["买价"])
    ask = _f(d["卖价"])
    last = _f(d["最新价"])
    mid = None
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2.0
    elif last is not None and last > 0:
        mid = last

    return {
        "code": code,
        "name": fields[37] if len(fields) > 37 else "",
        "cp": cp,
        "strike": _f(d["行权价"]),
        "bid": bid,
        "ask": ask,
        "last": last,
        "mid": mid,
        "oi": _i(d["持仓量"]),
        "volume": _i(fields[41]) if len(fields) > 41 else None,
        "change_pct": _f(d["涨幅"]),
        "expiry": expiry,
        "dte": dte,
    }


def parse_con_so(fields: list[str]) -> dict[str, Any]:
    # akshare: zip(field_list, [data_list[0]] + data_list[4:])
    if not fields:
        return {}
    rest = fields[4:] if len(fields) > 4 else []
    # name, vol, delta, gamma, theta, vega, iv, high, low, trade_code, strike, last, theory
    def g(i: int) -> str:
        return rest[i] if i < len(rest) else ""

    iv = _f(g(5))
    # Sina sometimes puts tiny junk in IV slot; treat absurd values as missing
    if iv is not None and (iv <= 0 or iv > 5):
        iv = None
    return {
        "delta": _f(g(1)),
        "gamma": _f(g(2)),
        "theta": _f(g(3)),
        "vega": _f(g(4)),
        "iv": iv,
        "theory": _f(g(11)) if len(rest) > 11 else _f(g(10)),
    }


def underlying_spot(hq_symbol: str) -> dict[str, Any]:
    text = http_get_text(f"https://hq.sinajs.cn/list={hq_symbol}", encoding="gbk")
    vars_ = parse_hq_vars(text)
    fields = vars_.get(hq_symbol, [])
    if not fields:
        raise RuntimeError(f"empty underlying quote for {hq_symbol}")
    last = _f(fields[3])
    prev = _f(fields[2])
    change_pct = None
    if last is not None and prev not in (None, 0):
        change_pct = (last - prev) / prev * 100.0
    return {
        "name": fields[0],
        "open": _f(fields[1]),
        "prev_close": prev,
        "last": last,
        "high": _f(fields[4]),
        "low": _f(fields[5]),
        "date": fields[30] if len(fields) > 30 else None,
        "time": fields[31] if len(fields) > 31 else None,
        "change_pct": change_pct,
    }


def pick_nearest_month(cate: str, months: list[str], prefer_positive_dte: bool = True) -> dict[str, Any]:
    infos = []
    for m in months:
        expiry, dte = expire_info(cate, m)
        infos.append({"month": m, "expiry": expiry, "dte": dte})
    if prefer_positive_dte:
        positive = [x for x in infos if x["dte"] > 0]
        if positive:
            return min(positive, key=lambda x: x["dte"])
    # fallback: least negative / smallest abs
    return min(infos, key=lambda x: (x["dte"] < 0, abs(x["dte"])))


def pick_month_near_dte(
    infos: list[dict[str, Any]],
    target_dte: int = 30,
    min_dte: int = 15,
) -> dict[str, Any]:
    """Pick the expiry whose DTE is closest to target (default ~30 days)."""
    if not infos:
        raise ValueError("no expiry infos")
    eligible = [x for x in infos if x["dte"] >= min_dte]
    if not eligible:
        eligible = [x for x in infos if x["dte"] > 0]
    if not eligible:
        eligible = infos
    return min(eligible, key=lambda x: abs(int(x["dte"]) - target_dte))


def pick_expiries_in_window(
    infos: list[dict[str, Any]],
    min_dte: int = 15,
    max_dte: int = 60,
    count: int = 2,
) -> list[dict[str, Any]]:
    """Pick the nearest `count` expiries satisfying min_dte <= DTE <= max_dte."""
    if min_dte > max_dte or count < 1:
        raise ValueError("invalid expiry window")
    eligible = [
        dict(x)
        for x in infos
        if min_dte <= int(x.get("dte", -1)) <= max_dte
    ]
    eligible.sort(key=lambda x: int(x["dte"]))
    if len(eligible) < count:
        raise ValueError(
            f"need {count} expiries with DTE {min_dte}-{max_dte}, got {len(eligible)}"
        )
    return eligible[:count]


def list_month_infos(cate: str) -> list[dict[str, Any]]:
    months = list_months(cate)
    infos = []
    for m in months:
        expiry, dte = expire_info(cate, m)
        infos.append({"month": m, "expiry": expiry, "dte": dte})
    return infos


def enrich_iv(row: dict[str, Any], spot: float, dte: int, greeks: dict[str, Any]) -> None:
    row["iv_sina"] = greeks.get("iv")
    row["delta"] = greeks.get("delta")
    row["gamma"] = greeks.get("gamma")
    row["theta"] = greeks.get("theta")
    row["vega"] = greeks.get("vega")
    t = max(dte, 0) / 365.0
    iv_bs = None
    if row.get("mid") and row.get("strike") and row.get("cp") in ("C", "P") and t > 0:
        iv_bs = implied_vol(row["mid"], spot, row["strike"], t, row["cp"])
    row["iv_bs"] = iv_bs
    sina = row.get("iv_sina")
    if sina is not None and 0.01 <= sina <= 3.0:
        row["iv"] = sina
    else:
        row["iv"] = iv_bs


def fetch_chain(symbol: str, month: str | None = None) -> dict[str, Any]:
    if symbol not in SYMBOL_META:
        raise ValueError(f"unsupported symbol {symbol}; choose from {list(SYMBOL_META)}")
    meta = SYMBOL_META[symbol]
    months = list_months(meta["cate"])
    if not months:
        raise RuntimeError(f"no contract months for {symbol}")
    if month is None:
        nearest = pick_nearest_month(meta["cate"], months)
    else:
        expiry, dte = expire_info(meta["cate"], month)
        nearest = {"month": month, "expiry": expiry, "dte": dte}

    spot_info = underlying_spot(meta["hq"])
    spot = spot_info["last"]
    if spot is None:
        raise RuntimeError(f"no spot for {symbol}")

    calls, puts = option_codes(symbol, nearest["month"])
    all_codes = calls + puts
    op_map = batch_hq(all_codes, prefix="CON_OP_")
    so_map = batch_hq(all_codes, prefix="CON_SO_")

    chain_rows: list[dict[str, Any]] = []
    for code in all_codes:
        fields = op_map.get(f"CON_OP_{code}")
        if not fields:
            continue
        row = parse_con_op(code, fields)
        greeks = parse_con_so(so_map.get(f"CON_SO_{code}", []))
        enrich_iv(row, spot, nearest["dte"], greeks)
        chain_rows.append(row)

    # Build strike-aligned view
    by_strike: dict[float, dict[str, Any]] = {}
    for row in chain_rows:
        k = row.get("strike")
        if k is None:
            continue
        slot = by_strike.setdefault(k, {"strike": k, "call": None, "put": None})
        if row["cp"] == "C":
            slot["call"] = row
        elif row["cp"] == "P":
            slot["put"] = row

    strikes = sorted(by_strike.keys())
    atm_strike = min(strikes, key=lambda k: abs(k - spot)) if strikes else None
    atm = by_strike.get(atm_strike) if atm_strike is not None else None

    call_iv = (atm or {}).get("call", {}) or {}
    put_iv = (atm or {}).get("put", {}) or {}
    skew = None
    if call_iv.get("iv") is not None and put_iv.get("iv") is not None:
        skew = put_iv["iv"] - call_iv["iv"]

    return {
        "symbol": symbol,
        "name": meta["name"],
        "spot": spot_info,
        "month": nearest["month"],
        "expiry": nearest["expiry"],
        "dte": nearest["dte"],
        "months_available": months,
        "atm_strike": atm_strike,
        "atm": {
            "strike": atm_strike,
            "call": atm.get("call") if atm else None,
            "put": atm.get("put") if atm else None,
            "skew_put_minus_call": skew,
        },
        "chain": [by_strike[k] for k in strikes],
        "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch SSE ETF option chain")
    parser.add_argument("--symbols", default="510050,510300")
    parser.add_argument("--month", default=None, help="YYYYMM; default nearest with DTE>0")
    parser.add_argument("--out", default=None, help="write JSON path")
    args = parser.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    results = []
    for sym in symbols:
        results.append(fetch_chain(sym, args.month))
    payload = results[0] if len(results) == 1 else {"underlyings": results}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
