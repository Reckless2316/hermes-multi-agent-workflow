"""Turn a ScanResult into a Hermes intake candidate. Strikes come from code only."""
from __future__ import annotations

from .types import ScanResult, SetupStatus


def result_to_candidate_md(result: ScanResult) -> str:
    sp = result.spread
    title = f"{result.symbol} {sp.structure if sp else 'none'} {sp.expiration if sp else ''}".strip()
    if sp is None:
        return (
            f"## Candidate: {result.symbol} {result.status.value}\n"
            f"Claim: {result.reason}\n"
            f"Sources:\n"
            f"  - url: https://desk.local/scan\n"
            f"    quote: \"deterministic scanner\"\n"
            f"Symbol: {result.symbol}\n"
            f"Style: options\n"
            f"Setup status: {result.status.value}\n"
            f"Reason: {result.reason}\n"
            f"Why it may matter: scanner output, no structure\n"
        )
    legs = ", ".join(
        f"{lg.side} {lg.contract.right[0].upper()}{lg.contract.strike:g}"
        for lg in sp.legs
    )
    gates = ", ".join(result.gates_passed) or "none"
    claim = (
        f"{sp.structure} {legs} {sp.dte}DTE credit {sp.credit:.2f} "
        f"max_loss ${sp.max_loss:.0f}"
    )
    return (
        f"## Candidate: {title}\n"
        f"Claim: {claim}\n"
        f"Sources:\n"
        f"  - url: https://desk.local/scan/{result.symbol}\n"
        f"    quote: \"{result.status.value}: {result.reason}\"\n"
        f"Symbol: {result.symbol}\n"
        f"Style: options\n"
        f"Direction: {'neutral' if sp.structure == 'iron_condor' else ('long' if 'put' in sp.structure else 'short')}\n"
        f"Setup status: {result.status.value}\n"
        f"Timeframe: {sp.dte} DTE exp {sp.expiration.isoformat()}\n"
        f"Entry: {sp.credit:.2f} credit\n"
        f"Stop: max_loss ${sp.max_loss * result.qty:.0f}\n"
        f"Target: ${result.profit_target or 0:.0f} ({result.management_dte} DTE manage)\n"
        f"Gates passed: {gates}\n"
        f"Reason: {result.reason}\n"
        f"Structure: {sp.structure}\n"
        f"Max loss: {sp.max_loss * result.qty:.0f}\n"
        f"Risk R: {((result.profit_target or 0) / (sp.max_loss * result.qty)) if sp.max_loss else 0:.2f}\n"
        f"Catalyst: none\n"
        f"Why it may matter: capital_efficiency={result.capital_efficiency}\n"
    )


def results_to_intake(results: list[ScanResult], *, source: str = "options") -> str:
    lines = [
        f"source: {source}",
        f"captured_at: {results[0].timestamp if results else ''}",
        "scanner: tasty_defined_risk_v1",
        "",
    ]
    actionable = [r for r in results if r.status in (SetupStatus.TAKE, SetupStatus.WAIT)]
    if not actionable:
        lines.append("(no qualifying TASTY_DEFINED_RISK_V1 setups this window)")
        return "\n".join(lines) + "\n"
    for r in actionable:
        lines.append(result_to_candidate_md(r).rstrip())
        lines.append("")
    return "\n".join(lines)
