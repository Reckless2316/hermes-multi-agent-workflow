"""Market-data adapter ABC.

Tradier is V1. Later: OPRA, Cboe, flow — same interface, same strategy engine.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from ..types import MarketState, OptionContract, UnderlyingQuote


class MarketDataAdapter(ABC):
    @abstractmethod
    def fetch_underlying(self, symbol: str) -> UnderlyingQuote:
        ...

    @abstractmethod
    def fetch_expirations(self, symbol: str) -> list[date]:
        ...

    @abstractmethod
    def fetch_chain(self, symbol: str, expiration: date) -> list[OptionContract]:
        ...

    def fetch_iv_rank(self, symbol: str) -> float | None:
        return None

    def build_state(self, symbols: list[str], as_of: date, dte_min: int, dte_max: int) -> MarketState:
        underlyings: dict[str, UnderlyingQuote] = {}
        chains: dict[tuple[str, date], list[OptionContract]] = {}
        iv_rank: dict[str, float] = {}
        for raw in symbols:
            symbol = raw.upper()
            try:
                underlyings[symbol] = self.fetch_underlying(symbol)
            except KeyError:
                continue
            for exp in self.fetch_expirations(symbol):
                dte = (exp - as_of).days
                if dte < dte_min or dte > dte_max:
                    continue
                chains[(symbol, exp)] = self.fetch_chain(symbol, exp)
            rank = self.fetch_iv_rank(symbol)
            if rank is not None:
                iv_rank[symbol] = rank
        return MarketState(as_of=as_of, underlyings=underlyings, chains=chains, iv_rank=iv_rank)
