"""TASTY_DEFINED_RISK_V1 — deterministic scanner, paper manager, intake.

No live Tradier calls. Replay fixtures only.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from desk.config import DeskConfig  # noqa: E402
from desk.data.replay import ReplayAdapter  # noqa: E402
from desk.data.tradier import TradierAdapter  # noqa: E402
from desk.intake import results_to_intake  # noqa: E402
from desk.paper import PaperTrader  # noqa: E402
from desk.strategy.tasty_v1 import best_take, scan_all, scan_symbol  # noqa: E402
from desk.types import SetupStatus  # noqa: E402
from engine.intake_parser import parse_intake_report  # noqa: E402


AS_OF = date(2026, 9, 15)
EXP = AS_OF + timedelta(days=45)


def _cfg(**overrides) -> DeskConfig:
    data = {
        "strategy": {
            "name": "tasty_defined_risk_v1",
            "universe": ["SPY"],
            "entry": {
                "dte": {"min": 25, "target": 45, "max": 55},
                "defined_risk_only": True,
                "allowed_structures": ["short_put_vertical", "short_call_vertical", "iron_condor"],
            },
            "widths": [5, 10],
            "short_delta": {"min": 0.16, "max": 0.35},
            "min_credit_over_width": 0.20,
            "portfolio": {"nav": 100000, "max_risk_per_trade_pct": 2.0,
                          "max_total_buying_power_pct": 50.0, "max_correlated_exposure_pct": 25.0},
        }
    }
    data["strategy"].update(overrides)
    return DeskConfig.from_dict(data)


def _put_only() -> DeskConfig:
    return _cfg(entry={
        "dte": {"min": 25, "target": 45, "max": 55},
        "defined_risk_only": True,
        "allowed_structures": ["short_put_vertical"],
    })


def _opt(strike, right, bid, ask, delta, occ=None, volume=200, oi=2000):
    return {
        "occ": occ or f"SPY{EXP.strftime('%y%m%d')}{right[0].upper()}{int(strike*1000):08d}",
        "strike": strike,
        "right": right,
        "bid": bid,
        "ask": ask,
        "last": (bid + ask) / 2,
        "volume": volume,
        "open_interest": oi,
        "delta": delta,
        "gamma": 0.01,
        "theta": -0.04,
        "vega": 0.08,
        "mid_iv": 0.18,
    }


def _payload(extra_puts=None) -> dict:
    puts = extra_puts or [
        # 10-wide 640/630 — fat credit, should win capital-efficiency vs 5-wide
        _opt(640, "put", 5.40, 5.60, -0.27),
        _opt(630, "put", 1.90, 2.10, -0.14),
        # 5-wide 645/640 — thinner credit/width still legal
        _opt(645, "put", 6.90, 7.10, -0.33),
    ]
    calls = [
        _opt(660, "call", 5.40, 5.60, 0.27),
        _opt(670, "call", 1.90, 2.10, 0.14),
    ]
    return {
        "quotes": {"SPY": {"last": 650.0, "bid": 649.9, "ask": 650.1, "volume": 80_000_000}},
        "expirations": {"SPY": [EXP.isoformat()]},
        "chains": {f"SPY:{EXP.isoformat()}": puts + calls},
        "iv_rank": {"SPY": 46},
    }


class TestTastyScanner(unittest.TestCase):
    def test_take_put_vertical_with_levels(self):
        state = ReplayAdapter(_payload()).build_state(["SPY"], AS_OF, 25, 55)
        results = scan_symbol(state, "SPY", _put_only())
        take = best_take(results)
        self.assertIsNotNone(take)
        assert take is not None
        self.assertEqual(take.status, SetupStatus.TAKE)
        self.assertEqual(take.spread.structure, "short_put_vertical")
        self.assertGreater(take.spread.max_loss, 0)
        self.assertGreater(take.spread.credit, 0)
        self.assertIn("DEFINED_RISK", take.gates_passed)
        self.assertIn("PORTFOLIO_OK", take.gates_passed)
        self.assertEqual(take.management_dte, 21)
        self.assertAlmostEqual(take.profit_target or 0, take.spread.max_profit * take.qty * 0.5, places=4)

    def test_ranks_capital_efficiency_not_pop(self):
        state = ReplayAdapter(_payload()).build_state(["SPY"], AS_OF, 25, 55)
        results = [r for r in scan_symbol(state, "SPY", _put_only()) if r.status == SetupStatus.TAKE]
        widths = {round(r.spread.width, 1): r.capital_efficiency for r in results if r.spread}
        self.assertIn(10.0, widths)
        self.assertIn(5.0, widths)
        self.assertGreater(widths[10.0], widths[5.0])
        best = best_take(results)
        self.assertEqual(best.spread.width, 10.0)

    def test_wait_on_stale_quote(self):
        puts = [_opt(640, "put", 0, 5.6, -0.27), _opt(630, "put", 1.9, 2.1, -0.14)]
        state = ReplayAdapter(_payload(puts)).build_state(["SPY"], AS_OF, 25, 55)
        results = scan_symbol(state, "SPY", _put_only())
        self.assertTrue(any(r.status == SetupStatus.WAIT and "DATA_OK" in r.reason for r in results))

    def test_skip_delta_too_high(self):
        puts = [_opt(640, "put", 8.4, 8.6, -0.55), _opt(630, "put", 5.9, 6.1, -0.40)]
        state = ReplayAdapter(_payload(puts)).build_state(["SPY"], AS_OF, 25, 55)
        results = [r for r in scan_symbol(state, "SPY", _put_only()) if r.spread and r.spread.structure == "short_put_vertical"]
        self.assertTrue(all(r.status == SetupStatus.SKIP for r in results))
        self.assertTrue(any("SHORT_DELTA" in r.reason for r in results))

    def test_portfolio_blocks_oversize(self):
        cfg = _cfg()
        # 2% of 100k = 2000. Force a huge max_loss by using tiny credit on 10-wide... 
        # Instead shrink nav.
        cfg = DeskConfig.from_dict({
            "strategy": {
                "universe": ["SPY"],
                "entry": {"dte": {"min": 25, "max": 55}, "allowed_structures": ["short_put_vertical"]},
                "widths": [10],
                "short_delta": {"min": 0.16, "max": 0.35},
                "min_credit_over_width": 0.20,
                "portfolio": {"nav": 1000, "max_risk_per_trade_pct": 2.0,
                              "max_total_buying_power_pct": 50, "max_correlated_exposure_pct": 25},
            }
        })
        state = ReplayAdapter(_payload()).build_state(["SPY"], AS_OF, 25, 55)
        results = scan_symbol(state, "SPY", cfg)
        takes = [r for r in results if r.status == SetupStatus.TAKE]
        self.assertEqual(takes, [])
        self.assertTrue(any("per-trade budget" in r.reason for r in results))

    def test_scan_all_one_best_per_symbol(self):
        state = ReplayAdapter(_payload()).build_state(["SPY"], AS_OF, 25, 55)
        chosen = scan_all(state, _cfg())
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0].status, SetupStatus.TAKE)


class TestIntakeAndPaper(unittest.TestCase):
    def test_intake_parses_through_hermes_parser(self):
        state = ReplayAdapter(_payload()).build_state(["SPY"], AS_OF, 25, 55)
        take = best_take(scan_symbol(state, "SPY", _put_only()))
        md = results_to_intake([take])
        report = parse_intake_report(md)
        self.assertEqual(report.metadata["scanner"], "tasty_defined_risk_v1")
        self.assertEqual(len(report.candidates), 1)
        c = report.candidates[0]
        self.assertEqual(c.fields["symbol"], "SPY")
        self.assertEqual(c.fields["setup_status"], "TAKE")
        self.assertEqual(c.fields["structure"], "short_put_vertical")
        self.assertTrue(c.fields["max_loss"])

    def test_paper_fill_and_profit_target(self):
        state = ReplayAdapter(_payload()).build_state(["SPY"], AS_OF, 25, 55)
        take = best_take(scan_symbol(state, "SPY", _put_only()))
        with tempfile.TemporaryDirectory() as td:
            journal = Path(td) / "trades.json"
            trader = PaperTrader(journal, _put_only())
            trade = trader.open_from_scan(take)
            self.assertEqual(trade.status, "OPEN")
            # credit dropped enough to hit 50% of max profit
            mark = trade.credit - (trade.profit_target / (100 * trade.qty))
            closed = trader.manage(AS_OF, {trade.id: mark})
            self.assertEqual(len(closed), 1)
            self.assertEqual(closed[0]["status"], "CLOSED")
            self.assertIn("profit_target", closed[0]["reason"])

    def test_paper_manage_at_21_dte(self):
        state = ReplayAdapter(_payload()).build_state(["SPY"], AS_OF, 25, 55)
        take = best_take(scan_symbol(state, "SPY", _put_only()))
        with tempfile.TemporaryDirectory() as td:
            journal = Path(td) / "trades.json"
            trader = PaperTrader(journal, _put_only())
            trade = trader.open_from_scan(take)
            near = EXP - timedelta(days=20)
            closed = trader.manage(near, None)
            self.assertEqual(len(closed), 1)
            self.assertIn("manage_at_dte", closed[0]["reason"])


class TestTradierParser(unittest.TestCase):
    def test_parses_chain_without_network(self):
        body = json.dumps({
            "options": {"option": [{
                "symbol": "SPY260930P00640000",
                "strike": 640,
                "option_type": "put",
                "bid": 5.4, "ask": 5.6, "last": 5.5,
                "volume": 10, "open_interest": 100,
                "greeks": {"delta": -0.27, "mid_iv": 0.18},
            }]}
        }).encode()

        def opener(req, timeout=0):
            self.assertIn("Bearer test-token", req.headers["Authorization"])
            return body

        ad = TradierAdapter(token="test-token", opener=opener)
        chain = ad.fetch_chain("SPY", EXP)
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0].right, "put")
        self.assertEqual(chain[0].delta, -0.27)

    def test_missing_token_fails_loudly(self):
        ad = TradierAdapter(token="")
        with self.assertRaises(RuntimeError):
            ad.fetch_underlying("SPY")


class TestEngineStaysGeneric(unittest.TestCase):
    def test_engine_package_has_no_tradier(self):
        root = Path(__file__).resolve().parent.parent / "engine"
        blob = "\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.py"))
        self.assertNotIn("tradier", blob.lower())
        self.assertNotIn("tasty", blob.lower())


if __name__ == "__main__":
    unittest.main()
