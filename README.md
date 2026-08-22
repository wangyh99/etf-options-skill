# A股股指 ETF 期权工具

面向 **上证50ETF（510050）**、**沪深300ETF（510300）** 的本地命令行工具：拉取期权链、用近 3 年周线估算未来约一个月波动区间，并给出卖出宽跨式建议。

仅需 Python 3.11+ 标准库，无需安装 akshare / pandas。

## 功能

| 功能 | 脚本 | 说明 |
|------|------|------|
| **卖出宽跨即时建议** | `scripts/advise_short_strangle.py` | 周线 MACD / KDJ / RSI / BOLL 预测月区间，上下再扩 2%；扫描约 30 天到期期权；只保留权利金/保证金 > 1.5% 的档位 |
| **期权日报** | `scripts/run_daily.py` | 拉取近月期权链、ATM IV、偏度，并按规则提示跨式 / 垂直价差 |
| **周线区间测算** | `scripts/weekly_tech_forecast.py` | 单独输出周线指标与月波动带（供对照） |
| **期权链拉取** | `scripts/fetch_option_chain.py` | 新浪财经公开接口：标的价、到期月、各档认购/认沽 mid 与 IV |

数据源：东方财富（周线）、新浪财经（期权与标的行情）。

## 环境

```bash
git clone https://github.com/wangyh99/etf-options-skill.git
cd etf-options-skill
python3 --version   # 建议 3.11+
```

无需 `pip install`。若本机 Python 缺系统 CA 证书，脚本会回退到不校验证书（仅用于公开行情）。

## 卖出宽跨建议（主功能）

```bash
python3 scripts/advise_short_strangle.py
```

常用参数：

```bash
python3 scripts/advise_short_strangle.py --symbols 510050,510300 --dte 30 --min-yield 0.015
```

| 参数 | 默认 | 含义 |
|------|------|------|
| `--symbols` | `510050,510300` | 标的代码，逗号分隔 |
| `--dte` | `30` | 目标剩余天数，自动选最接近的到期月（跳过过短合约） |
| `--min-yield` | `0.015` | 最低收益率：权利金 / 组合保证金 |
| `--out` | `data/short_strangle_advice.json` | JSON 输出路径 |

### 计算逻辑

1. 取标的近 **3 年周线**，计算 MACD、KDJ（JDK）、RSI、BOLL，并结合历史 4 周涨跌分位、周波动折算月 σ，得到**预测月区间**。
2. 在该区间上 **上下各扩大 2%**，作为交易带（卖出认沽行权价 ≤ 下沿，卖出认购行权价 ≥ 上沿）。
3. 选取 DTE 最接近 30 天的合约月，扫描交易带外的全部宽跨组合。
4. 保证金按上交所 **宽跨式空头（KKS）** 估算：  
   `Max(认购义务仓保证金, 认沽义务仓保证金) + 保证金较低一侧的权利金 × 合约单位`  
   合约单位 10000。券商可能在交易所标准上上浮。
5. 只输出 **权利金 / 保证金 > 1.5%** 的组合，按收益率排序并给出一条主建议；若无达标档位则提示观望。

终端会打印摘要，完整结果在 `data/short_strangle_advice.json`。

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
python3 -m unittest discover -s tests -v
```

覆盖指标、区间扩 2%、上交所保证金 / 收益率、到期月选择、宽跨筛选。不依赖网络。

## 仓库结构

```
scripts/advise_short_strangle.py   # 即时卖出宽跨建议
scripts/indicators.py              # MACD / KDJ / RSI / BOLL 与月区间
scripts/margin.py                  # 认购/认沽义务仓与 KKS 组合保证金
scripts/run_daily.py               # 日报入口
scripts/fetch_option_chain.py      # 期权链
scripts/weekly_tech_forecast.py    # 周线测算（对照用）
scripts/strategy_hints.py          # 日报策略规则
tests/                             # 单元测试
.cursor/skills/a-share-etf-options/  # Cursor Agent Skill
automations/daily-etf-options.md   # 交易日定时任务草稿
```

在 Cursor 对话中提到「期权日报 / 卖出宽跨 / 510050」时，可按项目 Skill 执行上述脚本。

可选：工作日收盘后用 Cursor Automation 或 `scripts/cron_local.sh` 跑日报。提示词见 [automations/daily-etf-options.md](automations/daily-etf-options.md)。

## 说明

本工具仅供研究与学习，**不构成投资建议**。期权卖方风险不对称，认购腿理论上亏损不封顶；保证金为交易所公式估算，下单前请以券商柜台为准。
