"""Portfolio / buying-power state. Deterministic; Hermes does not invent these numbers."""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import DeskConfig
from .types import Spread, SetupStatus


@dataclass
class OpenPosition:
    symbol: str
    structure: str
    max_loss: float
    buying_power: float
    qty: int


@dataclass
class PortfolioState:
    nav: float
    open: list[OpenPosition] = field(default_factory=list)

    def used_bp(self) -> float:
        return sum(p.buying_power * p.qty for p in self.open)

    def correlated_risk(self, symbol: str) -> float:
        return sum(p.max_loss * p.qty for p in self.open if p.symbol == symbol.upper())


def size_and_risk(
    spread: Spread,
    cfg: DeskConfig,
    portfolio: PortfolioState,
) -> tuple[int, SetupStatus, str]:
    """Return (qty, status, reason). qty is 0 if rejected."""
    risk_budget = cfg.risk_budget()
    if spread.max_loss <= 0:
        return 0, SetupStatus.SKIP, "max_loss not positive"
    qty = max(1, int(risk_budget // spread.max_loss))
    # If even 1 contract exceeds per-trade risk, skip — do not invent a fractional option.
    if spread.max_loss > risk_budget:
        return 0, SetupStatus.SKIP, (
            f"1-lot max_loss ${spread.max_loss:.0f} exceeds per-trade budget ${risk_budget:.0f}"
        )
    bp_add = spread.buying_power * qty
    bp_cap = cfg.nav * cfg.max_total_buying_power_pct / 100.0
    if portfolio.used_bp() + bp_add > bp_cap:
        return 0, SetupStatus.SKIP, (
            f"BP {portfolio.used_bp() + bp_add:.0f} would exceed cap {bp_cap:.0f}"
        )
    corr_cap = cfg.nav * cfg.max_correlated_exposure_pct / 100.0
    corr = portfolio.correlated_risk(spread.underlying) + spread.max_loss * qty
    if corr > corr_cap:
        return 0, SetupStatus.SKIP, (
            f"correlated risk on {spread.underlying} {corr:.0f} exceeds {corr_cap:.0f}"
        )
    return qty, SetupStatus.TAKE, "PORTFOLIO_OK"


def is_duplicate(spread: Spread, portfolio: PortfolioState) -> bool:
    for p in portfolio.open:
        if p.symbol == spread.underlying.upper() and p.structure == spread.structure:
            return True
    return False
