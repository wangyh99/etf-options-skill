"""HTML5 and DingTalk-friendly rendering for strategy reports."""

from __future__ import annotations

import re
from html import escape

_ACTION_RE = re.compile(r"(观望|卖出|买入)")


def _money(value) -> str:
    return "—" if value is None else f"{float(value):,.0f} 元"


def _box(value: dict | None) -> str:
    if not value:
        return "—"
    return f"{value['lo']:.4f} – {value['hi']:.4f}"


def _number(value, digits: int = 2) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def _highlight_actions(text: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        word = match.group(1)
        kind = {"观望": "wait", "卖出": "sell", "买入": "buy"}[word]
        return f"<mark class='action action-{kind}'>{word}</mark>"

    return _ACTION_RE.sub(replacer, escape(text))


def _render_structure(rec: dict, strategy: str, muted: bool = False) -> str:
    tone = "recommendation dim" if muted else "recommendation"
    parts = [
        f"<div class='{tone}'>",
        f"<h5>{_highlight_actions(rec['label'])}</h5>",
        "<div class='metrics'>",
        f"<div><b>净权利金</b><strong>{_money(rec['premium_1lot'])}</strong></div>",
        f"<div><b>保证金</b><strong>{_money(rec['margin_1lot'])}</strong></div>",
        f"<div><b>月均收益率</b><strong>{rec['yield_pct']:.2f}%</strong>"
        f"<small>持有到期 {rec.get('hold_yield_pct', rec['yield_pct']):.2f}%</small></div>",
        f"<div><b>最大亏损</b><strong>{escape(rec['max_loss_label'])}</strong></div>",
        "</div>",
        f"<p>盈亏平衡：{rec['be_dn']} – {rec['be_up']}</p>",
    ]
    if rec.get("legs"):
        legs = "；".join(
            f"{_highlight_actions(leg['action'])}"
            f" {escape(leg.get('option_type', '期权'))}"
            f" {escape(str(leg.get('strike', '')))}"
            for leg in rec["legs"]
        )
        parts.append(f"<p class='legs'>{legs}</p>")
    if strategy == "short_strangle":
        parts.append(
            f"<p class='risk'>认购侧亏损理论无上限；认沽侧标的归零损失约 "
            f"{_money(rec['put_side_loss_at_zero'])}。保证金不代表最大亏损。</p>"
        )
        if rec.get("scenarios") and not muted:
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
    parts.append("</div>")
    return "".join(parts)


def _render_forecast(fc: dict) -> str:
    if fc.get("model") == "asymmetric":
        state = fc["state"]
        features = fc["position_features"]
        reasons = "；".join(escape(reason) for reason in state["reasons"])
        return (
            "<div class='state-line'>"
            f"<span class='state-badge'>{escape(state['label'])}</span>"
            f"<span>{reasons}</span></div>"
            "<div class='box-grid'>"
            f"<div class='box-item risk-box'><b>风险箱体 P{fc['hist_quantile'] * 100:.0f}</b>"
            f"<strong>{_box(fc['risk_range'])}</strong><small>策略扫描的基础边界</small></div>"
            f"<div class='box-item'><b>无条件基线</b><strong>{_box(fc['baseline_range'])}</strong>"
            "<small>历史路径分位 + 波动率地板</small></div>"
            "</div>"
            "<div class='metrics'>"
            f"<div><b>最终扫描带</b><strong>{_box(fc['trade_range'])}</strong></div>"
            f"<div><b>Pos 1年 / 3年</b><strong>{_number(features.get('pos_252'))} / "
            f"{_number(features.get('pos_756'))}</strong></div>"
            f"<div><b>距年线（ATR）</b><strong>{_number(features.get('d_ma250_atr'))}</strong></div>"
            f"<div><b>ATR20 / 价格</b><strong>{_number((features.get('atr_pct') or 0) * 100)}%</strong></div>"
            "</div>"
            f"<p class='muted'>条件桶 {escape(str(fc['sample_info']['bucket']))}，"
            f"样本 {fc['sample_info']['conditional']} / 全部 {fc['sample_info']['all']}；"
            f"{'已回退无条件分位' if fc['sample_info']['risk_fallback'] else '使用条件分位'}。"
            f"短周期信号：{escape(fc['timeframe'])}线。</p>"
        )
    return (
        "<div class='metrics'>"
        f"<div><b>预测区间</b><strong>{_box(fc['predicted_range'])}</strong></div>"
        f"<div><b>交易带</b><strong>{_box(fc['trade_range'])}</strong></div>"
        f"<div><b>趋势</b><strong>{escape(fc['trend'])}</strong></div>"
        f"<div><b>历史分位</b><strong>P{fc['hist_quantile'] * 100:.0f}</strong></div>"
        "</div>"
        f"<p class='muted'>{escape(fc['timeframe'])}线未来 {fc['horizon_bars']} 根；"
        f"历史下行 {fc['hist_down_pct']}%，上行 {fc['hist_up_pct']}%；"
        f"波动率折算 {fc['horizon_sigma_pct']}%</p>"
    )


def _render_reference_context(ref: dict) -> str:
    context = ref.get("reference_context") or {}
    if not context:
        return (
            "<p class='muted ref-caption'>"
            "参考方案（最终扫描带最近可用档位，未形成正式推荐）</p>"
        )
    reason = context["reason"]
    if reason == "strike_coverage":
        reason_text = "可用行权价未覆盖最终扫描带，并非收益率不足"
    elif reason == "yield_below_min":
        reason_text = "最近可用档位未达到最低月均收益率"
    else:
        reason_text = "最近档位未形成可推荐结构"
    yield_text = (
        f"月均收益率已达到 {context['min_yield_pct']:.2f}% 下限"
        if context["yield_meets_min"]
        else f"月均收益率未达到 {context['min_yield_pct']:.2f}% 下限"
    )
    return (
        f"<div class='reference-warning risk-{escape(context['risk_level'])}'>"
        f"<p><b>观望原因：</b>{escape(reason_text)}；{escape(yield_text)}。</p>"
        "<div class='gap-grid'>"
        f"<div><b>认沽端偏差</b><strong>{context['put_inward_gap_pct']:.2f}%</strong>"
        f"<small>卖出 {ref['put_k']:.4f}；扫描带下沿 {context['trade_lo']:.4f}</small></div>"
        f"<div><b>认购端偏差</b><strong>{context['call_inward_gap_pct']:.2f}%</strong>"
        f"<small>卖出 {ref['call_k']:.4f}；扫描带上沿 {context['trade_hi']:.4f}</small></div>"
        "</div>"
        f"<p class='risk-level'><b>档位偏差风险：{escape(context['risk_level'])}</b>"
        "（偏差表示卖出腿向预测风险区内收缩）</p>"
        "</div>"
        "<p class='muted ref-caption'>参考方案（最终扫描带最近可用档位，非正式推荐）</p>"
    )


def _render_reference_risk_controls(ref: dict, strategy: str) -> str:
    context = ref.get("reference_context") or {}
    if not context:
        return ""
    strategy_note = (
        "宽跨认购侧亏损无上限，扫描带未被覆盖时原则上不使用裸卖结构。"
        if strategy == "short_strangle"
        else "铁鹰虽有最大亏损上限，档位内缩仍会明显提高触碰卖出腿的概率。"
    )
    return (
        "<div class='risk-controls'><b>如仍操作，风控参考</b><ul>"
        "<li>仓位不超过常规计划的 1/3，不因高收益率放大仓位。</li>"
        f"<li>组合回购价达到约 {_money(context['buyback_stop_1lot'])}"
        f"（初始净权利金的 2 倍）时整体止损，预计权利金损失约 "
        f"{_money(context['stop_loss_1lot'])}，另计滑点和费用。</li>"
        f"<li>标的触及卖出认沽 {ref['put_k']:.4f} 或卖出认购 {ref['call_k']:.4f}，"
        "不等待到期，平掉受威胁侧或整个组合。</li>"
        "<li>DTE 不高于 7 天时退出参考仓，避免到期前 Gamma 风险。</li>"
        f"</ul><p>{escape(strategy_note)}</p></div>"
    )


def _render_advice(expiry: dict, strategy: str) -> str:
    if strategy not in ("iron_condor", "short_strangle"):
        return ""
    kind = "iron" if strategy == "iron_condor" else "strangle"
    title = "铁鹰建议" if strategy == "iron_condor" else "宽跨建议"
    parts = [f"<div class='strategy-block strategy-{kind}'><h5>{escape(title)}</h5>"]
    if expiry.get("error"):
        parts.append(f"<p class='error'>{escape(expiry['error'])}</p></div>")
        return "".join(parts)
    rec = expiry.get("recommended")
    ref = expiry.get("reference")
    if rec:
        parts.append(_render_structure(rec, strategy))
    else:
        reason = (ref or {}).get("reference_context", {}).get("reason")
        stance = (
            " 可用行权价未覆盖最终扫描带。"
            if reason == "strike_coverage"
            else " 当前未达到最低月均收益率。"
        )
        parts.append(
            "<p class='stance'>"
            "<mark class='action action-wait'>观望</mark>"
            f"{stance}"
            "</p>"
        )
        if ref:
            parts.append(_render_reference_context(ref))
            parts.append(_render_structure(ref, strategy, muted=True))
            parts.append(_render_reference_risk_controls(ref, strategy))
    parts.append("</div>")
    return "".join(parts)


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
                parts.append(_render_forecast(fc))
            if expiry.get("error") and strategy == "forecast":
                parts.append(f"<p class='error'>{escape(expiry['error'])}</p>")
            parts.append(_render_advice(expiry, strategy))
            parts.append("</div>")
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
    --line:#d9dee7;--accent:#155eef;--warn:#b54708;--buy:#027a48;--sell:#b42318}@media(prefers-color-scheme:dark){
    :root{--bg:#101318;--panel:#171b22;--text:#eef2f6;--muted:#98a2b3;--line:#344054;--accent:#84adff}}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,sans-serif}
    main{max-width:1100px;margin:auto;padding:28px}h1{margin:0 0 18px}article,.expiry{background:var(--panel);
    border:1px solid var(--line);border-radius:12px;padding:18px;margin:14px 0}.expiry{border-radius:8px}
    h3,h4,h5{margin:0 0 10px}h4 span,small{color:var(--muted);font-weight:400}.metrics{display:grid;
    grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.metrics div{border-left:3px solid var(--accent);
    padding:8px 10px}.metrics b,.metrics strong{display:block}.muted{color:var(--muted)}.risk,.error{color:var(--warn)}
    .state-line{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0 14px}
    .state-badge{padding:4px 9px;border-radius:999px;border:1px solid var(--line);font-weight:700}
    .box-grid{display:grid;grid-template-columns:repeat(2,minmax(150px,1fr));gap:10px;margin:12px 0}
    .box-item{border:1px solid var(--line);border-radius:8px;padding:10px}.box-item.risk-box{border:2px solid var(--accent)}
    .box-item b,.box-item strong{display:block}
    .strategy-block{margin-top:14px;padding:12px;border-radius:8px;border:1px solid var(--line)}
    .strategy-iron{background:#eff4ff;border-color:#b2ccff}
    .strategy-strangle{background:#f4ebff;border-color:#d6bbfb}
    mark.action{padding:1px 6px;border-radius:4px;font-weight:700}
    .action-wait{background:#fef0c7;color:#b54708}
    .action-sell{background:#fee4e2;color:#b42318}
    .action-buy{background:#d1fadf;color:#027a48}
    .recommendation.dim{opacity:.72;filter:saturate(.35);background:#f2f4f7;border-radius:8px;padding:10px}
    .reference-warning{margin-top:10px;padding:10px 12px;border:1px solid #fedf89;border-radius:8px;
    background:#fffaeb;color:#93370d}.reference-warning p{margin:0 0 8px}.gap-grid{display:grid;
    grid-template-columns:repeat(2,1fr);gap:8px}.gap-grid div{padding:8px 10px;border-radius:7px;
    background:rgba(255,255,255,.62)}.gap-grid b,.gap-grid strong,.gap-grid small{display:block}
    .gap-grid strong{font-size:20px}.risk-controls{margin-top:10px;padding:10px 12px;
    border-left:3px solid var(--warn);background:#fff7ed;color:#7c2d12}.risk-controls ul{margin:7px 0;padding-left:20px}
    table{width:100%;border-collapse:collapse}th,td{padding:7px;border-bottom:1px solid var(--line);text-align:left}
    .disclaimer{color:var(--muted);border-top:1px solid var(--line);padding-top:14px}
    @media(max-width:700px){.box-grid,.gap-grid{grid-template-columns:1fr}}
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
            ref = expiry.get("reference")
            if rec:
                lines.extend([
                    f"- {expiry['expiry']} / DTE {expiry['dte']}：**{rec['label']}**",
                    f"- 权利金 {_money(rec['premium_1lot'])}，保证金 {_money(rec['margin_1lot'])}，"
                    f"月均收益率 **{rec['yield_pct']:.2f}%**",
                    f"- 最大亏损：**{rec['max_loss_label']}**；盈亏平衡 {rec['be_dn']}–{rec['be_up']}",
                ])
            else:
                context = (ref or {}).get("reference_context") or {}
                reason = (
                    "可用行权价未覆盖最终扫描带"
                    if context.get("reason") == "strike_coverage"
                    else "无满足最低月均收益率的结构"
                )
                lines.append(f"- {expiry['expiry']}：**观望**，{reason}")
                if ref:
                    lines.append(
                        f"- 参考最近档位：{ref['label']}，月均收益率 {ref['yield_pct']:.2f}%，"
                        f"最大亏损 {ref['max_loss_label']}"
                    )
                    if context:
                        lines.append(
                            f"- 偏差：认沽端 {context['put_inward_gap_pct']:.2f}%，"
                            f"认购端 {context['call_inward_gap_pct']:.2f}%，"
                            f"风险 {context['risk_level']}"
                        )
    lines.append(f"\n> {report.get('disclaimer', '仅供研究参考，不构成投资建议。')}")
    return "\n".join(lines)
