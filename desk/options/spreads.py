"""Build defined-risk structures from a normalized chain.

V1 constructors: short_put_vertical, short_call_vertical, iron_condor.
Credit is per-share (positive = credit). Dollar max_loss/profit assume 1 contract.
"""
from __future__ import annotations

from datetime import date

from ..types import OptionContract, Spread, SpreadLeg


def _mid(c: OptionContract) -> float:
    return c.mid


def _width_key(width: float) -> float:
    return round(width, 4)


def verticals(
    chain: list[OptionContract],
    *,
    right: str,
    widths: list[float],
    dte: int,
    iv_rank: float | None,
    structure: str,
) -> list[Spread]:
    """Credit verticals: sell closer-to-money, buy further OTM, same right."""
    side = [c for c in chain if c.right == right]
    by_strike = {c.strike: c for c in side}
    strikes = sorted(by_strike)
    want = {_width_key(w) for w in widths}
    out: list[Spread] = []
    for i, ks in enumerate(strikes):
        short = by_strike[ks]
        for kl in strikes:
            width = abs(kl - ks)
            if _width_key(width) not in want:
                continue
            long = by_strike[kl]
            if right == "put":
                # bull put: short higher strike, long lower strike
                if kl >= ks:
                    continue
            else:
                # bear call: short lower strike, long higher strike
                if kl <= ks:
                    continue
            credit = _mid(short) - _mid(long)
            if credit <= 0:
                continue
            max_profit = credit * 100
            max_loss = (width - credit) * 100
            out.append(Spread(
                structure=structure,
                underlying=short.underlying,
                expiration=short.expiration,
                dte=dte,
                legs=[
                    SpreadLeg(short, "sell"),
                    SpreadLeg(long, "buy"),
                ],
                width=width,
                credit=credit,
                max_profit=max_profit,
                max_loss=max_loss,
                buying_power=max_loss,
                short_delta=short.delta,
                iv_rank=iv_rank,
                extras={"short_strike": short.strike, "long_strike": long.strike},
            ))
    return out


def iron_condors(
    chain: list[OptionContract],
    *,
    widths: list[float],
    dte: int,
    iv_rank: float | None,
) -> list[Spread]:
    puts = verticals(chain, right="put", widths=widths, dte=dte, iv_rank=iv_rank, structure="short_put_vertical")
    calls = verticals(chain, right="call", widths=widths, dte=dte, iv_rank=iv_rank, structure="short_call_vertical")
    out: list[Spread] = []
    for p in puts:
        for c in calls:
            if _width_key(p.width) != _width_key(c.width):
                continue
            # wings must not cross: put short < call short
            if p.extras["short_strike"] >= c.extras["short_strike"]:
                continue
            credit = p.credit + c.credit
            width = p.width
            max_profit = credit * 100
            max_loss = (width - credit) * 100
            out.append(Spread(
                structure="iron_condor",
                underlying=p.underlying,
                expiration=p.expiration,
                dte=dte,
                legs=list(p.legs) + list(c.legs),
                width=width,
                credit=credit,
                max_profit=max_profit,
                max_loss=max_loss,
                buying_power=max_loss,
                short_delta=None,  # net; gates use abs of each short
                iv_rank=iv_rank,
                extras={
                    "put_short": p.extras["short_strike"],
                    "put_long": p.extras["long_strike"],
                    "call_short": c.extras["short_strike"],
                    "call_long": c.extras["long_strike"],
                    "put_short_delta": p.short_delta,
                    "call_short_delta": c.short_delta,
                },
            ))
    return out


def enumerate_spreads(
    chain: list[OptionContract],
    expiration: date,
    as_of: date,
    widths: list[float],
    structures: list[str],
    iv_rank: float | None,
) -> list[Spread]:
    dte = (expiration - as_of).days
    found: list[Spread] = []
    if "short_put_vertical" in structures:
        found.extend(verticals(chain, right="put", widths=widths, dte=dte, iv_rank=iv_rank, structure="short_put_vertical"))
    if "short_call_vertical" in structures:
        found.extend(verticals(chain, right="call", widths=widths, dte=dte, iv_rank=iv_rank, structure="short_call_vertical"))
    if "iron_condor" in structures:
        found.extend(iron_condors(chain, widths=widths, dte=dte, iv_rank=iv_rank))
    return found
