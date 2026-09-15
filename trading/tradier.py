"""Read-only Tradier Brokerage API adapter.

The class intentionally has no brokerage order submission methods. Production
credentials are used for real-time market/account reads. Creating a market-data
streaming session is the only POST request in this module.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Mapping

from .types import AccountSnapshot, OptionContract


class TradierError(RuntimeError):
    """Raised when Tradier transport or response handling fails."""


@dataclass(frozen=True)
class RateLimitState:
    allowed: int | None = None
    used: int | None = None
    available: int | None = None
    expiry_ms: int | None = None


@dataclass(frozen=True)
class TradierResponse:
    data: dict[str, Any]
    rate_limit: RateLimitState


def _number(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _one_or_many(value: Any) -> list[dict[str, Any]]:
    """Normalize Tradier endpoints that return one object or a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


class TradierClient:
    LIVE_BASE = "https://api.tradier.com/v1"
    SANDBOX_BASE = "https://sandbox.tradier.com/v1"
    LIVE_STREAM_BASE = "https://stream.tradier.com/v1"

    def __init__(self, token: str, *, account_id: str | None = None, sandbox: bool = False, timeout: float = 15.0, user_agent: str = "hermes-trading-desk/1.0") -> None:
        token = token.strip()
        if not token:
            raise ValueError("Tradier token is required")
        self._token = token
        self.account_id = account_id
        self.sandbox = sandbox
        self.timeout = timeout
        self.user_agent = user_agent
        self.base_url = self.SANDBOX_BASE if sandbox else self.LIVE_BASE
        self.last_rate_limit = RateLimitState()

    @classmethod
    def from_env(cls, *, live_data: bool = True) -> "TradierClient":
        token_name = "TRADIER_API_TOKEN" if live_data else "TRADIER_SANDBOX_TOKEN"
        return cls(os.environ.get(token_name, ""), account_id=os.environ.get("TRADIER_ACCOUNT_ID") or None, sandbox=not live_data)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json", "User-Agent": self.user_agent}

    @staticmethod
    def _rate_limit(headers: Mapping[str, str]) -> RateLimitState:
        lower = {str(k).lower(): str(v) for k, v in headers.items()}
        def maybe_int(key: str) -> int | None:
            raw = lower.get(key)
            if raw is None:
                return None
            try:
                return int(raw)
            except ValueError:
                return None
        return RateLimitState(allowed=maybe_int("x-ratelimit-allowed"), used=maybe_int("x-ratelimit-used"), available=maybe_int("x-ratelimit-available"), expiry_ms=maybe_int("x-ratelimit-expiry"))

    def _request_json(self, method: str, path: str, *, params: Mapping[str, Any] | None = None, body: Mapping[str, Any] | None = None) -> TradierResponse:
        method = method.upper()
        if method != "GET" and not (method == "POST" and path == "/markets/events/session"):
            raise TradierError(f"Read-only TradierClient blocks {method} {path}; live execution must use a separate reviewed adapter")
        query = ""
        if params:
            query = "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
        headers = self._headers()
        data: bytes | None = None
        if body is not None:
            data = urllib.parse.urlencode(body, doseq=True).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif method == "POST":
            data = b""
        request = urllib.request.Request(f"{self.base_url}{path}{query}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                text = response.read().decode("utf-8")
                decoded = json.loads(text) if text else {}
                rate = self._rate_limit(response.headers)
                self.last_rate_limit = rate
                if not isinstance(decoded, dict):
                    raise TradierError(f"Unexpected Tradier response type from {path}")
                return TradierResponse(decoded, rate)
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            raise TradierError(f"Tradier HTTP {exc.code} for {path}: {detail[:500]}") from exc
        except urllib.error.URLError as exc:
            raise TradierError(f"Tradier network error for {path}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise TradierError(f"Tradier returned invalid JSON for {path}") from exc

    def market_clock(self) -> dict[str, Any]:
        data = self._request_json("GET", "/markets/clock").data
        clock = data.get("clock") or {}
        return clock if isinstance(clock, dict) else {}

    def market_is_open(self) -> bool:
        return str(self.market_clock().get("state") or "").lower() == "open"

    def quotes(self, symbols: Iterable[str], *, greeks: bool = False) -> list[dict[str, Any]]:
        clean = [symbol.strip() for symbol in symbols if symbol and symbol.strip()]
        if not clean:
            return []
        data = self._request_json("GET", "/markets/quotes", params={"symbols": ",".join(clean), "greeks": str(greeks).lower()}).data
        return _one_or_many((data.get("quotes") or {}).get("quote"))

    def option_expirations(self, symbol: str) -> list[str]:
        data = self._request_json("GET", "/markets/options/expirations", params={"symbol": symbol}).data
        dates = (data.get("expirations") or {}).get("date")
        if dates is None:
            return []
        if isinstance(dates, list):
            return [str(value) for value in dates]
        return [str(dates)]

    def option_chain(self, symbol: str, expiration: str, *, greeks: bool = True) -> list[OptionContract]:
        data = self._request_json("GET", "/markets/options/chains", params={"symbol": symbol, "expiration": expiration, "greeks": str(greeks).lower()}).data
        contracts: list[OptionContract] = []
        for row in _one_or_many((data.get("options") or {}).get("option")):
            g = row.get("greeks") or {}
            contracts.append(OptionContract(
                symbol=str(row.get("symbol") or ""), underlying=str(row.get("underlying") or symbol), expiration=str(row.get("expiration_date") or expiration), option_type=str(row.get("option_type") or "").lower(), strike=_number(row.get("strike")), bid=_number(row.get("bid")), ask=_number(row.get("ask")), last=None if row.get("last") is None else _number(row.get("last")), volume=_integer(row.get("volume")), open_interest=_integer(row.get("open_interest")), delta=None if g.get("delta") is None else _number(g.get("delta")), gamma=None if g.get("gamma") is None else _number(g.get("gamma")), theta=None if g.get("theta") is None else _number(g.get("theta")), vega=None if g.get("vega") is None else _number(g.get("vega")), rho=None if g.get("rho") is None else _number(g.get("rho")), mid_iv=None if g.get("mid_iv") is None else _number(g.get("mid_iv")), bid_iv=None if g.get("bid_iv") is None else _number(g.get("bid_iv")), ask_iv=None if g.get("ask_iv") is None else _number(g.get("ask_iv")), greeks_updated_at=None if g.get("updated_at") is None else str(g.get("updated_at"))))
        return contracts

    def history(self, symbol: str, *, interval: str = "daily", start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        data = self._request_json("GET", "/markets/history", params={"symbol": symbol, "interval": interval, "start": start, "end": end}).data
        return _one_or_many((data.get("history") or {}).get("day"))

    def user_profile(self) -> dict[str, Any]:
        return self._request_json("GET", "/user/profile").data

    def _require_account(self, account_id: str | None = None) -> str:
        account = account_id or self.account_id
        if not account:
            raise ValueError("Tradier account id is required")
        return account

    def balances(self, account_id: str | None = None) -> AccountSnapshot:
        account = self._require_account(account_id)
        data = self._request_json("GET", f"/accounts/{urllib.parse.quote(account)}/balances").data
        balances = data.get("balances") or {}
        account_type = str(balances.get("account_type") or "")
        buying = balances.get("margin") or balances.get("pdt") or balances.get("cash") or {}
        option_bp = buying.get("option_buying_power")
        if option_bp is None and account_type == "cash":
            option_bp = buying.get("cash_available", balances.get("total_cash", 0))
        return AccountSnapshot(account_id=str(balances.get("account_number") or account), account_type=account_type, total_equity=_number(balances.get("total_equity")), total_cash=_number(balances.get("total_cash")), option_buying_power=_number(option_bp), stock_buying_power=_number(buying.get("stock_buying_power")), open_pl=_number(balances.get("open_pl")), current_requirement=_number(balances.get("current_requirement")), pending_orders_count=_integer(balances.get("pending_orders_count")))

    def positions(self, account_id: str | None = None) -> list[dict[str, Any]]:
        account = self._require_account(account_id)
        data = self._request_json("GET", f"/accounts/{urllib.parse.quote(account)}/positions").data
        return _one_or_many((data.get("positions") or {}).get("position"))

    def orders(self, account_id: str | None = None) -> list[dict[str, Any]]:
        """Read current/historical broker orders; this method does not submit any."""
        account = self._require_account(account_id)
        data = self._request_json("GET", f"/accounts/{urllib.parse.quote(account)}/orders").data
        return _one_or_many((data.get("orders") or {}).get("order"))

    def create_market_session(self) -> str:
        if self.sandbox:
            raise TradierError("Sandbox does not provide real-time streaming")
        data = self._request_json("POST", "/markets/events/session").data
        session_id = (data.get("stream") or {}).get("sessionid")
        if not session_id:
            raise TradierError("Tradier did not return a streaming session id")
        return str(session_id)

    def stream_market_events_http(self, symbols: Iterable[str], *, filters: Iterable[str] = ("quote", "trade", "timesale"), session_id: str | None = None) -> Iterator[dict[str, Any]]:
        if self.sandbox:
            raise TradierError("Use a production token for real-time streaming")
        clean = [symbol.strip() for symbol in symbols if symbol and symbol.strip()]
        if not clean:
            return
        query = urllib.parse.urlencode({"symbols": ",".join(clean), "sessionid": session_id or self.create_market_session(), "filter": ",".join(filters), "linebreak": "true", "validOnly": "true"})
        request = urllib.request.Request(f"{self.LIVE_STREAM_BASE}/markets/events?{query}", headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=None) as response:
                for raw in response:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        yield event
        except urllib.error.HTTPError as exc:
            raise TradierError(f"Tradier stream HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise TradierError(f"Tradier stream network error: {exc.reason}") from exc

    def reconnecting_market_stream(self, symbols: Iterable[str], *, filters: Iterable[str] = ("quote", "trade", "timesale"), initial_backoff_seconds: float = 1.0, max_backoff_seconds: float = 30.0) -> Iterator[dict[str, Any]]:
        backoff = max(0.1, initial_backoff_seconds)
        while True:
            try:
                for event in self.stream_market_events_http(symbols, filters=filters):
                    backoff = max(0.1, initial_backoff_seconds)
                    yield event
                time.sleep(backoff)
                backoff = min(max_backoff_seconds, backoff * 2)
            except TradierError:
                time.sleep(backoff)
                backoff = min(max_backoff_seconds, backoff * 2)
