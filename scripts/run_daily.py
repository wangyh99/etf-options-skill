#!/usr/bin/env python3
"""Daily pipeline: fetch chains → strategy hints → data/latest_report.json."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from fetch_option_chain import SYMBOL_META, fetch_chain
from strategy_hints import build_hints

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def slim_leg(leg: dict | None) -> dict | None:
    if not leg:
        return None
    keys = ("code", "name", "cp", "strike", "bid", "ask", "last", "mid", "iv", "iv_bs", "oi", "volume", "delta")
    return {k: leg.get(k) for k in keys}


def slim_chain_row(row: dict) -> dict:
    return {
        "strike": row.get("strike"),
        "call": slim_leg(row.get("call")),
        "put": slim_leg(row.get("put")),
    }


def summarize_underlying(snap: dict) -> dict:
    atm = snap.get("atm") or {}
    hints = build_hints(snap)
    # Keep chain near ATM ± 5 strikes for report size
    chain = snap.get("chain") or []
    atm_k = snap.get("atm_strike")
    if atm_k is not None and chain:
        strikes = [r["strike"] for r in chain]
        try:
            idx = strikes.index(atm_k)
        except ValueError:
            idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - atm_k))
        lo = max(0, idx - 5)
        hi = min(len(chain), idx + 6)
        window = chain[lo:hi]
    else:
        window = chain[:12]

    spot = snap.get("spot") or {}
    return {
        "symbol": snap.get("symbol"),
        "name": snap.get("name"),
        "spot": spot.get("last"),
        "prev_close": spot.get("prev_close"),
        "change_pct": spot.get("change_pct"),
        "quote_time": f"{spot.get('date') or ''} {spot.get('time') or ''}".strip(),
        "month": snap.get("month"),
        "expiry": snap.get("expiry"),
        "dte": snap.get("dte"),
        "atm_strike": atm_k,
        "atm_call": slim_leg(atm.get("call")),
        "atm_put": slim_leg(atm.get("put")),
        "skew_put_minus_call": atm.get("skew_put_minus_call"),
        "chain_window": [slim_chain_row(r) for r in window],
        "hints": hints,
        "fetched_at": snap.get("fetched_at"),
    }


def run(symbols: list[str], month: str | None = None) -> dict:
    underlyings = []
    errors = []
    for sym in symbols:
        try:
            snap = fetch_chain(sym, month)
            # persist full chain
            chains_dir = DATA / "chains"
            chains_dir.mkdir(parents=True, exist_ok=True)
            out_chain = chains_dir / f"{sym}_{snap['month']}.json"
            out_chain.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
            underlyings.append(summarize_underlying(snap))
        except Exception as exc:  # noqa: BLE001 — surface per-symbol failures
            errors.append({"symbol": sym, "error": str(exc)})

    report = {
        "as_of": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": "sina_finance",
        "disclaimer": "仅供研究参考，不构成投资建议。期权交易风险极高，请自行判断。",
        "underlyings": underlyings,
        "errors": errors,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="A-share ETF options daily report")
    parser.add_argument(
        "--symbols",
        default=",".join(SYMBOL_META.keys()),
        help="comma-separated ETF codes",
    )
    parser.add_argument("--month", default=None, help="YYYYMM override")
    parser.add_argument(
        "--out",
        default=str(DATA / "latest_report.json"),
        help="report output path",
    )
    args = parser.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    report = run(symbols, args.month)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}", file=sys.stderr)
    # companion payload for Canvas embedding
    try:
        from build_canvas_payload import compact as _compact

        payload = {
            "as_of": report["as_of"],
            "disclaimer": report["disclaimer"],
            "underlyings": [_compact(u) for u in report.get("underlyings") or []],
        }
        payload_path = DATA / "canvas_payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {payload_path}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"canvas payload skipped: {exc}", file=sys.stderr)
    if report["errors"] and not report["underlyings"]:
        return 1
    # brief stdout summary
    for u in report["underlyings"]:
        skew = u.get("skew_put_minus_call")
        skew_s = f"{skew * 100:.1f}%" if isinstance(skew, (int, float)) else "n/a"
        tip = (u.get("hints") or [{}])[0].get("title", "")
        print(
            f"{u['symbol']} spot={u['spot']} dte={u['dte']} "
            f"atm={u['atm_strike']} skew={skew_s} | {tip}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
