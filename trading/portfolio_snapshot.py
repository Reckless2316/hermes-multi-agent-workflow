from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import date
from typing import Any,Iterable
from .types import AccountSnapshot
_OCC_RE=re.compile(r"^(?P<root>[A-Z0-9.]{1,6})(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<right>[CP])(?P<strike>\d{8})$")
@dataclass(frozen=True)
class OCCContract:root:str;expiration:str;option_type:str;strike:float
def parse_occ_symbol(symbol):
    m=_OCC_RE.match(str(symbol or "").replace(" ","").upper())
    if not m:return None
    try:exp=date(2000+int(m.group("yy")),int(m.group("mm")),int(m.group("dd"))).isoformat()
    except ValueError:return None
    return OCCContract(m.group("root"),exp,"call" if m.group("right")=="C" else "put",int(m.group("strike"))/1000)
def sanitize_broker_position(row):
    sym=str(row.get("symbol") or "");occ=parse_occ_symbol(sym);out={"symbol":sym,"quantity":row.get("quantity"),"cost_basis":row.get("cost_basis"),"date_acquired":row.get("date_acquired"),"asset_type":"option" if occ else "equity_or_other"}
    if occ:out.update({"underlying":occ.root,"expiration":occ.expiration,"option_type":occ.option_type,"strike":occ.strike})
    return out
def build_portfolio_snapshot(account:AccountSnapshot,broker_positions:Iterable[dict[str,Any]],*,paper_positions:Iterable[dict[str,Any]]=(),paper_committed_defined_risk:float=0):
    papers=[{"position_id":r.get("id"),"underlying":r.get("underlying"),"strategy":r.get("strategy"),"expiration":r.get("expiration"),"direction":r.get("direction"),"quantity":r.get("quantity"),"max_loss":r.get("max_loss"),"buying_power_reduction":r.get("buying_power_reduction"),"profit_target_pct":r.get("profit_target_pct"),"manage_at_dte":r.get("manage_at_dte"),"entry_time":r.get("entry_time")} for r in paper_positions]
    return {"account":{"account_type":account.account_type,"total_equity":account.total_equity,"total_cash":account.total_cash,"option_buying_power":account.option_buying_power,"stock_buying_power":account.stock_buying_power,"open_pl":account.open_pl,"current_requirement":account.current_requirement,"pending_orders_count":account.pending_orders_count},"broker_positions":[sanitize_broker_position(p) for p in broker_positions],"paper_options_positions":papers,"paper_committed_defined_risk":float(paper_committed_defined_risk),"paper_defined_risk_pct_equity":float(paper_committed_defined_risk)/account.total_equity if account.total_equity>0 else None,"notes":["Broker positions are separate from paper positions.","No portfolio delta/theta/vega is invented; add provider-backed Greeks first.","Correlation/concentration remains contextual until deterministic limits are configured."]}
