"""SQLite persistence for confirmation worker (separate from phone coordinator DB)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ConfirmationStore:
    """Local SQLite: instructions seen, decisions, no-replay."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._migrate()

    def _migrate(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS instructions (
                instruction_id TEXT PRIMARY KEY,
                device_id TEXT,
                validation_hash TEXT,
                validated_at TEXT,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                decided_at TEXT
            );
            CREATE TABLE IF NOT EXISTS decision_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instruction_id TEXT NOT NULL,
                device_id TEXT,
                validation_hash TEXT,
                status TEXT NOT NULL,
                reason TEXT,
                payload_json TEXT,
                timestamp TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_instructions_status
                ON instructions(status);
            CREATE INDEX IF NOT EXISTS idx_log_instruction
                ON decision_log(instruction_id);
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ConfirmationStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def get(self, instruction_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM instructions WHERE instruction_id = ?",
            (instruction_id,),
        ).fetchone()
        return dict(row) if row else None

    def upsert_instruction(
        self,
        *,
        instruction_id: str,
        device_id: str,
        validation_hash: str,
        validated_at: str,
        payload: Mapping[str, Any],
        status: str,
        reason: Optional[str] = None,
        decided: bool = False,
    ) -> None:
        now = _utc_now()
        existing = self.get(instruction_id)
        decided_at = now if decided else (existing.get("decided_at") if existing else None)
        if existing:
            self._conn.execute(
                """
                UPDATE instructions SET
                    device_id = ?, validation_hash = ?, validated_at = ?,
                    payload_json = ?, status = ?, reason = ?,
                    updated_at = ?, decided_at = COALESCE(?, decided_at)
                WHERE instruction_id = ?
                """,
                (
                    device_id,
                    validation_hash,
                    validated_at,
                    json.dumps(payload, sort_keys=True),
                    status,
                    reason,
                    now,
                    decided_at if decided else None,
                    instruction_id,
                ),
            )
        else:
            self._conn.execute(
                """
                INSERT INTO instructions (
                    instruction_id, device_id, validation_hash, validated_at,
                    payload_json, status, reason, created_at, updated_at, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    instruction_id,
                    device_id,
                    validation_hash,
                    validated_at,
                    json.dumps(payload, sort_keys=True),
                    status,
                    reason,
                    now,
                    now,
                    decided_at,
                ),
            )
        self._conn.commit()

    def log_decision(
        self,
        *,
        instruction_id: str,
        device_id: Optional[str],
        validation_hash: Optional[str],
        status: str,
        reason: Optional[str],
        payload: Optional[Mapping[str, Any]],
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO decision_log (
                instruction_id, device_id, validation_hash, status, reason,
                payload_json, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instruction_id,
                device_id,
                validation_hash,
                status,
                reason,
                json.dumps(payload, sort_keys=True) if payload is not None else None,
                _utc_now(),
            ),
        )
        self._conn.commit()

    def list_by_status(self, status: str) -> List[dict]:
        rows = self._conn.execute(
            "SELECT * FROM instructions WHERE status = ? ORDER BY created_at ASC",
            (status,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_pending(self) -> List[dict]:
        return self.list_by_status("PENDING")

    def all_instructions(self) -> List[dict]:
        rows = self._conn.execute(
            "SELECT * FROM instructions ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def recent_logs(self, limit: int = 50) -> List[dict]:
        rows = self._conn.execute(
            "SELECT * FROM decision_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
