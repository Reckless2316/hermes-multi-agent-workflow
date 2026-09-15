"""Pass/fail gates. A gate checks one thing. Failure reason is specific."""
from __future__ import annotations

from dataclasses import dataclass

from ..config import DeskConfig
from ..types import Spread, SetupStatus


@dataclass
class GateOutcome:
    name: str
    ok: bool
    status: SetupStatus = SetupStatus.SKIP
    reason: str = ""


def gate_data_ok(spread: Spread) -> GateOutcome:
    for leg in spread.legs:
        c = leg.contract
        if c.bid <= 0 or c.ask <= 0 or c.ask < c.bid:
            return GateOutcome("DATA_OK", False, SetupStatus.WAIT, f"Stale/empty quote on {c.occ}")
    return GateOutcome("DATA_OK", True)


def gate_dte(spread: Spread, cfg: DeskConfig) -> GateOutcome:
    if spread.dte < cfg.dte_min or spread.dte > cfg.dte_max:
        return GateOutcome("DTE_WINDOW", False, SetupStatus.SKIP, f"DTE {spread.dte} outside {cfg.dte_min}-{cfg.dte_max}")
    return GateOutcome("DTE_WINDOW", True)


def gate_defined_risk(spread: Spread, cfg: DeskConfig) -> GateOutcome:
    if cfg.defined_risk_only and spread.max_loss <= 0:
        return GateOutcome("DEFINED_RISK", False, reason="max_loss is not a positive dollar amount")
    if cfg.defined_risk_only and spread.max_loss > spread.width * 100 * 1.01:
        return GateOutcome("DEFINED_RISK", False, reason="max_loss exceeds width — undefined or mis-priced")
    return GateOutcome("DEFINED_RISK", True)


def gate_width(spread: Spread, cfg: DeskConfig) -> GateOutcome:
    want = {round(w, 4) for w in cfg.widths}
    if round(spread.width, 4) not in want:
        return GateOutcome("WIDTH", False, reason=f"width {spread.width} not in {sorted(cfg.widths)}")
    return GateOutcome("WIDTH", True)


def gate_short_delta(spread: Spread, cfg: DeskConfig) -> GateOutcome:
    deltas: list[float] = []
    if spread.structure == "iron_condor":
        for key in ("put_short_delta", "call_short_delta"):
            v = spread.extras.get(key)
            if v is None:
                return GateOutcome("SHORT_DELTA", False, SetupStatus.WAIT, f"missing {key}")
            deltas.append(abs(float(v)))
    else:
        if spread.short_delta is None:
            return GateOutcome("SHORT_DELTA", False, SetupStatus.WAIT, "missing short delta")
        deltas.append(abs(spread.short_delta))
    for d in deltas:
        if d < cfg.short_delta_min or d > cfg.short_delta_max:
            return GateOutcome(
                "SHORT_DELTA", False,
                reason=f"|delta| {d:.3f} outside {cfg.short_delta_min}-{cfg.short_delta_max}",
            )
    return GateOutcome("SHORT_DELTA", True)


def gate_credit_width(spread: Spread, cfg: DeskConfig) -> GateOutcome:
    ratio = spread.credit_over_width()
    if ratio < cfg.min_credit_over_width:
        return GateOutcome(
            "CREDIT_WIDTH", False,
            reason=f"credit/width {ratio:.3f} < {cfg.min_credit_over_width}",
        )
    return GateOutcome("CREDIT_WIDTH", True)


def gate_bid_ask(spread: Spread, cfg: DeskConfig) -> GateOutcome:
    for leg in spread.legs:
        c = leg.contract
        mid = c.mid
        if mid <= 0:
            return GateOutcome("BID_ASK", False, SetupStatus.WAIT, f"no mid on {c.occ}")
        pct = c.spread_width / mid
        if pct > cfg.max_bid_ask_pct:
            return GateOutcome("BID_ASK", False, reason=f"{c.occ} bid/ask {pct:.2%} > {cfg.max_bid_ask_pct:.0%}")
    return GateOutcome("BID_ASK", True)


def gate_liquidity(spread: Spread, cfg: DeskConfig) -> GateOutcome:
    for leg in spread.legs:
        c = leg.contract
        if c.open_interest < cfg.min_open_interest:
            return GateOutcome("LIQUIDITY", False, reason=f"{c.occ} OI {c.open_interest} < {cfg.min_open_interest}")
        if c.volume < cfg.min_volume:
            return GateOutcome("LIQUIDITY", False, reason=f"{c.occ} volume {c.volume} < {cfg.min_volume}")
    return GateOutcome("LIQUIDITY", True)


def gate_iv_rank(spread: Spread, cfg: DeskConfig) -> GateOutcome:
    if not cfg.require_iv_rank:
        return GateOutcome("IV_RANK", True, reason="not required")
    if spread.iv_rank is None:
        return GateOutcome("IV_RANK", False, SetupStatus.WAIT, "iv_rank unavailable")
    if spread.iv_rank < cfg.min_iv_rank:
        return GateOutcome("IV_RANK", False, reason=f"iv_rank {spread.iv_rank} < {cfg.min_iv_rank}")
    return GateOutcome("IV_RANK", True)


def run_structure_gates(spread: Spread, cfg: DeskConfig) -> tuple[list[str], GateOutcome | None]:
    """Return (passed names, first failure or None)."""
    passed: list[str] = []
    for fn in (
        gate_data_ok,
        lambda s: gate_dte(s, cfg),
        lambda s: gate_defined_risk(s, cfg),
        lambda s: gate_width(s, cfg),
        lambda s: gate_short_delta(s, cfg),
        lambda s: gate_credit_width(s, cfg),
        lambda s: gate_bid_ask(s, cfg),
        lambda s: gate_liquidity(s, cfg),
        lambda s: gate_iv_rank(s, cfg),
    ):
        outcome = fn(spread)  # type: ignore[misc]
        if not outcome.ok:
            return passed, outcome
        passed.append(outcome.name)
    return passed, None
