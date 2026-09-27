from __future__ import annotations

import sqlite3
import time
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
                series_position_label TEXT,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                match_kind TEXT,
                match_method TEXT,
                matched_path TEXT,
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
                reason TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'planned',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                undone_at TEXT,
                FOREIGN KEY (proposal_id) REFERENCES proposals(id)
            );
            CREATE INDEX IF NOT EXISTS idx_operations_batch ON operations(batch_id);
            CREATE TABLE IF NOT EXISTS metadata_cache (
                cache_key TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                payload TEXT NOT NULL,
                fetched_at INTEGER NOT NULL
            );
            """
        )
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(proposals)")}
        for column in ("match_kind", "match_method", "matched_path", "series_position_label"):
            if column not in columns:
                self.conn.execute(f"ALTER TABLE proposals ADD COLUMN {column} TEXT")
        operation_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(operations)")}
        for column, definition in (
            ("reason", "TEXT NOT NULL DEFAULT ''"),
            ("confidence", "REAL NOT NULL DEFAULT 0"),
            ("state", "TEXT NOT NULL DEFAULT 'applied'"),
            ("completed_at", "TEXT"),
            ("undone_at", "TEXT"),
        ):
            if column not in operation_columns:
                self.conn.execute(f"ALTER TABLE operations ADD COLUMN {column} {definition}")
        self.conn.commit()

    def get_metadata_cache(self, cache_key: str, max_age_seconds: int) -> str | None:
        row = self.conn.execute(
            "SELECT payload, fetched_at FROM metadata_cache WHERE cache_key=?", (cache_key,)
        ).fetchone()
        if not row or time.time() - row["fetched_at"] > max_age_seconds:
            return None
        return str(row["payload"])

    def put_metadata_cache(self, cache_key: str, provider: str, payload: str) -> None:
        self.conn.execute(
            """INSERT INTO metadata_cache(cache_key,provider,payload,fetched_at)
               VALUES(?,?,?,?)
               ON CONFLICT(cache_key) DO UPDATE SET provider=excluded.provider,
               payload=excluded.payload, fetched_at=excluded.fetched_at""",
            (cache_key, provider, payload, int(time.time())),
        )
        self.conn.commit()

    def add_proposal(self, proposal: Proposal) -> int:
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO proposals
            (source_path,destination_path,sha256,confidence,media_type,title,author,series,series_number,series_position_label,reason,status,match_kind,match_method,matched_path)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(proposal.source_path), str(proposal.destination_path), proposal.sha256,
             proposal.confidence, proposal.media_type, proposal.title, proposal.author,
             proposal.series, proposal.series_number, proposal.series_position_label, proposal.reason, proposal.status,
             proposal.match_kind, proposal.match_method, str(proposal.matched_path) if proposal.matched_path else None),
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

    def create_operation(self, batch_id: str, proposal_id: int) -> int:
        row = self.get(proposal_id)
        if not row:
            raise RuntimeError(f"Proposal not found: {proposal_id}")
        cur = self.conn.execute(
            """INSERT INTO operations
               (batch_id,proposal_id,source_path,destination_path,sha256,reason,confidence,state)
               VALUES(?,?,?,?,?,?,?,'planned')""",
            (batch_id, proposal_id, row["source_path"], row["destination_path"], row["sha256"], row["reason"], row["confidence"]),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def mark_operation_applied(self, operation_id: int, proposal_id: int) -> None:
        self.conn.execute("UPDATE operations SET state='applied', completed_at=CURRENT_TIMESTAMP WHERE id=?", (operation_id,))
        self.conn.execute("UPDATE proposals SET status='applied', applied_at=CURRENT_TIMESTAMP WHERE id=?", (proposal_id,))
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
        self.conn.execute("UPDATE operations SET state='undone', undone_at=CURRENT_TIMESTAMP WHERE batch_id=?", (batch_id,))
        self.conn.execute(
            "UPDATE proposals SET status='undone' WHERE id IN (SELECT proposal_id FROM operations WHERE batch_id=?)",
            (batch_id,),
        )
        self.conn.commit()
