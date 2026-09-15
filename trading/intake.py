from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
from typing import Iterable
from .types import SizedCandidate

def candidate_id(item:SizedCandidate):
    c=item.candidate;material="|".join([c.underlying,c.strategy.value,c.expiration,*sorted(l.option_symbol for l in c.legs)]);return sha256(material.encode()).hexdigest()[:16]
def _money(v):return f"{v:.2f}"
def _strikes(item):return ", ".join(f"{l.side}:{l.option_type[0].upper()}{l.strike:g}" for l in item.candidate.legs)
def _title_strikes(item):
    return "/".join(f"{leg.option_type[0].upper()}{leg.strike:g}" for leg in item.candidate.legs)
def render_options_intake(candidates:Iterable[SizedCandidate],*,captured_at:str|None=None,sidecar_path:str|None=None):
    captured_at=captured_at or datetime.now(timezone.utc).isoformat();lines=["source: options",f"captured_at: {captured_at}","data_provider: Tradier Brokerage production market data","scanner: tasty_defined_risk_v1","execution_mode: paper",f"sidecar_json: {sidecar_path or 'not_provided'}",""]
    for s in candidates:
        c=s.candidate;lines += [f"## Candidate: {c.underlying} {c.strategy.value} {_title_strikes(s)} {c.expiration}",f"Claim: deterministic {c.strategy.value} passed all hard gates; capital efficiency {c.capital_efficiency:.3f}","Sources:",f"  - url: tradier://live/options-chain/{c.underlying}/{c.expiration}",f'    quote: "live chain snapshot captured {c.captured_at}"',f"Candidate id: {candidate_id(s)}",f"Symbol: {c.underlying}","Style: options",f"Direction: {c.direction}",f"Setup status: {c.status.value}",f"Timeframe: {c.dte} DTE",f"Entry: credit {_money(c.net_credit)}","Stop: defined max loss; no stop widening or averaging",f"Target: {_money(c.profit_target_dollars)} dollars per contract ({c.profit_target_pct:.0%} max profit)",f"Gates passed: {', '.join(c.gates_passed)}",f"Reason: {c.reason}",f"Structure: {c.strategy.value}",f"Expiration: {c.expiration}",f"Strikes: {_strikes(s)}",f"Width: {_money(c.width)}",f"Credit: {_money(c.net_credit)}",f"Natural credit: {_money(c.net_credit)}",f"Mid credit mark: {_money(c.mark_credit)}",f"Max profit: {_money(c.max_profit)}",f"Max loss: {_money(c.max_loss)}",f"Buying power reduction: {_money(c.buying_power_reduction)}",f"Capital efficiency: {c.capital_efficiency:.6f}",f"Premium to BPR: {c.premium_to_bpr:.6f}",f"Short delta: {'' if c.short_delta is None else f'{c.short_delta:.4f}'}",f"Mid IV: {'' if c.mid_iv is None else f'{c.mid_iv:.6f}'}","IV rank: unavailable_from_tradier",f"Contracts: {s.contracts}",f"Total max loss: {_money(s.total_max_loss)}",f"Total buying power reduction: {_money(s.total_buying_power_reduction)}",f"Profit target pct: {c.profit_target_pct:.4f}",f"Manage at DTE: {c.manage_at_dte}",f"Strategy version: {c.strategy_version}","Catalyst: context_lane_required","Why it may matter: passes deterministic price/liquidity/risk gates; Hermes must check market/event/portfolio context before proposal",""]
    return "\n".join(lines).rstrip()+"\n"
