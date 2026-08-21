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
    return yield_pct > min_yield
