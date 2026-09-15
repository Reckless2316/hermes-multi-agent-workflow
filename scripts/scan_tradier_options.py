#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from trading.config import StrategyConfig
from trading.intake import candidate_id,render_options_intake
from trading.duplicates import broker_has_exact_structure
from trading.options_engine import choose_expiration,scan_defined_risk
from trading.portfolio import SizingRejected,size_candidate
from trading.paper_options import OptionsPaperLedger
from trading.tradier import TradierClient,TradierError

def args():
 p=argparse.ArgumentParser();p.add_argument("--config",default=str(ROOT/"strategy/tasty_defined_risk_v1.yaml"));p.add_argument("--symbols");p.add_argument("--output");p.add_argument("--json-output");p.add_argument("--max-per-symbol",type=int,default=3);p.add_argument("--ledger",default=os.environ.get("OPTIONS_LEDGER_DB",str(ROOT/"work/options/options_ledger.db")));return p.parse_args()
def atomic(path,text):path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+".tmp");tmp.write_text(text);tmp.replace(path)
def main():
 a=args();cfg=StrategyConfig.load(a.config);symbols=tuple(x.strip().upper() for x in a.symbols.split(",") if x.strip()) if a.symbols else cfg.universe
 if not symbols:raise SystemExit("Strategy universe is empty")
 token=os.environ.get("TRADIER_API_TOKEN","");acct=os.environ.get("TRADIER_ACCOUNT_ID","")
 if not token or not acct:raise SystemExit("TRADIER_API_TOKEN and TRADIER_ACCOUNT_ID are required")
 client=TradierClient(token,account_id=acct,sandbox=False)
 clock=client.market_clock();state=str(clock.get("state") or "").lower()
 if state!="open":
  print(f"MARKET_NOT_OPEN state={state or 'unknown'} description={clock.get('description','')}");return 3
 account=client.balances();broker_positions=client.positions();sized=[];diagnostics=[]
 for symbol in symbols:
  try:
   exp=choose_expiration(client.option_expirations(symbol),cfg)
   if not exp:diagnostics.append({"symbol":symbol,"status":"NO_SETUP","reason":"no expiration in DTE window"});continue
   candidates=scan_defined_risk(symbol,client.option_chain(symbol,exp,greeks=True),cfg);count=0
   for c in candidates:
    if broker_has_exact_structure(c,broker_positions):diagnostics.append({"symbol":symbol,"strategy":c.strategy.value,"status":"SKIP","reason":"exact OCC structure already open in Tradier account"});continue
    try:s=size_candidate(c,account,cfg)
    except SizingRejected as exc:diagnostics.append({"symbol":symbol,"strategy":c.strategy.value,"status":"SKIP","reason":str(exc)});continue
    sized.append(s);count+=1
    if count>=a.max_per_symbol:break
   if not count:diagnostics.append({"symbol":symbol,"status":"NO_SETUP","reason":"no candidate passed gates and sizing"})
  except TradierError as exc:diagnostics.append({"symbol":symbol,"status":"ERROR","reason":str(exc)})
 ledger_path=Path(a.ledger)
 if ledger_path.exists():
  with OptionsPaperLedger(ledger_path) as ledger:
   keep=[]
   for item in sized:
    if ledger.is_duplicate_open(item):diagnostics.append({"symbol":item.candidate.underlying,"strategy":item.candidate.strategy.value,"status":"SKIP","reason":"duplicate exact structure already open in paper ledger"})
    else:keep.append(item)
   sized=keep
 sized.sort(key=lambda s:(s.candidate.capital_efficiency,s.total_profit_target,s.candidate.width),reverse=True);captured=datetime.now(timezone.utc).isoformat()
 if a.output:out=Path(a.output)
 else:
  profile=Path(os.environ.get("HERMES_PROFILE_DIR",str(ROOT/"work")));stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ");out=profile/"vault/intake"/f"{stamp}-options.md"
 jout=Path(a.json_output) if a.json_output else out.with_suffix(".json");atomic(out,render_options_intake(sized,captured_at=captured,sidecar_path=str(jout)))
 side={"captured_at":captured,"account":{"account_type":account.account_type,"total_equity":account.total_equity,"option_buying_power":account.option_buying_power,"pending_orders_count":account.pending_orders_count},"candidate_count":len(sized),"candidates":[{"candidate_id":candidate_id(s),**s.candidate.to_dict(),"contracts":s.contracts,"risk_budget":s.risk_budget,"sizing_reason":s.sizing_reason,"total_max_loss":s.total_max_loss,"total_profit_target":s.total_profit_target,"total_buying_power_reduction":s.total_buying_power_reduction} for s in sized],"diagnostics":diagnostics,"rate_limit":client.last_rate_limit.__dict__};atomic(jout,json.dumps(side,indent=2,sort_keys=True)+"\n");print(out);print(jout);print(f"candidates={len(sized)}");return 0
if __name__=="__main__":raise SystemExit(main())
