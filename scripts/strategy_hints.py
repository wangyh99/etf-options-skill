"""Deterministic strategy hints from an option-chain snapshot."""

from __future__ import annotations

from typing import Any


def _mid(leg: dict[str, Any] | None) -> float | None:
    if not leg:
        return None
    return leg.get("mid") or leg.get("last")


def _iv(leg: dict[str, Any] | None) -> float | None:
    if not leg:
        return None
    return leg.get("iv")


def _pct(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:.1f}%"


def nearest_otm_strikes(
    chain: list[dict[str, Any]],
    pivot: float,
    steps: int = 1,
) -> tuple[float | None, float | None]:
    """Return (put_side_lower, call_side_higher) relative to pivot (usually ATM)."""
    strikes = [row["strike"] for row in chain if row.get("strike") is not None]
    below = sorted([k for k in strikes if k < pivot], reverse=True)
    above = sorted([k for k in strikes if k > pivot])
    put_k = below[steps - 1] if len(below) >= steps else (below[-1] if below else None)
    call_k = above[steps - 1] if len(above) >= steps else (above[-1] if above else None)
    return put_k, call_k


def find_row(chain: list[dict[str, Any]], strike: float) -> dict[str, Any] | None:
    for row in chain:
        if row.get("strike") == strike:
            return row
    return None


def build_hints(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    spot = (snapshot.get("spot") or {}).get("last")
    chain = snapshot.get("chain") or []
    atm = snapshot.get("atm") or {}
    dte = snapshot.get("dte")
    symbol = snapshot.get("symbol")
    expiry = snapshot.get("expiry")

    if spot is None or not chain or not atm.get("strike"):
        return [
            {
                "id": "insufficient_data",
                "title": "数据不足",
                "bias": "none",
                "reason": "缺少现价或 ATM 期权链，无法生成策略提示。",
                "legs": [],
            }
        ]

    call = atm.get("call") or {}
    put = atm.get("put") or {}
    call_mid = _mid(call)
    put_mid = _mid(put)
    call_iv = _iv(call)
    put_iv = _iv(put)
    atm_iv = None
    if call_iv is not None and put_iv is not None:
        atm_iv = (call_iv + put_iv) / 2.0
    elif call_iv is not None:
        atm_iv = call_iv
    elif put_iv is not None:
        atm_iv = put_iv

    skew = atm.get("skew_put_minus_call")
    if skew is None and call_iv is not None and put_iv is not None:
        skew = put_iv - call_iv

    # Heuristic IV regime without history: use absolute ATM IV bands for ETF options
    regime = "mid"
    if atm_iv is not None:
        if atm_iv < 0.14:
            regime = "low"
        elif atm_iv > 0.28:
            regime = "high"

    straddle_debit = None
    if call_mid is not None and put_mid is not None:
        straddle_debit = call_mid + put_mid

    # 1) Vol regime primary hint
    if regime == "low" and straddle_debit is not None:
        hints.append(
            {
                "id": "long_straddle",
                "title": "低 IV：ATM 买入跨式",
                "bias": "long_vol",
                "reason": (
                    f"ATM IV≈{_pct(atm_iv)} 偏低；买入 ATM 认购+认沽，押注波动抬升。"
                    f" 约权利金 {straddle_debit:.4f}（按 mid）。"
                ),
                "legs": [
                    {
                        "action": "buy",
                        "cp": "C",
                        "strike": atm["strike"],
                        "code": call.get("code"),
                        "mid": call_mid,
                        "iv": call_iv,
                    },
                    {
                        "action": "buy",
                        "cp": "P",
                        "strike": atm["strike"],
                        "code": put.get("code"),
                        "mid": put_mid,
                        "iv": put_iv,
                    },
                ],
                "approx_debit": straddle_debit,
                "max_loss": straddle_debit,
                "symbol": symbol,
                "expiry": expiry,
                "dte": dte,
            }
        )
    elif regime == "high" and call_mid is not None and put_mid is not None:
        put_k, call_k = nearest_otm_strikes(chain, atm["strike"], steps=1)
        put_row = find_row(chain, put_k) if put_k else None
        call_row = find_row(chain, call_k) if call_k else None
        short_put = (put_row or {}).get("put") if put_row else None
        short_call = (call_row or {}).get("call") if call_row else None
        # Credit put vertical: sell ATM put, buy lower put
        lower_k = put_k
        lower_row = find_row(chain, lower_k) if lower_k else None
        lower_put = (lower_row or {}).get("put") if lower_row else None
        if _mid(put) is not None and _mid(lower_put) is not None and lower_k is not None:
            credit = _mid(put) - _mid(lower_put)
            width = atm["strike"] - lower_k
            hints.append(
                {
                    "id": "credit_put_vertical",
                    "title": "高 IV：认沽垂直价差（收权利金）",
                    "bias": "short_vol_mild_bull",
                    "reason": (
                        f"ATM IV≈{_pct(atm_iv)} 偏高；卖出 ATM 认沽、买入更低行权认沽收取权利金。"
                        f" 约净权利金 {credit:.4f}，最大亏损约 {width - credit:.4f}。"
                    ),
                    "legs": [
                        {
                            "action": "sell",
                            "cp": "P",
                            "strike": atm["strike"],
                            "code": put.get("code"),
                            "mid": _mid(put),
                            "iv": put_iv,
                        },
                        {
                            "action": "buy",
                            "cp": "P",
                            "strike": lower_k,
                            "code": (lower_put or {}).get("code"),
                            "mid": _mid(lower_put),
                            "iv": _iv(lower_put),
                        },
                    ],
                    "approx_credit": credit,
                    "max_loss": width - credit if credit is not None else None,
                    "symbol": symbol,
                    "expiry": expiry,
                    "dte": dte,
                }
            )
        elif short_put and short_call and _mid(short_put) and _mid(short_call):
            credit = _mid(short_put) + _mid(short_call)
            hints.append(
                {
                    "id": "short_strangle",
                    "title": "高 IV：OTM 卖出宽跨式（仅提示）",
                    "bias": "short_vol",
                    "reason": (
                        f"ATM IV≈{_pct(atm_iv)} 偏高；OTM 认购+认沽收权利金，风险不对称，需严格风控。"
                        f" 约净权利金 {credit:.4f}。"
                    ),
                    "legs": [
                        {
                            "action": "sell",
                            "cp": "C",
                            "strike": call_k,
                            "code": short_call.get("code"),
                            "mid": _mid(short_call),
                            "iv": _iv(short_call),
                        },
                        {
                            "action": "sell",
                            "cp": "P",
                            "strike": put_k,
                            "code": short_put.get("code"),
                            "mid": _mid(short_put),
                            "iv": _iv(short_put),
                        },
                    ],
                    "approx_credit": credit,
                    "symbol": symbol,
                    "expiry": expiry,
                    "dte": dte,
                }
            )
    else:
        # Mid IV: directional debit vertical based on mild skew
        put_k, call_k = nearest_otm_strikes(chain, atm["strike"], steps=1)
        if skew is not None and skew > 0.03 and call_mid is not None and call_k is not None:
            higher = find_row(chain, call_k)
            higher_call = (higher or {}).get("call")
            if _mid(higher_call) is not None:
                debit = call_mid - _mid(higher_call)
                hints.append(
                    {
                        "id": "debit_call_vertical",
                        "title": "中性/偏涨：认购垂直价差",
                        "bias": "mild_bull",
                        "reason": (
                            f"Put IV 高于 Call（skew={_pct(skew)}），下行溢价偏贵；"
                            f"买入 ATM 认购、卖出更高行权认购，约净支出 {debit:.4f}。"
                        ),
                        "legs": [
                            {
                                "action": "buy",
                                "cp": "C",
                                "strike": atm["strike"],
                                "code": call.get("code"),
                                "mid": call_mid,
                                "iv": call_iv,
                            },
                            {
                                "action": "sell",
                                "cp": "C",
                                "strike": call_k,
                                "code": (higher_call or {}).get("code"),
                                "mid": _mid(higher_call),
                                "iv": _iv(higher_call),
                            },
                        ],
                        "approx_debit": debit,
                        "symbol": symbol,
                        "expiry": expiry,
                        "dte": dte,
                    }
                )
        elif skew is not None and skew < -0.03 and put_mid is not None and put_k is not None:
            lower = find_row(chain, put_k)
            lower_put = (lower or {}).get("put")
            if _mid(lower_put) is not None:
                debit = put_mid - _mid(lower_put)
                hints.append(
                    {
                        "id": "debit_put_vertical",
                        "title": "中性/偏跌：认沽垂直价差",
                        "bias": "mild_bear",
                        "reason": (
                            f"Call IV 高于 Put（skew={_pct(skew)}）；"
                            f"买入 ATM 认沽、卖出更低行权认沽，约净支出 {debit:.4f}。"
                        ),
                        "legs": [
                            {
                                "action": "buy",
                                "cp": "P",
                                "strike": atm["strike"],
                                "code": put.get("code"),
                                "mid": put_mid,
                                "iv": put_iv,
                            },
                            {
                                "action": "sell",
                                "cp": "P",
                                "strike": put_k,
                                "code": (lower_put or {}).get("code"),
                                "mid": _mid(lower_put),
                                "iv": _iv(lower_put),
                            },
                        ],
                        "approx_debit": debit,
                        "symbol": symbol,
                        "expiry": expiry,
                        "dte": dte,
                    }
                )
        elif straddle_debit is not None:
            hints.append(
                {
                    "id": "watch_straddle",
                    "title": "中性 IV：观察 ATM 跨式成本",
                    "bias": "neutral",
                    "reason": (
                        f"ATM IV≈{_pct(atm_iv)} 处中性区间；ATM 跨式约 {straddle_debit:.4f}，"
                        "可等待 IV 极端或方向信号再动手。"
                    ),
                    "legs": [
                        {
                            "action": "watch",
                            "cp": "C",
                            "strike": atm["strike"],
                            "code": call.get("code"),
                            "mid": call_mid,
                            "iv": call_iv,
                        },
                        {
                            "action": "watch",
                            "cp": "P",
                            "strike": atm["strike"],
                            "code": put.get("code"),
                            "mid": put_mid,
                            "iv": put_iv,
                        },
                    ],
                    "approx_debit": straddle_debit,
                    "symbol": symbol,
                    "expiry": expiry,
                    "dte": dte,
                }
            )

    # Always add skew note as secondary hint when extreme
    if skew is not None and abs(skew) >= 0.04:
        side = "下行保护需求偏强（Put IV 更高）" if skew > 0 else "上行博弈偏强（Call IV 更高）"
        hints.append(
            {
                "id": "skew_note",
                "title": "偏度提示",
                "bias": "skew",
                "reason": f"ATM Put−Call IV = {_pct(skew)}；{side}。",
                "legs": [],
                "skew": skew,
                "symbol": symbol,
                "expiry": expiry,
                "dte": dte,
            }
        )

    if not hints:
        hints.append(
            {
                "id": "no_clear_setup",
                "title": "暂无清晰结构",
                "bias": "none",
                "reason": "IV/价差条件未触发规则；仅供盯盘，不生成交易腿。",
                "legs": [],
                "symbol": symbol,
                "expiry": expiry,
                "dte": dte,
            }
        )

    return hints[:3]
