#!/usr/bin/env python3
"""Build canvas_payload.json from latest_report.json (stdlib)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _iv(leg: dict | None) -> float | None:
    if not leg:
        return None
    v = leg.get("iv")
    if v is None:
        return None
    if v < 0.01:
        return leg.get("iv_bs")
    return v


def compact(u: dict) -> dict:
    chain = []
    for row in u.get("chain_window") or []:
        c = row.get("call") or {}
        p = row.get("put") or {}
        chain.append(
            {
                "strike": row["strike"],
                "call_mid": c.get("mid"),
                "put_mid": p.get("mid"),
                "call_iv": _iv(c),
                "put_iv": _iv(p),
                "call_oi": c.get("oi"),
                "put_oi": p.get("oi"),
            }
        )
    hints = []
    for h in u.get("hints") or []:
        hints.append(
            {
                "title": h.get("title"),
                "bias": h.get("bias"),
                "reason": h.get("reason"),
                "legs": [
                    {
                        "action": l.get("action"),
                        "cp": l.get("cp"),
                        "strike": l.get("strike"),
                        "mid": l.get("mid"),
                    }
                    for l in (h.get("legs") or [])
                ],
            }
        )
    return {
        "symbol": u["symbol"],
        "name": u["name"],
        "spot": u["spot"],
        "change_pct": u.get("change_pct"),
        "expiry": u["expiry"],
        "dte": u["dte"],
        "atm_strike": u["atm_strike"],
        "atm_call_iv": (u.get("atm_call") or {}).get("iv"),
        "atm_put_iv": (u.get("atm_put") or {}).get("iv"),
        "atm_call_mid": (u.get("atm_call") or {}).get("mid"),
        "atm_put_mid": (u.get("atm_put") or {}).get("mid"),
        "skew": u.get("skew_put_minus_call"),
        "chain": chain,
        "hints": hints,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(ROOT / "data" / "latest_report.json"))
    parser.add_argument("--out", default=str(ROOT / "data" / "canvas_payload.json"))
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    payload = {
        "as_of": report["as_of"],
        "disclaimer": report["disclaimer"],
        "underlyings": [compact(u) for u in report.get("underlyings") or []],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
