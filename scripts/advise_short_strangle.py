#!/usr/bin/env python3
"""
Current-time short-strangle advice for 510050 / 510300.

1) 3y weekly bars → 1-month range via MACD / KDJ / RSI / BOLL
2) Widen that range by 2% each side
3) Scan ~30DTE option chain; keep short strangles with premium/margin > 1.5%
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_option_chain import (  # noqa: E402
    SYMBOL_META,
    fetch_chain,
    list_month_infos,
    pick_month_near_dte,
)
from indicators import forecast_month_range  # noqa: E402
from margin import meets_yield, short_strangle_combo_margin  # noqa: E402

UA = "Mozilla/5.0"
CTX = ssl._create_unverified_context()
MIN_YIELD = 0.015
RANGE_PAD = 0.02
TARGET_DTE = 30
DISCLAIMER = "仅供研究参考，不构成投资建议。保证金为上交所组合策略估算，券商可能上浮。"


def fetch_weekly_em(secid: str, limit: int = 200) -> list[dict]:
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
        f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
        f"&klt=102&fqt=1&end=20500101&lmt={limit}"
    )
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Referer": "https://finance.eastmoney.com/"}
    )
    with urllib.request.urlopen(req, timeout=30, context=CTX) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
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
            }
        )
    return rows


def load_weekly_3y(secid: str) -> list[dict]:
    bars = fetch_weekly_em(secid, 180)
    cutoff = (datetime.now() - timedelta(days=365 * 3 + 14)).strftime("%Y-%m-%d")
    bars = [b for b in bars if b["date"] >= cutoff]
    if len(bars) < 80:
        raise RuntimeError(f"{secid}: not enough weekly bars ({len(bars)})")
    return bars


def _leg_mid(leg: dict | None) -> float | None:
    if not leg:
        return None
    return leg.get("mid") or leg.get("last")


def scan_strangles(
    chain: list[dict],
    spot: float,
    trade_lo: float,
    trade_hi: float,
    min_yield: float = MIN_YIELD,
) -> list[dict]:
    """Sell OTM put <= trade_lo and OTM call >= trade_hi; keep yield > min_yield."""
    rows = []
    puts = []
    calls = []
    for row in chain:
        k = row.get("strike")
        if k is None:
            continue
        put, call = row.get("put"), row.get("call")
        pm, cm = _leg_mid(put), _leg_mid(call)
        if k <= trade_lo and k < spot and put and pm and pm > 0:
            puts.append((k, put, pm))
        if k >= trade_hi and k > spot and call and cm and cm > 0:
            calls.append((k, call, cm))

    for pk, put, pm in puts:
        for ck, call, cm in calls:
            if ck <= pk:
                continue
            m = short_strangle_combo_margin(cm, pm, spot, ck, pk)
            yld = m["yield"]
            if not meets_yield(yld, min_yield):
                continue
            prem = m["premium"]
            rows.append(
                {
                    "put_k": pk,
                    "call_k": ck,
                    "put_name": put.get("name"),
                    "call_name": call.get("name"),
                    "put_code": put.get("code"),
                    "call_code": call.get("code"),
                    "put_mid": round(pm, 4),
                    "call_mid": round(cm, 4),
                    "put_iv": put.get("iv"),
                    "call_iv": call.get("iv"),
                    "premium_1lot": round(prem, 2),
                    "margin_1lot": round(m["combo_margin"], 2),
                    "call_margin": round(m["call_margin"], 2),
                    "put_margin": round(m["put_margin"], 2),
                    "yield": yld,
                    "yield_pct": round(yld * 100, 3),
                    "be_dn": round(pk - (pm + cm), 4),
                    "be_up": round(ck + (pm + cm), 4),
                }
            )
    rows.sort(key=lambda r: (-r["yield"], -r["premium_1lot"]))
    return rows


def pick_recommendation(cands: list[dict], trend: str) -> dict | None:
    if not cands:
        return None
    # Mild bearish: prefer a bit more downside cushion (lower put strike) if yield still ok
    if "空" in trend:
        scored = []
        top_y = cands[0]["yield"]
        for r in cands:
            if r["yield"] < top_y * 0.9:
                continue
            scored.append((r["yield"] * 1000 + (cands[0]["put_k"] - r["put_k"]) * 10, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]
    return cands[0]


def _round_forecast(fc: dict) -> dict:
    def r(x, n=4):
        return None if x is None else round(float(x), n)

    bl = fc["boll"]
    return {
        "spot": r(fc["spot"], 4),
        "ma20": r(fc["ma20"], 4),
        "ma60": r(fc["ma60"], 4),
        "trend": fc["trend"],
        "macd": {
            "dif": r(fc["macd"]["dif"], 5),
            "dea": r(fc["macd"]["dea"], 5),
            "hist": r(fc["macd"]["hist"], 5),
            "signal": fc["macd"]["signal"],
        },
        "rsi14": r(fc["rsi14"], 2),
        "rsi_zone": fc["rsi_zone"],
        "kdj": {
            "k": r(fc["kdj"]["k"], 2),
            "d": r(fc["kdj"]["d"], 2),
            "j": r(fc["kdj"]["j"], 2),
            "zone": fc["kdj"]["zone"],
        },
        "boll": {
            "mid": r(bl.get("mid"), 4),
            "upper": r(bl.get("upper"), 4),
            "lower": r(bl.get("lower"), 4),
            "pct_b": r(bl.get("pct_b"), 3),
            "width_pct": r(bl.get("width_pct"), 2),
        },
        "ann_vol_pct": r(fc["ann_vol_pct"], 2),
        "month_1sigma_pct": r(fc["month_1sigma_pct"], 2),
        "predicted_range": {
            "lo": r(fc["predicted_range"]["lo"], 4),
            "hi": r(fc["predicted_range"]["hi"], 4),
        },
        "trade_range": {
            "lo": r(fc["trade_range"]["lo"], 4),
            "hi": r(fc["trade_range"]["hi"], 4),
            "pad": fc["trade_range"]["pad"],
        },
    }


def advise_symbol(symbol: str, target_dte: int = TARGET_DTE, min_yield: float = MIN_YIELD) -> dict[str, Any]:
    meta = SYMBOL_META[symbol]
    bars = load_weekly_3y({"510050": "1.510050", "510300": "1.510300"}[symbol])
    fc = forecast_month_range(
        [b["close"] for b in bars],
        [b["high"] for b in bars],
        [b["low"] for b in bars],
    )
    infos = list_month_infos(meta["cate"])
    month_info = pick_month_near_dte(infos, target_dte=target_dte)
    snap = fetch_chain(symbol, month_info["month"])
    spot = snap["spot"]["last"] or fc["spot"]
    trade_lo = fc["trade_range"]["lo"]
    trade_hi = fc["trade_range"]["hi"]
    cands = scan_strangles(snap["chain"], spot, trade_lo, trade_hi, min_yield)
    rec = pick_recommendation(cands, fc["trend"])
    action = "卖出宽跨" if rec else "观望（无满足收益率的档位）"
    return {
        "symbol": symbol,
        "name": meta["name"],
        "weekly_from": bars[0]["date"],
        "weekly_to": bars[-1]["date"],
        "weekly_n": len(bars),
        "forecast": _round_forecast(fc),
        "expiry": snap["expiry"],
        "month": snap["month"],
        "dte": snap["dte"],
        "spot": spot,
        "candidates": cands,
        "recommended": rec,
        "action": action,
    }


def format_report(report: dict) -> str:
    lines = [
        f"卖出宽跨建议  {report['as_of']}",
        f"规则：周线 MACD/KDJ/RSI/BOLL → 月区间再扩 ±{RANGE_PAD*100:.0f}%；"
        f"约{TARGET_DTE}天到期；权利金/保证金 > {MIN_YIELD*100:.1f}%",
        "",
    ]
    if report.get("errors"):
        lines.append("抓取失败：")
        for e in report["errors"]:
            lines.append(f"  {e['symbol']}: {e['error']}")
        lines.append("")
    for u in report["underlyings"]:
        f = u["forecast"]
        pr, tr = f["predicted_range"], f["trade_range"]
        lines.append(f"=== {u['name']} ({u['symbol']}) 现价 {u['spot']} ===")
        lines.append(
            f"周线 {u['weekly_from']}→{u['weekly_to']}  趋势 {f['trend']}  "
            f"MACD {f['macd']['signal']}  RSI {f['rsi14']}({f['rsi_zone']})  "
            f"KDJ {f['kdj']['zone']}  BOLL%B {f['boll'].get('pct_b')}"
        )
        lines.append(
            f"预测月区间 {pr['lo']}–{pr['hi']}  → 交易带(扩2%) {tr['lo']}–{tr['hi']}"
        )
        lines.append(f"合约 {u['expiry']}  DTE {u['dte']}  候选 {len(u['candidates'])} 个")
        rec = u.get("recommended")
        if rec:
            lines.append(
                f"建议：卖出 {rec['put_name']} + {rec['call_name']}  "
                f"权利金 {rec['premium_1lot']:.0f}元 / 保证金 {rec['margin_1lot']:.0f}元  "
                f"收益率 {rec['yield_pct']:.2f}%  BE {rec['be_dn']}–{rec['be_up']}"
            )
        else:
            lines.append(f"建议：{u['action']}")
        if u["candidates"]:
            lines.append("达标档位（收益率降序，最多5档）：")
            for c in u["candidates"][:5]:
                lines.append(
                    f"  沽{c['put_k']}/购{c['call_k']}  "
                    f"权利金{c['premium_1lot']:.0f}  保证金{c['margin_1lot']:.0f}  "
                    f"收益{c['yield_pct']:.2f}%"
                )
        lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def run(symbols: list[str], target_dte: int, min_yield: float) -> dict:
    underlyings = []
    errors = []
    for sym in symbols:
        try:
            underlyings.append(advise_symbol(sym, target_dte=target_dte, min_yield=min_yield))
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": sym, "error": str(exc)})
    return {
        "as_of": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "target_dte": target_dte,
        "min_yield": min_yield,
        "range_pad": RANGE_PAD,
        "disclaimer": DISCLAIMER,
        "underlyings": underlyings,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="50/300 ETF 卖出宽跨即时建议")
    parser.add_argument("--symbols", default="510050,510300")
    parser.add_argument("--dte", type=int, default=TARGET_DTE)
    parser.add_argument("--min-yield", type=float, default=MIN_YIELD)
    parser.add_argument(
        "--out",
        default=str(ROOT / "data" / "short_strangle_advice.json"),
    )
    args = parser.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    report = run(symbols, args.dte, args.min_yield)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(format_report(report))
    print(f"\nwrote {out}", file=sys.stderr)
    if report["errors"] and not report["underlyings"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
