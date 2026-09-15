"""Deterministic construction and hard-gating of defined-risk options trades."""
from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Iterable

from .config import StrategyConfig
from .types import (
    GateCheck,
    OptionContract,
    OptionLeg,
    SetupStatus,
    SpreadCandidate,
    StrategyKind,
)


def days_to_expiration(expiration: str, *, as_of: date | None = None) -> int:
    return (date.fromisoformat(expiration) - (as_of or date.today())).days


def choose_expiration(
    expirations: Iterable[str],
    cfg: StrategyConfig,
    *,
    as_of: date | None = None,
) -> str | None:
    """Choose the expiration nearest the configured target inside the DTE window."""
    today = as_of or date.today()
    valid: list[tuple[int, str]] = []
    for expiration in expirations:
        try:
            dte = days_to_expiration(expiration, as_of=today)
        except ValueError:
            continue
        if cfg.entry.dte_min <= dte <= cfg.entry.dte_max:
            valid.append((dte, expiration))
    if not valid:
        return None
    valid.sort(key=lambda pair: (abs(pair[0] - cfg.entry.dte_target), pair[0]))
    return valid[0][1]


def _leg(contract: OptionContract, side: str) -> OptionLeg:
    return OptionLeg(
        option_symbol=contract.symbol,
        side=side,
        quantity=1,
        option_type=contract.option_type,
        strike=contract.strike,
        expiration=contract.expiration,
        bid=contract.bid,
        ask=contract.ask,
        mid=contract.mid,
        delta=contract.delta,
        open_interest=contract.open_interest,
        volume=contract.volume,
    )


def _contract_liquid(
    contract: OptionContract,
    cfg: StrategyConfig,
    *,
    short_leg: bool,
) -> tuple[bool, str]:
    rules = cfg.entry.liquidity
    if rules.require_two_sided_market and (
        contract.bid <= 0 or contract.ask <= 0 or contract.ask < contract.bid
    ):
        return False, "missing/invalid two-sided market"
    spread_pct = contract.bid_ask_pct_mid
    if spread_pct is None:
        return False, "no usable midpoint"
    if spread_pct > rules.max_bid_ask_pct_mid:
        return (
            False,
            f"bid/ask {spread_pct:.1%} > configured {rules.max_bid_ask_pct_mid:.1%}",
        )
    if contract.open_interest < rules.min_open_interest:
        return False, f"OI {contract.open_interest} < {rules.min_open_interest}"
    if short_leg and contract.volume < rules.min_volume:
        return False, f"volume {contract.volume} < {rules.min_volume}"
    return True, "liquidity checks passed"


def _short_delta_ok(
    contract: OptionContract, cfg: StrategyConfig
) -> tuple[bool, str]:
    if contract.delta is None or not isfinite(contract.delta):
        return False, "short-leg delta unavailable"
    delta = abs(contract.delta)
    rules = cfg.entry.delta
    passed = rules.minimum <= delta <= rules.maximum
    return (
        passed,
        f"|delta| {delta:.3f} "
        f"{'inside' if passed else 'outside'} "
        f"[{rules.minimum:.3f}, {rules.maximum:.3f}]",
    )


def _candidate_wings(
    short: OptionContract,
    same_type: list[OptionContract],
    cfg: StrategyConfig,
) -> list[OptionContract]:
    """Pick the nearest listed wing for each configured preferred width."""
    results: list[OptionContract] = []
    seen_symbols: set[str] = set()
    for preferred_width in cfg.entry.width.preferred:
        if not cfg.entry.width.minimum <= preferred_width <= cfg.entry.width.maximum:
            continue
        target = (
            short.strike - preferred_width
            if short.option_type == "put"
            else short.strike + preferred_width
        )
        eligible = [
            contract
            for contract in same_type
            if (
                contract.strike < short.strike
                if short.option_type == "put"
                else contract.strike > short.strike
            )
            and cfg.entry.width.minimum
            <= abs(short.strike - contract.strike)
            <= cfg.entry.width.maximum
        ]
        if not eligible:
            continue
        wing = min(eligible, key=lambda contract: abs(contract.strike - target))
        actual_width = abs(short.strike - wing.strike)
        if abs(actual_width - preferred_width) > cfg.entry.width.tolerance:
            continue
        if wing.symbol not in seen_symbols:
            seen_symbols.add(wing.symbol)
            results.append(wing)
    return results


def _vertical_candidate(
    underlying: str,
    short: OptionContract,
    long: OptionContract,
    cfg: StrategyConfig,
    *,
    as_of: date | None = None,
) -> SpreadCandidate | None:
    if short.option_type != long.option_type or short.expiration != long.expiration:
        return None

    kind = (
        StrategyKind.SHORT_PUT_VERTICAL
        if short.option_type == "put"
        else StrategyKind.SHORT_CALL_VERTICAL
    )
    direction = "long" if kind == StrategyKind.SHORT_PUT_VERTICAL else "short"
    dte = days_to_expiration(short.expiration, as_of=as_of)
    width = abs(short.strike - long.strike)

    # Conservative executable entry assumption. Midpoint is stored separately.
    natural_credit = short.bid - long.ask
    mark_credit = short.mid - long.mid
    max_profit = natural_credit * 100.0
    max_loss = (width - natural_credit) * 100.0
    target_pct = cfg.management.credit_vertical_profit_target_pct
    target_dollars = max_profit * target_pct

    gates: list[GateCheck] = []
    dte_ok = cfg.entry.dte_min <= dte <= cfg.entry.dte_max
    gates.append(GateCheck("DTE_OK", dte_ok, f"DTE {dte}", dte))

    passed, reason = _short_delta_ok(short, cfg)
    gates.append(GateCheck("SHORT_DELTA_OK", passed, reason, short.delta))

    passed, reason = _contract_liquid(short, cfg, short_leg=True)
    gates.append(GateCheck("SHORT_LIQUID", passed, reason))

    passed, reason = _contract_liquid(long, cfg, short_leg=False)
    gates.append(GateCheck("LONG_LIQUID", passed, reason))

    width_ok = cfg.entry.width.minimum <= width <= cfg.entry.width.maximum
    gates.append(GateCheck("WIDTH_OK", width_ok, f"width {width:.2f}", width))

    defined_risk = natural_credit > 0 and max_loss > 0
    gates.append(GateCheck("DEFINED_RISK", defined_risk, f"credit={natural_credit:.2f}, max_loss={max_loss:.2f}"))

    credit_to_width = natural_credit / width if width > 0 else 0.0
    gates.append(GateCheck("CREDIT_TO_WIDTH", credit_to_width >= cfg.entry.credit.minimum_credit_to_width, f"credit/width {credit_to_width:.1%}", credit_to_width))

    if not all(gate.passed for gate in gates):
        return None

    return SpreadCandidate(
        underlying=underlying,
        strategy=kind,
        expiration=short.expiration,
        dte=dte,
        direction=direction,
        legs=[_leg(short, "sell_to_open"), _leg(long, "buy_to_open")],
        width=width,
        net_credit=natural_credit,
        mark_credit=mark_credit,
        max_profit=max_profit,
        max_loss=max_loss,
        buying_power_reduction=max_loss,
        profit_target_pct=target_pct,
        profit_target_dollars=target_dollars,
        manage_at_dte=cfg.management.manage_at_dte,
        short_delta=abs(short.delta) if short.delta is not None else None,
        mid_iv=short.mid_iv,
        capital_efficiency=target_dollars / max_loss,
        premium_to_bpr=max_profit / max_loss,
        status=SetupStatus.TAKE,
        gates=gates,
    )


def scan_credit_verticals(
    underlying: str,
    chain: Iterable[OptionContract],
    cfg: StrategyConfig,
    *,
    as_of: date | None = None,
) -> list[SpreadCandidate]:
    contracts = [contract for contract in chain if contract.symbol and contract.strike > 0]
    candidates: list[SpreadCandidate] = []

    for option_type in ("put", "call"):
        same_type = sorted(
            [contract for contract in contracts if contract.option_type == option_type],
            key=lambda contract: contract.strike,
        )
        for short in same_type:
            if not _short_delta_ok(short, cfg)[0]:
                continue
            for long in _candidate_wings(short, same_type, cfg):
                candidate = _vertical_candidate(underlying, short, long, cfg, as_of=as_of)
                if candidate is not None:
                    candidates.append(candidate)

    candidates.sort(
        key=lambda candidate: (candidate.capital_efficiency, candidate.max_profit, candidate.width),
        reverse=True,
    )
    buckets: dict[StrategyKind, list[SpreadCandidate]] = {
        StrategyKind.SHORT_PUT_VERTICAL: [],
        StrategyKind.SHORT_CALL_VERTICAL: [],
    }
    for candidate in candidates:
        bucket = buckets[candidate.strategy]
        if len(bucket) < cfg.entry.max_candidates_per_side:
            bucket.append(candidate)
    return buckets[StrategyKind.SHORT_PUT_VERTICAL] + buckets[StrategyKind.SHORT_CALL_VERTICAL]


def build_iron_condors(
    verticals: Iterable[SpreadCandidate], cfg: StrategyConfig
) -> list[SpreadCandidate]:
    puts = [candidate for candidate in verticals if candidate.strategy == StrategyKind.SHORT_PUT_VERTICAL]
    calls = [candidate for candidate in verticals if candidate.strategy == StrategyKind.SHORT_CALL_VERTICAL]
    results: list[SpreadCandidate] = []
    seen: set[tuple[str, ...]] = set()

    for put in puts:
        for call in calls:
            if put.expiration != call.expiration or put.underlying != call.underlying:
                continue
            if put.legs[0].strike >= call.legs[0].strike:
                continue
            if abs(put.width - call.width) > cfg.entry.width.tolerance:
                continue

            width = max(put.width, call.width)
            natural_credit = put.net_credit + call.net_credit
            mark_credit = put.mark_credit + call.mark_credit
            max_profit = natural_credit * 100.0
            max_loss = (width - natural_credit) * 100.0
            credit_to_width = natural_credit / width if width > 0 else 0.0
            if max_loss <= 0 or credit_to_width < cfg.entry.credit.minimum_credit_to_width:
                continue

            signature = tuple(sorted(leg.option_symbol for leg in put.legs + call.legs))
            if signature in seen:
                continue
            seen.add(signature)

            target_pct = cfg.management.iron_condor_profit_target_pct
            target_dollars = max_profit * target_pct
            gates = [GateCheck(f"PUT_{gate.name}", gate.passed, gate.reason, gate.value) for gate in put.gates] + [GateCheck(f"CALL_{gate.name}", gate.passed, gate.reason, gate.value) for gate in call.gates]
            gates.extend([
                GateCheck("NON_OVERLAPPING_SHORTS", True, "put short below call short"),
                GateCheck("CONDOR_CREDIT_TO_WIDTH", True, f"combined credit/width {credit_to_width:.1%}", credit_to_width),
            ])

            short_deltas = [value for value in (put.short_delta, call.short_delta) if value is not None]
            iv_values = [value for value in (put.mid_iv, call.mid_iv) if value is not None]
            results.append(SpreadCandidate(
                underlying=put.underlying,
                strategy=StrategyKind.IRON_CONDOR,
                expiration=put.expiration,
                dte=put.dte,
                direction="neutral",
                legs=put.legs + call.legs,
                width=width,
                net_credit=natural_credit,
                mark_credit=mark_credit,
                max_profit=max_profit,
                max_loss=max_loss,
                buying_power_reduction=max_loss,
                profit_target_pct=target_pct,
                profit_target_dollars=target_dollars,
                manage_at_dte=cfg.management.manage_at_dte,
                short_delta=max(short_deltas) if short_deltas else None,
                mid_iv=(sum(iv_values) / len(iv_values)) if iv_values else None,
                capital_efficiency=target_dollars / max_loss,
                premium_to_bpr=max_profit / max_loss,
                status=SetupStatus.TAKE,
                gates=gates,
            ))

    results.sort(key=lambda candidate: (candidate.capital_efficiency, candidate.max_profit, candidate.width), reverse=True)
    return results[: cfg.entry.max_candidates_per_side]


def scan_defined_risk(
    underlying: str,
    chain: Iterable[OptionContract],
    cfg: StrategyConfig,
    *,
    as_of: date | None = None,
) -> list[SpreadCandidate]:
    verticals = scan_credit_verticals(underlying, chain, cfg, as_of=as_of)
    allowed = set(cfg.allowed_strategies)
    results = [candidate for candidate in verticals if candidate.strategy.value in allowed]
    if StrategyKind.IRON_CONDOR.value in allowed:
        results.extend(build_iron_condors(verticals, cfg))
    results.sort(key=lambda candidate: (candidate.capital_efficiency, candidate.max_profit, candidate.width), reverse=True)
    return results
