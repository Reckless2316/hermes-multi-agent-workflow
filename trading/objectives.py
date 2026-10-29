"""Objective curve: income -> growth -> speculation as one continuous dial.

``aggression`` in [0, 1] locates a trade purpose on the curve. Each named
objective is an anchor profile at a fixed aggression (income 0.0, growth 0.5,
speculation 1.0 by default). A point between two anchors linearly
interpolates every numeric parameter (DTE window, deltas, POP floor, payoff
floor, risk per trade, scoring weights) and considers the structure menus of
*both* anchors, so a 0.25 dial searches credit and debit structures under a
blended, mostly-income utility.

``auto`` maps the deterministic market situation (vol regime x trend
strength) to an aggression through an auditable YAML table, capped by the
operator's ``max_aggression``. Some cells are deliberately ``null``: for
example cheap premium with no trend gives no structural edge to buy or
sell, so the scanner reports NO_SETUP instead of forcing a trade.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import yaml

from .config import (
    CreditRules,
    DeltaRules,
    EntryRules,
    LiquidityRules,
    ManagementRules,
    RiskRules,
    StrategyConfig,
    WidthRules,
)
from .regime import MarketSituation, RegimeRules
from .types import CREDIT_STRATEGIES, Objective, StrategyKind

BIASES = ("bullish", "bearish", "neutral")
VOL_REGIMES = ("rich", "fair", "cheap")
TREND_KEYS = ("neutral", "trend", "strong_trend")
SUPPORTED = {kind.value for kind in StrategyKind}
CREDIT_VALUES = {kind.value for kind in CREDIT_STRATEGIES}
DIRECTIONAL = {
    "bullish": {"short_put_vertical", "long_call_vertical", "long_call"},
    "bearish": {"short_call_vertical", "long_put_vertical", "long_put"},
    "neutral": {"iron_condor"},
}


class ObjectiveConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Band:
    minimum: float
    target: float
    maximum: float

    def ok(self) -> bool:
        return 0 <= self.minimum <= self.target <= self.maximum <= 1


@dataclass(frozen=True)
class Weights:
    capital_efficiency: float = 0.0
    pop: float = 0.0
    payoff: float = 0.0
    model_edge: float = 0.0

    def total(self) -> float:
        return self.capital_efficiency + self.pop + self.payoff + self.model_edge


@dataclass(frozen=True)
class ObjectiveProfile:
    """A point on the curve. Anchors and interpolated profiles share this type."""

    objective: str
    aggression: float
    dte_min: int
    dte_target: int
    dte_max: int
    short_delta: Band
    long_delta: Band
    min_pop: float
    min_credit_to_width: float
    min_payoff_multiple: float
    max_breakeven_em: float
    profit_target_pct: float
    stop_loss_pct: float | None
    manage_at_dte: int
    risk_per_trade_pct: float
    weights: Weights
    structures: dict[str, tuple[str, ...]]
    blend: tuple[tuple[str, float], ...] = ()

    def menu(self, bias: str | None) -> tuple[str, ...]:
        """Structures for ``bias``; unknown bias admits only non-directional structures."""
        key = bias if bias in BIASES else "neutral"
        allowed = self.structures.get(key, ())
        if bias not in BIASES:
            allowed = tuple(s for s in allowed if s in DIRECTIONAL["neutral"])
        return allowed

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["structures"] = {k: list(v) for k, v in self.structures.items()}
        data["blend"] = [list(pair) for pair in self.blend]
        return data


def _band(raw: dict[str, Any] | None, name: str) -> Band:
    raw = raw or {}
    try:
        return Band(float(raw["minimum"]), float(raw["target"]), float(raw["maximum"]))
    except KeyError as exc:
        raise ObjectiveConfigError(f"{name} needs minimum/target/maximum") from exc


def _profile(name: str, raw: dict[str, Any]) -> ObjectiveProfile:
    dte = raw.get("dte") or {}
    weights = raw.get("weights") or {}
    structures_raw = raw.get("structures") or {}
    try:
        profile = ObjectiveProfile(
            objective=name,
            aggression=float(raw["aggression"]),
            dte_min=int(dte["min"]),
            dte_target=int(dte["target"]),
            dte_max=int(dte["max"]),
            short_delta=_band(raw.get("short_delta"), f"{name}.short_delta"),
            long_delta=_band(raw.get("long_delta"), f"{name}.long_delta"),
            min_pop=float(raw["min_pop"]),
            min_credit_to_width=float(raw["min_credit_to_width"]),
            min_payoff_multiple=float(raw["min_payoff_multiple"]),
            max_breakeven_em=float(raw["max_breakeven_em"]),
            profit_target_pct=float(raw["profit_target_pct"]),
            stop_loss_pct=None if raw.get("stop_loss_pct") is None else float(raw["stop_loss_pct"]),
            manage_at_dte=int(raw["manage_at_dte"]),
            risk_per_trade_pct=float(raw["risk_per_trade_pct"]),
            weights=Weights(**{k: float(v) for k, v in weights.items()}),
            structures={bias: tuple(str(s) for s in structures_raw.get(bias) or ()) for bias in BIASES},
            blend=((name, 1.0),),
        )
    except (KeyError, TypeError) as exc:
        raise ObjectiveConfigError(f"objective {name!r} is missing or has an invalid field: {exc}") from exc
    return profile


def _validate_profile(p: ObjectiveProfile) -> list[str]:
    e: list[str] = []
    if not 0 <= p.aggression <= 1:
        e.append(f"{p.objective}: aggression must be in [0, 1]")
    if not 0 < p.dte_min <= p.dte_target <= p.dte_max:
        e.append(f"{p.objective}: require 0 < dte.min <= dte.target <= dte.max")
    if p.manage_at_dte < 0 or p.manage_at_dte >= p.dte_min:
        e.append(f"{p.objective}: manage_at_dte must be >= 0 and below dte.min")
    if not (p.short_delta.ok() and p.long_delta.ok()):
        e.append(f"{p.objective}: delta bands must satisfy 0 <= min <= target <= max <= 1")
    if not 0 <= p.min_pop < 1:
        e.append(f"{p.objective}: min_pop must be in [0, 1)")
    if not 0 < p.min_credit_to_width <= 1:
        e.append(f"{p.objective}: min_credit_to_width must be in (0, 1]")
    if p.min_payoff_multiple < 0 or p.max_breakeven_em <= 0:
        e.append(f"{p.objective}: min_payoff_multiple >= 0 and max_breakeven_em > 0 required")
    if p.profit_target_pct <= 0:
        e.append(f"{p.objective}: profit_target_pct must be positive")
    if p.stop_loss_pct is not None and not 0 < p.stop_loss_pct < 1:
        e.append(f"{p.objective}: stop_loss_pct must be null or in (0, 1)")
    if not 0 < p.risk_per_trade_pct <= 0.05:
        e.append(f"{p.objective}: risk_per_trade_pct must be in (0, 0.05]")
    if p.weights.total() <= 0 or min(asdict(p.weights).values()) < 0:
        e.append(f"{p.objective}: weights must be non-negative with a positive sum")
    for bias, menu in p.structures.items():
        unknown = set(menu) - SUPPORTED
        if unknown:
            e.append(f"{p.objective}.{bias}: unknown structures {sorted(unknown)}")
        wrong = set(menu) & SUPPORTED - DIRECTIONAL[bias]
        if wrong:
            e.append(f"{p.objective}.{bias}: structures {sorted(wrong)} contradict the {bias} bias")
    return e



@dataclass(frozen=True)
class ObjectiveConfig:
    name: str
    version: int
    mode: str
    universe: tuple[str, ...]
    anchors: tuple[ObjectiveProfile, ...]
    liquidity: LiquidityRules
    width: WidthRules
    max_candidates_per_structure: int
    force_close_at_dte: int
    max_contracts_per_trade: int
    max_total_defined_risk_pct: float | None
    max_correlated_defined_risk_pct: float | None
    regime: RegimeRules
    iv_reference_dte: int
    auto_map: dict[str, dict[str, float | None]]
    max_aggression: float
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def load(cls, path: str | Path) -> "ObjectiveConfig":
        return cls.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ObjectiveConfig":
        objectives = data.get("objectives") or {}
        anchors = tuple(sorted((_profile(n, r or {}) for n, r in objectives.items()), key=lambda p: p.aggression))
        liquidity = data.get("liquidity") or {}
        width = data.get("width") or {}
        risk = data.get("risk") or {}
        regime = data.get("regime") or {}
        auto = data.get("auto") or {}
        regime_fields = {f.name for f in fields(RegimeRules)}
        cfg = cls(
            name=str(data.get("name", "objective_options_v1")),
            version=int(data.get("version", 1)),
            mode=str(data.get("mode", "paper")),
            universe=tuple(str(s).strip().upper() for s in ((data.get("universe") or {}).get("symbols") or []) if str(s).strip()),
            anchors=anchors,
            liquidity=LiquidityRules(
                min_open_interest=int(liquidity.get("min_open_interest", 100)),
                min_volume=int(liquidity.get("min_volume", 10)),
                max_bid_ask_pct_mid=float(liquidity.get("max_bid_ask_pct_mid", 0.20)),
                require_two_sided_market=bool(liquidity.get("require_two_sided_market", True)),
            ),
            width=WidthRules(
                minimum=float(width.get("minimum", 2.5)),
                maximum=float(width.get("maximum", 20.0)),
                preferred=tuple(float(v) for v in width.get("preferred", [5, 10, 15, 20])),
                tolerance=float(width.get("tolerance", 0.51)),
            ),
            max_candidates_per_structure=int(data.get("max_candidates_per_structure", 3)),
            force_close_at_dte=int((data.get("management") or {}).get("force_close_at_dte", 1)),
            max_contracts_per_trade=int(risk.get("max_contracts_per_trade", 10)),
            max_total_defined_risk_pct=None if risk.get("max_total_defined_risk_pct") is None else float(risk["max_total_defined_risk_pct"]),
            max_correlated_defined_risk_pct=None if risk.get("max_correlated_defined_risk_pct") is None else float(risk["max_correlated_defined_risk_pct"]),
            regime=RegimeRules(**{k: v for k, v in regime.items() if k in regime_fields}),
            iv_reference_dte=int(regime.get("iv_reference_dte", 30)),
            auto_map={vol: {k: (None if v is None else float(v)) for k, v in (auto.get("map") or {}).get(vol, {}).items()} for vol in VOL_REGIMES},
            max_aggression=float(auto.get("max_aggression", 1.0)),
            raw=data,
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        e: list[str] = []
        if self.mode != "paper":
            e.append("objective options are paper-only; mode must be 'paper'")
        names = [a.objective for a in self.anchors]
        if sorted(names) != sorted(o.value for o in Objective):
            e.append(f"objectives must define exactly {[o.value for o in Objective]}; got {names}")
        aggressions = [a.aggression for a in self.anchors]
        if len(set(aggressions)) != len(aggressions) or (aggressions and (aggressions[0] != 0 or aggressions[-1] != 1)):
            e.append("anchor aggressions must be distinct and span exactly 0.0 to 1.0")
        elif names != [o.value for o in Objective]:
            e.append("anchors must be ordered income < growth < speculation by aggression")
        for anchor in self.anchors:
            e.extend(_validate_profile(anchor))
        for anchor in self.anchors:
            if self.force_close_at_dte > anchor.manage_at_dte:
                e.append(f"force_close_at_dte exceeds {anchor.objective}.manage_at_dte")
        if not (self.width.minimum > 0 and self.width.maximum >= self.width.minimum):
            e.append("invalid width bounds")
        if not 0 < self.liquidity.max_bid_ask_pct_mid <= 1:
            e.append("max_bid_ask_pct_mid must be in (0, 1]")
        if self.max_candidates_per_structure < 1 or self.max_contracts_per_trade < 1:
            e.append("max_candidates_per_structure and max_contracts_per_trade must be >= 1")
        for key, value in (("max_total_defined_risk_pct", self.max_total_defined_risk_pct), ("max_correlated_defined_risk_pct", self.max_correlated_defined_risk_pct)):
            if value is not None and not 0 < value <= 1:
                e.append(f"{key} must be null or in (0, 1]")
        e.extend(self.regime.validate())
        if self.iv_reference_dte < 1:
            e.append("regime.iv_reference_dte must be >= 1")
        if not 0 <= self.max_aggression <= 1:
            e.append("auto.max_aggression must be in [0, 1]")
        for vol in VOL_REGIMES:
            row = self.auto_map.get(vol) or {}
            if set(row) != set(TREND_KEYS):
                e.append(f"auto.map.{vol} must define exactly {list(TREND_KEYS)}")
            for value in row.values():
                if value is not None and not 0 <= value <= 1:
                    e.append(f"auto.map.{vol} values must be null or in [0, 1]")
        if e:
            raise ObjectiveConfigError("Invalid objective config:\n  - " + "\n  - ".join(e))

    def anchor(self, objective: str) -> ObjectiveProfile:
        for a in self.anchors:
            if a.objective == objective:
                return a
        raise ObjectiveConfigError(f"Unknown objective {objective!r}")

    def profile_at(self, aggression: float) -> ObjectiveProfile:
        if not 0 <= aggression <= 1:
            raise ObjectiveConfigError(f"aggression must be in [0, 1], got {aggression}")
        for a in self.anchors:
            if abs(a.aggression - aggression) < 1e-9:
                return a
        lo = max((a for a in self.anchors if a.aggression < aggression), key=lambda a: a.aggression)
        hi = min((a for a in self.anchors if a.aggression > aggression), key=lambda a: a.aggression)
        return interpolate(lo, hi, (aggression - lo.aggression) / (hi.aggression - lo.aggression))

    def credit_strategy_config(self, profile: ObjectiveProfile, bias: str | None) -> StrategyConfig:
        """Express the credit half of a profile in the V1 scanner's config type."""
        credit = tuple(s for s in profile.menu(bias) if s in CREDIT_VALUES)
        cfg = StrategyConfig(
            name=self.name,
            version=self.version,
            mode=self.mode,
            allowed_strategies=credit,
            universe=self.universe,
            entry=EntryRules(
                dte_min=profile.dte_min,
                dte_target=profile.dte_target,
                dte_max=profile.dte_max,
                delta=DeltaRules(profile.short_delta.target, profile.short_delta.minimum, profile.short_delta.maximum),
                liquidity=self.liquidity,
                credit=CreditRules(profile.min_credit_to_width, max(profile.min_credit_to_width, 0.5)),
                width=self.width,
                max_candidates_per_side=self.max_candidates_per_structure,
            ),
            management=ManagementRules(
                credit_vertical_profit_target_pct=min(profile.profit_target_pct, 1.0),
                iron_condor_profit_target_pct=min(profile.profit_target_pct, 1.0),
                manage_at_dte=profile.manage_at_dte,
                close_partial_winner_at_manage_dte=True,
                force_close_at_dte=self.force_close_at_dte,
            ),
            risk=RiskRules(
                risk_per_trade_pct=profile.risk_per_trade_pct,
                max_contracts_per_trade=self.max_contracts_per_trade,
                max_total_defined_risk_pct=self.max_total_defined_risk_pct,
                max_correlated_defined_risk_pct=self.max_correlated_defined_risk_pct,
            ),
        )
        cfg.validate()
        return cfg


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def interpolate(lo: ObjectiveProfile, hi: ObjectiveProfile, t: float) -> ObjectiveProfile:
    """Blend two anchors. ``t`` = 0 is ``lo``, 1 is ``hi``."""

    def band(x: Band, y: Band) -> Band:
        return Band(_lerp(x.minimum, y.minimum, t), _lerp(x.target, y.target, t), _lerp(x.maximum, y.maximum, t))

    # A null stop means "hold to defined max loss", i.e. a 100% stop.
    stop = _lerp(1.0 if lo.stop_loss_pct is None else lo.stop_loss_pct, 1.0 if hi.stop_loss_pct is None else hi.stop_loss_pct, t)
    dte_min = round(_lerp(lo.dte_min, hi.dte_min, t))
    dte_max = round(_lerp(lo.dte_max, hi.dte_max, t))
    structures = {
        bias: tuple(dict.fromkeys(lo.structures.get(bias, ()) + hi.structures.get(bias, ())))
        for bias in BIASES
    }
    nearest = lo if t <= 0.5 else hi
    return ObjectiveProfile(
        objective=nearest.objective,
        aggression=_lerp(lo.aggression, hi.aggression, t),
        dte_min=dte_min,
        dte_target=min(max(round(_lerp(lo.dte_target, hi.dte_target, t)), dte_min), dte_max),
        dte_max=dte_max,
        short_delta=band(lo.short_delta, hi.short_delta),
        long_delta=band(lo.long_delta, hi.long_delta),
        min_pop=_lerp(lo.min_pop, hi.min_pop, t),
        min_credit_to_width=_lerp(lo.min_credit_to_width, hi.min_credit_to_width, t),
        min_payoff_multiple=_lerp(lo.min_payoff_multiple, hi.min_payoff_multiple, t),
        max_breakeven_em=_lerp(lo.max_breakeven_em, hi.max_breakeven_em, t),
        profit_target_pct=_lerp(lo.profit_target_pct, hi.profit_target_pct, t),
        stop_loss_pct=None if stop >= 0.999 else stop,
        manage_at_dte=min(round(_lerp(lo.manage_at_dte, hi.manage_at_dte, t)), dte_min - 1),
        risk_per_trade_pct=_lerp(lo.risk_per_trade_pct, hi.risk_per_trade_pct, t),
        weights=Weights(
            capital_efficiency=_lerp(lo.weights.capital_efficiency, hi.weights.capital_efficiency, t),
            pop=_lerp(lo.weights.pop, hi.weights.pop, t),
            payoff=_lerp(lo.weights.payoff, hi.weights.payoff, t),
            model_edge=_lerp(lo.weights.model_edge, hi.weights.model_edge, t),
        ),
        structures=structures,
        blend=((lo.objective, round(1 - t, 6)), (hi.objective, round(t, 6))),
    )


@dataclass(frozen=True)
class ObjectiveDecision:
    """How the dial was set for one symbol, and why."""

    aggression: float | None
    profile: ObjectiveProfile | None
    bias: str | None
    bias_source: str
    source: str  # explicit | auto
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggression": self.aggression,
            "objective": None if self.profile is None else self.profile.objective,
            "blend": [] if self.profile is None else [list(p) for p in self.profile.blend],
            "bias": self.bias,
            "bias_source": self.bias_source,
            "source": self.source,
            "reason": self.reason,
        }


def trend_key(situation: MarketSituation) -> str | None:
    if situation.trend == "unknown":
        return None
    if situation.trend == "neutral":
        return "neutral"
    return "strong_trend" if situation.trend_strength == "strong" else "trend"


def decide(
    cfg: ObjectiveConfig,
    situation: MarketSituation,
    *,
    objective: str = "auto",
    aggression: float | None = None,
    bias: str = "auto",
    max_aggression: float | None = None,
) -> ObjectiveDecision:
    """Resolve the dial and bias for one symbol. Explicit inputs always win."""
    cap = cfg.max_aggression if max_aggression is None else max_aggression
    if not 0 <= cap <= 1:
        raise ObjectiveConfigError("max_aggression must be in [0, 1]")

    if bias in BIASES:
        resolved_bias, bias_source = bias, "operator"
    elif bias == "auto":
        resolved_bias = situation.trend if situation.trend in BIASES else None
        bias_source = "trend" if resolved_bias else "unknown"
    else:
        raise ObjectiveConfigError(f"bias must be auto or one of {BIASES}, got {bias!r}")

    if aggression is not None:
        value, source, reason = float(aggression), "explicit", f"operator dial {float(aggression):.2f}"
    elif objective != "auto":
        value, source, reason = cfg.anchor(objective).aggression, "explicit", f"operator objective {objective}"
    else:
        key = trend_key(situation)
        if situation.vol_regime == "unknown" or key is None:
            return ObjectiveDecision(None, None, resolved_bias, bias_source, "auto", "situation unknown: " + "; ".join(situation.notes or ["missing inputs"]))
        mapped = cfg.auto_map[situation.vol_regime][key]
        if mapped is None:
            return ObjectiveDecision(None, None, resolved_bias, bias_source, "auto", f"no structural edge for vol={situation.vol_regime}, trend={key}")
        value, source = mapped, "auto"
        reason = f"vol={situation.vol_regime} (IV/RV {situation.iv_rv_ratio:.2f}), trend={key} -> {mapped:.2f}"
        if bias in BIASES and bias != situation.trend:
            reason += f"; operator bias {bias} overrides trend {situation.trend}"

    if value > cap:
        reason += f"; capped at max_aggression {cap:.2f}"
        value = cap
    profile = cfg.profile_at(value)
    return ObjectiveDecision(value, profile, resolved_bias, bias_source, source, reason)


def with_risk_override(profile: ObjectiveProfile, risk_per_trade_pct: float | None) -> ObjectiveProfile:
    """Cap the profile's risk per trade; an override can lower risk, never raise it."""
    if risk_per_trade_pct is None:
        return profile
    if not 0 < risk_per_trade_pct <= 1:
        raise ObjectiveConfigError("risk override must be in (0, 1]")
    if risk_per_trade_pct >= profile.risk_per_trade_pct:
        return profile
    return replace(profile, risk_per_trade_pct=risk_per_trade_pct)
