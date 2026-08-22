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
import sys
from datetime import datetime, timezone
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
from weekly_bars import load_weekly_3y  # noqa: E402

MIN_YIELD = 0.015
RANGE_PAD = 0.02
TARGET_DTE = 30
DISCLAIMER = "仅供研究参考，不构成投资建议。保证金为上交所组合策略估算，券商可能上浮。"


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
    bars, weekly_source = load_weekly_3y({"510050": "1.510050", "510300": "1.510300"}[symbol])
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
        "weekly_source": weekly_source,
        "forecast": _round_forecast(fc),
        "expiry": snap["expiry"],
        "month": snap["month"],
        "dte": snap["dte"],
        "spot": spot,
        "candidates": cands,
        "recommended": rec,
        "action": action,
    }


def _md_cell(v) -> str:
    if v is None:
        return "—"
    return str(v).replace("|", "\\|")


def format_report(report: dict) -> str:
    pad = report.get("range_pad", RANGE_PAD)
    dte = report.get("target_dte", TARGET_DTE)
    min_y = report.get("min_yield", MIN_YIELD)
    lines = [
        "# 卖出宽跨建议",
        "",
        f"- **时间**：{report['as_of']}",
        f"- **规则**：周线 MACD / KDJ / RSI / BOLL，历史 4 周幅度用 P80 → 月区间再扩 ±{pad * 100:.0f}%",
        f"- **合约**：DTE 约 {dte} 天；权利金 / 保证金 > {min_y * 100:.1f}%",
        "",
    ]
    if report.get("errors"):
        lines.extend(["## 抓取失败", ""])
        for e in report["errors"]:
            lines.append(f"- `{e['symbol']}`：{e['error']}")
        lines.append("")
    for u in report["underlyings"]:
        f = u["forecast"]
        pr, tr = f["predicted_range"], f["trade_range"]
        lines.extend(
            [
                f"## {u['name']}（{u['symbol']}）",
                "",
                f"**现价** {u['spot']} · **到期** {u['expiry']} · **DTE** {u['dte']}",
                "",
                "| 项目 | 值 |",
                "| --- | --- |",
                f"| 周线样本 | {u['weekly_from']} → {u['weekly_to']}（{u['weekly_n']} 根，{u.get('weekly_source') or '—'}） |",
                f"| 趋势 | {_md_cell(f['trend'])} |",
                f"| MACD | {_md_cell(f['macd']['signal'])} |",
                f"| RSI | {_md_cell(f['rsi14'])}（{f['rsi_zone']}） |",
                f"| KDJ | {_md_cell(f['kdj']['zone'])} |",
                f"| BOLL %B | {_md_cell(f['boll'].get('pct_b'))} |",
                f"| 预测月区间 | {pr['lo']} – {pr['hi']} |",
                f"| 交易带（扩 2%） | {tr['lo']} – {tr['hi']} |",
                "",
            ]
        )
        rec = u.get("recommended")
        if rec:
            lines.extend(
                [
                    "### 建议",
                    "",
                    f"卖出 **{rec['put_name']}** + **{rec['call_name']}**",
                    "",
                    f"- 权利金：{rec['premium_1lot']:.0f} 元 / 张组合",
                    f"- 保证金：{rec['margin_1lot']:.0f} 元（KKS 估算）",
                    f"- 收益率：**{rec['yield_pct']:.2f}%**",
                    f"- 盈亏平衡：{rec['be_dn']} – {rec['be_up']}",
                    "",
                ]
            )
        else:
            lines.extend(["### 建议", "", f"{u['action']}", ""])
        if u["candidates"]:
            lines.extend(
                [
                    "### 达标档位（收益率降序）",
                    "",
                    "| 结构 | 权利金 | 保证金 | 收益率 | 盈亏平衡 |",
                    "| --- | ---: | ---: | ---: | --- |",
                ]
            )
            for c in u["candidates"][:8]:
                lines.append(
                    f"| 沽{c['put_k']}/购{c['call_k']} | "
                    f"{c['premium_1lot']:.0f} | {c['margin_1lot']:.0f} | "
                    f"{c['yield_pct']:.2f}% | {c['be_dn']}–{c['be_up']} |"
                )
            lines.append("")
    lines.extend(["---", "", DISCLAIMER, ""])
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
        default=str(ROOT / "data" / "short_strangle_advice.md"),
        help="Markdown 输出路径",
    )
    parser.add_argument(
        "--json",
        default=None,
        help="可选：同时写入 JSON（便于程序读取）",
    )
    args = parser.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    report = run(symbols, args.dte, args.min_yield)
    md = format_report(report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"\nwrote {out}", file=sys.stderr)
    if args.json:
        jp = Path(args.json)
        jp.parent.mkdir(parents=True, exist_ok=True)
        jp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {jp}", file=sys.stderr)
    if report["errors"] and not report["underlyings"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
