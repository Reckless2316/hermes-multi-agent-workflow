#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,os,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from trading.paper_options import OptionsPaperLedger
from trading.portfolio_snapshot import build_portfolio_snapshot
from trading.tradier import TradierClient
def main():
 p=argparse.ArgumentParser();p.add_argument("--ledger",default=os.environ.get("OPTIONS_LEDGER_DB",str(ROOT/"work/options/options_ledger.db")));p.add_argument("--output",default=str(ROOT/"work/portfolio_snapshot.json"));a=p.parse_args();client=TradierClient.from_env(live_data=True);account=client.balances();broker=client.positions();lp=Path(a.ledger)
 if lp.exists():
  with OptionsPaperLedger(lp) as ledger:paper=ledger.open_positions();committed=ledger.committed_defined_risk()
 else:paper=[];committed=0
 payload=build_portfolio_snapshot(account,broker,paper_positions=paper,paper_committed_defined_risk=committed);payload.update({"captured_at":datetime.now(timezone.utc).isoformat(),"provider":"tradier","rate_limit":client.last_rate_limit.__dict__});out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True);tmp=out.with_suffix(out.suffix+".tmp");tmp.write_text(json.dumps(payload,indent=2,sort_keys=True,default=str)+"\n");tmp.replace(out);print(out);return 0
if __name__=="__main__":raise SystemExit(main())
