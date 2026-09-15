"""Deterministic account-aware position sizing for defined-risk candidates."""
from __future__ import annotations

from math import floor

from .types import AccountSnapshot, SizedCandidate, SpreadCandidate


class SizingRejected(ValueError):
    pass


def size_candidate(
    candidate: SpreadCandidate,
    account: AccountSnapshot,
    cfg,
    *,
    committed_defined_risk: float = 0.0,
    correlated_defined_risk: float = 0.0,
) -> SizedCandidate:
    if account.total_equity <= 0:
        raise SizingRejected("Account equity must be positive")
    if candidate.max_loss <= 0 or candidate.buying_power_reduction <= 0:
        raise SizingRejected("Candidate max loss/BPR must be positive")

    risk_budget = account.total_equity * cfg.risk.risk_per_trade_pct
    by_risk = floor(risk_budget / candidate.max_loss)
    by_buying_power = floor(
        account.option_buying_power / candidate.buying_power_reduction
    )
    contracts = min(
        by_risk,
        by_buying_power,
        cfg.risk.max_contracts_per_trade,
    )

    if cfg.risk.max_total_defined_risk_pct is not None:
        cap = account.total_equity * cfg.risk.max_total_defined_risk_pct
        remaining = max(0.0, cap - committed_defined_risk)
        contracts = min(contracts, floor(remaining / candidate.max_loss))

    if cfg.risk.max_correlated_defined_risk_pct is not None:
        cap = account.total_equity * cfg.risk.max_correlated_defined_risk_pct
        remaining = max(0.0, cap - correlated_defined_risk)
        contracts = min(contracts, floor(remaining / candidate.max_loss))

    if contracts < 1:
        raise SizingRejected(
            "No contract fits configured risk budget and current option buying power"
        )

    return SizedCandidate(
        candidate=candidate,
        contracts=contracts,
        risk_budget=risk_budget,
        total_max_loss=candidate.max_loss * contracts,
        total_profit_target=candidate.profit_target_dollars * contracts,
        total_buying_power_reduction=candidate.buying_power_reduction * contracts,
        sizing_reason=(
            f"{contracts} contract(s): risk budget ${risk_budget:.2f}, "
            f"per-contract max loss ${candidate.max_loss:.2f}, "
            f"option BP ${account.option_buying_power:.2f}"
        ),
    )
