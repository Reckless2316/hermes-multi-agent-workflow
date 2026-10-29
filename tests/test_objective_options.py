"""Objective curve (income / growth / speculation) options mechanism tests."""
from __future__ import annotations

import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from math import log, sqrt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from engine.intake_parser import parse_intake_report  # noqa: E402
from options_fixtures import bs, chain, history  # noqa: E402
from trading import pricing  # noqa: E402
from trading.config import StrategyConfig  # noqa: E402
from trading.intake import candidate_id, render_objective_intake  # noqa: E402
from trading.objective_engine import scan_objective  # noqa: E402
from trading.objective_scan import revalidation_context, run_objective_scan, sidecar_payload, spot_from_quote  # noqa: E402
from trading.objectives import ObjectiveConfig, ObjectiveConfigError, decide, with_risk_override  # noqa: E402
from trading.paper_options import OptionsPaperLedger  # noqa: E402
from trading.portfolio import size_candidate  # noqa: E402
from trading.position_manager import manage_debit_position, natural_close_debit, natural_close_value, plan_position  # noqa: E402
from trading.regime import MarketSituation, RegimeRules, atm_iv, classify, closes_from_history, realized_vol  # noqa: E402
from trading.revalidate import RevalidationRejected, revalidate_for_paper_fill  # noqa: E402
from trading.structures import StructureEconomicsError, economics  # noqa: E402
from trading.types import AccountSnapshot, ManagementAction, OptionContract, PositionState, StrategyKind, sized_candidate_from_dict  # noqa: E402

CONFIG_PATH = ROOT / "strategy/objective_options_v1.yaml"
AS_OF = date(2026, 9, 15)


def base_raw() -> dict:
    return copy.deepcopy(ObjectiveConfig.load(CONFIG_PATH).raw)


def relaxed_cfg() -> ObjectiveConfig:
    """Flat-IV synthetic chains cannot reach V1's 30% credit/width at 0.30 delta."""
    raw = base_raw()
    raw["objectives"]["income"]["min_credit_to_width"] = 0.20
    return ObjectiveConfig.from_dict(raw)


def account(equity: float = 100_000, bp: float = 50_000) -> AccountSnapshot:
    return AccountSnapshot("TEST", "margin", equity, 25_000, bp, 100_000)


def situation(*, spot=600.0, rv=0.20, iv=0.20, trend="bullish", strength="moderate", vol_regime="fair") -> MarketSituation:
    return MarketSituation("SPY", spot, AS_OF.isoformat(), 80, rv, iv, iv / rv, vol_regime, trend, strength, 1.0, spot * 0.98, spot * 0.95)


class PricingTests(unittest.TestCase):
    def test_breakevens_by_structure(self):
        self.assertEqual(pricing.breakevens([("buy_to_open", "call", 100.0, 1)], -2.0), [102.0])
        self.assertEqual(pricing.breakevens([("buy_to_open", "put", 100.0, 1)], -3.0), [97.0])
        put_credit = [("sell_to_open", "put", 95.0, 1), ("buy_to_open", "put", 90.0, 1)]
        self.assertEqual(pricing.breakevens(put_credit, 1.5), [93.5])
        condor = put_credit + [("sell_to_open", "call", 105.0, 1), ("buy_to_open", "call", 110.0, 1)]
        self.assertEqual(pricing.breakevens(condor, 3.0), [92.0, 108.0])
        call_debit = [("buy_to_open", "call", 100.0, 1), ("sell_to_open", "call", 110.0, 1)]
        self.assertEqual(pricing.breakevens(call_debit, -4.0), [104.0])

    def test_long_call_pop_matches_closed_form(self):
        spot, sigma, years = 100.0, 0.25, 60 / 365
        pop = pricing.prob_profit([("buy_to_open", "call", 100.0, 1)], -3.0, spot=spot, sigma=sigma, years=years)
        sd = sigma * sqrt(years)
        expected = 1 - pricing.norm_cdf((log(103.0 / spot) + 0.5 * sd * sd) / sd)
        self.assertAlmostEqual(pop, expected, places=12)

    def test_fairly_priced_option_has_zero_expectation_at_its_own_vol(self):
        spot, sigma, years = 100.0, 0.30, 45 / 365
        price, _ = bs("put", spot, 95.0, sigma, years)
        ev = pricing.expected_pnl([("buy_to_open", "put", 95.0, 1)], -price, spot=spot, sigma=sigma, years=years)
        self.assertAlmostEqual(ev, 0.0, places=10)
        self.assertGreater(pricing.expected_pnl([("buy_to_open", "put", 95.0, 1)], -price, spot=spot, sigma=0.45, years=years), 0)

    def test_condor_pop_is_probability_between_breakevens(self):
        legs = [("sell_to_open", "put", 95.0, 1), ("buy_to_open", "put", 90.0, 1), ("sell_to_open", "call", 105.0, 1), ("buy_to_open", "call", 110.0, 1)]
        pop = pricing.prob_profit(legs, 3.0, spot=100.0, sigma=0.2, years=45 / 365)
        self.assertGreater(pop, 0.5)
        self.assertLess(pop, 1.0)

    def test_model_inputs_validated(self):
        with self.assertRaises(ValueError):
            pricing.prob_profit([("buy_to_open", "call", 100.0, 1)], -1.0, spot=100.0, sigma=0.0, years=0.1)


class StructureEconomicsTests(unittest.TestCase):
    def test_economics(self):
        self.assertEqual(economics(StrategyKind.SHORT_PUT_VERTICAL, 5.0, 1.5), (150.0, 350.0))
        self.assertEqual(economics(StrategyKind.LONG_CALL_VERTICAL, 10.0, -4.0), (600.0, 400.0))
        self.assertEqual(economics(StrategyKind.LONG_CALL, 0.0, -2.5), (None, 250.0))
        # a long put is capped at the underlying going to zero
        self.assertEqual(economics(StrategyKind.LONG_PUT, 0.0, -2.5, 100.0), (9750.0, 250.0))
        with self.assertRaises(StructureEconomicsError):
            economics(StrategyKind.LONG_PUT, 0.0, -2.5)

    def test_wrong_sign_rejected(self):
        with self.assertRaises(StructureEconomicsError):
            economics(StrategyKind.LONG_CALL, 0.0, 1.0)
        with self.assertRaises(StructureEconomicsError):
            economics(StrategyKind.SHORT_CALL_VERTICAL, 5.0, -1.0)
        with self.assertRaises(StructureEconomicsError):
            economics(StrategyKind.LONG_CALL_VERTICAL, 5.0, -5.0)


class RegimeTests(unittest.TestCase):
    rules = RegimeRules()

    def test_realized_vol_of_alternating_series(self):
        closes = closes_from_history(history(daily_vol=0.01, bars=60))
        n = self.rules.rv_window
        self.assertAlmostEqual(realized_vol(closes, n), 0.01 * sqrt(n / (n - 1)) * sqrt(252), places=5)  # closes rounded to 4dp

    def test_trend_classes(self):
        _, ch = chain(spot=500, sigma=0.2)
        up = closes_from_history(history(daily_drift=0.004, daily_vol=0.006))
        down = closes_from_history(history(daily_drift=-0.004, daily_vol=0.006))
        flat = closes_from_history(history(daily_vol=0.01))
        self.assertEqual(classify("X", spot=up[-1], closes=up, chain=ch, rules=self.rules).trend, "bullish")
        self.assertEqual(classify("X", spot=down[-1], closes=down, chain=ch, rules=self.rules).trend, "bearish")
        flat_sit = classify("X", spot=flat[-1], closes=flat, chain=ch, rules=self.rules)
        self.assertEqual((flat_sit.trend, flat_sit.trend_strength), ("neutral", "none"))

    def test_vol_regimes(self):
        closes = closes_from_history(history(daily_vol=0.01))  # RV ~ 16%
        for iv, regime in ((0.25, "rich"), (0.165, "fair"), (0.10, "cheap")):
            _, ch = chain(spot=closes[-1], sigma=iv)
            self.assertEqual(classify("X", spot=closes[-1], closes=closes, chain=ch, rules=self.rules).vol_regime, regime)

    def test_short_history_is_unknown_not_guessed(self):
        closes = closes_from_history(history(bars=10))
        _, ch = chain(spot=closes[-1])
        s = classify("X", spot=closes[-1], closes=closes, chain=ch, rules=self.rules)
        self.assertFalse(s.known)
        self.assertEqual((s.vol_regime, s.trend), ("unknown", "unknown"))
        self.assertTrue(s.notes)

    def test_atm_iv_uses_nearest_strike(self):
        contracts = [OptionContract("A", "X", "2026-10-30", "call", 100, 1, 1.1, mid_iv=0.2), OptionContract("B", "X", "2026-10-30", "put", 100, 1, 1.1, mid_iv=0.3), OptionContract("C", "X", "2026-10-30", "call", 110, 1, 1.1, mid_iv=0.9)]
        self.assertAlmostEqual(atm_iv(contracts, 101), 0.25)
        self.assertIsNone(atm_iv([], 100))


class ObjectiveConfigTests(unittest.TestCase):
    def test_loads_three_anchors(self):
        cfg = ObjectiveConfig.load(CONFIG_PATH)
        self.assertEqual([a.objective for a in cfg.anchors], ["income", "growth", "speculation"])
        self.assertEqual([a.aggression for a in cfg.anchors], [0.0, 0.5, 1.0])

    def test_rejects_unsafe_or_inconsistent_configs(self):
        cases = []
        raw = base_raw(); raw["mode"] = "live"; cases.append(raw)
        raw = base_raw(); del raw["objectives"]["growth"]; cases.append(raw)
        raw = base_raw(); raw["objectives"]["growth"]["structures"]["bearish"] = ["long_call"]; cases.append(raw)
        raw = base_raw(); raw["objectives"]["income"]["structures"]["neutral"] = ["naked_put"]; cases.append(raw)
        raw = base_raw(); raw["objectives"]["speculation"]["aggression"] = 0.9; cases.append(raw)
        raw = base_raw(); raw["objectives"]["speculation"]["risk_per_trade_pct"] = 0.10; cases.append(raw)
        raw = base_raw(); raw["auto"]["map"]["cheap"].pop("neutral"); cases.append(raw)
        raw = base_raw(); raw["objectives"]["growth"]["manage_at_dte"] = 60; cases.append(raw)
        for raw in cases:
            with self.assertRaises(ObjectiveConfigError):
                ObjectiveConfig.from_dict(raw)

    def test_curve_interpolates_numbers_and_unions_menus(self):
        cfg = ObjectiveConfig.load(CONFIG_PATH)
        income, growth = cfg.anchor("income"), cfg.anchor("growth")
        mid = cfg.profile_at(0.25)
        self.assertAlmostEqual(mid.min_pop, (income.min_pop + growth.min_pop) / 2)
        self.assertAlmostEqual(mid.risk_per_trade_pct, (income.risk_per_trade_pct + growth.risk_per_trade_pct) / 2)
        self.assertEqual(mid.menu("bullish"), ("short_put_vertical", "long_call_vertical", "long_call"))
        self.assertEqual(dict(mid.blend), {"income": 0.5, "growth": 0.5})
        self.assertEqual(cfg.profile_at(0.5), growth)
        # null stop (hold to max loss) blends as a 100% stop
        self.assertAlmostEqual(cfg.profile_at(0.75).stop_loss_pct, 0.75)
        self.assertIsNone(cfg.profile_at(1.0).stop_loss_pct)
        with self.assertRaises(ObjectiveConfigError):
            cfg.profile_at(1.5)

    def test_risk_per_trade_falls_along_the_curve(self):
        cfg = ObjectiveConfig.load(CONFIG_PATH)
        risks = [cfg.profile_at(x / 10).risk_per_trade_pct for x in range(11)]
        self.assertEqual(risks, sorted(risks, reverse=True))

    def test_risk_override_caps_and_never_raises(self):
        cfg = ObjectiveConfig.load(CONFIG_PATH)
        blended = cfg.profile_at(0.3)
        self.assertEqual(with_risk_override(blended, 0.005).risk_per_trade_pct, 0.005)
        self.assertEqual(with_risk_override(cfg.anchor("income"), 0.005).risk_per_trade_pct, 0.005)
        speculation = cfg.anchor("speculation")
        self.assertIs(with_risk_override(speculation, 0.005), speculation)
        with self.assertRaises(ObjectiveConfigError):
            with_risk_override(blended, 0.0)

    def test_unknown_bias_admits_only_non_directional(self):
        cfg = ObjectiveConfig.load(CONFIG_PATH)
        self.assertEqual(cfg.anchor("income").menu(None), ("iron_condor",))
        self.assertEqual(cfg.anchor("growth").menu(None), ())


class DecisionTests(unittest.TestCase):
    cfg = ObjectiveConfig.load(CONFIG_PATH)

    def test_auto_table(self):
        self.assertEqual(decide(self.cfg, situation(vol_regime="rich", trend="neutral", strength="none")).aggression, 0.0)
        self.assertEqual(decide(self.cfg, situation(vol_regime="fair", trend="bullish")).aggression, 0.5)
        self.assertEqual(decide(self.cfg, situation(vol_regime="cheap", trend="bullish", strength="strong")).aggression, 1.0)

    def test_no_edge_cell_refuses(self):
        d = decide(self.cfg, situation(vol_regime="cheap", trend="neutral", strength="none"))
        self.assertIsNone(d.profile)
        self.assertIn("no structural edge", d.reason)

    def test_unknown_situation_refuses_auto_but_honours_explicit(self):
        unknown = replace(situation(), vol_regime="unknown", trend="unknown", trend_strength="unknown", notes=["short history"])
        self.assertIsNone(decide(self.cfg, unknown).profile)
        explicit = decide(self.cfg, unknown, objective="income")
        self.assertEqual(explicit.profile.objective, "income")
        self.assertIsNone(explicit.bias)

    def test_cap_and_overrides(self):
        d = decide(self.cfg, situation(vol_regime="cheap", trend="bullish", strength="strong"), max_aggression=0.5)
        self.assertEqual(d.aggression, 0.5)
        self.assertIn("capped", d.reason)
        d = decide(self.cfg, situation(trend="bullish"), aggression=0.8, bias="bearish")
        self.assertEqual((d.aggression, d.bias, d.bias_source, d.source), (0.8, "bearish", "operator", "explicit"))
        with self.assertRaises(ObjectiveConfigError):
            decide(self.cfg, situation(), bias="sideways")


class EngineTests(unittest.TestCase):
    def scan(self, cfg, aggression, bias, *, sigma=0.20, rv=0.20, dte=None, spot=600.0, rejections=None):
        profile = cfg.profile_at(aggression)
        expiration, contracts = chain(spot=spot, sigma=sigma, dte=dte or profile.dte_target)
        sit = situation(spot=spot, rv=rv, iv=sigma, trend=bias if bias in ("bullish", "bearish") else "neutral")
        return contracts, scan_objective("SPY", contracts, cfg, profile, spot=spot, situation=sit, bias=bias, as_of=AS_OF, rejections=rejections)

    def assert_well_formed(self, c, profile):
        self.assertTrue(all(g.passed for g in c.gates), c.gates)
        self.assertGreater(c.max_loss, 0)
        self.assertEqual(c.strategy_version, "objective_options_v1")
        self.assertEqual(c.objective, profile.objective)
        self.assertIn("score", c.analytics)
        self.assertGreaterEqual(c.analytics["model"]["pop_iv"], profile.min_pop - 1e-12)
        max_profit, max_loss = economics(c.strategy, c.width, c.net_credit)
        self.assertEqual((c.max_profit, c.max_loss), (max_profit, max_loss))

    def test_income_neutral_builds_condors_ranked_by_score(self):
        cfg = relaxed_cfg()
        _, out = self.scan(cfg, 0.0, "neutral", sigma=0.25)
        self.assertTrue(out)
        self.assertEqual({c.strategy for c in out}, {StrategyKind.IRON_CONDOR})
        scores = [c.analytics["score"] for c in out]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for c in out:
            self.assert_well_formed(c, cfg.anchor("income"))
            self.assertGreater(c.net_credit, 0)

    def test_growth_bullish_builds_only_bullish_debits(self):
        cfg = ObjectiveConfig.load(CONFIG_PATH)
        rejections: dict[str, int] = {}
        _, out = self.scan(cfg, 0.5, "bullish", rejections=rejections)
        self.assertTrue(out)
        self.assertTrue({c.strategy for c in out} <= {StrategyKind.LONG_CALL_VERTICAL, StrategyKind.LONG_CALL})
        growth = cfg.anchor("growth")
        for c in out:
            self.assert_well_formed(c, growth)
            self.assertLess(c.net_credit, 0)
            self.assertEqual(c.direction, "long")
            long_leg = next(l for l in c.legs if l.side == "buy_to_open")
            self.assertTrue(growth.long_delta.minimum <= abs(long_leg.delta) <= growth.long_delta.maximum)
            if c.strategy == StrategyKind.LONG_CALL_VERTICAL:
                self.assertGreaterEqual(c.premium_to_bpr, growth.min_payoff_multiple)
        self.assertTrue(rejections, "objective gates should reject some raw structures")

    def test_bearish_mirror(self):
        cfg = ObjectiveConfig.load(CONFIG_PATH)
        _, out = self.scan(cfg, 1.0, "bearish", sigma=0.15, rv=0.25)
        self.assertTrue(out)
        self.assertTrue({c.strategy for c in out} <= {StrategyKind.LONG_PUT, StrategyKind.LONG_PUT_VERTICAL})
        self.assertTrue(all(c.direction == "short" for c in out))

    def test_speculation_is_further_otm_and_smaller_than_growth(self):
        cfg = ObjectiveConfig.load(CONFIG_PATH)
        _, growth = self.scan(cfg, 0.5, "bullish", dte=60)
        _, spec = self.scan(cfg, 1.0, "bullish", dte=60, sigma=0.15, rv=0.25)
        def long_delta(c):
            return abs(next(l for l in c.legs if l.side == "buy_to_open").delta)
        self.assertLess(max(long_delta(c) for c in spec), min(long_delta(c) for c in growth))
        self.assertLess(min(c.max_loss for c in spec), min(c.max_loss for c in growth))

    def test_neutral_growth_finds_nothing(self):
        cfg = ObjectiveConfig.load(CONFIG_PATH)
        self.assertEqual(self.scan(cfg, 0.5, "neutral")[1], [])

    def test_model_edge_follows_realized_vs_implied(self):
        cfg = ObjectiveConfig.load(CONFIG_PATH)
        _, cheap = self.scan(cfg, 1.0, "bullish", sigma=0.15, rv=0.30)
        self.assertTrue(all(c.analytics["model"]["model_edge_rv"] > 0 for c in cheap))
        _, rich = self.scan(relaxed_cfg(), 0.0, "neutral", sigma=0.30, rv=0.15)
        self.assertTrue(all(c.analytics["model"]["model_edge_rv"] > 0 for c in rich))
        _, rich_bought = self.scan(cfg, 0.5, "bullish", sigma=0.30, rv=0.15)
        self.assertTrue(all(c.analytics["model"]["model_edge_rv"] < 0 for c in rich_bought))

    def test_illiquid_long_leg_rejected(self):
        cfg = ObjectiveConfig.load(CONFIG_PATH)
        profile = cfg.anchor("growth")
        _, contracts = chain(spot=600, dte=profile.dte_target, open_interest=5)
        sit = situation()
        self.assertEqual(scan_objective("SPY", contracts, cfg, profile, spot=600, situation=sit, bias="bullish", as_of=AS_OF), [])

    def test_blend_searches_both_families(self):
        cfg = relaxed_cfg()
        _, out = self.scan(cfg, 0.25, "bullish", sigma=0.25, dte=45)
        kinds = {c.strategy for c in out}
        self.assertIn(StrategyKind.SHORT_PUT_VERTICAL, kinds)
        self.assertTrue(kinds & {StrategyKind.LONG_CALL_VERTICAL, StrategyKind.LONG_CALL})


class SizingAndRevalidationTests(unittest.TestCase):
    cfg = ObjectiveConfig.load(CONFIG_PATH)

    def growth_candidate(self):
        profile = self.cfg.anchor("growth")
        _, contracts = chain(spot=600, dte=75)
        out = scan_objective("SPY", contracts, self.cfg, profile, spot=600, situation=situation(), bias="bullish", as_of=AS_OF, context={"objective_decision": {"bias": "bullish", "aggression": 0.5}})
        vertical = next(c for c in out if c.strategy == StrategyKind.LONG_CALL_VERTICAL)
        return contracts, vertical

    def test_sizing_uses_profile_risk(self):
        _, c = self.growth_candidate()
        sized = size_candidate(c, account(1_000_000, 1_000_000), self.cfg.credit_strategy_config(self.cfg.anchor("growth"), "bullish"))
        self.assertEqual(sized.risk_budget, 1_000_000 * 0.0075)
        self.assertLessEqual(sized.total_max_loss, sized.risk_budget)

    def approved(self):
        contracts, c = self.growth_candidate()
        sizing = self.cfg.credit_strategy_config(self.cfg.anchor("growth"), "bullish")
        return contracts, size_candidate(c, account(1_000_000, 1_000_000), sizing)

    def revalidate(self, approved, contracts):
        return self.revalidate_at(approved, contracts, spot=600)

    def revalidate_at(self, approved, contracts, *, spot):
        rescan, sizing, fill_gate = revalidation_context(self.cfg, approved.candidate, spot=spot)
        return revalidate_for_paper_fill(approved, contracts, account(1_000_000, 1_000_000), sizing, as_of=AS_OF, rescan=rescan, fill_gate=fill_gate)

    def test_same_quotes_fill_at_approved_debit(self):
        contracts, approved = self.approved()
        rv = self.revalidate(approved, contracts)
        filled = rv.to_fill_candidate()
        self.assertEqual(rv.fill_credit, approved.candidate.net_credit)
        self.assertEqual(filled.candidate.max_loss, approved.candidate.max_loss)
        self.assertEqual(filled.total_max_loss, approved.total_max_loss)

    def _bump(self, contracts, symbol, delta_ask):
        return [replace(c, ask=round(c.ask + delta_ask, 2)) if c.symbol == symbol else c for c in contracts]

    def test_higher_debit_is_not_chased(self):
        contracts, approved = self.approved()
        long_symbol = next(l.option_symbol for l in approved.candidate.legs if l.side == "buy_to_open")
        with self.assertRaisesRegex(RevalidationRejected, "debit deteriorated"):
            self.revalidate(approved, self._bump(contracts, long_symbol, 0.25))

    def test_cheaper_debit_still_fills_at_approved_limit(self):
        contracts, approved = self.approved()
        long_symbol = next(l.option_symbol for l in approved.candidate.legs if l.side == "buy_to_open")
        rv = self.revalidate(approved, self._bump(contracts, long_symbol, -0.05))
        self.assertGreater(rv.current_natural_credit, rv.approved_limit_credit)
        self.assertEqual(rv.fill_credit, approved.candidate.net_credit)

    def test_gates_rerun_at_approved_fill_premium(self):
        # Spot falls 600 -> 598: the fresh long call is cheaper (passes POP at the
        # fresh debit), but the fill happens at the higher approved debit.
        profile = self.cfg.anchor("growth")
        _, at_600 = chain(spot=600, dte=75)
        _, at_598 = chain(spot=598, dte=75)
        out = scan_objective("SPY", at_600, self.cfg, profile, spot=600, situation=situation(), bias="bullish", as_of=AS_OF, context={"objective_decision": {"bias": "bullish", "aggression": 0.5}})
        call = next(c for c in out if c.strategy == StrategyKind.LONG_CALL and c.legs[0].strike == 590.0)
        approved = size_candidate(call, account(1_000_000, 1_000_000), self.cfg.credit_strategy_config(profile, "bullish"))
        fresh_pop = pricing.prob_profit(pricing.legs_from_candidate(call), -next(c for c in at_598 if c.symbol == call.legs[0].option_symbol).ask, spot=598, sigma=call.mid_iv, years=75 / 365)
        self.assertGreaterEqual(fresh_pop, profile.min_pop)  # fresh economics alone would pass
        with self.assertRaisesRegex(RevalidationRejected, "POP_OK fails at the approved fill premium"):
            self.revalidate_at(approved, at_598, spot=598)

    def test_fill_analytics_reflect_fill_premium(self):
        contracts, approved = self.approved()
        long_symbol = next(l.option_symbol for l in approved.candidate.legs if l.side == "buy_to_open")
        filled = self.revalidate(approved, self._bump(contracts, long_symbol, -0.05)).to_fill_candidate().candidate
        legs = pricing.legs_from_candidate(filled)
        expected = pricing.prob_profit(legs, approved.candidate.net_credit, spot=600, sigma=filled.analytics["model"]["sigma_iv"], years=pricing.years_from_dte(filled.dte))
        self.assertAlmostEqual(filled.analytics["model"]["pop_iv"], expected)
        self.assertEqual([g.name for g in filled.gates].count("POP_OK"), 1)

    def test_delta_drift_out_of_band_rejects(self):
        contracts, approved = self.approved()
        long_symbol = next(l.option_symbol for l in approved.candidate.legs if l.side == "buy_to_open")
        drifted = [replace(c, delta=0.95) if c.symbol == long_symbol else c for c in contracts]
        with self.assertRaisesRegex(RevalidationRejected, "no longer passes"):
            self.revalidate(approved, drifted)

    def test_sidecar_round_trip_keeps_analytics_and_unbounded_profit(self):
        profile = self.cfg.anchor("speculation")
        _, contracts = chain(spot=600, sigma=0.15, dte=45)
        out = scan_objective("SPY", contracts, self.cfg, profile, spot=600, situation=situation(rv=0.25, iv=0.15), bias="bullish", as_of=AS_OF)
        long_call = next(c for c in out if c.strategy == StrategyKind.LONG_CALL)
        sized = size_candidate(long_call, account(1_000_000, 1_000_000), self.cfg.credit_strategy_config(profile, "bullish"))
        raw = json.loads(json.dumps({**sized.candidate.to_dict(), "contracts": sized.contracts}))
        back = sized_candidate_from_dict(raw)
        self.assertIsNone(back.candidate.max_profit)
        self.assertIsNone(back.candidate.premium_to_bpr)
        self.assertEqual(back.candidate.analytics["profile"]["objective"], "speculation")


class LedgerAndManagementTests(unittest.TestCase):
    def long_call_item(self):
        cfg = ObjectiveConfig.load(CONFIG_PATH)
        profile = cfg.anchor("speculation")
        _, contracts = chain(spot=600, sigma=0.15, dte=45)
        out = scan_objective("SPY", contracts, cfg, profile, spot=600, situation=situation(rv=0.25, iv=0.15), bias="bullish", as_of=AS_OF)
        c = next(c for c in out if c.strategy == StrategyKind.LONG_CALL)
        return size_candidate(c, account(1_000_000, 1_000_000), cfg.credit_strategy_config(profile, "bullish"))

    def test_debit_lifecycle(self):
        item = self.long_call_item()
        with tempfile.TemporaryDirectory() as td, OptionsPaperLedger(Path(td) / "l.db") as ledger:
            pid = ledger.open_position(item)
            self.assertIsNone(ledger.open_positions()[0]["max_profit"])
            with self.assertRaises(ValueError):
                ledger.close_position(pid, exit_debit=0.5, reason="bad sign")
            sell_at = -item.candidate.net_credit * 2  # doubled
            row = ledger.close_position(pid, exit_debit=-sell_at, reason="CLOSE_WINNER")
            self.assertAlmostEqual(row["realized_pnl"], -item.candidate.net_credit * 100 * item.contracts)
            self.assertEqual(row["outcome"], "WIN")

    def test_credit_positions_reject_negative_exit(self):
        cfg = relaxed_cfg()
        profile = cfg.anchor("income")
        _, contracts = chain(spot=600, sigma=0.25, dte=45)
        c = scan_objective("SPY", contracts, cfg, profile, spot=600, situation=situation(iv=0.25), bias="neutral", as_of=AS_OF)[0]
        item = size_candidate(c, account(), cfg.credit_strategy_config(profile, "neutral"))
        with tempfile.TemporaryDirectory() as td, OptionsPaperLedger(Path(td) / "l.db") as ledger:
            pid = ledger.open_position(item)
            with self.assertRaises(ValueError):
                ledger.close_position(pid, exit_debit=-0.1, reason="bad sign")

    def test_migrates_v1_not_null_schema(self):
        # V1 DDL verbatim (column order and constraints), including max_profit NOT NULL.
        ddl = """CREATE TABLE options_positions (id TEXT PRIMARY KEY, signature TEXT NOT NULL, approval_slug TEXT, underlying TEXT NOT NULL,
            strategy TEXT NOT NULL, expiration TEXT NOT NULL, direction TEXT NOT NULL, quantity INTEGER NOT NULL, legs_json TEXT NOT NULL,
            entry_credit REAL NOT NULL, entry_mark_credit REAL NOT NULL, max_profit REAL NOT NULL, max_loss REAL NOT NULL,
            buying_power_reduction REAL NOT NULL, profit_target_pct REAL NOT NULL, manage_at_dte INTEGER NOT NULL, strategy_version TEXT NOT NULL,
            status TEXT NOT NULL, entry_time TEXT NOT NULL, exit_time TEXT, exit_debit REAL, realized_pnl REAL, outcome TEXT, close_reason TEXT,
            candidate_json TEXT NOT NULL)"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "v1.db"
            conn = sqlite3.connect(path)
            conn.execute(ddl)
            conn.execute("INSERT INTO options_positions (id,signature,underlying,strategy,expiration,direction,quantity,legs_json,entry_credit,entry_mark_credit,max_profit,max_loss,buying_power_reduction,profit_target_pct,manage_at_dte,strategy_version,status,entry_time,candidate_json) VALUES ('old','sig','SPY','short_put_vertical','2026-10-30','long',1,'[]',1.0,1.0,100,400,400,0.5,21,'tasty_defined_risk_v1','OPEN','t','{}')")
            conn.commit()
            conn.close()
            with OptionsPaperLedger(path) as ledger:
                notnull = {r["name"]: r["notnull"] for r in ledger.conn.execute("PRAGMA table_info(options_positions)")}
                self.assertEqual(notnull["max_profit"], 0)
                self.assertEqual([r["id"] for r in ledger.open_positions()], ["old"])
                ledger.open_position(self.long_call_item())
            with OptionsPaperLedger(path) as ledger:
                self.assertEqual(len(ledger.all_positions()), 2)

    def debit_state(self, *, expiration="2026-11-30", max_profit=None):
        return PositionState("p", "SPY", StrategyKind.LONG_CALL, expiration, "t", -4.0, 0.0, 2, max_profit, 800.0, 1.0, 7)

    def test_debit_management_rules(self):
        cases = [
            (dict(current_close_value=8.0, stop_loss_pct=None), ManagementAction.CLOSE_WINNER),
            (dict(current_close_value=1.9, stop_loss_pct=0.5), ManagementAction.CLOSE_STOP_LOSS),
            (dict(current_close_value=1.9, stop_loss_pct=None), ManagementAction.HOLD),
            (dict(current_close_value=5.0, stop_loss_pct=0.5), ManagementAction.HOLD),
        ]
        for kwargs, action in cases:
            d = manage_debit_position(self.debit_state(), force_close_at_dte=1, as_of=AS_OF, **kwargs)
            self.assertEqual(d.action, action, kwargs)
        self.assertEqual(manage_debit_position(self.debit_state(expiration="2026-09-20"), current_close_value=4.5, stop_loss_pct=None, force_close_at_dte=1, as_of=AS_OF).action, ManagementAction.CLOSE_AT_MANAGEMENT_DTE)
        self.assertEqual(manage_debit_position(self.debit_state(expiration="2026-09-16"), current_close_value=4.5, stop_loss_pct=None, force_close_at_dte=1, as_of=AS_OF).action, ManagementAction.CLOSE_BEFORE_EXPIRATION)
        # vertical target capped at max profit: +100% of $800 would exceed $500 cap
        capped = manage_debit_position(self.debit_state(max_profit=500.0), current_close_value=6.6, stop_loss_pct=None, force_close_at_dte=1, as_of=AS_OF)
        self.assertEqual(capped.action, ManagementAction.CLOSE_WINNER)
        with self.assertRaises(ValueError):
            manage_debit_position(replace(self.debit_state(), entry_credit=1.0), current_close_value=1.0, stop_loss_pct=None, force_close_at_dte=1)

    def test_close_value_signs(self):
        legs = [{"option_symbol": "L", "side": "buy_to_open", "quantity": 1}, {"option_symbol": "S", "side": "sell_to_open", "quantity": 1}]
        quotes = {"L": {"bid": 5.0, "ask": 5.2}, "S": {"bid": 2.0, "ask": 2.1}}
        self.assertAlmostEqual(natural_close_value(legs, quotes), 2.9)
        self.assertEqual(natural_close_debit(legs, quotes), 0.0)

    def test_plan_position_routes_debit_rows(self):
        item = self.long_call_item()
        symbol = item.candidate.legs[0].option_symbol
        with tempfile.TemporaryDirectory() as td, OptionsPaperLedger(Path(td) / "l.db") as ledger:
            ledger.open_position(item)
            row = ledger.open_positions()[0]
        debit = -item.candidate.net_credit
        v1 = StrategyConfig.load(ROOT / "strategy/tasty_defined_risk_v1.yaml")
        decision, exit_debit = plan_position(row, {symbol: {"bid": debit * 2.2, "ask": debit * 2.3}}, v1, as_of=AS_OF)
        self.assertEqual(decision.action, ManagementAction.CLOSE_WINNER)
        self.assertAlmostEqual(exit_debit, -debit * 2.2)
        decision, _ = plan_position(row, {symbol: {"bid": debit * 0.9, "ask": debit}}, v1, as_of=AS_OF)
        self.assertEqual(decision.action, ManagementAction.HOLD)


class FakeClient:
    """Duck-typed read-only Tradier surface over synthetic data."""

    def __init__(self, books: dict[str, dict]):
        self.books = books
        self.calls: list[tuple] = []

    def quotes(self, symbols, greeks=False):
        return [{"symbol": s, "last": self.books[s]["spot"]} for s in symbols]

    def history(self, symbol, interval="daily", start=None, end=None):
        self.calls.append(("history", symbol, start, end))
        return self.books[symbol]["history"]

    def option_expirations(self, symbol):
        return sorted(self.books[symbol]["chains"])

    def option_chain(self, symbol, expiration, greeks=True):
        self.calls.append(("chain", symbol, expiration))
        return self.books[symbol]["chains"][expiration]

    def balances(self):
        return account(1_000_000, 1_000_000)

    def positions(self):
        return self.books.get("_positions", [])


def book(*, drift, vol, iv):
    rows = history(daily_drift=drift, daily_vol=vol)
    spot = closes_from_history(rows)[-1]
    chains = {}
    for dte in (30, 45, 75):
        expiration, contracts = chain(spot=spot, sigma=iv, dte=dte)
        chains[expiration] = contracts
    return {"spot": spot, "history": rows, "chains": chains}


class EndToEndScanTests(unittest.TestCase):
    def test_auto_scan_sidecar_and_intake(self):
        cfg = ObjectiveConfig.load(CONFIG_PATH)
        client = FakeClient({
            "QQQ": book(drift=0.004, vol=0.006, iv=0.08),  # cheap vol, strong uptrend -> speculation
            "IWM": book(drift=0.0, vol=0.012, iv=0.15),  # cheap vol, no trend -> no edge
        })
        out = run_objective_scan(client, cfg, ("QQQ", "IWM"), as_of=AS_OF)
        self.assertTrue(out.sized)
        self.assertTrue(all(i.candidate.underlying == "QQQ" and i.candidate.objective == "speculation" for i in out.sized))
        self.assertTrue(any(d["symbol"] == "IWM" and "no structural edge" in d["reason"] for d in out.diagnostics))
        self.assertLessEqual(max(i.total_max_loss for i in out.sized), 1_000_000 * cfg.anchor("speculation").risk_per_trade_pct)

        payload = json.loads(json.dumps(sidecar_payload(out, captured_at="2026-09-15T15:00:00Z", cfg=cfg, request={"objective": "auto"}), default=str))
        self.assertEqual(payload["candidate_count"], len(out.sized))
        self.assertEqual({s["symbol"] for s in payload["symbols"]}, {"QQQ", "IWM"})

        text = render_objective_intake(out.sized, captured_at="2026-09-15T15:00:00Z", sidecar_path="/tmp/s.json", request={"objective": "auto"})
        report = parse_intake_report(text)
        self.assertEqual(len(report.candidates), len(out.sized))
        first = report.candidates[0]
        self.assertEqual(first.fields["candidate_id"], candidate_id(out.sized[0]))
        self.assertEqual(first.fields["objective"], "speculation")
        self.assertTrue(first.fields["entry"].startswith("debit "))
        self.assertEqual(report.metadata["sidecar_json"], "/tmp/s.json")

    def test_explicit_income_neutral_and_broker_duplicate(self):
        cfg = relaxed_cfg()
        books = {"SPY": book(drift=0.0, vol=0.012, iv=0.25)}
        out = run_objective_scan(FakeClient(books), cfg, ("SPY",), objective="income", as_of=AS_OF)
        self.assertTrue(out.sized)
        self.assertTrue(all(i.candidate.strategy == StrategyKind.IRON_CONDOR for i in out.sized))
        top = out.sized[0].candidate
        books["_positions"] = [{"symbol": l.option_symbol, "quantity": (1 if l.side == "buy_to_open" else -1)} for l in top.legs]
        again = run_objective_scan(FakeClient(books), cfg, ("SPY",), objective="income", as_of=AS_OF)
        self.assertNotIn(candidate_id(out.sized[0]), [candidate_id(i) for i in again.sized])
        self.assertTrue(any("already open in Tradier" in d["reason"] for d in again.diagnostics))

    def test_reference_chain_reused_when_same_expiration(self):
        cfg = ObjectiveConfig.load(CONFIG_PATH)
        client = FakeClient({"QQQ": book(drift=0.004, vol=0.006, iv=0.08)})
        run_objective_scan(client, cfg, ("QQQ",), aggression=1.0, as_of=AS_OF)
        chain_calls = [c for c in client.calls if c[0] == "chain"]
        self.assertEqual(len(chain_calls), len({c[2] for c in chain_calls}))

    def test_spot_from_quote(self):
        self.assertEqual(spot_from_quote({"last": 10.0, "bid": 9, "ask": 11}), 10.0)
        self.assertEqual(spot_from_quote({"last": None, "bid": 9, "ask": 11}), 10.0)
        self.assertIsNone(spot_from_quote({"last": 0, "bid": 0, "ask": 0, "prevclose": 9}))


if __name__ == "__main__":
    unittest.main()
