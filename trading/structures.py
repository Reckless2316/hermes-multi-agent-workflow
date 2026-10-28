"""Per-structure economics shared by scanning, revalidation, and the paper ledger.

Premium is signed per share: positive = net credit received, negative = net
debit paid. Every supported structure has a finite max loss.
"""
from __future__ import annotations

from dataclasses import replace

from .types import (
    CREDIT_STRATEGIES,
    DEBIT_VERTICAL_STRATEGIES,
    LONG_OPTION_STRATEGIES,
    SpreadCandidate,
    StrategyKind,
)


class StructureEconomicsError(ValueError):
    pass


def economics(
    kind: StrategyKind,
    width: float,
    net_premium: float,
    strike: float | None = None,
) -> tuple[float | None, float]:
    """Return (max_profit, max_loss) in dollars per contract (100 multiplier).

    ``strike`` is required for a long put, whose profit is capped at the
    underlying going to zero: (strike - debit) * 100. A long call is unbounded.
    """
    if kind in CREDIT_STRATEGIES:
        if net_premium <= 0:
            raise StructureEconomicsError(f"{kind.value} requires a net credit, got {net_premium:.2f}")
        max_loss = (width - net_premium) * 100.0
        if max_loss <= 0:
            raise StructureEconomicsError(f"credit {net_premium:.2f} >= width {width:.2f}")
        return round(net_premium * 100.0, 2), round(max_loss, 2)
    debit = -net_premium
    if debit <= 0:
        raise StructureEconomicsError(f"{kind.value} requires a net debit, got credit {net_premium:.2f}")
    if kind in DEBIT_VERTICAL_STRATEGIES:
        max_profit = (width - debit) * 100.0
        if max_profit <= 0:
            raise StructureEconomicsError(f"debit {debit:.2f} >= width {width:.2f}")
        return round(max_profit, 2), round(debit * 100.0, 2)
    if kind == StrategyKind.LONG_PUT:
        if strike is None:
            raise StructureEconomicsError("long_put economics need the strike")
        max_profit = (strike - debit) * 100.0
        if max_profit <= 0:
            raise StructureEconomicsError(f"debit {debit:.2f} >= strike {strike:.2f}")
        return round(max_profit, 2), round(debit * 100.0, 2)
    if kind in LONG_OPTION_STRATEGIES:
        return None, round(debit * 100.0, 2)
    raise StructureEconomicsError(f"Unsupported strategy {kind.value}")


def profit_target_dollars(
    kind: StrategyKind,
    max_profit: float | None,
    max_loss: float,
    target_pct: float,
) -> float:
    """Credit: fraction of max profit. Debit: return on debit paid, capped at max profit."""
    if kind in CREDIT_STRATEGIES:
        assert max_profit is not None
        return max_profit * target_pct
    target = max_loss * target_pct
    return target if max_profit is None else min(target, max_profit)


def reprice(candidate: SpreadCandidate, net_premium: float) -> SpreadCandidate:
    """Recompute all premium-derived economics at a new signed fill premium."""
    strike = candidate.legs[0].strike if candidate.strategy in LONG_OPTION_STRATEGIES else None
    max_profit, max_loss = economics(candidate.strategy, candidate.width, net_premium, strike)
    target = profit_target_dollars(candidate.strategy, max_profit, max_loss, candidate.profit_target_pct)
    return replace(
        candidate,
        net_credit=net_premium,
        max_profit=max_profit,
        max_loss=max_loss,
        buying_power_reduction=max_loss,
        profit_target_dollars=target,
        capital_efficiency=target / max_loss,
        premium_to_bpr=None if max_profit is None else max_profit / max_loss,
    )
