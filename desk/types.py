"""Normalized market and setup types. No broker-specific fields here."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal


class SetupStatus(str, Enum):
    TAKE = "TAKE"
    WAIT = "WAIT"
    SKIP = "SKIP"
    NO_SETUP = "NO_SETUP"


Right = Literal["call", "put"]
Side = Literal["buy", "sell"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class OptionContract:
    occ: str
    underlying: str
    expiration: date
    strike: float
    right: Right
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume: int = 0
    open_interest: int = 0
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    mid_iv: float | None = None

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return float(self.last or self.bid or self.ask or 0.0)

    @property
    def spread_width(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return self.ask - self.bid
        return 0.0


@dataclass
class UnderlyingQuote:
    symbol: str
    last: float
    bid: float = 0.0
    ask: float = 0.0
    volume: int = 0


@dataclass
class SpreadLeg:
    contract: OptionContract
    side: Side
    qty: int = 1


@dataclass
class Spread:
    structure: str
    underlying: str
    expiration: date
    dte: int
    legs: list[SpreadLeg]
    width: float
    credit: float  # >0 credit received, <0 debit paid, per share
    max_profit: float  # dollars for 1 contract
    max_loss: float  # dollars for 1 contract (defined)
    buying_power: float  # dollars for 1 contract
    short_delta: float | None = None
    iv_rank: float | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def credit_over_width(self) -> float:
        if self.width <= 0:
            return 0.0
        return self.credit / self.width


@dataclass
class ScanResult:
    symbol: str
    status: SetupStatus = SetupStatus.NO_SETUP
    reason: str = ""
    gates_passed: list[str] = field(default_factory=list)
    spread: Spread | None = None
    qty: int = 1
    capital_efficiency: float | None = None
    profit_target: float | None = None  # dollars, all contracts
    management_dte: int | None = None
    timestamp: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "status": self.status.value,
            "reason": self.reason,
            "gates_passed": self.gates_passed,
            "qty": self.qty,
            "capital_efficiency": self.capital_efficiency,
            "profit_target": self.profit_target,
            "management_dte": self.management_dte,
            "timestamp": self.timestamp,
            "spread": None,
        }
        if self.spread:
            payload["spread"] = {
                "structure": self.spread.structure,
                "underlying": self.spread.underlying,
                "expiration": self.spread.expiration.isoformat(),
                "dte": self.spread.dte,
                "width": self.spread.width,
                "credit": self.spread.credit,
                "max_profit": self.spread.max_profit,
                "max_loss": self.spread.max_loss,
                "buying_power": self.spread.buying_power,
                "short_delta": self.spread.short_delta,
                "iv_rank": self.spread.iv_rank,
                "extras": self.spread.extras,
                "legs": [
                    {
                        "side": lg.side,
                        "qty": lg.qty,
                        "occ": lg.contract.occ,
                        "strike": lg.contract.strike,
                        "right": lg.contract.right,
                        "bid": lg.contract.bid,
                        "ask": lg.contract.ask,
                    }
                    for lg in self.spread.legs
                ],
            }
        return payload


@dataclass
class MarketState:
    as_of: date
    underlyings: dict[str, UnderlyingQuote]
    chains: dict[tuple[str, date], list[OptionContract]]
    iv_rank: dict[str, float] = field(default_factory=dict)

    def chain(self, symbol: str, expiration: date) -> list[OptionContract]:
        return self.chains.get((symbol.upper(), expiration), [])
