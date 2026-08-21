# A股股指 ETF 期权智能体

每日拉取上证 50ETF（510050）、沪深 300ETF（510300）期权链，计算 ATM IV / 偏度，并给出规则化策略提示。

## 快速开始

日报（期权链 + 策略提示）：

```bash
python3 scripts/run_daily.py
```

**即时卖出宽跨建议**（周线 MACD/KDJ/RSI/BOLL → 月波动区间再扩 ±2% → 约30天到期、权利金/保证金>1.5%）：

```bash
python3 scripts/advise_short_strangle.py
python3 -m unittest discover -s tests -v
```

产出 `data/short_strangle_advice.json`。保证金按上交所宽跨式空头组合（KKS）公式估算。

日报产出：

- `data/latest_report.json` — 完整日报
- `data/canvas_payload.json` — Canvas 嵌入用精简数据
- `data/chains/<symbol>_<YYYYMM>.json` — 原始期权链

查看可视化：打开旁路 Canvas [etf-options-daily.canvas.tsx](/Users/wangyh/.cursor/projects/Users-wangyh-code-CursorProjects-stock/canvases/etf-options-daily.canvas.tsx)（Agent 会按最新 payload 更新）。

## Agent Skill

项目 Skill：`.cursor/skills/a-share-etf-options/`

在对话中提到「期权日报 / 510050 / ETF期权策略」时，按该 Skill 执行流水线并刷新 Canvas。

## Automation draft (saved locally)

| Draft field | Value |
|-------------|--------|
| Name / description | A股ETF期权日报 — 交易日收盘后拉期权链、更新 Canvas、输出策略摘要 |
| Trigger | 工作日 15:10（cron `10 15 * * 1-5`，按本地展示时区理解） |
| Tools | 默认 Agent（跑脚本 + 写 Canvas）；无 Slack |
| Instructions | 见 [automations/daily-etf-options.md](automations/daily-etf-options.md) |
| Resolved settings | 仓库需先 push 到 GitHub，并在 Automations 编辑器中选择 repo/branch |
| To finish in editor | 绑定 Cloud Agent 仓库与分支；确认时区/cron；首次保存后试跑一次 |

若编辑器未自动打开，可在 Cursor Automations 中新建，粘贴上述 cron 与 prompt。

## 说明

- 数据源：新浪财经公开行情（不强制 akshare）
- 仅供研究参考，不构成投资建议
