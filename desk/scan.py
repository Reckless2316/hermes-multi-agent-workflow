"""CLI: python -m desk.scan [--replay FILE] [--emit-intake]

Live path needs TRADIER_ACCESS_TOKEN. Replay path needs no secrets.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone

from .config import DeskConfig
from .data.replay import ReplayAdapter
from .data.tradier import TradierAdapter
from .intake import results_to_intake
from .portfolio import PortfolioState
from .strategy.tasty_v1 import scan_all
from .types import SetupStatus


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m desk.scan")
    p.add_argument("--config", default=None)
    p.add_argument("--replay", default=None, help="Fixture JSON (no network)")
    p.add_argument("--as-of", default=None, help="YYYY-MM-DD (default today UTC)")
    p.add_argument("--emit-intake", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    cfg = DeskConfig.load(args.config)
    as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc).date()
    if args.replay:
        adapter = ReplayAdapter.from_path(args.replay)
    else:
        adapter = TradierAdapter()
    state = adapter.build_state(cfg.universe, as_of, cfg.dte_min, cfg.dte_max)
    results = scan_all(state, cfg, PortfolioState(nav=cfg.nav))
    if args.emit_intake:
        sys.stdout.write(results_to_intake(results))
        return 0
    if args.json:
        sys.stdout.write(json.dumps([r.to_dict() for r in results], indent=2, default=str) + "\n")
        return 0
    takes = [r for r in results if r.status == SetupStatus.TAKE]
    print(f"as_of={as_of}  takes={len(takes)}  reported={len(results)}")
    for r in results:
        ce = f" ce={r.capital_efficiency:.3f}" if r.capital_efficiency is not None else ""
        print(f"  {r.status.value:9} {r.symbol:5} {r.reason}{ce}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
