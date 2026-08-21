---
name: a-share-etf-options
description: >-
  Fetches China A-share index ETF option chains (510050/510300), computes IV and
  basic Greeks proxies, and suggests non-directional or lightly directional
  strategies. Use when the user asks for A-share ETF options prices, 股指ETF期权,
  期权日报, IV skew, or trading strategy hints for SSE/SZSE ETF options.
---

# A-share ETF Options Daily Desk

## Scope (locked)

| Item | Value |
|------|--------|
| Underlyings | `510050` (上证50ETF), `510300` (沪深300ETF) |
| Data source | Sina Finance public APIs via `scripts/fetch_option_chain.py` (stdlib; akshare optional) |
| Strategies | ATM straddle/strangle hints, IV skew (put vs call), vertical debit/credit spreads near ATM |
| Delivery | Run scripts → write `data/latest_report.json` + `data/canvas_payload.json` → render Canvas + short chat summary |
| Schedule | Trading-day cron via Cursor Automation (weekdays 15:10) or `scripts/cron_local.sh` |

Not investment advice. Always include the disclaimer in outputs.

## Workflow

1. From repo root, run the daily pipeline:

```bash
python3 scripts/run_daily.py
```

   Optional flags: `--symbols 510050,510300` `--month YYYYMM`

2. Read `data/latest_report.json` (and `data/canvas_payload.json` for Canvas).

3. Present results:
   - **Primary**: create/update Canvas `etf-options-daily.canvas.tsx` under the workspace `canvases/` directory, embedding `canvas_payload.json` inline (no `fetch()`).
   - **Chat**: 5–8 line summary — spot, nearest expiry, ATM IV, skew signal, top 1–3 strategy hints.

4. If market data fetch fails, report the error plainly; do not invent prices.

## Strategy rules (deterministic)

Use fields already computed in the report (`hints[]`). Do not invent new trade ideas beyond these rules unless the user asks for a deeper dive:

- **High IV / rich premium**: prefer short-vol style hints (credit vertical) only when ATM IV is high *and* skew is not extreme.
- **Low IV**: prefer long-vol (debit straddle/strangle or debit vertical) when ATM IV is low.
- **Skew**: if put IV >> call IV near ATM → note downside demand; reverse for call-heavy skew.
- Always list: legs, approx debit/credit from mid, max loss/gain sketch, and why (IV / skew / ATM).

## Output checklist

- [ ] Spot price and change for each underlying
- [ ] Nearest expiry date and DTE
- [ ] ATM call/put mid and IV
- [ ] Skew summary
- [ ] 1–3 strategy hints with legs
- [ ] Disclaimer: 仅供研究参考，不构成投资建议

## Files

- Pipeline: [scripts/run_daily.py](../../../scripts/run_daily.py)
- Short-strangle advice: [scripts/advise_short_strangle.py](../../../scripts/advise_short_strangle.py)
- Fetch: [scripts/fetch_option_chain.py](../../../scripts/fetch_option_chain.py)
- Strategy: [scripts/strategy_hints.py](../../../scripts/strategy_hints.py)
- Automation prompt: [automations/daily-etf-options.md](../../../automations/daily-etf-options.md)
- Reference: [reference.md](reference.md)
