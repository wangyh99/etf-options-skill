"""SSE ETF option margin (exchange formula, 1 lot = 10000 shares)."""

from __future__ import annotations

CONTRACT_MULT = 10000
CALL_GUARD = 0.12
CALL_FLOOR = 0.07
PUT_GUARD = 0.12


def call_short_margin(premium: float, spot: float, strike: float, multiplier: int = CONTRACT_MULT) -> float:
    """认购义务仓开仓保证金。"""
    if premium < 0 or spot <= 0 or strike <= 0:
        raise ValueError("invalid call margin inputs")
    otm = max(strike - spot, 0.0)
    per_share = premium + max(CALL_GUARD * spot - otm, CALL_FLOOR * spot)
    return per_share * multiplier


def put_short_margin(premium: float, spot: float, strike: float, multiplier: int = CONTRACT_MULT) -> float:
    """认沽义务仓开仓保证金。"""
    if premium < 0 or spot <= 0 or strike <= 0:
        raise ValueError("invalid put margin inputs")
    otm = max(spot - strike, 0.0)
    inner = premium + max(PUT_GUARD * spot - otm, 0.07 * strike)
    per_share = min(inner, strike)
    return per_share * multiplier


def short_strangle_combo_margin(
    call_premium: float,
    put_premium: float,
    spot: float,
    call_strike: float,
    put_strike: float,
    multiplier: int = CONTRACT_MULT,
) -> dict:
    """
    宽跨式空头(KKS)开仓保证金：
    Max(认购保证金, 认沽保证金) + 保证金较低一侧的权利金 × 合约单位。
    两侧相等时，取两侧权利金较大者。
    """
    if call_strike <= put_strike:
        raise ValueError("strangle requires call_strike > put_strike")
    mc = call_short_margin(call_premium, spot, call_strike, multiplier)
    mp = put_short_margin(put_premium, spot, put_strike, multiplier)
    if mc > mp:
        extra = put_premium * multiplier
    elif mp > mc:
        extra = call_premium * multiplier
    else:
        extra = max(call_premium, put_premium) * multiplier
    combo = max(mc, mp) + extra
    prem = (call_premium + put_premium) * multiplier
    yield_pct = prem / combo if combo > 0 else 0.0
    return {
        "call_margin": mc,
        "put_margin": mp,
        "combo_margin": combo,
        "premium": prem,
        "yield": yield_pct,
    }


def meets_yield(yield_pct: float, min_yield: float = 0.015) -> bool:
    return yield_pct + 1e-12 >= min_yield


def monthly_yield(hold_yield: float, dte: int, month_days: int = 30) -> float:
    """Convert holding-period yield into a 30-day average yield: hold_yield * 30 / DTE."""
    if dte <= 0:
        raise ValueError("dte must be positive")
    return hold_yield * month_days / dte


def short_strangle_risk_profile(
    call_premium: float,
    put_premium: float,
    spot: float,
    call_strike: float,
    put_strike: float,
    multiplier: int = CONTRACT_MULT,
    scenario_moves: tuple[float, ...] = (-0.20, -0.10, 0.10, 0.20),
) -> dict:
    """Risk disclosure for an uncovered short strangle; upside loss is unbounded."""
    margin = short_strangle_combo_margin(
        call_premium, put_premium, spot, call_strike, put_strike, multiplier
    )
    credit = call_premium + put_premium

    def pnl(at_spot: float) -> float:
        intrinsic = max(put_strike - at_spot, 0.0) + max(at_spot - call_strike, 0.0)
        return (credit - intrinsic) * multiplier

    return {
        **margin,
        "max_profit": credit * multiplier,
        "max_loss": None,
        "max_loss_label": "理论无限（认购侧）",
        "put_side_loss_at_zero": max(put_strike - credit, 0.0) * multiplier,
        "scenarios": [
            {
                "move_pct": move * 100,
                "spot": spot * (1 + move),
                "pnl": pnl(max(spot * (1 + move), 0.0)),
            }
            for move in scenario_moves
        ],
    }


def iron_condor_margin(
    short_put_k: float,
    long_put_k: float,
    short_call_k: float,
    long_call_k: float,
    short_put_prem: float,
    long_put_prem: float,
    short_call_prem: float,
    long_call_prem: float,
    multiplier: int = CONTRACT_MULT,
) -> dict:
    """
    铁鹰 = 认沽牛市价差 + 认购熊市价差。
    上交所两组合分别收保证金：行权价差 × 合约单位，合计为两侧宽度之和。
    到期最多一边穿仓，经济最大亏损 = max(两侧宽度)×乘数 − 净权利金。
    """
    if not (long_put_k < short_put_k < short_call_k < long_call_k):
        raise ValueError("iron condor strikes must be long_put < short_put < short_call < long_call")
    put_width = short_put_k - long_put_k
    call_width = long_call_k - short_call_k
    credit = short_put_prem + short_call_prem - long_put_prem - long_call_prem
    if credit <= 0:
        raise ValueError("iron condor net credit must be positive")
    premium = credit * multiplier
    margin = (put_width + call_width) * multiplier
    max_loss = max(put_width, call_width) * multiplier - premium
    yld = premium / margin if margin > 0 else 0.0
    return {
        "put_width": put_width,
        "call_width": call_width,
        "margin": margin,
        "premium": premium,
        "max_loss": max_loss,
        "yield": yld,
    }
