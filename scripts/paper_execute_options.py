#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from trading.config import StrategyConfig
from trading.paper_options import OptionsPaperLedger
from trading.duplicates import broker_has_exact_structure
from trading.revalidate import RevalidationRejected,revalidate_for_paper_fill
from trading.tradier import TradierClient
from trading.types import sized_candidate_from_dict
def main():
 p=argparse.ArgumentParser();p.add_argument("candidate_json");p.add_argument("--approval-slug",required=True);p.add_argument("--config",default=str(ROOT/"strategy/tasty_defined_risk_v1.yaml"));p.add_argument("--ledger",default=os.environ.get("OPTIONS_LEDGER_DB",str(ROOT/"work/options/options_ledger.db")));p.add_argument("--export");p.add_argument("--snapshot-output");a=p.parse_args();raw=json.loads(Path(a.candidate_json).read_text())
 if "candidates" in raw:
  if len(raw["candidates"])!=1:raise SystemExit("sidecar must contain exactly one selected candidate")
  raw=raw["candidates"][0]
 approved=sized_candidate_from_dict(raw);cfg=StrategyConfig.load(a.config);client=TradierClient.from_env(live_data=True)
 if not client.market_is_open():
  print("WAIT_REPROPOSE: US market is not open; do not paper-fill stale/non-executable quotes")
  return 2
 account=client.balances();broker_positions=client.positions()
 if broker_has_exact_structure(approved.candidate,broker_positions):
  print("WAIT_REPROPOSE: exact OCC structure is already open in Tradier account")
  return 2
 chain=client.option_chain(approved.candidate.underlying,approved.candidate.expiration,greeks=True)
 with OptionsPaperLedger(a.ledger) as ledger:
  try:rv=revalidate_for_paper_fill(approved,chain,account,cfg,committed_defined_risk=ledger.committed_defined_risk())
  except RevalidationRejected as exc:print(f"WAIT_REPROPOSE: {exc}");return 2
  filled=rv.to_fill_candidate();pid=ledger.open_position(filled,approval_slug=a.approval_slug)
  if a.export:ledger.export_json(a.export)
  if a.snapshot_output:
   snap={"approval_slug":a.approval_slug,"underlying":filled.candidate.underlying,"strategy":filled.candidate.strategy.value,"expiration":filled.candidate.expiration,"approved_limit_credit":rv.approved_limit_credit,"current_natural_credit":rv.current_natural_credit,"paper_fill_credit":rv.fill_credit,"contracts":filled.contracts,"total_max_loss":filled.total_max_loss,"option_buying_power_at_recheck":account.option_buying_power,"total_equity_at_recheck":account.total_equity,"fresh_candidate":filled.candidate.to_dict(),"rate_limit":client.last_rate_limit.__dict__};path=Path(a.snapshot_output);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".tmp");tmp.write_text(json.dumps(snap,indent=2,sort_keys=True)+"\n");tmp.replace(path)
 print(f"PAPER_FILLED position_id={pid} credit={rv.fill_credit:.2f}");return 0
if __name__=="__main__":raise SystemExit(main())
