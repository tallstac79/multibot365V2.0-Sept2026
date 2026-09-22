"""Confirmation worker: ingest → revalidate → pending / terminal; approve/reject; expire."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from .normalize import normalize_payload
from .revalidate import is_stale_pending, revalidate
from .schema import DEFAULT_STALE_SECONDS, DecisionStatus, TERMINAL_STATUSES
from .store import ConfirmationStore

log = logging.getLogger("tools.confirmation")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ConfirmationWorker:
    """Companion confirmation worker. Never Place Bet."""

    def __init__(
        self,
        root: Path | str,
        *,
        max_age_seconds: int = DEFAULT_STALE_SECONDS,
        db_path: Path | str | None = None,
    ):
        self.root = Path(root)
        self.inbox = self.root / "inbox"
        self.outbox = self.root / "outbox"
        self.data_dir = self.root / "data"
        self.max_age_seconds = max_age_seconds
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.outbox.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else self.data_dir / "confirmation.sqlite3"
        self.store = ConfirmationStore(self.db_path)

    def close(self) -> None:
        self.store.close()

    def _write_outbox(self, instruction_id: str, decision: Mapping[str, Any]) -> Path:
        path = self.outbox / f"{instruction_id}.json"
        path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _decision_doc(
        self,
        *,
        instruction_id: str,
        status: DecisionStatus,
        reason: str,
        payload: Optional[Mapping[str, Any]],
        validation_hash: Optional[str] = None,
        device_id: Optional[str] = None,
    ) -> dict:
        return {
            "instruction_id": instruction_id,
            "status": status.value,
            "reason": reason,
            "validation_hash": validation_hash or (payload or {}).get("validation_hash"),
            "device_id": device_id or (payload or {}).get("device_id"),
            "decided_at": _utc_now(),
            "payload": dict(payload) if payload else None,
        }

    def ingest_mapping(self, raw: Mapping[str, Any], *, normalize: bool = True) -> dict:
        """Ingest a READY_STATE (or nested adapter payload). Returns decision dict."""
        try:
            payload = normalize_payload(raw) if normalize else dict(raw)
        except ValueError as exc:
            # Without instruction_id we cannot key the store — still log outbox under INTERNAL/STATE
            instruction_id = str(raw.get("instruction_id") or "unknown")
            doc = self._decision_doc(
                instruction_id=instruction_id,
                status=DecisionStatus.STATE_INVALID,
                reason=str(exc),
                payload=raw if isinstance(raw, Mapping) else None,
            )
            if instruction_id != "unknown":
                self.store.upsert_instruction(
                    instruction_id=instruction_id,
                    device_id=str(raw.get("device_id") or ""),
                    validation_hash=str(raw.get("validation_hash") or ""),
                    validated_at=str(raw.get("validated_at") or ""),
                    payload=raw,
                    status=DecisionStatus.STATE_INVALID.value,
                    reason=str(exc),
                    decided=True,
                )
                self.store.log_decision(
                    instruction_id=instruction_id,
                    device_id=str(raw.get("device_id") or ""),
                    validation_hash=str(raw.get("validation_hash") or ""),
                    status=DecisionStatus.STATE_INVALID.value,
                    reason=str(exc),
                    payload=raw,
                )
                self._write_outbox(instruction_id, doc)
            log.info(
                "decision=%s instruction_id=%s reason=%s",
                DecisionStatus.STATE_INVALID.value,
                instruction_id,
                exc,
            )
            return doc

        instruction_id = payload["instruction_id"]
        existing = self.store.get(instruction_id)
        result = revalidate(
            payload,
            already_seen=existing,
            max_age_seconds=self.max_age_seconds,
        )

        status = result.status
        reason = result.reason
        rs = result.ready_state
        store_payload = rs.to_dict() if rs else payload

        decided = status != DecisionStatus.PENDING
        self.store.upsert_instruction(
            instruction_id=instruction_id,
            device_id=str(store_payload.get("device_id") or ""),
            validation_hash=str(store_payload.get("validation_hash") or ""),
            validated_at=str(store_payload.get("validated_at") or ""),
            payload=store_payload,
            status=status.value,
            reason=reason,
            decided=decided,
        )
        self.store.log_decision(
            instruction_id=instruction_id,
            device_id=str(store_payload.get("device_id") or ""),
            validation_hash=str(store_payload.get("validation_hash") or ""),
            status=status.value,
            reason=reason,
            payload=store_payload,
        )

        doc = self._decision_doc(
            instruction_id=instruction_id,
            status=status if status != DecisionStatus.PENDING else DecisionStatus.PENDING,
            reason=reason,
            payload=store_payload,
        )
        # Outbox: write terminal decisions immediately; pending also gets a pending marker
        self._write_outbox(instruction_id, doc)
        log.info(
            "decision=%s instruction_id=%s device_id=%s validation_hash=%s reason=%s",
            status.value,
            instruction_id,
            store_payload.get("device_id"),
            store_payload.get("validation_hash"),
            reason,
        )
        return doc

    def ingest_file(self, path: Path | str, *, normalize: bool = True) -> dict:
        p = Path(path)
        raw = json.loads(p.read_text(encoding="utf-8"))
        return self.ingest_mapping(raw, normalize=normalize)

    def ingest_inbox(self) -> list:
        results = []
        for path in sorted(self.inbox.glob("*.json")):
            results.append(self.ingest_file(path))
        return results

    def pending(self) -> list:
        return self.store.list_pending()

    def approve(self, instruction_id: str, *, note: str = "human APPROVE") -> dict:
        row = self.store.get(instruction_id)
        if row is None:
            doc = self._decision_doc(
                instruction_id=instruction_id,
                status=DecisionStatus.STATE_INVALID,
                reason="unknown instruction_id",
                payload=None,
            )
            return doc
        if row["status"] == DecisionStatus.APPROVED.value:
            doc = self._decision_doc(
                instruction_id=instruction_id,
                status=DecisionStatus.DUPLICATE,
                reason="already APPROVED; no second approval",
                payload=json.loads(row["payload_json"]),
                validation_hash=row.get("validation_hash"),
                device_id=row.get("device_id"),
            )
            self.store.log_decision(
                instruction_id=instruction_id,
                device_id=row.get("device_id"),
                validation_hash=row.get("validation_hash"),
                status=DecisionStatus.DUPLICATE.value,
                reason=doc["reason"],
                payload=json.loads(row["payload_json"]),
            )
            self._write_outbox(instruction_id, doc)
            return doc
        if row["status"] != DecisionStatus.PENDING.value:
            doc = self._decision_doc(
                instruction_id=instruction_id,
                status=DecisionStatus.DUPLICATE,
                reason=f"cannot approve from status {row['status']}",
                payload=json.loads(row["payload_json"]),
                validation_hash=row.get("validation_hash"),
                device_id=row.get("device_id"),
            )
            self._write_outbox(instruction_id, doc)
            return doc

        # Expire check at approval time
        if is_stale_pending(row, max_age_seconds=self.max_age_seconds):
            return self._expire_row(row, reason="stale at approval time")

        payload = json.loads(row["payload_json"])
        self.store.upsert_instruction(
            instruction_id=instruction_id,
            device_id=row.get("device_id") or "",
            validation_hash=row.get("validation_hash") or "",
            validated_at=row.get("validated_at") or "",
            payload=payload,
            status=DecisionStatus.APPROVED.value,
            reason=note,
            decided=True,
        )
        self.store.log_decision(
            instruction_id=instruction_id,
            device_id=row.get("device_id"),
            validation_hash=row.get("validation_hash"),
            status=DecisionStatus.APPROVED.value,
            reason=note,
            payload=payload,
        )
        doc = self._decision_doc(
            instruction_id=instruction_id,
            status=DecisionStatus.APPROVED,
            reason=note,
            payload=payload,
            validation_hash=row.get("validation_hash"),
            device_id=row.get("device_id"),
        )
        self._write_outbox(instruction_id, doc)
        log.info("decision=APPROVED instruction_id=%s note=%s", instruction_id, note)
        return doc

    def reject(self, instruction_id: str, *, note: str = "human REJECT") -> dict:
        row = self.store.get(instruction_id)
        if row is None:
            return self._decision_doc(
                instruction_id=instruction_id,
                status=DecisionStatus.STATE_INVALID,
                reason="unknown instruction_id",
                payload=None,
            )
        if row["status"] != DecisionStatus.PENDING.value:
            doc = self._decision_doc(
                instruction_id=instruction_id,
                status=DecisionStatus.DUPLICATE,
                reason=f"cannot reject from status {row['status']}",
                payload=json.loads(row["payload_json"]),
                validation_hash=row.get("validation_hash"),
                device_id=row.get("device_id"),
            )
            self._write_outbox(instruction_id, doc)
            return doc
        payload = json.loads(row["payload_json"])
        self.store.upsert_instruction(
            instruction_id=instruction_id,
            device_id=row.get("device_id") or "",
            validation_hash=row.get("validation_hash") or "",
            validated_at=row.get("validated_at") or "",
            payload=payload,
            status=DecisionStatus.REJECTED.value,
            reason=note,
            decided=True,
        )
        self.store.log_decision(
            instruction_id=instruction_id,
            device_id=row.get("device_id"),
            validation_hash=row.get("validation_hash"),
            status=DecisionStatus.REJECTED.value,
            reason=note,
            payload=payload,
        )
        doc = self._decision_doc(
            instruction_id=instruction_id,
            status=DecisionStatus.REJECTED,
            reason=note,
            payload=payload,
            validation_hash=row.get("validation_hash"),
            device_id=row.get("device_id"),
        )
        self._write_outbox(instruction_id, doc)
        log.info("decision=REJECTED instruction_id=%s note=%s", instruction_id, note)
        return doc

    def _expire_row(self, row: Mapping[str, Any], *, reason: str) -> dict:
        instruction_id = row["instruction_id"]
        payload = json.loads(row["payload_json"])
        self.store.upsert_instruction(
            instruction_id=instruction_id,
            device_id=row.get("device_id") or "",
            validation_hash=row.get("validation_hash") or "",
            validated_at=row.get("validated_at") or "",
            payload=payload,
            status=DecisionStatus.EXPIRED.value,
            reason=reason,
            decided=True,
        )
        self.store.log_decision(
            instruction_id=instruction_id,
            device_id=row.get("device_id"),
            validation_hash=row.get("validation_hash"),
            status=DecisionStatus.EXPIRED.value,
            reason=reason,
            payload=payload,
        )
        doc = self._decision_doc(
            instruction_id=instruction_id,
            status=DecisionStatus.EXPIRED,
            reason=reason,
            payload=payload,
            validation_hash=row.get("validation_hash"),
            device_id=row.get("device_id"),
        )
        self._write_outbox(instruction_id, doc)
        return doc

    def expire(self) -> list:
        """Auto-expire stale PENDING payloads."""
        expired = []
        for row in self.store.list_pending():
            if is_stale_pending(row, max_age_seconds=self.max_age_seconds):
                expired.append(
                    self._expire_row(
                        row,
                        reason=f"auto-expired after {self.max_age_seconds}s",
                    )
                )
        return expired

    def status_summary(self) -> dict:
        counts: dict[str, int] = {}
        for row in self.store.all_instructions():
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return {
            "db_path": str(self.db_path),
            "max_age_seconds": self.max_age_seconds,
            "counts": counts,
            "pending": [r["instruction_id"] for r in self.store.list_pending()],
        }
