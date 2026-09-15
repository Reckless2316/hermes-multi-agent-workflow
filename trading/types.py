"""Typed objects for the deterministic defined-risk options desk."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SetupStatus(str, Enum):
    TAKE = "TAKE"
    WAIT = "WAIT"
    SKIP = "SKIP"
    NO_SETUP = "NO_SETUP"


class StrategyKind(str, Enum):
    SHORT_PUT_VERTICAL = "short_put_vertical"
    SHORT_CALL_VERTICAL = "short_call_vertical"
    IRON_CONDOR = "iron_condor"


@dataclass(frozen=True)
class OptionContract:
    symbol: str
    underlying: str
    expiration: str
    option_type: str
    strike: float
    bid: float
    ask: float
    last: float | None = None
    volume: int = 0
    open_interest: int = 0
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    mid_iv: float | None = None
    bid_iv: float | None = None
    ask_iv: float | None = None
    greeks_updated_at: str | None = None

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0 and self.ask >= self.bid:
            return (self.bid + self.ask) / 2.0
        if self.last is not None and self.last > 0:
            return float(self.last)
        return 0.0

    @property
    def spread(self) -> float:
        return max(0.0, self.ask - self.bid)

    @property
    def bid_ask_pct_mid(self) -> float | None:
        mid = self.mid
        return None if mid <= 0 else self.spread / mid


@dataclass(frozen=True)
class OptionLeg:
    option_symbol: str
    side: str
    quantity: int
    option_type: str
    strike: float
    expiration: str
    bid: float
    ask: float
    mid: float
    delta: float | None = None
    open_interest: int = 0
    volume: int = 0


@dataclass
class GateCheck:
    name: str
    passed: bool
    reason: str
    value: Any = None


@dataclass
class SpreadCandidate:
    underlying: str
    strategy: StrategyKind
    expiration: str
    dte: int
    direction: str
    legs: list[OptionLeg]
    width: float
    net_credit: float
    mark_credit: float
    max_profit: float
    max_loss: float
    buying_power_reduction: float
    profit_target_pct: float
    profit_target_dollars: float
    manage_at_dte: int
    short_delta: float | None
    mid_iv: float | None
    capital_efficiency: float
    premium_to_bpr: float
    status: SetupStatus = SetupStatus.TAKE
    gates: list[GateCheck] = field(default_factory=list)
    reason: str = "All deterministic gates passed"
    source: str = "tradier"
    strategy_version: str = "tasty_defined_risk_v1"
    captured_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def gates_passed(self) -> list[str]:
        return [g.name for g in self.gates if g.passed]

    @property
    def gate_failures(self) -> list[str]:
        return [f"{g.name}: {g.reason}" for g in self.gates if not g.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "underlying": self.underlying,
            "strategy": self.strategy.value,
            "expiration": self.expiration,
            "dte": self.dte,
            "direction": self.direction,
            "legs": [leg.__dict__.copy() for leg in self.legs],
            "width": self.width,
            "net_credit": self.net_credit,
            "mark_credit": self.mark_credit,
            "max_profit": self.max_profit,
            "max_loss": self.max_loss,
            "buying_power_reduction": self.buying_power_reduction,
            "profit_target_pct": self.profit_target_pct,
            "profit_target_dollars": self.profit_target_dollars,
            "manage_at_dte": self.manage_at_dte,
            "short_delta": self.short_delta,
            "mid_iv": self.mid_iv,
            "capital_efficiency": self.capital_efficiency,
            "premium_to_bpr": self.premium_to_bpr,
            "status": self.status.value,
            "gates": [g.__dict__.copy() for g in self.gates],
            "gates_passed": self.gates_passed,
            "gate_failures": self.gate_failures,
            "reason": self.reason,
            "source": self.source,
            "strategy_version": self.strategy_version,
            "captured_at": self.captured_at,
        }


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    account_type: str
    total_equity: float
    total_cash: float
    option_buying_power: float
    stock_buying_power: float
    open_pl: float = 0.0
    current_requirement: float = 0.0
    pending_orders_count: int = 0


@dataclass(frozen=True)
class SizedCandidate:
    candidate: SpreadCandidate
    contracts: int
    risk_budget: float
    total_max_loss: float
    total_profit_target: float
    total_buying_power_reduction: float
    sizing_reason: str


@dataclass(frozen=True)
class PositionState:
    position_id: str
    underlying: str
    strategy: StrategyKind
    expiration: str
    opened_at: str
    entry_credit: float
    width: float
    quantity: int
    max_profit: float
    max_loss: float
    profit_target_pct: float
    manage_at_dte: int


class ManagementAction(str, Enum):
    HOLD = "HOLD"
    CLOSE_WINNER = "CLOSE_WINNER"
    CLOSE_AT_MANAGEMENT_DTE = "CLOSE_AT_MANAGEMENT_DTE"
    REVIEW_AT_MANAGEMENT_DTE = "REVIEW_AT_MANAGEMENT_DTE"
    REVIEW_ROLL_FOR_CREDIT = "REVIEW_ROLL_FOR_CREDIT"
    CLOSE_BEFORE_EXPIRATION = "CLOSE_BEFORE_EXPIRATION"


@dataclass(frozen=True)
class ManagementDecision:
    action: ManagementAction
    reason: str
    pnl_dollars: float
    pct_max_profit: float
    dte: int


def spread_candidate_from_dict(data: dict[str, Any]) -> SpreadCandidate:
    legs = [OptionLeg(**leg) for leg in data.get("legs", [])]
    gates = [GateCheck(**g) for g in (data.get("gates") or []) if isinstance(g, dict)]
    return SpreadCandidate(
        underlying=str(data["underlying"]),
        strategy=StrategyKind(str(data["strategy"])),
        expiration=str(data["expiration"]),
        dte=int(data["dte"]),
        direction=str(data["direction"]),
        legs=legs,
        width=float(data["width"]),
        net_credit=float(data["net_credit"]),
        mark_credit=float(data.get("mark_credit", data["net_credit"])),
        max_profit=float(data["max_profit"]),
        max_loss=float(data["max_loss"]),
        buying_power_reduction=float(data["buying_power_reduction"]),
        profit_target_pct=float(data["profit_target_pct"]),
        profit_target_dollars=float(data["profit_target_dollars"]),
        manage_at_dte=int(data["manage_at_dte"]),
        short_delta=None if data.get("short_delta") is None else float(data["short_delta"]),
        mid_iv=None if data.get("mid_iv") is None else float(data["mid_iv"]),
        capital_efficiency=float(data["capital_efficiency"]),
        premium_to_bpr=float(data["premium_to_bpr"]),
        status=SetupStatus(str(data.get("status", "TAKE"))),
        gates=gates,
        reason=str(data.get("reason", "All deterministic gates passed")),
        source=str(data.get("source", "tradier")),
        strategy_version=str(data.get("strategy_version", "tasty_defined_risk_v1")),
        captured_at=str(data.get("captured_at") or datetime.now(timezone.utc).isoformat()),
    )


def sized_candidate_from_dict(data: dict[str, Any]) -> SizedCandidate:
    candidate = spread_candidate_from_dict(data)
    contracts = int(data.get("contracts", 1))
    return SizedCandidate(
        candidate=candidate,
        contracts=contracts,
        risk_budget=float(data.get("risk_budget", 0.0)),
        total_max_loss=float(data.get("total_max_loss", candidate.max_loss * contracts)),
        total_profit_target=float(data.get("total_profit_target", candidate.profit_target_dollars * contracts)),
        total_buying_power_reduction=float(data.get("total_buying_power_reduction", candidate.buying_power_reduction * contracts)),
        sizing_reason=str(data.get("sizing_reason", "loaded from approved candidate")),
    )
