"""Deterministic market-situation model: trend, realized vol, implied vol.

Inputs are provider data only (Tradier daily history + option chain). Every
classification records the numbers it came from. Nothing here is a forecast;
it decides which objective/structure family has a structural reason to exist.

- Realized vol: close-to-close log-return stdev, annualized with sqrt(252).
- ATM IV: mean of call/put ``mid_iv`` at the strike nearest spot.
- IV/RV ratio: > rich threshold favours premium selling; < cheap favours buying.
- Trend: price vs fast/slow SMA plus a momentum z-score
  (lookback log return divided by the realized-vol-implied stdev over the
  same horizon). |z| >= strong threshold is a strong trend.

This is not IV Rank. IV Rank needs a year of IV history which Tradier does
not supply; it stays unavailable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from math import log, sqrt
from typing import Any, Iterable, Sequence

from .types import OptionContract

TRADING_DAYS = 252.0


@dataclass(frozen=True)
class RegimeRules:
    rv_window: int = 20
    sma_fast: int = 20
    sma_slow: int = 50
    momentum_lookback: int = 20
    trend_z: float = 0.5
    strong_trend_z: float = 1.25
    iv_rich_ratio: float = 1.15
    iv_cheap_ratio: float = 0.90

    def validate(self) -> list[str]:
        errors = []
        if not (2 <= self.rv_window and 1 <= self.sma_fast < self.sma_slow and self.momentum_lookback >= 1):
            errors.append("regime windows must satisfy rv_window>=2, 1<=sma_fast<sma_slow, momentum_lookback>=1")
        if not (0 <= self.trend_z <= self.strong_trend_z):
            errors.append("regime requires 0 <= trend_z <= strong_trend_z")
        if not (0 < self.iv_cheap_ratio < self.iv_rich_ratio):
            errors.append("regime requires 0 < iv_cheap_ratio < iv_rich_ratio")
        return errors

    @property
    def min_history(self) -> int:
        return max(self.rv_window + 1, self.sma_slow, self.momentum_lookback + 1)


@dataclass(frozen=True)
class MarketSituation:
    symbol: str
    spot: float
    as_of: str
    history_bars: int
    realized_vol: float | None
    atm_iv: float | None
    iv_rv_ratio: float | None
    vol_regime: str  # rich | fair | cheap | unknown
    trend: str  # bullish | bearish | neutral | unknown
    trend_strength: str  # strong | moderate | none | unknown
    momentum_z: float | None
    sma_fast: float | None
    sma_slow: float | None
    notes: list[str] = field(default_factory=list)

    @property
    def known(self) -> bool:
        return self.vol_regime != "unknown" and self.trend != "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def closes_from_history(rows: Iterable[dict[str, Any]]) -> list[float]:
    """Extract positive closes from Tradier ``/markets/history`` rows, oldest first."""
    dated: list[tuple[str, float]] = []
    for row in rows:
        try:
            close = float(row.get("close"))
        except (TypeError, ValueError):
            continue
        if close > 0:
            dated.append((str(row.get("date") or ""), close))
    dated.sort(key=lambda pair: pair[0])
    return [close for _, close in dated]


def realized_vol(closes: Sequence[float], window: int) -> float | None:
    if len(closes) < window + 1:
        return None
    tail = closes[-(window + 1):]
    returns = [log(b / a) for a, b in zip(tail, tail[1:])]
    mu = sum(returns) / len(returns)
    var = sum((r - mu) ** 2 for r in returns) / (len(returns) - 1)
    return sqrt(var) * sqrt(TRADING_DAYS)


def sma(values: Sequence[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def atm_iv(chain: Iterable[OptionContract], spot: float) -> float | None:
    usable = [c for c in chain if c.mid_iv is not None and c.mid_iv > 0 and c.strike > 0]
    if not usable or spot <= 0:
        return None
    nearest = min(abs(c.strike - spot) for c in usable)
    ivs = [float(c.mid_iv) for c in usable if abs(c.strike - spot) == nearest]
    return sum(ivs) / len(ivs)


def classify(
    symbol: str,
    *,
    spot: float,
    closes: Sequence[float],
    chain: Iterable[OptionContract],
    rules: RegimeRules,
    as_of: date | None = None,
) -> MarketSituation:
    notes: list[str] = []
    rv = realized_vol(closes, rules.rv_window)
    iv = atm_iv(chain, spot)
    fast = sma(closes, rules.sma_fast)
    slow = sma(closes, rules.sma_slow)

    ratio = None if rv is None or iv is None or rv <= 0 else iv / rv
    if ratio is None:
        vol_regime = "unknown"
        if rv is None:
            notes.append(f"realized vol needs {rules.rv_window + 1} closes; have {len(closes)}")
        if iv is None:
            notes.append("no usable ATM mid_iv in chain")
    elif ratio >= rules.iv_rich_ratio:
        vol_regime = "rich"
    elif ratio <= rules.iv_cheap_ratio:
        vol_regime = "cheap"
    else:
        vol_regime = "fair"

    z = None
    if rv is not None and rv > 0 and len(closes) > rules.momentum_lookback:
        horizon_sd = rv * sqrt(rules.momentum_lookback / TRADING_DAYS)
        z = log(closes[-1] / closes[-1 - rules.momentum_lookback]) / horizon_sd

    if z is None or fast is None or slow is None:
        trend, strength = "unknown", "unknown"
        notes.append(f"trend needs {rules.min_history} closes; have {len(closes)}")
    else:
        last = closes[-1]
        if z >= rules.trend_z and last > fast > slow:
            trend = "bullish"
        elif z <= -rules.trend_z and last < fast < slow:
            trend = "bearish"
        else:
            trend = "neutral"
        if trend == "neutral":
            strength = "none"
        else:
            strength = "strong" if abs(z) >= rules.strong_trend_z else "moderate"

    return MarketSituation(
        symbol=symbol,
        spot=spot,
        as_of=(as_of or date.today()).isoformat(),
        history_bars=len(closes),
        realized_vol=rv,
        atm_iv=iv,
        iv_rv_ratio=ratio,
        vol_regime=vol_regime,
        trend=trend,
        trend_strength=strength,
        momentum_z=z,
        sma_fast=fast,
        sma_slow=slow,
        notes=notes,
    )
