#!/usr/bin/env python3
"""Post-approval paper fill: re-fetch exact OCC legs, re-run gates, never chase.

Works for V1 credit candidates (tasty_defined_risk_v1) and objective candidates
(objective_options_v1, credit or debit). The candidate's ``strategy_version``
selects which gates are re-run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trading.config import StrategyConfig  # noqa: E402
from trading.duplicates import broker_has_exact_structure  # noqa: E402
from trading.objective_scan import is_objective_candidate, revalidation_context, spot_from_quote  # noqa: E402
from trading.objectives import ObjectiveConfig  # noqa: E402
from trading.paper_options import OptionsPaperLedger  # noqa: E402
from trading.revalidate import RevalidationRejected, revalidate_for_paper_fill  # noqa: E402
from trading.tradier import TradierClient  # noqa: E402
from trading.types import sized_candidate_from_dict  # noqa: E402


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("candidate_json")
    p.add_argument("--approval-slug", required=True)
    p.add_argument("--config", default=str(ROOT / "strategy/tasty_defined_risk_v1.yaml"))
    p.add_argument("--objective-config", default=os.environ.get("OBJECTIVE_STRATEGY_CONFIG", str(ROOT / "strategy/objective_options_v1.yaml")))
    p.add_argument("--ledger", default=os.environ.get("OPTIONS_LEDGER_DB", str(ROOT / "work/options/options_ledger.db")))
    p.add_argument("--export")
    p.add_argument("--snapshot-output")
    a = p.parse_args()

    raw = json.loads(Path(a.candidate_json).read_text(encoding="utf-8"))
    if "candidates" in raw:
        if len(raw["candidates"]) != 1:
            raise SystemExit("sidecar must contain exactly one selected candidate")
        raw = raw["candidates"][0]
    approved = sized_candidate_from_dict(raw)
    objective_cfg = ObjectiveConfig.load(a.objective_config)
    objective = is_objective_candidate(approved.candidate, objective_cfg)

    client = TradierClient.from_env(live_data=True)
    if not client.market_is_open():
        print("WAIT_REPROPOSE: US market is not open; do not paper-fill stale/non-executable quotes")
        return 2
    account = client.balances()
    if broker_has_exact_structure(approved.candidate, client.positions()):
        print("WAIT_REPROPOSE: exact OCC structure is already open in Tradier account")
        return 2

    underlying = approved.candidate.underlying
    chain = client.option_chain(underlying, approved.candidate.expiration, greeks=True)
    rescan = fill_gate = None
    if objective:
        quotes = client.quotes([underlying])
        spot = spot_from_quote(quotes[0]) if quotes else None
        if spot is None:
            print("WAIT_REPROPOSE: no live underlying price for objective gates")
            return 2
        rescan, cfg, fill_gate = revalidation_context(objective_cfg, approved.candidate, spot=spot)
    else:
        cfg = StrategyConfig.load(a.config)

    with OptionsPaperLedger(a.ledger) as ledger:
        try:
            rv = revalidate_for_paper_fill(approved, chain, account, cfg, committed_defined_risk=ledger.committed_defined_risk(), rescan=rescan, fill_gate=fill_gate)
        except RevalidationRejected as exc:
            print(f"WAIT_REPROPOSE: {exc}")
            return 2
        filled = rv.to_fill_candidate()
        position_id = ledger.open_position(filled, approval_slug=a.approval_slug)
        if a.export:
            ledger.export_json(a.export)

    if a.snapshot_output:
        atomic_json(Path(a.snapshot_output), {
            "approval_slug": a.approval_slug,
            "underlying": filled.candidate.underlying,
            "strategy": filled.candidate.strategy.value,
            "strategy_version": filled.candidate.strategy_version,
            "objective": filled.candidate.objective,
            "expiration": filled.candidate.expiration,
            "approved_limit_credit": rv.approved_limit_credit,
            "current_natural_credit": rv.current_natural_credit,
            "paper_fill_credit": rv.fill_credit,
            "premium_convention": "signed per share: positive credit, negative debit",
            "contracts": filled.contracts,
            "total_max_loss": filled.total_max_loss,
            "option_buying_power_at_recheck": account.option_buying_power,
            "total_equity_at_recheck": account.total_equity,
            "fresh_candidate": filled.candidate.to_dict(),
            "rate_limit": client.last_rate_limit.__dict__,
        })
    kind = "debit" if filled.candidate.is_debit else "credit"
    print(f"PAPER_FILLED position_id={position_id} {kind}={abs(rv.fill_credit):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
