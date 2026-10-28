"""Build, gate, and rank defined-risk structures for one point on the objective curve.

Credit structures reuse the V1 scanner (``options_engine``) through a
``StrategyConfig`` derived from the profile, so V1's gates are not duplicated.
Debit structures (long verticals, long calls/puts) are built here.

Every candidate then passes objective gates and is scored:

- ``POP_OK``          P(expiry P&L > 0) under the legs' market IV >= profile floor
- ``PAYOFF_MULTIPLE`` debit verticals: max profit / max loss >= profile floor
- ``BREAKEVEN_REACH`` debits: breakeven within ``max_breakeven_em`` expected moves

Score (higher is better) is a weighted sum of four normalized terms:

- capital efficiency: target-profit dollars / max loss, clipped to [0, 2] / 2
- POP under market IV
- payoff: P&L at a favorable 2-expected-move settle / max loss, clipped [0, 10] / 10
- model edge: E[P&L] under *realized* vol / max loss, clipped [-1, 1]

Model edge is the situation term: when realized vol exceeds implied, bought
premium has positive expectation under the realized-vol model and sold
premium negative, and vice versa. It is labelled as a model estimate,
not a forecast. With realized vol unavailable the term is zero and noted.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from math import isfinite
from typing import Iterable

from . import pricing
from .objectives import CREDIT_VALUES, ObjectiveConfig, ObjectiveProfile
from .options_engine import (
    _candidate_wings,
    _contract_liquid,
    _leg,
    build_iron_condors,
    choose_expiration,
    days_to_expiration,
    scan_credit_verticals,
)
from .regime import MarketSituation
from .structures import StructureEconomicsError, economics, profit_target_dollars, reprice
from .types import GateCheck, OptionContract, SetupStatus, SpreadCandidate, StrategyKind

# Gates added by ``evaluate``; they depend on premium and spot, so they are
# re-run (not inherited) whenever either changes.
OBJECTIVE_GATES = frozenset({"POP_OK", "PAYOFF_MULTIPLE", "BREAKEVEN_REACH"})

DEBIT_BUILDERS = {
    "long_call_vertical": ("call", True),
    "long_put_vertical": ("put", True),
    "long_call": ("call", False),
    "long_put": ("put", False),
}


def choose_objective_expiration(expirations: Iterable[str], cfg: ObjectiveConfig, profile: ObjectiveProfile, *, as_of: date | None = None) -> str | None:
    return choose_expiration(expirations, cfg.credit_strategy_config(profile, "neutral"), as_of=as_of)


def choose_reference_expiration(expirations: Iterable[str], target_dte: int, *, as_of: date | None = None) -> str | None:
    """Expiration nearest ``target_dte`` (>= 7 DTE) for the ATM IV reading."""
    best: tuple[int, int, str] | None = None
    for expiration in expirations:
        try:
            dte = days_to_expiration(expiration, as_of=as_of)
        except ValueError:
            continue
        if dte < 7:
            continue
        key = (abs(dte - target_dte), dte, expiration)
        if best is None or key < best:
            best = key
    return None if best is None else best[2]


def _long_delta_ok(contract: OptionContract, profile: ObjectiveProfile) -> tuple[bool, str]:
    if contract.delta is None or not isfinite(contract.delta):
        return False, "long-leg delta unavailable"
    delta = abs(contract.delta)
    band = profile.long_delta
    passed = band.minimum <= delta <= band.maximum
    return passed, f"|delta| {delta:.3f} {'inside' if passed else 'outside'} [{band.minimum:.3f}, {band.maximum:.3f}]"


def _debit_candidate(
    underlying: str,
    kind: StrategyKind,
    long: OptionContract,
    short: OptionContract | None,
    profile: ObjectiveProfile,
    cfg: ObjectiveConfig,
    *,
    as_of: date | None,
) -> SpreadCandidate | None:
    strategy_cfg = cfg.credit_strategy_config(profile, "neutral")
    dte = days_to_expiration(long.expiration, as_of=as_of)
    width = 0.0 if short is None else abs(short.strike - long.strike)
    natural_premium = round(-(long.ask - (0.0 if short is None else short.bid)), 4)
    mark_premium = round(-(long.mid - (0.0 if short is None else short.mid)), 4)

    gates = [GateCheck("DTE_OK", profile.dte_min <= dte <= profile.dte_max, f"DTE {dte} in [{profile.dte_min}, {profile.dte_max}]", dte)]
    passed, reason = _long_delta_ok(long, profile)
    gates.append(GateCheck("LONG_DELTA_OK", passed, reason, long.delta))
    passed, reason = _contract_liquid(long, strategy_cfg, short_leg=True)
    gates.append(GateCheck("LONG_LIQUID", passed, reason))
    if short is not None:
        passed, reason = _contract_liquid(short, strategy_cfg, short_leg=False)
        gates.append(GateCheck("SHORT_LIQUID", passed, reason))
        width_ok = cfg.width.minimum <= width <= cfg.width.maximum
        gates.append(GateCheck("WIDTH_OK", width_ok, f"width {width:.2f}", width))
    try:
        max_profit, max_loss = economics(kind, width, natural_premium, long.strike if short is None else None)
        defined = True
        detail = f"debit={-natural_premium:.2f}, max_loss={max_loss:.2f}"
    except StructureEconomicsError as exc:
        max_profit, max_loss, defined, detail = None, 0.0, False, str(exc)
    gates.append(GateCheck("DEFINED_RISK", defined, detail))
    if not all(g.passed for g in gates):
        return None

    target = profit_target_dollars(kind, max_profit, max_loss, profile.profit_target_pct)
    legs = [_leg(long, "buy_to_open")] + ([] if short is None else [_leg(short, "sell_to_open")])
    return SpreadCandidate(
        underlying=underlying,
        strategy=kind,
        expiration=long.expiration,
        dte=dte,
        direction="long" if long.option_type == "call" else "short",
        legs=legs,
        width=width,
        net_credit=natural_premium,
        mark_credit=mark_premium,
        max_profit=max_profit,
        max_loss=max_loss,
        buying_power_reduction=max_loss,
        profit_target_pct=profile.profit_target_pct,
        profit_target_dollars=target,
        manage_at_dte=profile.manage_at_dte,
        short_delta=None if short is None or short.delta is None else abs(short.delta),
        mid_iv=long.mid_iv,
        capital_efficiency=target / max_loss,
        premium_to_bpr=None if max_profit is None else max_profit / max_loss,
        status=SetupStatus.TAKE,
        gates=gates,
    )


def scan_debit_structures(
    underlying: str,
    chain: Iterable[OptionContract],
    structures: Iterable[str],
    profile: ObjectiveProfile,
    cfg: ObjectiveConfig,
    *,
    as_of: date | None = None,
) -> list[SpreadCandidate]:
    contracts = [c for c in chain if c.symbol and c.strike > 0]
    strategy_cfg = cfg.credit_strategy_config(profile, "neutral")
    results: list[SpreadCandidate] = []
    for name in structures:
        if name not in DEBIT_BUILDERS:
            continue
        option_type, vertical = DEBIT_BUILDERS[name]
        kind = StrategyKind(name)
        same_type = sorted((c for c in contracts if c.option_type == option_type), key=lambda c: c.strike)
        for long in same_type:
            if not _long_delta_ok(long, profile)[0]:
                continue
            # The sold leg sits further OTM: above for calls, below for puts,
            # the same orientation V1 uses to place a credit hedge.
            shorts = _candidate_wings(long, same_type, strategy_cfg) if vertical else [None]
            for short in shorts:
                candidate = _debit_candidate(underlying, kind, long, short, profile, cfg, as_of=as_of)
                if candidate is not None:
                    results.append(candidate)
    return results


def _sigma(candidate: SpreadCandidate, situation: MarketSituation) -> float | None:
    ivs = [c for c in (candidate.mid_iv,) if c is not None and c > 0]
    if ivs:
        return ivs[0]
    return situation.atm_iv if situation.atm_iv and situation.atm_iv > 0 else None


def _favorable_price(candidate: SpreadCandidate, spot: float, em: float) -> float:
    if candidate.direction == "long":
        return spot + 2.0 * em
    if candidate.direction == "short":
        return max(spot - 2.0 * em, 0.01)
    return spot


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def evaluate(
    candidate: SpreadCandidate,
    *,
    spot: float,
    situation: MarketSituation,
    profile: ObjectiveProfile,
) -> tuple[SpreadCandidate | None, str | None]:
    """Attach model analytics + objective gates.

    Returns ``(candidate, None)`` on success or ``(None, failed_gate_name)``.
    """
    legs = pricing.legs_from_candidate(candidate)
    premium = candidate.net_credit
    years = pricing.years_from_dte(candidate.dte)
    sigma = _sigma(candidate, situation)
    gates = list(candidate.gates)
    if sigma is None:
        return None, "POP_OK"

    pop = pricing.prob_profit(legs, premium, spot=spot, sigma=sigma, years=years)
    em = pricing.expected_move(spot, sigma, years)
    bes = pricing.breakevens(legs, premium)
    risk_per_share = candidate.max_loss / 100.0
    favorable = pricing.expiry_pnl(legs, premium, _favorable_price(candidate, spot, em))
    payoff_2em = favorable / risk_per_share
    rv = situation.realized_vol
    model_edge = None if rv is None or rv <= 0 else pricing.expected_pnl(legs, premium, spot=spot, sigma=rv, years=years) / risk_per_share

    gates.append(GateCheck("POP_OK", pop >= profile.min_pop, f"POP {pop:.1%} vs floor {profile.min_pop:.1%} (IV {sigma:.1%})", pop))
    if candidate.strategy.value in ("long_call_vertical", "long_put_vertical"):
        multiple = candidate.premium_to_bpr or 0.0
        gates.append(GateCheck("PAYOFF_MULTIPLE", multiple >= profile.min_payoff_multiple, f"max profit/max loss {multiple:.2f} vs floor {profile.min_payoff_multiple:.2f}", multiple))
    if candidate.is_debit:
        favorable_be = [b for b in bes if (b > spot if candidate.direction == "long" else b < spot)]
        distance = 0.0 if not favorable_be else min(abs(b - spot) for b in favorable_be)
        reach = distance / em if em > 0 else float("inf")
        gates.append(GateCheck("BREAKEVEN_REACH", reach <= profile.max_breakeven_em, f"breakeven {reach:.2f} expected moves away vs max {profile.max_breakeven_em:.2f}", reach))
    failed = next((g.name for g in gates if not g.passed), None)
    if failed is not None:
        return None, failed

    w = profile.weights
    components = {
        "capital_efficiency": w.capital_efficiency * _clip(candidate.capital_efficiency, 0.0, 2.0) / 2.0,
        "pop": w.pop * pop,
        "payoff": w.payoff * _clip(payoff_2em, 0.0, 10.0) / 10.0,
        "model_edge": 0.0 if model_edge is None else w.model_edge * _clip(model_edge, -1.0, 1.0),
    }
    score = sum(components.values()) / w.total()
    analytics = {
        "model": {
            "spot": spot,
            "sigma_iv": sigma,
            "pop_iv": pop,
            "expected_move": em,
            "breakevens": bes,
            "payoff_at_2em_per_risk": payoff_2em,
            "realized_vol": rv,
            "model_edge_rv": model_edge,
            "model_edge_note": "E[expiry P&L] under realized-vol lognormal / max loss; model estimate, not a forecast" if model_edge is not None else "realized vol unavailable; edge term zero",
        },
        "score": score,
        "score_components": components,
    }
    return replace(candidate, gates=gates, analytics={**candidate.analytics, **analytics}), None


def scan_objective(
    underlying: str,
    chain: Iterable[OptionContract],
    cfg: ObjectiveConfig,
    profile: ObjectiveProfile,
    *,
    spot: float,
    situation: MarketSituation,
    bias: str | None,
    as_of: date | None = None,
    context: dict | None = None,
    rejections: dict[str, int] | None = None,
) -> list[SpreadCandidate]:
    """All passing structures for ``profile`` and ``bias``, best score first."""
    chain = list(chain)
    menu = profile.menu(bias)
    raw: list[SpreadCandidate] = []
    credit_cfg = cfg.credit_strategy_config(profile, bias)
    if credit_cfg.allowed_strategies:
        verticals = scan_credit_verticals(underlying, chain, credit_cfg, as_of=as_of)
        raw.extend(c for c in verticals if c.strategy.value in credit_cfg.allowed_strategies)
        if "iron_condor" in credit_cfg.allowed_strategies:
            raw.extend(build_iron_condors(verticals, credit_cfg))
    raw.extend(scan_debit_structures(underlying, chain, (s for s in menu if s not in CREDIT_VALUES), profile, cfg, as_of=as_of))

    management = {
        "profit_target_pct": profile.profit_target_pct,
        "profit_target_basis": "max_profit",
        "stop_loss_pct": None,
        "manage_at_dte": profile.manage_at_dte,
        "force_close_at_dte": cfg.force_close_at_dte,
    }
    scored: list[SpreadCandidate] = []
    for candidate in raw:
        candidate = reprice(candidate, round(candidate.net_credit, 4))
        evaluated, failed = evaluate(candidate, spot=spot, situation=situation, profile=profile)
        if evaluated is None:
            if rejections is not None and failed:
                key = f"{candidate.strategy.value}:{failed}"
                rejections[key] = rejections.get(key, 0) + 1
            continue
        mgmt = dict(management)
        if evaluated.is_debit:
            mgmt.update(profit_target_basis="debit_paid", stop_loss_pct=profile.stop_loss_pct)
        analytics = {
            **evaluated.analytics,
            **(context or {}),
            "profile": profile.to_dict(),
            "situation": situation.to_dict(),
            "management": mgmt,
        }
        scored.append(replace(
            evaluated,
            objective=profile.objective,
            strategy_version=cfg.name,
            reason=f"All deterministic and {profile.objective} objective gates passed",
            analytics=analytics,
        ))

    scored.sort(key=lambda c: (c.analytics["score"], c.capital_efficiency, -c.max_loss), reverse=True)
    per_structure: dict[StrategyKind, int] = {}
    ranked: list[SpreadCandidate] = []
    for candidate in scored:
        count = per_structure.get(candidate.strategy, 0)
        if count < cfg.max_candidates_per_structure:
            per_structure[candidate.strategy] = count + 1
            ranked.append(candidate)
    return ranked
