import time, unittest
from pathlib import Path
import tempfile
from tools.complete_execution.gate import (
    GateError, assert_not_duplicate, assert_not_stale, assert_price_ok,
    record_prepare, record_dispatch_result, persist, recover_after_restart, validation_hash,
)

def sample_cer(**over):
    base = {
        "state": "COMPLETE_EXECUTION_READY",
        "fixture": "Arsenal v Leeds",
        "market": "MONEYLINE",
        "selection_role": "HOME",
        "selection_name": "Arsenal",
        "line": "NONE",
        "price": "1.33",
        "stake": "1.00",
        "minimum_price": "1.01",
        "final_control_bounds": [400, 1300, 600, 1360],
        "timestamp_ms": int(time.time() * 1000),
    }
    base.update(over)
    base["validation_hash"] = validation_hash(base)
    return base

class GateTests(unittest.TestCase):
    def test_duplicate_protection(self):
        store = {}
        cer = sample_cer()
        record_prepare(store, "id1", cer)
        record_dispatch_result(store, "id1", "INSUFFICIENT_BALANCE", False)
        with self.assertRaises(GateError) as ctx:
            assert_not_duplicate(store, "id1", cer["validation_hash"])
        self.assertEqual(ctx.exception.code, "DUPLICATE")

    def test_stale_protection(self):
        cer = sample_cer(timestamp_ms=int(time.time()*1000) - 200_000)
        with self.assertRaises(GateError) as ctx:
            assert_not_stale(cer, max_age_s=120)
        self.assertEqual(ctx.exception.code, "EXPIRED")

    def test_price_change_protection(self):
        cer = sample_cer(price="1.33")
        with self.assertRaises(GateError) as ctx:
            assert_price_ok(cer, "1.40")
        self.assertEqual(ctx.exception.code, "PRICE_CHANGED")

    def test_restart_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "exec_store.json"
            store = {}
            cer = sample_cer()
            record_prepare(store, "id2", cer)
            persist(path, store)
            recovered = recover_after_restart(path)
            self.assertIn("id2", recovered)
            self.assertEqual(recovered["id2"]["phase"], "PREPARED")
            self.assertFalse(recovered["id2"]["terminal"])

if __name__ == "__main__":
    unittest.main()
