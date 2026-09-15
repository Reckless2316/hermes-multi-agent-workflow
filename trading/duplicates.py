"""Objective duplicate checks across deterministic paper and broker state."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .types import SpreadCandidate


def broker_has_exact_structure(
    candidate: SpreadCandidate,
    broker_positions: Iterable[dict[str, Any]],
) -> bool:
    """Return True only when all exact OCC legs are already open with matching signs.

    This deliberately does not infer how unrelated broker positions are grouped.
    It rejects only an objectively identical leg set.
    """
    quantities: dict[str, float] = defaultdict(float)
    for position in broker_positions:
        symbol = str(position.get("symbol") or "")
        try:
            quantity = float(position.get("quantity") or 0)
        except (TypeError, ValueError):
            quantity = 0.0
        if symbol:
            quantities[symbol] += quantity

    for leg in candidate.legs:
        actual = quantities.get(leg.option_symbol, 0.0)
        required = float(leg.quantity)
        if leg.side == "sell_to_open":
            if actual > -required:
                return False
        elif leg.side == "buy_to_open":
            if actual < required:
                return False
        else:
            return False
    return True
