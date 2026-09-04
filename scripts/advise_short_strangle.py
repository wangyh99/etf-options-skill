#!/usr/bin/env python3
"""CLI for configurable iron-condor and short-strangle advice."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_loader import DEFAULT_CONFIG_PATH, load_config, validate_strategy_params  # noqa: E402
from strategy_engine import (  # noqa: E402
    DISCLAIMER,
    advice_report,
    forecast_report,
    pick_recommendation,
    scan_iron_condors,
    scan_short_strangles,
)

MIN_YIELD = 0.01
MAX_YIELD = 0.03
RANGE_PAD = 0.02
TARGET_DTE = 30


def format_report(report: dict, strategy_only: bool = False) -> str:
    strategy = report.get("strategy", "iron_condor")
    title = "铁鹰策略建议" if strategy == "iron_condor" else "卖出宽跨策略建议"
    params = report["params"]
    lines = [
        f"# {title}",
        "",
        f"- 时间：{report['as_of']}",
        f"- 参数：{params['timeframe']}线 P{params['quantile'] * 100:.0f}，"
        f"交易带扩 ±{params['range_pad'] * 100:.0f}%，收益率 "
        f"{params['min_yield'] * 100:.1f}%–{params['max_yield'] * 100:.1f}%",
        "",
    ]
    for underlying in report.get("underlyings", []):
        lines.extend([f"## {underlying['name']}（{underlying['symbol']}）", ""])
        for expiry in underlying["expiries"]:
            fc = expiry["forecast"]
            lines.extend([
                f"### {expiry['expiry']}（DTE {expiry['dte']}）",
                "",
            ])
            if not strategy_only:
                lines.extend([
                    f"- 预测区间：{fc['predicted_range']['lo']} – {fc['predicted_range']['hi']}",
                    f"- 交易带：{fc['trade_range']['lo']} – {fc['trade_range']['hi']}",
                    f"- 趋势：{fc['trend']}；历史 P{fc['hist_quantile'] * 100:.0f} "
                    f"下行 {fc['hist_down_pct']}% / 上行 {fc['hist_up_pct']}%",
                    "",
                ])
            if expiry.get("error"):
                lines.extend([f"- 行情错误：{expiry['error']}", ""])
                continue
            rec = expiry.get("recommended")
            if not rec:
                lines.extend(["- 当前无满足收益率范围的结构，建议观望。", ""])
                continue
            lines.extend([
                f"- 结构：**{rec['label']}**",
                f"- 净权利金：{rec['premium_1lot']:.0f} 元；保证金：{rec['margin_1lot']:.0f} 元",
                f"- 收益率：**{rec['yield_pct']:.2f}%**；盈亏平衡：{rec['be_dn']} – {rec['be_up']}",
                f"- 最大亏损：**{rec['max_loss_label']}**",
            ])
            if strategy == "short_strangle":
                lines.append(
                    f"- 认沽侧标的归零损失约 {rec['put_side_loss_at_zero']:.0f} 元；"
                    "保证金不是最大亏损。"
                )
            lines.append("")
    for error in report.get("errors", []):
        lines.append(f"- {error['symbol']}：{error['error']}")
    lines.extend(["---", "", report.get("disclaimer", DISCLAIMER), ""])
    return "\n".join(lines)


def run(
    symbols: list[str],
    target_dte: int = TARGET_DTE,
    min_yield: float = MIN_YIELD,
    max_yield: float = MAX_YIELD,
    strategy: str = "iron_condor",
    **overrides,
) -> dict:
    """Backward-compatible programmatic entry point."""
    params = {
        "symbols": symbols,
        "dte_min": max(15, target_dte - 15),
        "dte_max": min(60, target_dte + 30),
        "min_yield": min_yield,
        "max_yield": max_yield,
        **overrides,
    }
    return advice_report(strategy, validate_strategy_params(params))


def main() -> int:
    parser = argparse.ArgumentParser(description="50/300 ETF 铁鹰/宽跨策略")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--strategy", choices=("iron_condor", "short_strangle"), default="iron_condor")
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--timeframe", choices=("daily", "weekly"), default=None)
    parser.add_argument("--quantile", type=float, default=None, help="0.80-0.99")
    parser.add_argument("--range-pad", type=float, default=None, help="0.02-0.05")
    parser.add_argument("--dte", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--dte-min", type=int, default=None)
    parser.add_argument("--dte-max", type=int, default=None)
    parser.add_argument("--min-yield", type=float, default=None)
    parser.add_argument("--max-yield", type=float, default=None)
    parser.add_argument("--forecast-only", action="store_true")
    parser.add_argument("--strategy-only", action="store_true")
    parser.add_argument("--format", choices=("markdown", "html", "json"), default="markdown")
    parser.add_argument("--out", default=None)
    parser.add_argument("--send-dingtalk", action="store_true")
    parser.add_argument("--json", default=None, help="兼容旧参数：额外输出 JSON")
    args = parser.parse_args()

    config = load_config(args.config)
    params = dict(config["strategy"])
    cli_values = {
        "timeframe": args.timeframe,
        "quantile": args.quantile,
        "range_pad": args.range_pad,
        "dte_min": args.dte_min,
        "dte_max": args.dte_max,
        "min_yield": args.min_yield,
        "max_yield": args.max_yield,
    }
    params.update({key: value for key, value in cli_values.items() if value is not None})
    if args.dte is not None:
        params["dte_min"] = max(15, args.dte - 15)
        params["dte_max"] = min(60, args.dte + 30)
    if args.symbols:
        params["symbols"] = [item.strip() for item in args.symbols.split(",") if item.strip()]
    params = validate_strategy_params(params)
    report = forecast_report(params) if args.forecast_only else advice_report(args.strategy, params)

    if args.format == "json":
        output = json.dumps(report, ensure_ascii=False, indent=2)
    elif args.format == "html":
        from report_html import format_html  # noqa: E402
        output = format_html(report, strategy_only=args.strategy_only)
    else:
        output = format_report(report, strategy_only=args.strategy_only)

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8")
        print(f"wrote {path}", file=sys.stderr)
    else:
        print(output)
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.send_dingtalk:
        from dingtalk import send_report  # noqa: E402
        send_report(report, config["dingtalk"])
        print("sent to DingTalk", file=sys.stderr)
    return 1 if report.get("errors") and not report.get("underlyings") else 0


if __name__ == "__main__":
    raise SystemExit(main())
