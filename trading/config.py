"""Configuration for the deterministic defined-risk options strategy."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class StrategyConfigError(ValueError):
    """Raised when strategy YAML is internally inconsistent or unsafe for V1."""


@dataclass(frozen=True)
class LiquidityRules:
    min_open_interest: int = 100
    min_volume: int = 10
    max_bid_ask_pct_mid: float = 0.20
    require_two_sided_market: bool = True


@dataclass(frozen=True)
class DeltaRules:
    target: float = 0.30
    minimum: float = 0.20
    maximum: float = 0.35


@dataclass(frozen=True)
class CreditRules:
    minimum_credit_to_width: float = 0.30
    target_credit_to_width: float = 0.50


@dataclass(frozen=True)
class WidthRules:
    minimum: float = 2.5
    maximum: float = 20.0
    preferred: tuple[float, ...] = (5.0, 10.0, 15.0, 20.0)
    tolerance: float = 0.51


@dataclass(frozen=True)
class EntryRules:
    dte_min: int = 25
    dte_target: int = 45
    dte_max: int = 50
    delta: DeltaRules = field(default_factory=DeltaRules)
    liquidity: LiquidityRules = field(default_factory=LiquidityRules)
    credit: CreditRules = field(default_factory=CreditRules)
    width: WidthRules = field(default_factory=WidthRules)
    max_candidates_per_side: int = 5


@dataclass(frozen=True)
class ManagementRules:
    credit_vertical_profit_target_pct: float = 0.50
    iron_condor_profit_target_pct: float = 0.50
    manage_at_dte: int = 21
    close_partial_winner_at_manage_dte: bool = True
    force_close_at_dte: int = 1


@dataclass(frozen=True)
class RiskRules:
    risk_per_trade_pct: float = 0.01
    max_contracts_per_trade: int = 10
    max_total_defined_risk_pct: float | None = None
    max_correlated_defined_risk_pct: float | None = None


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    version: int
    mode: str
    allowed_strategies: tuple[str, ...]
    universe: tuple[str, ...]
    entry: EntryRules
    management: ManagementRules
    risk: RiskRules
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def load(cls, path: str | Path) -> "StrategyConfig":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StrategyConfig":
        entry = data.get("entry") or {}
        short_delta = entry.get("short_delta") or {}
        liquidity = entry.get("liquidity") or {}
        credit = entry.get("credit") or {}
        width = entry.get("width") or {}
        management = data.get("management") or {}
        risk = data.get("risk") or {}

        cfg = cls(
            name=str(data.get("name", "tasty_defined_risk_v1")),
            version=int(data.get("version", 1)),
            mode=str(data.get("mode", "paper")),
            allowed_strategies=tuple(
                data.get("allowed_strategies")
                or [
                    "short_put_vertical",
                    "short_call_vertical",
                    "iron_condor",
                ]
            ),
            universe=tuple(
                str(symbol).strip().upper()
                for symbol in ((data.get("universe") or {}).get("symbols") or [])
                if str(symbol).strip()
            ),
            entry=EntryRules(
                dte_min=int(entry.get("dte_min", 25)),
                dte_target=int(entry.get("dte_target", 45)),
                dte_max=int(entry.get("dte_max", 50)),
                delta=DeltaRules(
                    target=float(short_delta.get("target", 0.30)),
                    minimum=float(short_delta.get("minimum", 0.20)),
                    maximum=float(short_delta.get("maximum", 0.35)),
                ),
                liquidity=LiquidityRules(
                    min_open_interest=int(liquidity.get("min_open_interest", 100)),
                    min_volume=int(liquidity.get("min_volume", 10)),
                    max_bid_ask_pct_mid=float(
                        liquidity.get("max_bid_ask_pct_mid", 0.20)
                    ),
                    require_two_sided_market=bool(
                        liquidity.get("require_two_sided_market", True)
                    ),
                ),
                credit=CreditRules(
                    minimum_credit_to_width=float(
                        credit.get("minimum_credit_to_width", 0.30)
                    ),
                    target_credit_to_width=float(
                        credit.get("target_credit_to_width", 0.50)
                    ),
                ),
                width=WidthRules(
                    minimum=float(width.get("minimum", 2.5)),
                    maximum=float(width.get("maximum", 20.0)),
                    preferred=tuple(
                        float(value)
                        for value in width.get("preferred", [5, 10, 15, 20])
                    ),
                    tolerance=float(width.get("tolerance", 0.51)),
                ),
                max_candidates_per_side=int(
                    entry.get("max_candidates_per_side", 5)
                ),
            ),
            management=ManagementRules(
                credit_vertical_profit_target_pct=float(
                    management.get("credit_vertical_profit_target_pct", 0.50)
                ),
                iron_condor_profit_target_pct=float(
                    management.get("iron_condor_profit_target_pct", 0.50)
                ),
                manage_at_dte=int(management.get("manage_at_dte", 21)),
                close_partial_winner_at_manage_dte=bool(
                    management.get("close_partial_winner_at_manage_dte", True)
                ),
                force_close_at_dte=int(management.get("force_close_at_dte", 1)),
            ),
            risk=RiskRules(
                risk_per_trade_pct=float(risk.get("risk_per_trade_pct", 0.01)),
                max_contracts_per_trade=int(
                    risk.get("max_contracts_per_trade", 10)
                ),
                max_total_defined_risk_pct=(
                    None
                    if risk.get("max_total_defined_risk_pct") is None
                    else float(risk["max_total_defined_risk_pct"])
                ),
                max_correlated_defined_risk_pct=(
                    None
                    if risk.get("max_correlated_defined_risk_pct") is None
                    else float(risk["max_correlated_defined_risk_pct"])
                ),
            ),
            raw=data,
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        entry = self.entry
        management = self.management
        risk = self.risk
        errors: list[str] = []

        if not (0 < entry.dte_min <= entry.dte_target <= entry.dte_max):
            errors.append("Require 0 < dte_min <= dte_target <= dte_max")
        if not (
            0
            <= entry.delta.minimum
            <= entry.delta.target
            <= entry.delta.maximum
            <= 1
        ):
            errors.append("Invalid short-delta bounds")
        if not (0 < entry.credit.minimum_credit_to_width <= 1):
            errors.append("minimum_credit_to_width must be in (0, 1]")
        if not (
            entry.width.minimum > 0
            and entry.width.maximum >= entry.width.minimum
        ):
            errors.append("Invalid spread width bounds")
        if not (0 < entry.liquidity.max_bid_ask_pct_mid <= 1):
            errors.append("max_bid_ask_pct_mid must be in (0, 1]")
        if entry.max_candidates_per_side < 1:
            errors.append("max_candidates_per_side must be >= 1")

        if not (0 < risk.risk_per_trade_pct <= 1):
            errors.append("risk_per_trade_pct must be in (0, 1]")
        if risk.max_contracts_per_trade < 1:
            errors.append("max_contracts_per_trade must be >= 1")
        for key, value in (
            ("max_total_defined_risk_pct", risk.max_total_defined_risk_pct),
            (
                "max_correlated_defined_risk_pct",
                risk.max_correlated_defined_risk_pct,
            ),
        ):
            if value is not None and not (0 < value <= 1):
                errors.append(f"{key} must be null or in (0, 1]")

        if not (0 < management.credit_vertical_profit_target_pct <= 1):
            errors.append("vertical profit target must be in (0, 1]")
        if not (0 < management.iron_condor_profit_target_pct <= 1):
            errors.append("condor profit target must be in (0, 1]")
        if (
            management.manage_at_dte < 0
            or management.force_close_at_dte < 0
            or management.force_close_at_dte > management.manage_at_dte
        ):
            errors.append("Invalid management DTE thresholds")

        allowed = {
            "short_put_vertical",
            "short_call_vertical",
            "iron_condor",
        }
        unknown = set(self.allowed_strategies) - allowed
        if unknown:
            errors.append(f"Unknown strategies: {sorted(unknown)}")
        if self.mode != "paper":
            errors.append("V1 is paper-only; mode must be 'paper'")

        if errors:
            raise StrategyConfigError(
                "Invalid strategy config:\n  - " + "\n  - ".join(errors)
            )
