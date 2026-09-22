"""Unit tests for confirmation worker (stdlib unittest)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.confirmation.normalize import normalize_payload
from tools.confirmation.schema import DecisionStatus
from tools.confirmation.store import ConfirmationStore
from tools.confirmation.worker import ConfirmationWorker

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str, *, fresh: bool = True) -> dict:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    # Keep stale fixture timestamps; refresh others so the 120s window does not flake.
    if fresh and name != "stale_ready_state.json" and isinstance(data, dict):
        data = dict(data)
        data["validated_at"] = _iso(datetime.now(timezone.utc))
        # Nested adapter fixture may nest ready_state
        for key in ("ready_state", "result", "evidence"):
            nested = data.get(key)
            if isinstance(nested, dict) and "validated_at" in nested:
                nested = dict(nested)
                nested["validated_at"] = data["validated_at"]
                data[key] = nested
    return data


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        (self.root / "inbox").mkdir()
        (self.root / "outbox").mkdir()
        (self.root / "data").mkdir()
        self.worker = ConfirmationWorker(self.root, max_age_seconds=120)

    def tearDown(self) -> None:
        self.worker.close()
        self._tmpdir.cleanup()

    def test_duplicate_instruction_id(self) -> None:
        payload = _load("valid_ready_state.json")
        first = self.worker.ingest_mapping(payload)
        self.assertEqual(first["status"], DecisionStatus.PENDING.value)
        second = self.worker.ingest_mapping(payload)
        self.assertEqual(second["status"], DecisionStatus.DUPLICATE.value)

    def test_stale_validated_at_expired(self) -> None:
        payload = _load("stale_ready_state.json")
        doc = self.worker.ingest_mapping(payload)
        self.assertEqual(doc["status"], DecisionStatus.EXPIRED.value)

    def test_malformed_missing_fields_state_invalid(self) -> None:
        payload = _load("malformed_ready_state.json")
        doc = self.worker.ingest_mapping(payload)
        self.assertEqual(doc["status"], DecisionStatus.STATE_INVALID.value)

    def test_price_below_minimum(self) -> None:
        payload = _load("price_below_minimum.json")
        doc = self.worker.ingest_mapping(payload)
        self.assertEqual(doc["status"], DecisionStatus.PRICE_INVALID.value)

    def test_restart_persist_pending_and_approve(self) -> None:
        payload = _load("valid_ready_state.json")
        payload = dict(payload)
        payload["instruction_id"] = "instr-restart-001"
        payload["validation_hash"] = "hash-restart-001"
        doc = self.worker.ingest_mapping(payload)
        self.assertEqual(doc["status"], DecisionStatus.PENDING.value)
        db_path = self.worker.db_path
        self.worker.close()

        # Simulate restart: new worker, same DB
        worker2 = ConfirmationWorker(self.root, max_age_seconds=120, db_path=db_path)
        try:
            pending = worker2.pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["instruction_id"], "instr-restart-001")
            approved = worker2.approve("instr-restart-001")
            self.assertEqual(approved["status"], DecisionStatus.APPROVED.value)
            out = json.loads((self.root / "outbox" / "instr-restart-001.json").read_text())
            self.assertEqual(out["status"], DecisionStatus.APPROVED.value)
        finally:
            worker2.close()
            # re-open for tearDown
            self.worker = ConfirmationWorker(self.root, max_age_seconds=120, db_path=db_path)

    def test_approve_then_reapprove_duplicate(self) -> None:
        payload = _load("valid_ready_state.json")
        payload = dict(payload)
        payload["instruction_id"] = "instr-reapprove-001"
        payload["validation_hash"] = "hash-reapprove-001"
        self.worker.ingest_mapping(payload)
        first = self.worker.approve("instr-reapprove-001")
        self.assertEqual(first["status"], DecisionStatus.APPROVED.value)
        second = self.worker.approve("instr-reapprove-001")
        self.assertEqual(second["status"], DecisionStatus.DUPLICATE.value)
        # Store must remain APPROVED (no second APPROVED overwrite race)
        row = self.worker.store.get("instr-reapprove-001")
        self.assertEqual(row["status"], DecisionStatus.APPROVED.value)

    def test_normalizer_nested_adapter_shape(self) -> None:
        nested = _load("nested_adapter_ready_state.json")
        flat = normalize_payload(nested)
        self.assertEqual(flat["instruction_id"], "instr-nested-001")
        self.assertEqual(flat["fixture"], "Alpha United v Beta City")
        self.assertEqual(flat["current_price"], 2.10)
        self.assertEqual(flat["minimum_price"], 1.50)
        doc = self.worker.ingest_mapping(nested)
        self.assertEqual(doc["status"], DecisionStatus.PENDING.value)

    def test_expire_stale_pending(self) -> None:
        payload = _load("valid_ready_state.json")
        payload = dict(payload)
        payload["instruction_id"] = "instr-expire-001"
        payload["validation_hash"] = "hash-expire-001"
        # Force validated_at just inside window at ingest, then shrink max age
        self.worker.ingest_mapping(payload)
        self.worker.max_age_seconds = 0
        expired = self.worker.expire()
        self.assertTrue(any(d["instruction_id"] == "instr-expire-001" for d in expired))
        self.assertEqual(expired[0]["status"], DecisionStatus.EXPIRED.value)

    def test_store_close_reopen_no_replay(self) -> None:
        """Closing and reopening SQLite preserves decisions (restart path)."""
        payload = _load("valid_ready_state.json")
        payload = dict(payload)
        payload["instruction_id"] = "instr-store-001"
        self.worker.ingest_mapping(payload)
        self.worker.approve("instr-store-001")
        path = self.worker.db_path
        self.worker.close()
        with ConfirmationStore(path) as store:
            row = store.get("instr-store-001")
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "APPROVED")
        self.worker = ConfirmationWorker(self.root, db_path=path)
        again = self.worker.ingest_mapping(payload)
        self.assertEqual(again["status"], DecisionStatus.DUPLICATE.value)


if __name__ == "__main__":
    unittest.main()
