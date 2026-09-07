"""Domain tests for the automated-trading triage.yaml.

Generic engine tests stay in test_engine_core.py (synthetic config).
These load the real desk config: scoring around the 70 bar, and every
classifier value in route.map.
"""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import TriageConfig  # noqa: E402
from engine.engine import TriageEngine  # noqa: E402
from engine.intake_parser import parse_intake_report  # noqa: E402
from engine.routing import route_from_classification  # noqa: E402
from engine.scoring import score_candidate_heuristic, score_from_breakdown  # noqa: E402


ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "triage.yaml"


class TestTradingConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = TriageConfig.load(CONFIG)

    def test_desk_identity(self):
        self.assertEqual(self.cfg.name, "automated-trading")
        self.assertEqual(self.cfg.board, "trading")
        self.assertEqual([s.id for s in self.cfg.sources], ["options", "swing"])
        self.assertEqual({s.skill for s in self.cfg.sources}, {"triage-scout-options", "triage-scout-swing"})

    def test_every_classifier_value_has_a_path(self):
        self.assertEqual(
            self.cfg.route.map,
            {
                "options_take": "options",
                "swing_take": "swing",
                "wait": "watch",
                "skip": "shelve",
                "no_edge": "shelve",
            },
        )
        for target in self.cfg.route.map.values():
            self.assertIn(target, self.cfg.paths)

    def test_threshold_is_reachable_but_not_trivial(self):
        self.assertEqual(self.cfg.rubric.threshold, 70)
        self.assertEqual(self.cfg.rubric.max_total, 100)
        self.assertLess(self.cfg.rubric.threshold, self.cfg.rubric.max_total)

    def test_fulfillment_is_persistent_dir(self):
        engine = TriageEngine(self.cfg)
        for path_name, subdir in (("options", "options"), ("swing", "swings"), ("watch", "watchlist")):
            specs = engine.fulfillment_specs("btc-long-fvg", path_name)
            self.assertGreaterEqual(len(specs), 1)
            for s in specs:
                self.assertEqual(s.workspace_kind, "dir")
                self.assertIn(subdir, s.workspace_path)
                self.assertIn("btc-long-fvg", s.workspace_path)

    def test_shelve_is_auto(self):
        self.assertTrue(self.cfg.get_path("shelve").auto)


class TestTradingScoring(unittest.TestCase):
    def setUp(self):
        self.cfg = TriageConfig.load(CONFIG)

    def test_strong_breakdown_advances(self):
        r = score_from_breakdown(
            {
                "setup_clarity": 22,
                "risk_reward": 16,
                "gate_completeness": 22,
                "market_context": 12,
                "uniqueness": 12,
            },
            self.cfg.rubric,
        )
        self.assertGreaterEqual(r.total, 70)
        self.assertTrue(r.advance)

    def test_weak_breakdown_does_not_advance(self):
        r = score_from_breakdown(
            {
                "setup_clarity": 8,
                "risk_reward": 5,
                "gate_completeness": 8,
                "market_context": 4,
                "uniqueness": 4,
            },
            self.cfg.rubric,
        )
        self.assertLess(r.total, 70)
        self.assertFalse(r.advance)

    def test_heuristic_take_with_levels_can_clear(self):
        cand = {
            "title": "BTC long 4h/15m",
            "claim": "dumb obvious HTF failure swing into aligned 15m FVG",
            "why_it_may_matter": "liquid perp, HTF aligned",
            "setup_status": "TAKE",
            "style": "swing",
            "entry": "64200",
            "stop": "63100",
            "target": "66400",
            "gates_passed": "DATA_OK, HTF_BIAS, LTF_FVG, CISD_CONFIRM, LEVELS",
            "risk_r": "2",
            "reason": "All gates passed",
            "sources": [{"url": "https://example.test/btc"}],
        }
        r = score_candidate_heuristic(cand, self.cfg.rubric)
        self.assertTrue(r.advance, msg=r.breakdown)

    def test_heuristic_naked_options_fails_risk(self):
        cand = {
            "title": "NVDA naked calls",
            "claim": "undefined risk lottery",
            "style": "options",
            "setup_status": "TAKE",
            "reason": "naked short premium",
            "sources": [{"url": "https://example.test/nvda"}],
        }
        r = score_candidate_heuristic(cand, self.cfg.rubric)
        self.assertEqual(r.breakdown["risk_reward"], 0)
        self.assertFalse(r.advance)


class TestTradingRouting(unittest.TestCase):
    def setUp(self):
        self.cfg = TriageConfig.load(CONFIG)

    def test_each_disposition(self):
        cases = {
            "options_take": "options",
            "SWING_TAKE": "swing",
            "wait": "watch",
            "skip": "shelve",
            "no_edge": "shelve",
        }
        for value, path in cases.items():
            self.assertEqual(route_from_classification(value, self.cfg.route), path)


class TestIntakeParser(unittest.TestCase):
    def test_parses_trading_fields(self):
        report = parse_intake_report(
            """
source: swing
captured_at: 2026-09-07T18:00:00Z

## Candidate: BTC long 4h/15m
Claim: HTF failure swing, LTF FVG tap, CISD printed
Sources:
  - url: https://example.test/chart
    quote: "CISD through 1h swing low"
Symbol: BTC
Style: swing
Direction: long
Setup status: TAKE
Entry: 64200
Stop: 63100
Target: 66400
Gates passed: DATA_OK, HTF_BIAS, LTF_FVG, CISD_CONFIRM, LEVELS
Why it may matter: liquid perp, dumb obvious
""".strip()
        )
        self.assertEqual(report.metadata["source"], "swing")
        self.assertEqual(len(report.candidates), 1)
        c = report.candidates[0]
        self.assertEqual(c.title, "BTC long 4h/15m")
        self.assertIn("failure swing", c.claim)
        self.assertEqual(c.sources[0]["url"], "https://example.test/chart")
        self.assertEqual(c.why_it_may_matter, "liquid perp, dumb obvious")
        self.assertEqual(c.fields["symbol"], "BTC")
        self.assertEqual(c.fields["setup_status"], "TAKE")
        self.assertEqual(c.fields["entry"], "64200")
        self.assertIn("CISD_CONFIRM", c.fields["gates_passed"])


if __name__ == "__main__":
    unittest.main()
