# A股股指 ETF 期权工具

面向 **上证50ETF（510050）**、**沪深300ETF（510300）** 的本地策略系统：通过 HTML5 控制台或 CLI，用近 3 年日线/周线预测交易带，并给出铁鹰（Iron Condor）与卖出宽跨建议。

需要 Python 3.11+、Flask 和 PyYAML，无需 akshare / pandas。

## 功能

| 功能 | 脚本 | 说明 |
|------|------|------|
| **双策略控制台** | `scripts/serve_web.py` | 铁鹰/宽跨 Tab，可调 P80–P99、日/周线、扩幅、DTE、收益率并保存 YAML |
| **策略 CLI** | `scripts/advise_short_strangle.py` | 两个 DTE 15–60 到期日；Markdown/JSON/HTML；可选钉钉推送 |
| **期权日报** | `scripts/run_daily.py` | 拉取近月期权链、ATM IV、偏度，并按规则提示跨式 / 垂直价差 |
| **周线区间测算** | `scripts/weekly_tech_forecast.py` | 单独输出周线指标与月波动带（供对照） |
| **期权链拉取** | `scripts/fetch_option_chain.py` | 新浪财经公开接口：标的价、到期月、各档认购/认沽 mid 与 IV |

数据源：腾讯财经周线（主，东方财富周线目前会直接断连）、新浪财经日线回退、新浪期权与标的行情。

## 环境

```bash
git clone https://github.com/wangyh99/etf-options-skill.git
cd etf-options-skill
python3 --version   # 建议 3.11+
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

首次运行前复制配置：

```bash
cp config/strategy.yaml.example config/strategy.yaml
```

真实配置已被 `.gitignore` 排除，不会提交钉钉凭据。

## HTML5 控制台

```bash
.venv/bin/python scripts/serve_web.py
```

浏览器打开 <http://127.0.0.1:8765>。页面包含“铁鹰策略 / 宽跨策略”两个 Tab：

- **预测交易带**：展示两个 ETF、两个目标到期日的预测区间和交易带。
- **当前交易策略**：展示当前 Tab 的建议、保证金、收益率和最大亏损。
- **保存当前参数**：写入 `config/strategy.yaml`，下次启动自动加载。

## 策略 CLI

```bash
.venv/bin/python scripts/advise_short_strangle.py --strategy iron_condor
.venv/bin/python scripts/advise_short_strangle.py --strategy short_strangle
```

常用参数：

```bash
.venv/bin/python scripts/advise_short_strangle.py \
  --strategy iron_condor --timeframe weekly --quantile 0.90 --range-pad 0.03 \
  --dte-min 15 --dte-max 60 --min-yield 0.01 --max-yield 0.03

# 只输出策略部分的独立 HTML5 文件
.venv/bin/python scripts/advise_short_strangle.py \
  --strategy short_strangle --strategy-only --format html \
  --out data/strategy_advice.html

# 生成报告后向钉钉发送 Markdown 摘要
.venv/bin/python scripts/advise_short_strangle.py \
  --strategy iron_condor --strategy-only --format html \
  --out data/strategy_advice.html --send-dingtalk
```

| 参数 | 默认 | 含义 |
|------|------|------|
| `--symbols` | `510050,510300` | 标的代码，逗号分隔 |
| `--strategy` | `iron_condor` | `iron_condor` 或 `short_strangle` |
| `--timeframe` | YAML | `daily` 或 `weekly` |
| `--quantile` | YAML | 历史分位 0.80–0.99 |
| `--range-pad` | YAML | 交易带上下扩幅 0.02–0.05 |
| `--dte-min/--dte-max` | YAML | 到期窗口 15–60，选最近两个到期日 |
| `--min-yield/--max-yield` | YAML | 收益率范围 0.01–0.03 |
| `--strategy-only` | 关闭 | 隐藏预测说明，仅输出当前策略 |
| `--format` | `markdown` | `markdown`、`json` 或 `html` |
| `--send-dingtalk` | 关闭 | 使用 YAML 中的机器人配置发送摘要 |
| `--json` | 无 | 可选，同时再写一份 JSON |

### 计算逻辑

1. 取标的近 **3 年日线或周线**，按每个到期日 DTE 折算预测窗口，计算 MACD、KDJ、RSI、BOLL 和历史 P80–P99 前瞻分位。
2. 在预测区间上按配置 **上下扩大 2%–5%**，作为交易带。
3. 筛选 DTE 15–60 的最近两个到期日；卖沽不高于交易带下沿，卖购不低于上沿。
4. 保证金按上交所两个垂直价差估算：  
   `(认沽行权价差 + 认购行权价差) × 合约单位`  
   合约单位 10000。到期最多一边穿仓，经济最大亏损 = `max(两侧宽度)×10000 − 净权利金`。券商可能上浮。
5. 宽跨按 KKS 组合保证金估算。其认购侧亏损理论上无上限，报告会显示“最大亏损：理论无限”及情景损益，绝不把保证金当最大亏损。

## 钉钉配置

`config/strategy.yaml` 支持完整 `webhook`，或单独填写 `access_token`；机器人开启加签时再填写 `secret`。钉钉机器人不支持任意 HTML，因此本地保存完整 HTML5，群内发送由同一报告生成的 Markdown 摘要。

## 期权日报

```bash
python3 scripts/run_daily.py
python3 scripts/run_daily.py --symbols 510050 --month 202609
```

产出：

- `data/latest_report.json` — ATM、偏度、近月链窗口、规则化策略提示
- `data/canvas_payload.json` — 精简数据，可供 Cursor Canvas 嵌入
- `data/chains/<代码>_<YYYYMM>.json` — 原始期权链（本地缓存，不入库）

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```

覆盖动态预测、双到期、双策略、风险披露、YAML、HTML 转义、Flask API 和钉钉签名。不依赖网络。

## 仓库结构

```
scripts/serve_web.py               # Flask HTML5 控制台
scripts/advise_short_strangle.py   # 双策略 CLI
scripts/strategy_engine.py         # 预测与策略编排
scripts/report_html.py             # HTML5/钉钉报告
scripts/config_loader.py           # YAML 配置
scripts/dingtalk.py                # 钉钉机器人
scripts/indicators.py              # MACD / KDJ / RSI / BOLL 与月区间
scripts/margin.py                  # 义务仓、KKS 与铁鹰保证金
scripts/run_daily.py               # 日报入口
scripts/fetch_option_chain.py      # 期权链
scripts/weekly_tech_forecast.py    # 周线测算（对照用）
scripts/strategy_hints.py          # 日报策略规则
tests/                             # 单元测试
.cursor/skills/a-share-etf-options/  # Cursor Agent Skill
automations/daily-etf-options.md   # 交易日定时任务草稿
```

在 Cursor 对话中提到「期权日报 / 铁鹰 / 卖出宽跨 / 510050」时，可按项目 Skill 执行上述脚本。

可选：工作日收盘后用 Cursor Automation 或 `scripts/cron_local.sh` 跑日报。提示词见 [automations/daily-etf-options.md](automations/daily-etf-options.md)。

## 说明

本工具仅供研究与学习，**不构成投资建议**。铁鹰亏损有上限，但仍可能在短时间内接近最大亏损；裸卖宽跨认购侧亏损理论上无上限。保证金为交易所公式估算，下单前请以券商柜台为准。
