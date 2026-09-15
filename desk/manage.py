"""CLI: python -m desk.manage --journal PATH --as-of YYYY-MM-DD [--marks PATH]"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

from .config import DeskConfig
from .paper import PaperTrader


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m desk.manage")
    p.add_argument("--journal", required=True)
    p.add_argument("--as-of", default=None)
    p.add_argument("--marks", default=None, help="JSON object {trade_id: current_credit_per_share}")
    p.add_argument("--config", default=None)
    args = p.parse_args(argv)
    cfg = DeskConfig.load(args.config)
    as_of = date.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc).date()
    marks = None
    if args.marks:
        marks = json.loads(Path(args.marks).read_text(encoding="utf-8"))
        marks = {k: float(v) for k, v in marks.items()}
    trader = PaperTrader(args.journal, cfg)
    closed = trader.manage(as_of, marks)
    print(json.dumps({"closed": len(closed), "trades": closed}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
