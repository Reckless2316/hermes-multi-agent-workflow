"""Paper execution + 25/50% and 21-DTE position manager.

Fills at the current mid from the adapter (or the authorized setup's credit if
replaying). Live multi-leg routing is out of scope.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .config import DeskConfig
from .types import ScanResult, SetupStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PaperTrade:
    id: str
    symbol: str
    structure: str
    status: str = "OPEN"  # OPEN / CLOSED
    qty: int = 1
    credit: float = 0.0          # per share at entry
    max_profit: float = 0.0      # dollars, all qty
    max_loss: float = 0.0
    buying_power: float = 0.0
    profit_target: float = 0.0   # dollars
    profit_target_pct: float = 50.0
    management_dte: int = 21
    entry_dte: int = 45
    expiration: str = ""
    entry_time: str = field(default_factory=_now)
    exit_time: str | None = None
    exit_credit: float | None = None
    pnl: float | None = None
    reason: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


class PaperTrader:
    def __init__(self, journal_path: str | Path, cfg: DeskConfig | None = None):
        self.journal_path = Path(journal_path)
        self.cfg = cfg

    def _load(self) -> list[dict]:
        if not self.journal_path.exists():
            return []
        return json.loads(self.journal_path.read_text(encoding="utf-8"))

    def _save(self, rows: list[dict]) -> None:
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self.journal_path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")

    def open_from_scan(self, result: ScanResult) -> PaperTrade:
        if result.status != SetupStatus.TAKE or result.spread is None:
            raise ValueError(f"refusing to paper-fill a non-TAKE: {result.status} {result.reason}")
        sp = result.spread
        pct = (self.cfg.profit_target_pct(sp.structure) if self.cfg else 50.0)
        trade = PaperTrade(
            id="p_" + uuid.uuid4().hex[:10],
            symbol=sp.underlying,
            structure=sp.structure,
            qty=result.qty,
            credit=sp.credit,
            max_profit=sp.max_profit * result.qty,
            max_loss=sp.max_loss * result.qty,
            buying_power=sp.buying_power * result.qty,
            profit_target=result.profit_target or (sp.max_profit * result.qty * pct / 100.0),
            profit_target_pct=pct,
            management_dte=result.management_dte or 21,
            entry_dte=sp.dte,
            expiration=sp.expiration.isoformat(),
            extras={
                "legs": [
                    {"occ": lg.contract.occ, "side": lg.side, "strike": lg.contract.strike, "right": lg.contract.right}
                    for lg in sp.legs
                ],
                "width": sp.width,
                "capital_efficiency": result.capital_efficiency,
            },
        )
        rows = self._load()
        rows.append(asdict(trade))
        self._save(rows)
        return trade

    def open_raw(self, **fields: Any) -> PaperTrade:
        trade = PaperTrade(id="p_" + uuid.uuid4().hex[:10], **fields)
        rows = self._load()
        rows.append(asdict(trade))
        self._save(rows)
        return trade

    def manage(self, as_of: date, marks: dict[str, float] | None = None) -> list[dict]:
        """Close OPEN trades at profit target or management DTE.

        `marks` maps trade id -> current credit (per share) to close the spread.
        If omitted, uses a conservative model: remaining credit = entry_credit * remaining_dte/entry_dte
        is NOT used — without a mark we only act on DTE.
        """
        rows = self._load()
        closed: list[dict] = []
        for row in rows:
            if row.get("status") != "OPEN":
                continue
            exp = date.fromisoformat(row["expiration"])
            dte = (exp - as_of).days
            mark = None if not marks else marks.get(row["id"])
            should_close = False
            reason = ""
            pnl = None
            if dte <= int(row.get("management_dte") or 21):
                should_close = True
                reason = f"manage_at_dte ({dte} DTE)"
            if mark is not None:
                entry_c = float(row["credit"])
                captured = (entry_c - mark) * 100 * int(row["qty"])
                if captured >= float(row["profit_target"]) * 0.999:
                    should_close = True
                    reason = f"profit_target ${row['profit_target']:.2f}"
                pnl = captured
            if should_close:
                if pnl is None:
                    # DTE exit without a mark: realize 0 rather than invent a fill.
                    pnl = 0.0
                    mark = float(row["credit"])
                    reason += " (no mark; PnL recorded 0 — supply marks for a real close)"
                row["status"] = "CLOSED"
                row["exit_time"] = _now()
                row["exit_credit"] = mark
                row["pnl"] = round(pnl, 2)
                row["reason"] = reason
                closed.append(row)
        self._save(rows)
        return closed
