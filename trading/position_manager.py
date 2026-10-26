"""Mechanical management of open paper positions (credit and debit structures)."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from typing import Any

from .options_engine import days_to_expiration
from .types import ManagementAction, ManagementDecision, PositionState, StrategyKind


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


def manage_debit_position(
    position: PositionState,
    *,
    current_close_value: float,
    stop_loss_pct: float | None,
    force_close_at_dte: int,
    as_of: date | None = None,
) -> ManagementDecision:
    """Mechanical exits for long verticals / long options.

    ``position.entry_credit`` is the signed entry premium (negative debit) and
    ``position.profit_target_pct`` is the target return on debit paid, capped at
    max profit. Debit structures bleed extrinsic value near expiry, so the
    management DTE closes them regardless of P&L; there is no roll-for-credit.
    """
    if current_close_value < 0:
        raise ValueError("current_close_value must be non-negative")
    if position.entry_credit >= 0:
        raise ValueError("manage_debit_position needs a debit (negative entry_credit) position")

    debit = -position.entry_credit
    risk = debit * 100.0 * position.quantity
    dte = days_to_expiration(position.expiration, as_of=as_of)
    pnl = (current_close_value - debit) * 100.0 * position.quantity
    target = risk * position.profit_target_pct
    if position.max_profit:
        target = min(target, position.max_profit)
    pct_target = pnl / target if target > 0 else 0.0

    if pnl >= target:
        return ManagementDecision(ManagementAction.CLOSE_WINNER, f"Target reached: P&L ${pnl:.2f} >= ${target:.2f} ({position.profit_target_pct:.0%} of debit)", pnl, pct_target, dte)
    if stop_loss_pct is not None and pnl <= -risk * stop_loss_pct:
        return ManagementDecision(ManagementAction.CLOSE_STOP_LOSS, f"Stop: lost {-pnl / risk:.1%} of debit >= {stop_loss_pct:.0%}", pnl, pct_target, dte)
    if dte <= force_close_at_dte:
        return ManagementDecision(ManagementAction.CLOSE_BEFORE_EXPIRATION, f"DTE {dte} <= force-close {force_close_at_dte}", pnl, pct_target, dte)
    if dte <= position.manage_at_dte:
        return ManagementDecision(ManagementAction.CLOSE_AT_MANAGEMENT_DTE, f"DTE {dte} <= management {position.manage_at_dte}: exit before theta acceleration", pnl, pct_target, dte)
    return ManagementDecision(ManagementAction.HOLD, "No mechanical exit or management trigger", pnl, pct_target, dte)


def natural_close_value(
    legs: list[dict], quotes_by_symbol: dict[str, dict]
) -> float:
    """Signed conservative close premium per share: positive = credit received.

    Sell what was bought at the bid, buy back what was sold at the ask.
    """
    return -_natural_close_cost(legs, quotes_by_symbol)


def natural_close_debit(
    legs: list[dict], quotes_by_symbol: dict[str, dict]
) -> float:
    """Conservative close cost for credit structures, floored at zero."""
    return max(0.0, _natural_close_cost(legs, quotes_by_symbol))


def _natural_close_cost(
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
    return debit


def plan_position(
    row: dict[str, Any],
    quotes_by_symbol: dict[str, dict],
    cfg,
    *,
    as_of: date | None = None,
) -> tuple[ManagementDecision, float]:
    """Decide one open ledger row. Returns (decision, signed exit_debit per share).

    Management rules recorded on the candidate at entry (objective positions)
    win over the V1 config, so a position is managed by the rules it was
    approved under even if the strategy file changes later.
    """
    legs = json.loads(row["legs_json"])
    candidate = json.loads(row["candidate_json"] or "{}")
    mgmt = (candidate.get("analytics") or {}).get("management") or {}
    entry = float(row["entry_credit"])
    width = float(candidate.get("width") or 0.0)
    if not width and len(legs) >= 2:
        width = abs(float(legs[0]["strike"]) - float(legs[1]["strike"]))
    state = PositionState(
        row["id"],
        row["underlying"],
        StrategyKind(row["strategy"]),
        row["expiration"],
        row["entry_time"],
        entry,
        width,
        int(row["quantity"]),
        None if row["max_profit"] is None else float(row["max_profit"]),
        float(row["max_loss"]),
        float(row["profit_target_pct"]),
        int(row["manage_at_dte"]),
    )
    force_close = int(mgmt.get("force_close_at_dte", cfg.management.force_close_at_dte))
    if entry < 0:
        # A long structure is worth at least zero: it can always be left to expire.
        value = max(0.0, natural_close_value(legs, quotes_by_symbol))
        decision = manage_debit_position(
            state,
            current_close_value=value,
            stop_loss_pct=mgmt.get("stop_loss_pct"),
            force_close_at_dte=force_close,
            as_of=as_of,
        )
        return decision, -value
    debit = natural_close_debit(legs, quotes_by_symbol)
    credit_cfg = replace(cfg, management=replace(cfg.management, force_close_at_dte=force_close)) if mgmt else cfg
    return manage_credit_position(state, current_close_debit=debit, cfg=credit_cfg, as_of=as_of), debit
