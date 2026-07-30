# Reference — A-share ETF options desk

## Symbols

| Code | Cate (Sina) | Name |
|------|-------------|------|
| 510050 | 50ETF | 上证50ETF |
| 510300 | 300ETF | 沪深300ETF |

## Sina endpoints used

- Months: `StockOptionService.getStockName?cate={50ETF|300ETF}`
- Expiry/DTE: `StockOptionService.getRemainderDay?cate=...&date=YYYY-MM`
- Codes: `hq.sinajs.cn/list=OP_UP_{code}{YYMM}` / `OP_DOWN_...`
- Quote: `hq.sinajs.cn/list=CON_OP_{optCode}`
- Greeks/IV: `hq.sinajs.cn/list=CON_SO_{optCode}`
- Underlying: `hq.sinajs.cn/list=sh{code}`

Always send `Referer: https://stock.finance.sina.com.cn/`.

## Report JSON shape

See `data/latest_report.json` after `python3 scripts/run_daily.py`.

Key fields per underlying:

- `spot`, `change_pct`, `nearest_expiry`, `dte`
- `atm`: strike, call/put mid & IV
- `skew`: put_iv - call_iv near ATM
- `chain`: list of strikes with call/put quotes (nearest expiry)
- `hints`: strategy suggestions from `strategy_hints.py`

## IV

Prefer exchange/Sina IV from `CON_SO` when present and > 0; else Black–Scholes implied vol from mid price (`scripts/iv.py`), r=0.015, q=0.
