"""Mechanical management of open paper credit positions."""
from __future__ import annotations

from datetime import date

from .options_engine import days_to_expiration
from .types import ManagementAction, ManagementDecision, PositionState


def manage_credit_position(
    position: PositionState,
    *,
    current_close_debit: float,
    cfg,
    as_of: date | None = None,
) -> ManagementDecision:
    if current_close_debit < 0:
        raise ValueError("current_close_debit must be non-negative")

    dte = days_to_expiration(position.expiration, as_of=as_of)
    pnl = (
        (position.entry_credit - current_close_debit)
        * 100.0
        * position.quantity
    )
    max_profit = position.entry_credit * 100.0 * position.quantity
    pct_max_profit = pnl / max_profit if max_profit > 0 else 0.0

    if pct_max_profit >= position.profit_target_pct:
        return ManagementDecision(
            ManagementAction.CLOSE_WINNER,
            f"Profit target reached: {pct_max_profit:.1%} "
            f">= {position.profit_target_pct:.1%}",
            pnl,
            pct_max_profit,
            dte,
        )

    if dte <= cfg.management.force_close_at_dte:
        return ManagementDecision(
            ManagementAction.CLOSE_BEFORE_EXPIRATION,
            f"DTE {dte} <= force-close {cfg.management.force_close_at_dte}",
            pnl,
            pct_max_profit,
            dte,
        )

    if dte <= position.manage_at_dte:
        if pnl <= 0:
            return ManagementDecision(
                ManagementAction.REVIEW_ROLL_FOR_CREDIT,
                "At/inside management DTE and not profitable; only consider "
                "a roll if verified for net credit",
                pnl,
                pct_max_profit,
                dte,
            )
        if cfg.management.close_partial_winner_at_manage_dte:
            return ManagementDecision(
                ManagementAction.CLOSE_AT_MANAGEMENT_DTE,
                "At/inside management DTE with a profit; close under "
                "configured early-management rule",
                pnl,
                pct_max_profit,
                dte,
            )
        return ManagementDecision(
            ManagementAction.REVIEW_AT_MANAGEMENT_DTE,
            "At/inside management DTE with partial winner; review",
            pnl,
            pct_max_profit,
            dte,
        )

    return ManagementDecision(
        ManagementAction.HOLD,
        "No mechanical exit or management trigger",
        pnl,
        pct_max_profit,
        dte,
    )


def natural_close_debit(
    legs: list[dict], quotes_by_symbol: dict[str, dict]
) -> float:
    """Conservative close: buy original shorts at ask, sell hedges at bid."""
    debit = 0.0
    for leg in legs:
        symbol = str(leg["option_symbol"])
        quote = quotes_by_symbol.get(symbol)
        if quote is None:
            raise ValueError(f"Missing live quote for {symbol}")
        bid = float(quote.get("bid") or 0)
        ask = float(quote.get("ask") or 0)
        if bid < 0 or ask <= 0 or ask < bid:
            raise ValueError(
                f"Invalid live quote for {symbol}: bid={bid}, ask={ask}"
            )
        quantity = int(leg.get("quantity", 1))
        side = str(leg["side"])
        if side == "sell_to_open":
            debit += ask * quantity
        elif side == "buy_to_open":
            debit -= bid * quantity
        else:
            raise ValueError(f"Unsupported opening side {side!r}")
    return max(0.0, debit)
