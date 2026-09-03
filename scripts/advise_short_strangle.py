#!/usr/bin/env python3
"""
Iron condor advice for 510050 / 510300.

1) 3y weekly → 1-month P80 range via MACD / KDJ / RSI / BOLL, then +2% pad
2) Short OTM put/call outside the band; buy further OTM wings
3) Keep structures whose net credit / (two vertical margins) is in 1.5%–2.2%
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
from margin import iron_condor_margin, meets_yield_band  # noqa: E402
from weekly_bars import load_weekly_3y  # noqa: E402

MIN_YIELD = 0.015
MAX_YIELD = 0.022
TARGET_YIELD = 0.0185
RANGE_PAD = 0.02
TARGET_DTE = 30
MAX_WING_STEPS = 6
DISCLAIMER = (
    "仅供研究参考，不构成投资建议。"
    "铁鹰保证金按认沽牛市价差+认购熊市价差的行权价差之和估算，券商可能上浮。"
)


def _leg_mid(leg: dict | None) -> float | None:
    if not leg:
        return None
    return leg.get("mid") or leg.get("last")


def _collect_legs(chain: list[dict], side: str) -> list[tuple[float, dict, float]]:
    legs: list[tuple[float, dict, float]] = []
    for row in chain:
        k = row.get("strike")
        if k is None:
            continue
        leg = row.get(side)
        mid = _leg_mid(leg)
        if leg and mid and mid > 0:
            legs.append((float(k), leg, float(mid)))
    legs.sort(key=lambda x: x[0])
    return legs


def _structure_row(
    long_put: tuple[float, dict, float],
    short_put: tuple[float, dict, float],
    short_call: tuple[float, dict, float],
    long_call: tuple[float, dict, float],
) -> dict | None:
    lpk, lput, lpm = long_put
    spk, sput, spm = short_put
    sck, scall, scm = short_call
    lck, lcall, lcm = long_call
    credit = spm + scm - lpm - lcm
    if credit <= 0:
        return None
    try:
        m = iron_condor_margin(spk, lpk, sck, lck, spm, lpm, scm, lcm)
    except ValueError:
        return None
    return {
        "long_put_k": lpk,
        "short_put_k": spk,
        "short_call_k": sck,
        "long_call_k": lck,
        "put_k": spk,
        "call_k": sck,
        "long_put_name": lput.get("name"),
        "short_put_name": sput.get("name"),
        "short_call_name": scall.get("name"),
        "long_call_name": lcall.get("name"),
        "put_name": sput.get("name"),
        "call_name": scall.get("name"),
        "long_put_code": lput.get("code"),
        "short_put_code": sput.get("code"),
        "short_call_code": scall.get("code"),
        "long_call_code": lcall.get("code"),
        "long_put_mid": round(lpm, 4),
        "short_put_mid": round(spm, 4),
        "short_call_mid": round(scm, 4),
        "long_call_mid": round(lcm, 4),
        "put_mid": round(spm, 4),
        "call_mid": round(scm, 4),
        "short_put_iv": sput.get("iv"),
        "short_call_iv": scall.get("iv"),
        "put_iv": sput.get("iv"),
        "call_iv": scall.get("iv"),
        "put_width": round(m["put_width"], 4),
        "call_width": round(m["call_width"], 4),
        "net_credit": round(credit, 4),
        "premium_1lot": round(m["premium"], 2),
        "margin_1lot": round(m["margin"], 2),
        "max_loss_1lot": round(m["max_loss"], 2),
        "yield": m["yield"],
        "yield_pct": round(m["yield"] * 100, 3),
        "be_dn": round(spk - credit, 4),
        "be_up": round(sck + credit, 4),
        "label": f"沽{lpk}/{spk} + 购{sck}/{lck}",
    }


def scan_iron_condors(
    chain: list[dict],
    spot: float,
    trade_lo: float,
    trade_hi: float,
    min_yield: float = MIN_YIELD,
    max_yield: float = MAX_YIELD,
    max_wing_steps: int = MAX_WING_STEPS,
) -> list[dict]:
    """
    Short put ≤ trade_lo, short call ≥ trade_hi; buy further OTM wings.
    Keep net credit / (put_width + call_width) × 10000 inside the yield band.
    """
    puts = _collect_legs(chain, "put")
    calls = _collect_legs(chain, "call")
    rows: list[dict] = []
    for sp_idx, short_put in enumerate(puts):
        spk = short_put[0]
        if not (spk <= trade_lo and spk < spot):
            continue
        long_puts = puts[max(0, sp_idx - max_wing_steps) : sp_idx]
        for sc_idx, short_call in enumerate(calls):
            sck = short_call[0]
            if not (sck >= trade_hi and sck > spot and sck > spk):
                continue
            long_calls = calls[sc_idx + 1 : sc_idx + 1 + max_wing_steps]
            for long_put in long_puts:
                for long_call in long_calls:
                    row = _structure_row(long_put, short_put, short_call, long_call)
                    if row is None:
                        continue
                    if not meets_yield_band(row["yield"], min_yield, max_yield):
                        continue
                    rows.append(row)
    rows.sort(key=lambda r: (abs(r["yield"] - TARGET_YIELD), -r["premium_1lot"]))
    return rows


def scan_all_iron_condors(
    chain: list[dict],
    spot: float,
    trade_lo: float,
    trade_hi: float,
    max_wing_steps: int = MAX_WING_STEPS,
) -> list[dict]:
    """All positive-credit iron condors outside the trade band (no yield filter)."""
    return scan_iron_condors(
        chain,
        spot,
        trade_lo,
        trade_hi,
        min_yield=0.0,
        max_yield=10.0,
        max_wing_steps=max_wing_steps,
    )


def pick_recommendation(cands: list[dict], trend: str) -> dict | None:
    if not cands:
        return None
    ranked = sorted(cands, key=lambda r: (abs(r["yield"] - TARGET_YIELD), -r["premium_1lot"]))
    best = ranked[0]
    if "空" not in trend:
        return best
    band = [r for r in ranked if abs(r["yield"] - TARGET_YIELD) <= max(abs(best["yield"] - TARGET_YIELD), 0.002)]
    return min(band, key=lambda r: (r.get("short_put_k", r.get("put_k", 0)), -r["premium_1lot"]))


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


def advise_symbol(
    symbol: str,
    target_dte: int = TARGET_DTE,
    min_yield: float = MIN_YIELD,
    max_yield: float = MAX_YIELD,
) -> dict[str, Any]:
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
    scanned = scan_all_iron_condors(snap["chain"], spot, trade_lo, trade_hi)
    cands = [r for r in scanned if meets_yield_band(r["yield"], min_yield, max_yield)]
    cands.sort(key=lambda r: (abs(r["yield"] - TARGET_YIELD), -r["premium_1lot"]))
    misses = [r for r in scanned if not meets_yield_band(r["yield"], min_yield, max_yield)]
    misses.sort(key=lambda r: (min(abs(r["yield"] - min_yield), abs(r["yield"] - max_yield)), -r["premium_1lot"]))
    rec = pick_recommendation(cands, fc["trend"])
    action = "卖出铁鹰" if rec else "观望（无 1.5%–2.2% 档位）"
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
        "n_scanned": len(scanned),
        "candidates": cands,
        "near_misses": misses[:6],
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
    max_y = report.get("max_yield", MAX_YIELD)
    lines = [
        "# 铁鹰建议",
        "",
        f"- **时间**：{report['as_of']}",
        f"- **规则**：周线 MACD / KDJ / RSI / BOLL，历史 4 周幅度用 P80 → 月区间再扩 ±{pad * 100:.0f}%",
        f"- **合约**：DTE 约 {dte} 天；净权利金 /（两侧行权价差之和×10000）落在 {min_y * 100:.1f}%–{max_y * 100:.1f}%",
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
                    f"买入 **{rec['long_put_name']}** / 卖出 **{rec['short_put_name']}**"
                    f" + 卖出 **{rec['short_call_name']}** / 买入 **{rec['long_call_name']}**",
                    "",
                    f"- 净权利金：{rec['premium_1lot']:.0f} 元 / 张组合",
                    f"- 保证金：{rec['margin_1lot']:.0f} 元（两侧价差之和）",
                    f"- 最大亏损：{rec['max_loss_1lot']:.0f} 元（较宽一侧 − 净权利金）",
                    f"- 收益率：**{rec['yield_pct']:.2f}%**",
                    f"- 盈亏平衡：{rec['be_dn']} – {rec['be_up']}",
                    "",
                ]
            )
        else:
            lines.extend(["### 建议", "", f"{u['action']}", ""])
            misses = u.get("near_misses") or []
            if misses:
                lines.extend(
                    [
                        "最接近目标区间的档位：",
                        "",
                    ]
                )
                for c in misses[:3]:
                    lines.append(
                        f"- {c['label']}：净权利金 {c['premium_1lot']:.0f}，"
                        f"保证金 {c['margin_1lot']:.0f}，收益率 {c['yield_pct']:.2f}%"
                    )
                lines.append("")
        if u["candidates"]:
            lines.extend(
                [
                    "### 达标档位（靠近 1.85%）",
                    "",
                    "| 结构 | 净权利金 | 保证金 | 最大亏损 | 收益率 | 盈亏平衡 |",
                    "| --- | ---: | ---: | ---: | ---: | --- |",
                ]
            )
            for c in u["candidates"][:8]:
                label = c.get("label") or (
                    f"沽{c.get('long_put_k')}/{c.get('put_k')} + 购{c.get('call_k')}/{c.get('long_call_k')}"
                )
                lines.append(
                    f"| {label} | "
                    f"{c['premium_1lot']:.0f} | {c['margin_1lot']:.0f} | "
                    f"{c.get('max_loss_1lot', 0):.0f} | {c['yield_pct']:.2f}% | "
                    f"{c['be_dn']}–{c['be_up']} |"
                )
            lines.append("")
    lines.extend(["---", "", DISCLAIMER, ""])
    return "\n".join(lines)


def run(symbols: list[str], target_dte: int, min_yield: float, max_yield: float = MAX_YIELD) -> dict:
    underlyings = []
    errors = []
    for sym in symbols:
        try:
            underlyings.append(
                advise_symbol(sym, target_dte=target_dte, min_yield=min_yield, max_yield=max_yield)
            )
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": sym, "error": str(exc)})
    return {
        "as_of": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "target_dte": target_dte,
        "min_yield": min_yield,
        "max_yield": max_yield,
        "range_pad": RANGE_PAD,
        "disclaimer": DISCLAIMER,
        "underlyings": underlyings,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="50/300 ETF 铁鹰即时建议")
    parser.add_argument("--symbols", default="510050,510300")
    parser.add_argument("--dte", type=int, default=TARGET_DTE)
    parser.add_argument("--min-yield", type=float, default=MIN_YIELD)
    parser.add_argument("--max-yield", type=float, default=MAX_YIELD)
    parser.add_argument(
        "--out",
        default=str(ROOT / "data" / "iron_condor_advice.md"),
        help="Markdown 输出路径",
    )
    parser.add_argument(
        "--json",
        default=None,
        help="可选：同时写入 JSON（便于程序读取）",
    )
    args = parser.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    report = run(symbols, args.dte, args.min_yield, args.max_yield)
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
