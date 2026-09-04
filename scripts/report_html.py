"""HTML5 and DingTalk-friendly rendering for strategy reports."""

from __future__ import annotations

from html import escape


def _money(value) -> str:
    return "—" if value is None else f"{float(value):,.0f} 元"


def format_fragment(report: dict, strategy_only: bool = False) -> str:
    strategy = report.get("strategy", "forecast")
    title = {
        "iron_condor": "铁鹰策略",
        "short_strangle": "宽跨策略",
        "forecast": "交易带预测",
    }.get(strategy, "策略报告")
    parts = [f"<section class='report'><h2>{escape(title)}</h2>"]
    for error in report.get("errors", []):
        parts.append(f"<p class='error'>{escape(error['symbol'])}：{escape(error['error'])}</p>")
    for underlying in report.get("underlyings", []):
        parts.append(
            f"<article><h3>{escape(underlying['name'])} "
            f"<small>{escape(underlying['symbol'])}</small></h3>"
        )
        parts.append(
            f"<p class='muted'>K线 {escape(underlying['bars_from'])} 至 "
            f"{escape(underlying['bars_to'])}，{underlying['bars_n']} 根，"
            f"来源 {escape(underlying['bars_source'])}</p>"
        )
        for expiry in underlying["expiries"]:
            fc = expiry["forecast"]
            parts.append(
                f"<div class='expiry'><h4>{escape(expiry['expiry'])} "
                f"<span>DTE {expiry['dte']}</span></h4>"
            )
            if not strategy_only:
                parts.append(
                    "<div class='metrics'>"
                    f"<div><b>预测区间</b><strong>{fc['predicted_range']['lo']} – "
                    f"{fc['predicted_range']['hi']}</strong></div>"
                    f"<div><b>交易带</b><strong>{fc['trade_range']['lo']} – "
                    f"{fc['trade_range']['hi']}</strong></div>"
                    f"<div><b>趋势</b><strong>{escape(fc['trend'])}</strong></div>"
                    f"<div><b>历史分位</b><strong>P{fc['hist_quantile'] * 100:.0f}</strong></div>"
                    "</div>"
                    f"<p class='muted'>{escape(fc['timeframe'])}线未来 {fc['horizon_bars']} 根；"
                    f"历史下行 {fc['hist_down_pct']}%，上行 {fc['hist_up_pct']}%；"
                    f"波动率折算 {fc['horizon_sigma_pct']}%</p>"
                )
            if expiry.get("error"):
                parts.append(f"<p class='error'>{escape(expiry['error'])}</p></div>")
                continue
            rec = expiry.get("recommended")
            if rec is None:
                if strategy != "forecast":
                    parts.append("<p class='empty'>当前收益率范围内无可用结构，建议观望。</p>")
                parts.append("</div>")
                continue
            parts.append(
                f"<div class='recommendation'><h5>{escape(rec['label'])}</h5>"
                "<div class='metrics'>"
                f"<div><b>净权利金</b><strong>{_money(rec['premium_1lot'])}</strong></div>"
                f"<div><b>保证金</b><strong>{_money(rec['margin_1lot'])}</strong></div>"
                f"<div><b>收益率</b><strong>{rec['yield_pct']:.2f}%</strong></div>"
                f"<div><b>最大亏损</b><strong>{escape(rec['max_loss_label'])}</strong></div>"
                "</div>"
                f"<p>盈亏平衡：{rec['be_dn']} – {rec['be_up']}</p>"
            )
            if strategy == "short_strangle":
                parts.append(
                    f"<p class='risk'>认购侧亏损理论无上限；认沽侧标的归零损失约 "
                    f"{_money(rec['put_side_loss_at_zero'])}。保证金不代表最大亏损。</p>"
                )
                if rec.get("scenarios"):
                    parts.append(
                        "<table><thead><tr><th>标的变动</th><th>情景价格</th>"
                        "<th>到期损益</th></tr></thead><tbody>"
                    )
                    for scenario in rec["scenarios"]:
                        parts.append(
                            f"<tr><td>{scenario['move_pct']:+.0f}%</td>"
                            f"<td>{scenario['spot']}</td><td>{_money(scenario['pnl'])}</td></tr>"
                        )
                    parts.append("</tbody></table>")
            parts.append("</div></div>")
        parts.append("</article>")
    parts.append(
        f"<p class='disclaimer'>{escape(report.get('disclaimer', '仅供研究参考，不构成投资建议。'))}</p>"
        "</section>"
    )
    return "".join(parts)


def format_html(report: dict, strategy_only: bool = False) -> str:
    title = "ETF 期权策略报告"
    styles = """
    :root{color-scheme:light dark;--bg:#f4f6f8;--panel:#fff;--text:#18212f;--muted:#667085;
    --line:#d9dee7;--accent:#155eef;--warn:#b54708}@media(prefers-color-scheme:dark){
    :root{--bg:#101318;--panel:#171b22;--text:#eef2f6;--muted:#98a2b3;--line:#344054;--accent:#84adff}}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,sans-serif}
    main{max-width:1100px;margin:auto;padding:28px}h1{margin:0 0 18px}article,.expiry{background:var(--panel);
    border:1px solid var(--line);border-radius:12px;padding:18px;margin:14px 0}.expiry{border-radius:8px}
    h3,h4,h5{margin:0 0 10px}h4 span,small{color:var(--muted);font-weight:400}.metrics{display:grid;
    grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.metrics div{border-left:3px solid var(--accent);
    padding:8px 10px}.metrics b,.metrics strong{display:block}.muted{color:var(--muted)}.risk,.error{color:var(--warn)}
    table{width:100%;border-collapse:collapse}th,td{padding:7px;border-bottom:1px solid var(--line);text-align:left}
    .disclaimer{color:var(--muted);border-top:1px solid var(--line);padding-top:14px}
    """
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title><style>{styles}</style></head>"
        f"<body><main><h1>{title}</h1>{format_fragment(report, strategy_only)}</main></body></html>"
    )


def format_dingtalk_markdown(report: dict) -> str:
    strategy = "铁鹰" if report.get("strategy") == "iron_condor" else "宽跨"
    lines = [f"## ETF期权{strategy}策略", f"> {report.get('as_of', '')}"]
    for underlying in report.get("underlyings", []):
        lines.append(f"\n### {underlying['name']}（{underlying['symbol']}）")
        for expiry in underlying["expiries"]:
            rec = expiry.get("recommended")
            if rec:
                lines.extend([
                    f"- {expiry['expiry']} / DTE {expiry['dte']}：**{rec['label']}**",
                    f"- 权利金 {_money(rec['premium_1lot'])}，保证金 {_money(rec['margin_1lot'])}，"
                    f"收益率 **{rec['yield_pct']:.2f}%**",
                    f"- 最大亏损：**{rec['max_loss_label']}**；盈亏平衡 {rec['be_dn']}–{rec['be_up']}",
                ])
            else:
                lines.append(f"- {expiry['expiry']}：无达标结构，观望")
    lines.append(f"\n> {report.get('disclaimer', '仅供研究参考，不构成投资建议。')}")
    return "\n".join(lines)
