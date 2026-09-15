"""Tradier brokerage API adapter.

Production (realtime for account holders): https://api.tradier.com
Sandbox (delayed): https://sandbox.tradier.com

Auth: Authorization: Bearer $TRADIER_ACCESS_TOKEN
Never log the token. Live multi-leg execution is out of scope for V1.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import MarketDataAdapter
from ..types import OptionContract, UnderlyingQuote


PROD = "https://api.tradier.com"
SANDBOX = "https://sandbox.tradier.com"


def _as_list(node: Any) -> list:
    if node is None:
        return []
    if isinstance(node, list):
        return node
    return [node]


def _parse_date(value: str) -> date:
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


class TradierAdapter(MarketDataAdapter):
    def __init__(
        self,
        token: str | None = None,
        base_url: str | None = None,
        timeout: float = 20.0,
        opener=None,
    ):
        self.token = token if token is not None else os.environ.get("TRADIER_ACCESS_TOKEN", "")
        env_base = os.environ.get("TRADIER_BASE_URL", "")
        self.base_url = (base_url or env_base or PROD).rstrip("/")
        self.timeout = timeout
        self._opener = opener  # optional: callable(Request, timeout=) -> bytes

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError(
                "TRADIER_ACCESS_TOKEN is not set. Desk scan against live Tradier "
                "needs a brokerage token in the environment; tests should use ReplayAdapter."
            )
        qs = f"?{urlencode(params)}" if params else ""
        url = f"{self.base_url}{path}{qs}"
        req = Request(url, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        })
        if self._opener:
            raw = self._opener(req, timeout=self.timeout)
        else:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        import json
        return json.loads(raw.decode("utf-8"))

    def fetch_underlying(self, symbol: str) -> UnderlyingQuote:
        data = self._get("/v1/markets/quotes", {"symbols": symbol})
        q = _as_list((data.get("quotes") or {}).get("quote"))[0]
        return UnderlyingQuote(
            symbol=symbol.upper(),
            last=float(q.get("last") or q.get("close") or 0),
            bid=float(q.get("bid") or 0),
            ask=float(q.get("ask") or 0),
            volume=int(q.get("volume") or 0),
        )

    def fetch_expirations(self, symbol: str) -> list[date]:
        data = self._get("/v1/markets/options/expirations", {
            "symbol": symbol,
            "includeAllRoots": "false",
        })
        dates = _as_list(((data.get("expirations") or {}).get("date")))
        out = []
        for d in dates:
            if isinstance(d, dict):
                d = d.get("date")
            if d:
                out.append(_parse_date(str(d)))
        return out

    def fetch_chain(self, symbol: str, expiration: date) -> list[OptionContract]:
        data = self._get("/v1/markets/options/chains", {
            "symbol": symbol,
            "expiration": expiration.isoformat(),
            "greeks": "true",
        })
        options = _as_list(((data.get("options") or {}).get("option")))
        return [self._contract(symbol, expiration, o) for o in options]

    def fetch_iv_rank(self, symbol: str) -> float | None:
        return None

    @staticmethod
    def _contract(symbol: str, expiration: date, o: dict[str, Any]) -> OptionContract:
        g = o.get("greeks") or {}
        right = str(o.get("option_type") or o.get("type") or "").lower()
        if right not in ("call", "put"):
            right = "call" if "C" in str(o.get("symbol", ""))[-9:] else "put"
        return OptionContract(
            occ=str(o.get("symbol") or ""),
            underlying=symbol.upper(),
            expiration=expiration,
            strike=float(o.get("strike") or 0),
            right=right,  # type: ignore[arg-type]
            bid=float(o.get("bid") or 0),
            ask=float(o.get("ask") or 0),
            last=float(o.get("last") or 0),
            volume=int(o.get("volume") or 0),
            open_interest=int(o.get("open_interest") or 0),
            delta=_f(g.get("delta")),
            gamma=_f(g.get("gamma")),
            theta=_f(g.get("theta")),
            vega=_f(g.get("vega")),
            mid_iv=_f(g.get("mid_iv") or g.get("smv_vol")),
        )


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
