"""End-to-end objective scan: situation -> dial -> structures -> sizing -> dedup.

Kept free of argparse/file I/O so it can run against any client with the
read-only TradierClient surface (quotes, history, option_expirations,
option_chain, balances, positions).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .duplicates import broker_has_exact_structure
from .objective_engine import choose_objective_expiration, choose_reference_expiration, scan_objective
from .objectives import ObjectiveConfig, ObjectiveDecision, ObjectiveProfile, decide, with_risk_override
from .portfolio import SizingRejected, size_candidate
from .regime import MarketSituation, classify, closes_from_history
from .tradier import TradierError
from .types import AccountSnapshot, OptionContract, SizedCandidate, SpreadCandidate


@dataclass
class SymbolScan:
    symbol: str
    situation: MarketSituation | None = None
    decision: ObjectiveDecision | None = None
    expiration: str | None = None
    rejections: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "situation": None if self.situation is None else self.situation.to_dict(),
            "decision": None if self.decision is None else self.decision.to_dict(),
            "expiration": self.expiration,
            "objective_gate_rejections": dict(sorted(self.rejections.items())),
        }


@dataclass
class ScanOutput:
    sized: list[SizedCandidate]
    diagnostics: list[dict[str, Any]]
    symbols: list[SymbolScan]
    account: AccountSnapshot


def spot_from_quote(quote: dict[str, Any]) -> float | None:
    """Last trade, else a valid two-sided midpoint. Never a stale prevclose."""
    def num(key: str) -> float | None:
        try:
            value = float(quote.get(key))
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    last = num("last")
    if last:
        return last
    bid, ask = num("bid"), num("ask")
    if bid and ask and ask >= bid:
        return (bid + ask) / 2.0
    return None


def candidate_sort_key(item: SizedCandidate) -> tuple[float, float, float]:
    c = item.candidate
    return (float(c.analytics.get("score", 0.0)), c.capital_efficiency, item.total_profit_target)


def _history_start(cfg: ObjectiveConfig, as_of: date) -> str:
    # Calendar days covering the trading bars the regime needs, plus holidays.
    return (as_of - timedelta(days=int(cfg.regime.min_history * 1.6) + 10)).isoformat()


def scan_symbol(
    client,
    symbol: str,
    cfg: ObjectiveConfig,
    *,
    objective: str,
    aggression: float | None,
    bias: str,
    max_aggression: float | None,
    risk_override: float | None,
    as_of: date,
) -> tuple[list[SpreadCandidate], ObjectiveProfile | None, SymbolScan, list[dict[str, Any]]]:
    record = SymbolScan(symbol)
    diagnostics: list[dict[str, Any]] = []
    quotes = client.quotes([symbol])
    spot = spot_from_quote(quotes[0]) if quotes else None
    if spot is None:
        diagnostics.append({"symbol": symbol, "status": "NO_SETUP", "reason": "no live underlying price"})
        return [], None, record, diagnostics

    closes = closes_from_history(client.history(symbol, interval="daily", start=_history_start(cfg, as_of), end=as_of.isoformat()))
    expirations = client.option_expirations(symbol)
    reference = choose_reference_expiration(expirations, cfg.iv_reference_dte, as_of=as_of)
    chains: dict[str, list[OptionContract]] = {}
    if reference:
        chains[reference] = client.option_chain(symbol, reference, greeks=True)
    situation = classify(symbol, spot=spot, closes=closes, chain=chains.get(reference, []), rules=cfg.regime, as_of=as_of)
    record.situation = situation

    decision = decide(cfg, situation, objective=objective, aggression=aggression, bias=bias, max_aggression=max_aggression)
    record.decision = decision
    if decision.profile is None:
        diagnostics.append({"symbol": symbol, "status": "NO_SETUP", "reason": decision.reason})
        return [], None, record, diagnostics

    profile = with_risk_override(decision.profile, risk_override)
    if not profile.menu(decision.bias):
        diagnostics.append({"symbol": symbol, "status": "NO_SETUP", "reason": f"{profile.objective} has no structures for bias {decision.bias or 'unknown'}"})
        return [], profile, record, diagnostics

    expiration = choose_objective_expiration(expirations, cfg, profile, as_of=as_of)
    record.expiration = expiration
    if not expiration:
        diagnostics.append({"symbol": symbol, "status": "NO_SETUP", "reason": f"no expiration in {profile.dte_min}-{profile.dte_max} DTE"})
        return [], profile, record, diagnostics
    if expiration not in chains:
        chains[expiration] = client.option_chain(symbol, expiration, greeks=True)

    context = {"objective_decision": decision.to_dict()}
    candidates = scan_objective(
        symbol,
        chains[expiration],
        cfg,
        profile,
        spot=spot,
        situation=situation,
        bias=decision.bias,
        as_of=as_of,
        context=context,
        rejections=record.rejections,
    )
    if not candidates:
        diagnostics.append({"symbol": symbol, "status": "NO_SETUP", "reason": "no structure passed deterministic and objective gates", "objective_gate_rejections": dict(record.rejections)})
    return candidates, profile, record, diagnostics


def run_objective_scan(
    client,
    cfg: ObjectiveConfig,
    symbols: tuple[str, ...],
    *,
    objective: str = "auto",
    aggression: float | None = None,
    bias: str = "auto",
    max_aggression: float | None = None,
    risk_override: float | None = None,
    max_per_symbol: int = 3,
    ledger=None,
    as_of: date | None = None,
) -> ScanOutput:
    as_of = as_of or date.today()
    account = client.balances()
    broker_positions = client.positions()
    committed = 0.0 if ledger is None else ledger.committed_defined_risk()
    sized: list[SizedCandidate] = []
    diagnostics: list[dict[str, Any]] = []
    records: list[SymbolScan] = []

    for symbol in symbols:
        try:
            candidates, profile, record, notes = scan_symbol(
                client, symbol, cfg,
                objective=objective, aggression=aggression, bias=bias,
                max_aggression=max_aggression, risk_override=risk_override, as_of=as_of,
            )
        except TradierError as exc:  # provider failure for one symbol must not end the sweep
            diagnostics.append({"symbol": symbol, "status": "ERROR", "reason": str(exc)})
            records.append(SymbolScan(symbol))
            continue
        records.append(record)
        diagnostics.extend(notes)
        if profile is None:
            continue
        sizing_cfg = cfg.credit_strategy_config(profile, record.decision.bias if record.decision else None)
        kept = 0
        for candidate in candidates:
            if kept >= max_per_symbol:
                break
            if broker_has_exact_structure(candidate, broker_positions):
                diagnostics.append({"symbol": symbol, "strategy": candidate.strategy.value, "status": "SKIP", "reason": "exact OCC structure already open in Tradier account"})
                continue
            try:
                item = size_candidate(candidate, account, sizing_cfg, committed_defined_risk=committed)
            except SizingRejected as exc:
                diagnostics.append({"symbol": symbol, "strategy": candidate.strategy.value, "status": "SKIP", "reason": str(exc)})
                continue
            if ledger is not None and ledger.is_duplicate_open(item):
                diagnostics.append({"symbol": symbol, "strategy": candidate.strategy.value, "status": "SKIP", "reason": "duplicate exact structure already open in paper ledger"})
                continue
            sized.append(item)
            kept += 1

    sized.sort(key=candidate_sort_key, reverse=True)
    return ScanOutput(sized=sized, diagnostics=diagnostics, symbols=records, account=account)


def sidecar_payload(output: ScanOutput, *, captured_at: str, cfg: ObjectiveConfig, request: dict[str, Any], rate_limit: dict | None = None) -> dict[str, Any]:
    from .intake import candidate_id

    return {
        "captured_at": captured_at,
        "strategy": cfg.name,
        "request": request,
        "account": {
            "account_type": output.account.account_type,
            "total_equity": output.account.total_equity,
            "option_buying_power": output.account.option_buying_power,
            "pending_orders_count": output.account.pending_orders_count,
        },
        "symbols": [record.to_dict() for record in output.symbols],
        "candidate_count": len(output.sized),
        "candidates": [
            {
                "candidate_id": candidate_id(item),
                **item.candidate.to_dict(),
                "contracts": item.contracts,
                "risk_budget": item.risk_budget,
                "sizing_reason": item.sizing_reason,
                "total_max_loss": item.total_max_loss,
                "total_profit_target": item.total_profit_target,
                "total_buying_power_reduction": item.total_buying_power_reduction,
            }
            for item in output.sized
        ],
        "diagnostics": output.diagnostics,
        "rate_limit": rate_limit or {},
    }


def is_objective_candidate(candidate: SpreadCandidate, cfg: ObjectiveConfig) -> bool:
    return candidate.strategy_version == cfg.name and bool(candidate.analytics.get("profile"))


def revalidation_context(cfg: ObjectiveConfig, approved: SpreadCandidate, *, spot: float):
    """Rebuild the approved candidate's profile/bias/situation for exact-leg recheck.

    Returns ``(rescan, sizing_cfg)`` for ``revalidate_for_paper_fill``. The
    stored situation supplies realized vol for scoring only; hard gates (POP,
    breakeven reach, liquidity, delta) are re-run on the fresh spot and chain.
    """
    stored = approved.analytics
    profile = cfg.profile_at(float(stored["profile"]["aggression"]))
    profile = with_risk_override(profile, min(profile.risk_per_trade_pct, float(stored["profile"]["risk_per_trade_pct"])))
    bias = (stored.get("objective_decision") or {}).get("bias")
    situation_raw = dict(stored.get("situation") or {})
    situation_raw["spot"] = spot
    situation = MarketSituation(**situation_raw)
    sizing_cfg = cfg.credit_strategy_config(profile, bias)

    def rescan(underlying, exact_chain, _cfg, as_of):
        return scan_objective(underlying, exact_chain, cfg, profile, spot=spot, situation=situation, bias=bias, as_of=as_of, context={"objective_decision": stored.get("objective_decision", {})})

    return rescan, sizing_cfg
