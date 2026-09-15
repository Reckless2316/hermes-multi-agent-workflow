"""SQLite paper ledger for defined-risk multileg options positions."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .types import SizedCandidate


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _signature(item: SizedCandidate) -> str:
    candidate = item.candidate
    return "|".join(
        [
            candidate.underlying,
            candidate.strategy.value,
            candidate.expiration,
            *sorted(leg.option_symbol for leg in candidate.legs),
        ]
    )


class OptionsPaperLedger:
    """Append lifecycle state for exact multileg paper positions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=10.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS options_positions (
                id TEXT PRIMARY KEY,
                signature TEXT NOT NULL,
                approval_slug TEXT,
                underlying TEXT NOT NULL,
                strategy TEXT NOT NULL,
                expiration TEXT NOT NULL,
                direction TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                legs_json TEXT NOT NULL,
                entry_credit REAL NOT NULL,
                entry_mark_credit REAL NOT NULL,
                max_profit REAL NOT NULL,
                max_loss REAL NOT NULL,
                buying_power_reduction REAL NOT NULL,
                profit_target_pct REAL NOT NULL,
                manage_at_dte INTEGER NOT NULL,
                strategy_version TEXT NOT NULL,
                status TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                exit_time TEXT,
                exit_debit REAL,
                realized_pnl REAL,
                outcome TEXT,
                close_reason TEXT,
                candidate_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_options_positions_status
                ON options_positions(status);
            CREATE INDEX IF NOT EXISTS idx_options_positions_signature
                ON options_positions(signature);
            CREATE TABLE IF NOT EXISTS options_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id TEXT NOT NULL,
                event_time TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def __enter__(self) -> "OptionsPaperLedger":
        return self

    def __exit__(self, *exc: object) -> None:
        self.conn.close()

    def _event(self, position_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO options_events(position_id,event_time,event_type,payload_json) VALUES (?,?,?,?)",
            (position_id, _now(), event_type, json.dumps(payload, sort_keys=True, default=str)),
        )

    def is_duplicate_open(self, item: SizedCandidate) -> bool:
        return self.conn.execute("SELECT 1 FROM options_positions WHERE signature=? AND status='OPEN' LIMIT 1", (_signature(item),)).fetchone() is not None

    def open_position(self, item: SizedCandidate, *, approval_slug: str | None = None) -> str:
        if self.is_duplicate_open(item):
            raise ValueError("Duplicate open options structure")
        candidate = item.candidate
        position_id = uuid.uuid4().hex[:12]
        entry_time = _now()
        candidate_payload = {
            **candidate.to_dict(),
            "contracts": item.contracts,
            "risk_budget": item.risk_budget,
            "total_max_loss": item.total_max_loss,
            "total_profit_target": item.total_profit_target,
            "total_buying_power_reduction": item.total_buying_power_reduction,
        }
        legs_json = json.dumps([asdict(leg) for leg in candidate.legs], sort_keys=True)
        self.conn.execute(
            """
            INSERT INTO options_positions (
                id, signature, approval_slug, underlying, strategy, expiration,
                direction, quantity, legs_json, entry_credit, entry_mark_credit,
                max_profit, max_loss, buying_power_reduction, profit_target_pct,
                manage_at_dte, strategy_version, status, entry_time, candidate_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'OPEN',?,?)
            """,
            (position_id, _signature(item), approval_slug, candidate.underlying, candidate.strategy.value, candidate.expiration, candidate.direction, item.contracts, legs_json, candidate.net_credit, candidate.mark_credit, candidate.max_profit * item.contracts, item.total_max_loss, item.total_buying_power_reduction, candidate.profit_target_pct, candidate.manage_at_dte, candidate.strategy_version, entry_time, json.dumps(candidate_payload, sort_keys=True)),
        )
        self._event(position_id, "OPEN", candidate_payload)
        self.conn.commit()
        return position_id

    def close_position(self, position_id: str, *, exit_debit: float, reason: str) -> dict[str, Any]:
        if exit_debit < 0:
            raise ValueError("exit_debit must be non-negative")
        row = self.conn.execute("SELECT * FROM options_positions WHERE id=?", (position_id,)).fetchone()
        if row is None:
            raise KeyError(position_id)
        if row["status"] != "OPEN":
            raise ValueError("Position is not open")
        pnl = (float(row["entry_credit"]) - exit_debit) * 100.0 * int(row["quantity"])
        outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BE"
        self.conn.execute("""UPDATE options_positions SET status='CLOSED', exit_time=?, exit_debit=?, realized_pnl=?, outcome=?, close_reason=? WHERE id=?""", (_now(), exit_debit, pnl, outcome, reason, position_id))
        self._event(position_id, "CLOSE", {"exit_debit": exit_debit, "realized_pnl": pnl, "outcome": outcome, "reason": reason})
        self.conn.commit()
        return dict(self.conn.execute("SELECT * FROM options_positions WHERE id=?", (position_id,)).fetchone())

    def open_positions(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute("SELECT * FROM options_positions WHERE status='OPEN' ORDER BY entry_time").fetchall()]

    def all_positions(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute("SELECT * FROM options_positions ORDER BY entry_time").fetchall()]

    def committed_defined_risk(self) -> float:
        row = self.conn.execute("SELECT COALESCE(SUM(max_loss),0) AS risk FROM options_positions WHERE status='OPEN'").fetchone()
        return float(row["risk"])

    def metrics(self) -> dict[str, float | int]:
        pnl = [float(row["realized_pnl"] or 0) for row in self.conn.execute("SELECT realized_pnl FROM options_positions WHERE status='CLOSED'").fetchall()]
        wins = [value for value in pnl if value > 0]
        losses = [value for value in pnl if value < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        return {
            "closed_trades": len(pnl),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(pnl) if pnl else 0.0,
            "net_pnl": sum(pnl),
            "avg_pnl": sum(pnl) / len(pnl) if pnl else 0.0,
            "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0,
        }

    def export_json(self, path: str | Path) -> None:
        output = []
        for row in self.all_positions():
            row["legs"] = json.loads(row.pop("legs_json"))
            row["candidate"] = json.loads(row.pop("candidate_json"))
            output.append(row)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + ".tmp")
        temp.write_text(json.dumps(output, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        temp.replace(target)
