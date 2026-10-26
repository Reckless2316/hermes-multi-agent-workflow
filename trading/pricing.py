"""Closed-form expiry analytics for multileg option structures.

All functions take legs as ``(side, option_type, strike, quantity)`` and a
signed per-share premium (positive = credit). Terminal price is modelled as
lognormal with zero drift and volatility ``sigma`` over ``years``. Rates and
dividends are ignored: this is a ranking/gating model, not a pricer, and
every number it emits is labelled with the sigma it was computed under.
"""
from __future__ import annotations

from math import erf, log, sqrt
from typing import Iterable, Sequence

Leg = tuple[str, str, float, int]

YEAR_DAYS = 365.0


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def years_from_dte(dte: int) -> float:
    # Expiring today still has a few hours; floor avoids a zero-variance model.
    return max(dte, 0.5) / YEAR_DAYS


def _sign(side: str) -> int:
    if side == "buy_to_open":
        return 1
    if side == "sell_to_open":
        return -1
    raise ValueError(f"Unsupported opening side {side!r}")


def _intrinsic(option_type: str, strike: float, price: float) -> float:
    if option_type == "call":
        return max(price - strike, 0.0)
    if option_type == "put":
        return max(strike - price, 0.0)
    raise ValueError(f"Unsupported option type {option_type!r}")


def expiry_pnl(legs: Sequence[Leg], net_premium: float, price: float) -> float:
    """Per-share P&L at expiration if the underlying settles at ``price``."""
    payoff = sum(_sign(side) * qty * _intrinsic(typ, strike, price) for side, typ, strike, qty in legs)
    return payoff + net_premium


def _slope_beyond(legs: Sequence[Leg]) -> float:
    """Per-share P&L slope as price -> infinity (only calls contribute)."""
    return float(sum(_sign(side) * qty for side, typ, _, qty in legs if typ == "call"))


def breakevens(legs: Sequence[Leg], net_premium: float) -> list[float]:
    """Exact breakevens of the piecewise-linear expiry P&L (sorted, positive)."""
    knots = sorted({0.0, *(strike for _, _, strike, _ in legs)})
    points: list[float] = []
    values = [expiry_pnl(legs, net_premium, k) for k in knots]
    for (x0, y0), (x1, y1) in zip(zip(knots, values), zip(knots[1:], values[1:])):
        if y0 == 0.0 and x0 > 0:
            points.append(x0)
        if (y0 < 0 < y1) or (y0 > 0 > y1):
            points.append(x0 + (x1 - x0) * (-y0) / (y1 - y0))
    last_x, last_y = knots[-1], values[-1]
    if last_y == 0.0 and last_x > 0:
        points.append(last_x)
    slope = _slope_beyond(legs)
    if slope != 0 and (last_y < 0 < slope or last_y > 0 > slope):
        points.append(last_x - last_y / slope)
    return sorted({round(p, 10) for p in points if p > 0})


def _lognormal_cdf(price: float, spot: float, sigma: float, years: float) -> float:
    if price <= 0:
        return 0.0
    sd = sigma * sqrt(years)
    return norm_cdf((log(price / spot) + 0.5 * sd * sd) / sd)


def prob_profit(
    legs: Sequence[Leg],
    net_premium: float,
    *,
    spot: float,
    sigma: float,
    years: float,
) -> float:
    """P(expiry P&L > 0) under the zero-drift lognormal model."""
    _require_model_inputs(spot, sigma, years)
    edges = [0.0, *breakevens(legs, net_premium), float("inf")]
    total = 0.0
    for lo, hi in zip(edges, edges[1:]):
        probe = (lo + hi) / 2.0 if hi != float("inf") else (lo * 2.0 + 1.0)
        if expiry_pnl(legs, net_premium, probe) > 0:
            upper = 1.0 if hi == float("inf") else _lognormal_cdf(hi, spot, sigma, years)
            total += upper - _lognormal_cdf(lo, spot, sigma, years)
    return min(max(total, 0.0), 1.0)


def _expected_intrinsic(option_type: str, strike: float, spot: float, sigma: float, years: float) -> float:
    sd = sigma * sqrt(years)
    d1 = (log(spot / strike) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    if option_type == "call":
        return spot * norm_cdf(d1) - strike * norm_cdf(d2)
    return strike * norm_cdf(-d2) - spot * norm_cdf(-d1)


def expected_pnl(
    legs: Sequence[Leg],
    net_premium: float,
    *,
    spot: float,
    sigma: float,
    years: float,
) -> float:
    """E[expiry P&L] per share under the zero-drift lognormal model."""
    _require_model_inputs(spot, sigma, years)
    payoff = sum(
        _sign(side) * qty * _expected_intrinsic(typ, strike, spot, sigma, years)
        for side, typ, strike, qty in legs
    )
    return payoff + net_premium


def expected_move(spot: float, sigma: float, years: float) -> float:
    """One-standard-deviation price move."""
    return spot * sigma * sqrt(years)


def prob_touch_price(target: float, *, spot: float, sigma: float, years: float) -> float:
    """Reflection-principle estimate of P(price touches ``target`` before expiry)."""
    _require_model_inputs(spot, sigma, years)
    if target <= 0:
        return 0.0
    sd = sigma * sqrt(years)
    distance = abs(log(target / spot))
    return min(1.0, 2.0 * (1.0 - norm_cdf(distance / sd)))


def legs_from_candidate(candidate) -> list[Leg]:
    return [(leg.side, leg.option_type, float(leg.strike), int(leg.quantity)) for leg in candidate.legs]


def _require_model_inputs(spot: float, sigma: float, years: float) -> None:
    if not (spot > 0 and sigma > 0 and years > 0):
        raise ValueError(f"Model needs positive spot/sigma/years, got {spot}, {sigma}, {years}")


def mean(values: Iterable[float]) -> float | None:
    data = list(values)
    return sum(data) / len(data) if data else None


__all__ = [
    "Leg",
    "breakevens",
    "expected_move",
    "expected_pnl",
    "expiry_pnl",
    "legs_from_candidate",
    "mean",
    "norm_cdf",
    "prob_profit",
    "prob_touch_price",
    "years_from_dte",
]
