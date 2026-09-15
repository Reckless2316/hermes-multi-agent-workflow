"""Post-approval exact-leg revalidation."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from .options_engine import scan_defined_risk
from .portfolio import SizingRejected, size_candidate
from .types import AccountSnapshot, SizedCandidate, SpreadCandidate


class RevalidationRejected(ValueError):
    pass


def _signature(candidate: SpreadCandidate) -> tuple[str, ...]:
    return tuple(sorted(leg.option_symbol for leg in candidate.legs))


@dataclass(frozen=True)
class RevalidationResult:
    approved: SizedCandidate
    fresh_market_candidate: SpreadCandidate
    current_natural_credit: float
    approved_limit_credit: float
    fill_credit: float
    reason: str

    def to_fill_candidate(self) -> SizedCandidate:
        """Record fresh quotes while retaining the human-approved credit limit."""
        fresh = self.fresh_market_candidate
        max_profit = self.fill_credit * 100.0
        max_loss = (fresh.width - self.fill_credit) * 100.0
        if max_loss <= 0:
            raise RevalidationRejected(
                "Approved fill credit makes max-loss math invalid"
            )
        target = max_profit * fresh.profit_target_pct
        filled = replace(
            fresh,
            net_credit=self.fill_credit,
            max_profit=max_profit,
            max_loss=max_loss,
            buying_power_reduction=max_loss,
            profit_target_dollars=target,
            capital_efficiency=target / max_loss,
            premium_to_bpr=max_profit / max_loss,
            reason=(
                fresh.reason
                + "; paper fill locked to human-approved credit limit"
            ),
        )
        quantity = self.approved.contracts
        return SizedCandidate(
            candidate=filled,
            contracts=quantity,
            risk_budget=self.approved.risk_budget,
            total_max_loss=max_loss * quantity,
            total_profit_target=target * quantity,
            total_buying_power_reduction=max_loss * quantity,
            sizing_reason=self.approved.sizing_reason,
        )


def revalidate_for_paper_fill(
    approved: SizedCandidate,
    fresh_chain,
    current_account: AccountSnapshot,
    cfg,
    *,
    as_of: date | None = None,
    committed_defined_risk: float = 0.0,
) -> RevalidationResult:
    """Revalidate the exact approved OCC structure, not its discovery rank."""
    signature = _signature(approved.candidate)
    required = set(signature)
    exact_chain = [contract for contract in fresh_chain if contract.symbol in required]
    if len(exact_chain) != len(signature):
        missing = sorted(required - {contract.symbol for contract in exact_chain})
        raise RevalidationRejected(f"Fresh chain missing approved legs: {missing}")

    fresh_candidates = scan_defined_risk(
        approved.candidate.underlying,
        exact_chain,
        cfg,
        as_of=as_of,
    )
    fresh = next(
        (candidate for candidate in fresh_candidates if _signature(candidate) == signature),
        None,
    )
    if fresh is None:
        raise RevalidationRejected(
            "Exact approved structure no longer passes deterministic gates"
        )

    approved_credit = approved.candidate.net_credit
    if fresh.net_credit + 1e-9 < approved_credit:
        raise RevalidationRejected(
            f"Natural credit deteriorated from {approved_credit:.2f} "
            f"to {fresh.net_credit:.2f}; do not chase"
        )

    try:
        still_sized = size_candidate(
            approved.candidate,
            current_account,
            cfg,
            committed_defined_risk=committed_defined_risk,
        )
    except SizingRejected as exc:
        raise RevalidationRejected(str(exc)) from exc

    if still_sized.contracts < approved.contracts:
        raise RevalidationRejected(
            f"Account now supports only {still_sized.contracts} contract(s), "
            f"approved {approved.contracts}; repropose"
        )

    return RevalidationResult(
        approved=approved,
        fresh_market_candidate=fresh,
        current_natural_credit=fresh.net_credit,
        approved_limit_credit=approved_credit,
        fill_credit=approved_credit,
        reason=(
            "Exact structure still passes; current natural credit "
            "meets/exceeds approved paper limit"
        ),
    )
