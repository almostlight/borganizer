from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .models import Proposal


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_path TEXT NOT NULL,
                destination_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                confidence REAL NOT NULL,
                media_type TEXT NOT NULL,
                title TEXT,
                author TEXT,
                series TEXT,
                series_number REAL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                applied_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_unique
              ON proposals(source_path, sha256, destination_path)
              WHERE status='pending';

            CREATE TABLE IF NOT EXISTS operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                proposal_id INTEGER NOT NULL,
                source_path TEXT NOT NULL,
                destination_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (proposal_id) REFERENCES proposals(id)
            );
            CREATE INDEX IF NOT EXISTS idx_operations_batch ON operations(batch_id);
            """
        )
        self.conn.commit()

    def add_proposal(self, proposal: Proposal) -> int:
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO proposals
            (source_path,destination_path,sha256,confidence,media_type,title,author,series,series_number,reason,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (str(proposal.source_path), str(proposal.destination_path), proposal.sha256,
             proposal.confidence, proposal.media_type, proposal.title, proposal.author,
             proposal.series, proposal.series_number, proposal.reason, proposal.status),
        )
        self.conn.commit()
        if cur.lastrowid:
            return int(cur.lastrowid)
        row = self.conn.execute(
            "SELECT id FROM proposals WHERE source_path=? AND sha256=? AND destination_path=? AND status=? ORDER BY id DESC LIMIT 1",
            (str(proposal.source_path), proposal.sha256, str(proposal.destination_path), proposal.status),
        ).fetchone()
        if not row:
            raise RuntimeError("Could not retrieve inserted/existing proposal")
        return int(row["id"])

    def pending(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM proposals WHERE status='pending' ORDER BY id"))

    def get(self, proposal_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()

    def mark_applied(self, ids: Iterable[int], batch_id: str) -> None:
        ids = list(ids)
        for proposal_id in ids:
            row = self.get(proposal_id)
            if not row:
                continue
            self.conn.execute("UPDATE proposals SET status='applied', applied_at=CURRENT_TIMESTAMP WHERE id=?", (proposal_id,))
            self.conn.execute(
                "INSERT INTO operations(batch_id,proposal_id,source_path,destination_path,sha256) VALUES(?,?,?,?,?)",
                (batch_id, proposal_id, row["source_path"], row["destination_path"], row["sha256"]),
            )
        self.conn.commit()

    def mark_rejected(self, proposal_id: int) -> None:
        self.conn.execute("UPDATE proposals SET status='rejected' WHERE id=?", (proposal_id,))
        self.conn.commit()

    def latest_batch(self) -> str | None:
        row = self.conn.execute("SELECT batch_id FROM operations ORDER BY id DESC LIMIT 1").fetchone()
        return row[0] if row else None

    def batch_operations(self, batch_id: str) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM operations WHERE batch_id=? ORDER BY id DESC", (batch_id,)))


    def counts(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT status, COUNT(*) AS n FROM proposals GROUP BY status").fetchall()
        return {row["status"]: int(row["n"]) for row in rows}

    def mark_undone(self, batch_id: str) -> None:
        self.conn.execute(
            "UPDATE proposals SET status='undone' WHERE id IN (SELECT proposal_id FROM operations WHERE batch_id=?)",
            (batch_id,),
        )
        self.conn.commit()
