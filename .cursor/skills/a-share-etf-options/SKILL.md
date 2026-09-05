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
| Strategies | Configurable iron condor and short strangle, ATM hints, IV skew, vertical spreads |
| Delivery | Flask HTML5 console, CLI HTML/JSON/Markdown, optional DingTalk summary |
| Schedule | Trading-day cron via Cursor Automation (weekdays 15:10) or `scripts/cron_local.sh` |

Not investment advice. Always include the disclaimer in outputs.

## Workflow

1. Install dependencies and start the interactive console:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config/strategy.yaml.example config/strategy.yaml
.venv/bin/python scripts/serve_web.py
```

   Open `http://127.0.0.1:8765`. The page supports a baseline/asymmetric box
   selector, P80-P99 risk coverage, daily/weekly short-term indicators,
   2%-5% range padding, two expiries in DTE 15-60 and a 1%-3% yield band.

2. For automation or DingTalk, use the CLI:

```bash
.venv/bin/python scripts/advise_short_strangle.py \
  --strategy iron_condor --strategy-only --format html \
  --out data/strategy_advice.html --send-dingtalk
```

3. If market data fetch fails, report the error plainly; do not invent prices.

## Strategy rules (deterministic)

Use fields already computed in the report (`hints[]`). Do not invent new trade ideas beyond these rules unless the user asks for a deeper dive:

- **High IV / rich premium**: prefer short-vol style hints (credit vertical) only when ATM IV is high *and* skew is not extreme.
- **Low IV**: prefer long-vol (debit straddle/strangle or debit vertical) when ATM IV is low.
- **Skew**: if put IV >> call IV near ATM → note downside demand; reverse for call-heavy skew.
- **Asymmetric box**: use about 10 years of adjusted daily prices to compute
  Pos252/756/1260, ATR-normalized moving-average distance and a rule-based
  breakout/reversion regime. Display P60 core, P80-P99 risk and unconditional
  baseline boxes; option strikes must use only the padded risk box.
- Always list: legs, approx debit/credit from mid, max loss/gain sketch, and why (IV / skew / ATM).
- Iron condor reports numeric maximum loss. Short strangle must report upside
  maximum loss as unbounded; exchange margin is never a substitute for maximum loss.

## Output checklist

- [ ] Spot price and change for each underlying
- [ ] Nearest expiry date and DTE
- [ ] ATM call/put mid and IV
- [ ] Skew summary
- [ ] 1–3 strategy hints with legs
- [ ] Disclaimer: 仅供研究参考，不构成投资建议

## Files

- Pipeline: [scripts/run_daily.py](../../../scripts/run_daily.py)
- Iron-condor advice: [scripts/advise_short_strangle.py](../../../scripts/advise_short_strangle.py)
- Web console: [scripts/serve_web.py](../../../scripts/serve_web.py)
- Strategy engine: [scripts/strategy_engine.py](../../../scripts/strategy_engine.py)
- Config example: [config/strategy.yaml.example](../../../config/strategy.yaml.example)
- Fetch: [scripts/fetch_option_chain.py](../../../scripts/fetch_option_chain.py)
- Strategy: [scripts/strategy_hints.py](../../../scripts/strategy_hints.py)
- Automation prompt: [automations/daily-etf-options.md](../../../automations/daily-etf-options.md)
- Reference: [reference.md](reference.md)
