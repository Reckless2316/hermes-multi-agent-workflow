#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from trading.config import StrategyConfig
from trading.paper_options import OptionsPaperLedger
from trading.position_manager import manage_credit_position,natural_close_debit
from trading.tradier import TradierClient
from trading.types import ManagementAction,PositionState,StrategyKind
def main():
 p=argparse.ArgumentParser();p.add_argument("--config",default=str(ROOT/"strategy/tasty_defined_risk_v1.yaml"));p.add_argument("--ledger",default=os.environ.get("OPTIONS_LEDGER_DB",str(ROOT/"work/options/options_ledger.db")));p.add_argument("--export");p.add_argument("--dry-run",action="store_true");a=p.parse_args();cfg=StrategyConfig.load(a.config);client=TradierClient.from_env(live_data=True);closed=[];reviews=[]
 if not client.market_is_open():
  print(json.dumps({"closed":[],"reviews":[{"action":"MARKET_CLOSED","reason":"No automatic paper close outside regular Tradier market-open state"}]},indent=2));return 0
 with OptionsPaperLedger(a.ledger) as ledger:
  pos=ledger.open_positions()
  if not pos:print("open_positions=0");return 0
  legs={r["id"]:json.loads(r["legs_json"]) for r in pos};symbols=sorted({l["option_symbol"] for ls in legs.values() for l in ls});quotes={str(q.get("symbol")):q for q in client.quotes(symbols)}
  for r in pos:
   try:debit=natural_close_debit(legs[r["id"]],quotes)
   except ValueError as exc:reviews.append({"position_id":r["id"],"action":"DATA_ERROR","reason":str(exc)});continue
   ls=legs[r["id"]];width=max(abs(float(ls[0]["strike"])-float(ls[1]["strike"])),0);state=PositionState(r["id"],r["underlying"],StrategyKind(r["strategy"]),r["expiration"],r["entry_time"],float(r["entry_credit"]),width,int(r["quantity"]),float(r["max_profit"]),float(r["max_loss"]),float(r["profit_target_pct"]),int(r["manage_at_dte"]));d=manage_credit_position(state,current_close_debit=debit,cfg=cfg);rec={"position_id":r["id"],"underlying":r["underlying"],"action":d.action.value,"reason":d.reason,"close_debit":debit,"pnl_dollars":d.pnl_dollars,"pct_max_profit":d.pct_max_profit,"dte":d.dte}
   if d.action in {ManagementAction.CLOSE_WINNER,ManagementAction.CLOSE_AT_MANAGEMENT_DTE,ManagementAction.CLOSE_BEFORE_EXPIRATION}:
    if not a.dry_run:ledger.close_position(r["id"],exit_debit=debit,reason=d.action.value)
    closed.append(rec)
   elif d.action!=ManagementAction.HOLD:reviews.append(rec)
  if a.export:ledger.export_json(a.export)
 print(json.dumps({"closed":closed,"reviews":reviews},indent=2,sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
