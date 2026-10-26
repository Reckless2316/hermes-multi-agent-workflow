"""Post-approval exact-leg revalidation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable

from .options_engine import scan_defined_risk
from .portfolio import SizingRejected, size_candidate
from .structures import StructureEconomicsError, reprice
from .types import AccountSnapshot, OptionContract, SizedCandidate, SpreadCandidate

# (underlying, exact-leg chain, cfg, as_of) -> candidates passing all gates
Rescan = Callable[[str, list[OptionContract], object, "date | None"], Iterable[SpreadCandidate]]


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
        """Record fresh quotes while retaining the human-approved premium limit."""
        try:
            filled = reprice(self.fresh_market_candidate, self.fill_credit)
        except StructureEconomicsError as exc:
            raise RevalidationRejected(
                f"Approved fill premium makes max-loss math invalid: {exc}"
            ) from exc
        filled.reason = (
            self.fresh_market_candidate.reason
            + "; paper fill locked to human-approved premium limit"
        )
        max_loss = filled.max_loss
        target = filled.profit_target_dollars
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
    rescan: Rescan | None = None,
) -> RevalidationResult:
    """Revalidate the exact approved OCC structure, not its discovery rank.

    ``rescan`` rebuilds candidates from the exact-leg chain; it defaults to the
    V1 credit scanner. Objective candidates pass a closure over their stored
    profile so their own objective gates are re-run on fresh quotes.

    Premium is signed (credit positive, debit negative), so a lower fresh
    natural premium is always worse: less credit or more debit. Never chase.
    """
    signature = _signature(approved.candidate)
    required = set(signature)
    exact_chain = [contract for contract in fresh_chain if contract.symbol in required]
    if len(exact_chain) != len(signature):
        missing = sorted(required - {contract.symbol for contract in exact_chain})
        raise RevalidationRejected(f"Fresh chain missing approved legs: {missing}")

    if rescan is None:
        fresh_candidates = scan_defined_risk(
            approved.candidate.underlying,
            exact_chain,
            cfg,
            as_of=as_of,
        )
    else:
        fresh_candidates = list(rescan(approved.candidate.underlying, exact_chain, cfg, as_of))
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
            f"Natural {'debit' if approved.candidate.is_debit else 'credit'} "
            f"deteriorated from {abs(approved_credit):.2f} "
            f"to {abs(fresh.net_credit):.2f}; do not chase"
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
            "Exact structure still passes; current natural premium "
            "meets/beats approved paper limit"
        ),
    )
