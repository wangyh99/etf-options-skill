"""Black–Scholes implied volatility (pure stdlib)."""

from __future__ import annotations

import math
from typing import Literal

OptionType = Literal["C", "P"]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_price(
    spot: float,
    strike: float,
    t: float,
    r: float,
    sigma: float,
    option_type: OptionType,
    q: float = 0.0,
) -> float:
    if t <= 0 or sigma <= 0 or spot <= 0 or strike <= 0:
        intrinsic = max(spot - strike, 0.0) if option_type == "C" else max(strike - spot, 0.0)
        return intrinsic
    sqrt_t = math.sqrt(t)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    if option_type == "C":
        return spot * math.exp(-q * t) * _norm_cdf(d1) - strike * math.exp(-r * t) * _norm_cdf(d2)
    return strike * math.exp(-r * t) * _norm_cdf(-d2) - spot * math.exp(-q * t) * _norm_cdf(-d1)


def implied_vol(
    market_price: float,
    spot: float,
    strike: float,
    t: float,
    option_type: OptionType,
    r: float = 0.015,
    q: float = 0.0,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-6,
    max_iter: int = 80,
) -> float | None:
    """Solve IV by bisection. Returns None if unsolvable."""
    if market_price is None or market_price <= 0 or spot <= 0 or strike <= 0:
        return None
    if t <= 1e-8:
        return None
    disc = math.exp(-r * t)
    fwd_intrinsic = (
        max(spot * math.exp(-q * t) - strike * disc, 0.0)
        if option_type == "C"
        else max(strike * disc - spot * math.exp(-q * t), 0.0)
    )
    if market_price < fwd_intrinsic * 0.999:
        return None

    flo = bs_price(spot, strike, t, r, lo, option_type, q) - market_price
    fhi = bs_price(spot, strike, t, r, hi, option_type, q) - market_price
    if flo * fhi > 0:
        # widen upper bound once
        hi = 10.0
        fhi = bs_price(spot, strike, t, r, hi, option_type, q) - market_price
        if flo * fhi > 0:
            return None

    a, b = lo, hi
    for _ in range(max_iter):
        mid = 0.5 * (a + b)
        fmid = bs_price(spot, strike, t, r, mid, option_type, q) - market_price
        if abs(fmid) < tol:
            return mid
        if flo * fmid <= 0:
            b = mid
            fhi = fmid
        else:
            a = mid
            flo = fmid
    return 0.5 * (a + b)
