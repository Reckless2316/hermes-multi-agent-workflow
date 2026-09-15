"""Replay adapter — fixture JSON, no network. Used by tests and offline scans."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any
import json

from ..types import OptionContract, UnderlyingQuote
from .base import MarketDataAdapter


def _parse_date(value: str) -> date:
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


class ReplayAdapter(MarketDataAdapter):
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    @classmethod
    def from_path(cls, path: str | Path) -> "ReplayAdapter":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def fetch_underlying(self, symbol: str) -> UnderlyingQuote:
        q = (self.payload.get("quotes") or {}).get(symbol.upper())
        if not q:
            raise KeyError(symbol)
        return UnderlyingQuote(
            symbol=symbol.upper(),
            last=float(q["last"]),
            bid=float(q.get("bid") or 0),
            ask=float(q.get("ask") or 0),
            volume=int(q.get("volume") or 0),
        )

    def fetch_expirations(self, symbol: str) -> list[date]:
        return [_parse_date(d) for d in (self.payload.get("expirations") or {}).get(symbol.upper(), [])]

    def fetch_chain(self, symbol: str, expiration: date) -> list[OptionContract]:
        key = f"{symbol.upper()}:{expiration.isoformat()}"
        rows = (self.payload.get("chains") or {}).get(key) or []
        out = []
        for o in rows:
            out.append(OptionContract(
                occ=o["occ"],
                underlying=symbol.upper(),
                expiration=expiration,
                strike=float(o["strike"]),
                right=o["right"],
                bid=float(o.get("bid") or 0),
                ask=float(o.get("ask") or 0),
                last=float(o.get("last") or 0),
                volume=int(o.get("volume") or 0),
                open_interest=int(o.get("open_interest") or 0),
                delta=o.get("delta"),
                gamma=o.get("gamma"),
                theta=o.get("theta"),
                vega=o.get("vega"),
                mid_iv=o.get("mid_iv"),
            ))
        return out

    def fetch_iv_rank(self, symbol: str) -> float | None:
        rank = (self.payload.get("iv_rank") or {}).get(symbol.upper())
        return None if rank is None else float(rank)
