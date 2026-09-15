#!/usr/bin/env python3
from __future__ import annotations
import argparse,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from trading.config import StrategyConfig
from trading.market_state import MarketStateStore
from trading.tradier import TradierClient,TradierError
def main():
 p=argparse.ArgumentParser();p.add_argument("--config",default=str(ROOT/"strategy/tasty_defined_risk_v1.yaml"));p.add_argument("--symbols");p.add_argument("--state-db",default=str(ROOT/"work/market_state.db"));a=p.parse_args();cfg=StrategyConfig.load(a.config);symbols=[x.strip().upper() for x in a.symbols.split(",") if x.strip()] if a.symbols else list(cfg.universe);token=os.environ.get("TRADIER_API_TOKEN","")
 if not token:raise SystemExit("TRADIER_API_TOKEN is required")
 client=TradierClient(token,account_id=os.environ.get("TRADIER_ACCOUNT_ID"),sandbox=False)
 with MarketStateStore(a.state_db) as state:
  state.set_stream_status(False,"starting")
  try:
   for event in client.reconnecting_market_stream(symbols):state.apply_event(event)
  except KeyboardInterrupt:state.set_stream_status(False,"stopped");return 0
  except TradierError as exc:state.set_stream_status(False,str(exc));raise SystemExit(str(exc)) from exc
 return 0
if __name__=="__main__":raise SystemExit(main())
