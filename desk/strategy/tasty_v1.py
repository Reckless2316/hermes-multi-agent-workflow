"""TASTY_DEFINED_RISK_V1 scanner.

Python authorizes TAKE/WAIT/SKIP. Hermes may only veto a TAKE.
Rank survivors by capital efficiency:

    expected_realized_profit / buying_power_reduction

where expected_realized_profit is max_profit * profit_target_pct (manage winners
early), not theoretical max profit and not headline POP.
"""
from __future__ import annotations

from datetime import date

from ..config import DeskConfig
from ..options.spreads import enumerate_spreads
from ..portfolio import PortfolioState, is_duplicate, size_and_risk
from ..types import MarketState, ScanResult, SetupStatus, Spread
from .gates import run_structure_gates

_V1_STRUCTURES = {"short_put_vertical", "short_call_vertical", "iron_condor"}


def capital_efficiency(spread: Spread, qty: int, profit_target_pct: float) -> float:
    bp = spread.buying_power * qty
    if bp <= 0:
        return 0.0
    expected = spread.max_profit * qty * (profit_target_pct / 100.0)
    return expected / bp


def _evaluate_spread(
    spread: Spread,
    cfg: DeskConfig,
    portfolio: PortfolioState,
) -> ScanResult:
    result = ScanResult(symbol=spread.underlying, spread=spread)
    if spread.structure not in _V1_STRUCTURES:
        result.status = SetupStatus.SKIP
        result.reason = f"{spread.structure} has no v1 constructor"
        return result
    passed, failure = run_structure_gates(spread, cfg)
    result.gates_passed = list(passed)
    if failure is not None:
        result.status = failure.status
        result.reason = f"{failure.name}: {failure.reason}"
        return result
    if is_duplicate(spread, portfolio):
        result.status = SetupStatus.SKIP
        result.reason = f"duplicate open {spread.structure} on {spread.underlying}"
        return result
    qty, status, reason = size_and_risk(spread, cfg, portfolio)
    if status != SetupStatus.TAKE:
        result.status = status
        result.reason = reason
        return result
    result.gates_passed.append("PORTFOLIO_OK")
    pct = cfg.profit_target_pct(spread.structure)
    result.qty = qty
    result.status = SetupStatus.TAKE
    result.reason = "All gates passed"
    result.management_dte = cfg.manage_at_dte
    result.profit_target = spread.max_profit * qty * (pct / 100.0)
    result.capital_efficiency = capital_efficiency(spread, qty, pct)
    return result


def scan_symbol(
    state: MarketState,
    symbol: str,
    cfg: DeskConfig,
    portfolio: PortfolioState | None = None,
) -> list[ScanResult]:
    portfolio = portfolio or PortfolioState(nav=cfg.nav)
    symbol = symbol.upper()
    results: list[ScanResult] = []
    for (sym, exp), chain in state.chains.items():
        if sym != symbol:
            continue
        spreads = enumerate_spreads(
            chain, exp, state.as_of, cfg.widths, cfg.allowed_structures,
            state.iv_rank.get(symbol),
        )
        for sp in spreads:
            results.append(_evaluate_spread(sp, cfg, portfolio))
    return results


def best_take(results: list[ScanResult]) -> ScanResult | None:
    takes = [r for r in results if r.status == SetupStatus.TAKE and r.capital_efficiency is not None]
    if not takes:
        return None
    takes.sort(key=lambda r: r.capital_efficiency or 0.0, reverse=True)
    return takes[0]


def scan_all(
    state: MarketState,
    cfg: DeskConfig,
    portfolio: PortfolioState | None = None,
) -> list[ScanResult]:
    portfolio = portfolio or PortfolioState(nav=cfg.nav)
    chosen: list[ScanResult] = []
    for symbol in cfg.universe:
        results = scan_symbol(state, symbol, cfg, portfolio)
        take = best_take(results)
        if take is not None:
            chosen.append(take)
            continue
        # Surface a WAIT if that's the most informative non-take; else skip noise.
        waits = [r for r in results if r.status == SetupStatus.WAIT]
        if waits:
            chosen.append(waits[0])
    return chosen
