"""Load `desk/strategy.yaml` — strategy numbers live here, not in prompts."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise ImportError("desk config needs PyYAML: pip install pyyaml") from exc


ROOT = Path(__file__).resolve().parent
DEFAULT_PATH = ROOT / "strategy.yaml"


@dataclass
class DeskConfig:
    name: str
    universe: list[str]
    dte_min: int
    dte_target: int
    dte_max: int
    defined_risk_only: bool
    allowed_structures: list[str]
    widths: list[float]
    short_delta_min: float
    short_delta_max: float
    min_credit_over_width: float
    max_bid_ask_pct: float
    min_open_interest: int
    min_volume: int
    require_iv_rank: bool
    min_iv_rank: float
    default_profit_target_pct: float
    calendar_profit_target_pct: float
    broken_wing_profit_target_pct: float
    manage_at_dte: int
    nav: float
    max_risk_per_trade_pct: float
    max_total_buying_power_pct: float
    max_correlated_exposure_pct: float
    multiplier: int = 100
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "DeskConfig":
        p = Path(path) if path else DEFAULT_PATH
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeskConfig":
        s = data.get("strategy") or data
        entry = s.get("entry") or {}
        dte = entry.get("dte") or {}
        mgmt = s.get("management") or {}
        port = s.get("portfolio") or {}
        liq = s.get("liquidity") or {}
        delta = s.get("short_delta") or {}
        return cls(
            name=s.get("name", "tasty_defined_risk_v1"),
            universe=list(s.get("universe") or ["SPY", "QQQ", "IWM"]),
            dte_min=int(dte.get("min", 25)),
            dte_target=int(dte.get("target", 45)),
            dte_max=int(dte.get("max", 55)),
            defined_risk_only=bool(entry.get("defined_risk_only", True)),
            allowed_structures=list(entry.get("allowed_structures") or ["short_put_vertical"]),
            widths=[float(x) for x in (s.get("widths") or [1, 2.5, 5, 10, 15, 20])],
            short_delta_min=float(delta.get("min", 0.16)),
            short_delta_max=float(delta.get("max", 0.35)),
            min_credit_over_width=float(s.get("min_credit_over_width", 0.20)),
            max_bid_ask_pct=float(liq.get("max_bid_ask_pct", 0.15)),
            min_open_interest=int(liq.get("min_open_interest", 100)),
            min_volume=int(liq.get("min_volume", 10)),
            require_iv_rank=bool(s.get("require_iv_rank", False)),
            min_iv_rank=float(s.get("min_iv_rank", 25)),
            default_profit_target_pct=float(mgmt.get("default_profit_target_pct", 50)),
            calendar_profit_target_pct=float(mgmt.get("calendar_profit_target_pct", 25)),
            broken_wing_profit_target_pct=float(mgmt.get("broken_wing_profit_target_pct", 25)),
            manage_at_dte=int(mgmt.get("manage_at_dte", 21)),
            nav=float(port.get("nav", 100_000)),
            max_risk_per_trade_pct=float(port.get("max_risk_per_trade_pct", 2.0)),
            max_total_buying_power_pct=float(port.get("max_total_buying_power_pct", 50.0)),
            max_correlated_exposure_pct=float(port.get("max_correlated_exposure_pct", 25.0)),
            multiplier=int(s.get("multiplier", 100)),
            raw=data,
        )

    def profit_target_pct(self, structure: str) -> float:
        if structure == "calendar":
            return self.calendar_profit_target_pct
        if structure == "broken_wing_butterfly":
            return self.broken_wing_profit_target_pct
        return self.default_profit_target_pct

    def risk_budget(self) -> float:
        return self.nav * self.max_risk_per_trade_pct / 100.0
