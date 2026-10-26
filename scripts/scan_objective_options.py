#!/usr/bin/env python3
"""Objective-driven defined-risk options scan (income / growth / speculation curve).

Examples:
  # Let the market situation set the dial, capped at growth:
  python scripts/scan_objective_options.py --objective auto --max-aggression 0.5
  # Explicit purpose:
  python scripts/scan_objective_options.py --objective income
  # Any point on the curve, with an operator thesis:
  python scripts/scan_objective_options.py --aggression 0.8 --bias bullish --symbols QQQ
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from trading.intake import render_objective_intake  # noqa: E402
from trading.objective_scan import run_objective_scan, sidecar_payload  # noqa: E402
from trading.objectives import ObjectiveConfig, ObjectiveConfigError  # noqa: E402
from trading.paper_options import OptionsPaperLedger  # noqa: E402
from trading.tradier import TradierClient  # noqa: E402


def unit_interval(text: str) -> float:
    value = float(text)
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError("must be in [0, 1]")
    return value


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=os.environ.get("OBJECTIVE_STRATEGY_CONFIG", str(ROOT / "strategy/objective_options_v1.yaml")))
    p.add_argument("--objective", choices=["auto", "income", "growth", "speculation"], default="auto")
    p.add_argument("--aggression", type=unit_interval, help="explicit dial in [0,1]; overrides --objective")
    p.add_argument("--bias", choices=["auto", "bullish", "bearish", "neutral"], default="auto", help="operator thesis; auto follows the measured trend")
    p.add_argument("--max-aggression", type=unit_interval, help="cap for auto mode (default: config auto.max_aggression)")
    p.add_argument("--risk-per-trade-pct", type=float, help="reduce (never raise) the profile's risk per trade, e.g. 0.005")
    p.add_argument("--symbols")
    p.add_argument("--max-per-symbol", type=int, default=3)
    p.add_argument("--output")
    p.add_argument("--json-output")
    p.add_argument("--ledger", default=os.environ.get("OPTIONS_LEDGER_DB", str(ROOT / "work/options/options_ledger.db")))
    return p.parse_args()


def atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    a = parse_args()
    try:
        cfg = ObjectiveConfig.load(a.config)
    except ObjectiveConfigError as exc:
        raise SystemExit(str(exc)) from exc
    if a.risk_per_trade_pct is not None and not 0 < a.risk_per_trade_pct <= min(p.risk_per_trade_pct for p in cfg.anchors):
        raise SystemExit("--risk-per-trade-pct must be > 0 and no larger than the most conservative anchor's risk")
    symbols = tuple(x.strip().upper() for x in a.symbols.split(",") if x.strip()) if a.symbols else cfg.universe
    if not symbols:
        raise SystemExit("Strategy universe is empty")

    token = os.environ.get("TRADIER_API_TOKEN", "")
    account_id = os.environ.get("TRADIER_ACCOUNT_ID", "")
    if not token or not account_id:
        raise SystemExit("TRADIER_API_TOKEN and TRADIER_ACCOUNT_ID are required")
    client = TradierClient(token, account_id=account_id, sandbox=False)
    clock = client.market_clock()
    state = str(clock.get("state") or "").lower()
    if state != "open":
        print(f"MARKET_NOT_OPEN state={state or 'unknown'} description={clock.get('description', '')}")
        return 3

    request = {"objective": a.objective, "aggression": a.aggression, "bias": a.bias, "max_aggression": a.max_aggression, "risk_per_trade_pct": a.risk_per_trade_pct, "symbols": list(symbols)}
    ledger_path = Path(a.ledger)
    ledger = OptionsPaperLedger(ledger_path) if ledger_path.exists() else None
    try:
        output = run_objective_scan(
            client, cfg, symbols,
            objective=a.objective, aggression=a.aggression, bias=a.bias,
            max_aggression=a.max_aggression, risk_override=a.risk_per_trade_pct,
            max_per_symbol=a.max_per_symbol, ledger=ledger,
        )
    finally:
        if ledger is not None:
            ledger.conn.close()

    captured = datetime.now(timezone.utc).isoformat()
    if a.output:
        out = Path(a.output)
    else:
        profile_dir = Path(os.environ.get("HERMES_PROFILE_DIR", str(ROOT / "work")))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = profile_dir / "vault/intake" / f"{stamp}-options-objective.md"
    jout = Path(a.json_output) if a.json_output else out.with_suffix(".json")
    atomic(out, render_objective_intake(output.sized, captured_at=captured, sidecar_path=str(jout), request=request))
    atomic(jout, json.dumps(sidecar_payload(output, captured_at=captured, cfg=cfg, request=request, rate_limit=client.last_rate_limit.__dict__), indent=2, sort_keys=True, default=str) + "\n")
    print(out)
    print(jout)
    print(f"candidates={len(output.sized)}")
    for record in output.symbols:
        d = record.decision
        print(f"  {record.symbol}: {'-' if d is None else d.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
