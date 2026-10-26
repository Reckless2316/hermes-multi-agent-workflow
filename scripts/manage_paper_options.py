#!/usr/bin/env python3
"""Mechanically manage open paper options positions at conservative natural prices."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trading.config import StrategyConfig  # noqa: E402
from trading.paper_options import OptionsPaperLedger  # noqa: E402
from trading.position_manager import plan_position  # noqa: E402
from trading.tradier import TradierClient  # noqa: E402
from trading.types import ManagementAction  # noqa: E402

CLOSE_ACTIONS = {
    ManagementAction.CLOSE_WINNER,
    ManagementAction.CLOSE_AT_MANAGEMENT_DTE,
    ManagementAction.CLOSE_BEFORE_EXPIRATION,
    ManagementAction.CLOSE_STOP_LOSS,
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=str(ROOT / "strategy/tasty_defined_risk_v1.yaml"))
    p.add_argument("--ledger", default=os.environ.get("OPTIONS_LEDGER_DB", str(ROOT / "work/options/options_ledger.db")))
    p.add_argument("--export")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    cfg = StrategyConfig.load(a.config)
    client = TradierClient.from_env(live_data=True)
    closed: list[dict] = []
    reviews: list[dict] = []
    if not client.market_is_open():
        print(json.dumps({"closed": [], "reviews": [{"action": "MARKET_CLOSED", "reason": "No automatic paper close outside regular Tradier market-open state"}]}, indent=2))
        return 0

    with OptionsPaperLedger(a.ledger) as ledger:
        positions = ledger.open_positions()
        if not positions:
            print("open_positions=0")
            return 0
        symbols = sorted({leg["option_symbol"] for row in positions for leg in json.loads(row["legs_json"])})
        quotes = {str(q.get("symbol")): q for q in client.quotes(symbols)}
        for row in positions:
            try:
                decision, exit_debit = plan_position(row, quotes, cfg)
            except ValueError as exc:
                reviews.append({"position_id": row["id"], "action": "DATA_ERROR", "reason": str(exc)})
                continue
            record = {
                "position_id": row["id"],
                "underlying": row["underlying"],
                "strategy": row["strategy"],
                "action": decision.action.value,
                "reason": decision.reason,
                "exit_debit": exit_debit,
                "pnl_dollars": decision.pnl_dollars,
                "pct_max_profit": decision.pct_max_profit,
                "dte": decision.dte,
            }
            if decision.action in CLOSE_ACTIONS:
                if not a.dry_run:
                    ledger.close_position(row["id"], exit_debit=exit_debit, reason=decision.action.value)
                closed.append(record)
            elif decision.action != ManagementAction.HOLD:
                reviews.append(record)
        if a.export:
            ledger.export_json(a.export)
    print(json.dumps({"closed": closed, "reviews": reviews}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
