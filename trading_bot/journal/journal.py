from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

DEFAULT_DB_PATH = Path("journal.db")


@dataclass
class JournalEntry:
    entry_date: str
    strategy: str
    symbol: str
    metrics: dict
    notes: str = ""


class Journal:
    """SQLite-backed daily journal of backtest/trade results.

    One row per (date, strategy, symbol) run, so repeated backtests on the
    same day accumulate a history you can review to see how a strategy's
    performance evolves as it's tuned.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        # check_same_thread=False: FastAPI runs sync endpoints in a
        # threadpool, so this connection may be used from multiple threads.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_date TEXT NOT NULL,
                strategy TEXT NOT NULL,
                symbol TEXT NOT NULL,
                metrics TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def log(self, entry: JournalEntry) -> None:
        self._conn.execute(
            "INSERT INTO entries (entry_date, strategy, symbol, metrics, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                entry.entry_date,
                entry.strategy,
                entry.symbol,
                json.dumps(entry.metrics),
                entry.notes,
                datetime.utcnow().isoformat(),
            ),
        )
        self._conn.commit()

    def entries_for(self, entry_date: str | None = None) -> list[dict]:
        entry_date = entry_date or date.today().isoformat()
        cur = self._conn.execute(
            "SELECT entry_date, strategy, symbol, metrics, notes, created_at "
            "FROM entries WHERE entry_date = ? ORDER BY created_at",
            (entry_date,),
        )
        rows = cur.fetchall()
        return [
            {
                "entry_date": r[0],
                "strategy": r[1],
                "symbol": r[2],
                "metrics": json.loads(r[3]),
                "notes": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    def to_markdown(self, entry_date: str | None = None) -> str:
        entry_date = entry_date or date.today().isoformat()
        rows = self.entries_for(entry_date)
        if not rows:
            return f"# Journal — {entry_date}\n\nNo entries.\n"

        lines = [f"# Journal — {entry_date}\n"]
        for r in rows:
            lines.append(f"## {r['strategy']} on {r['symbol']}")
            for k, v in r["metrics"].items():
                lines.append(f"- **{k}**: {v}")
            if r["notes"]:
                lines.append(f"\n{r['notes']}")
            lines.append("")
        return "\n".join(lines)
