"""Internally consistent synthetic option chains and price history for tests.

Mids, deltas, and IV come from Black-Scholes (zero rates), so the scanner's
gate math runs on prices that agree with their own Greeks.
"""
from __future__ import annotations

from datetime import date, timedelta
from math import exp, log, sqrt

from trading.pricing import norm_cdf
from trading.types import OptionContract


def bs(option_type: str, spot: float, strike: float, sigma: float, years: float) -> tuple[float, float]:
    sd = sigma * sqrt(years)
    d1 = (log(spot / strike) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    if option_type == "call":
        return spot * norm_cdf(d1) - strike * norm_cdf(d2), norm_cdf(d1)
    return strike * norm_cdf(-d2) - spot * norm_cdf(-d1), norm_cdf(d1) - 1.0


def occ(underlying: str, expiration: str, option_type: str, strike: float) -> str:
    stamp = date.fromisoformat(expiration).strftime("%y%m%d")
    return f"{underlying}{stamp}{option_type[0].upper()}{int(round(strike * 1000)):08d}"


def chain(
    *,
    underlying: str = "SPY",
    spot: float = 600.0,
    sigma: float = 0.20,
    as_of: date = date(2026, 9, 15),
    dte: int = 45,
    step: float = 5.0,
    span: float = 0.25,
    half_spread: float = 0.02,
    open_interest: int = 1000,
    volume: int = 200,
    skew: float = 0.0,
) -> tuple[str, list[OptionContract]]:
    """Return (expiration, contracts) for one expiry around ``spot``.

    ``skew`` > 0 adds equity-style skew: IV(K) = sigma * (1 + skew * ln(spot/K)),
    so OTM puts are richer and OTM calls cheaper than ATM.
    """
    expiration = (as_of + timedelta(days=dte)).isoformat()
    years = dte / 365.0
    lo = int(spot * (1 - span) // step) * step
    hi = int(spot * (1 + span) // step + 1) * step
    contracts: list[OptionContract] = []
    strike = lo
    while strike <= hi:
        iv = max(0.01, sigma * (1 + skew * log(spot / strike)))
        for option_type in ("call", "put"):
            mid, delta = bs(option_type, spot, strike, iv, years)
            if mid < 0.05:
                continue
            half = max(0.01, mid * half_spread)
            contracts.append(OptionContract(
                symbol=occ(underlying, expiration, option_type, strike),
                underlying=underlying,
                expiration=expiration,
                option_type=option_type,
                strike=float(strike),
                bid=round(mid - half, 2),
                ask=round(mid + half, 2),
                volume=volume,
                open_interest=open_interest,
                delta=delta,
                mid_iv=iv,
            ))
        strike += step
    return expiration, contracts


def history(
    *,
    start: float = 500.0,
    bars: int = 80,
    daily_drift: float = 0.0,
    daily_vol: float = 0.01,
    as_of: date = date(2026, 9, 15),
) -> list[dict]:
    """Deterministic alternating-shock daily closes in Tradier history row shape."""
    rows = []
    price = start
    for i in range(bars):
        shock = daily_vol if i % 2 == 0 else -daily_vol
        price *= exp(daily_drift + shock)
        rows.append({"date": (as_of - timedelta(days=bars - i)).isoformat(), "close": round(price, 4)})
    return rows
