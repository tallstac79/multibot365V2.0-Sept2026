"""COMPLETE_EXECUTION_READY protections: duplicate, stale, price-change, restart recovery."""
from __future__ import annotations
import hashlib, json, time
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_MAX_AGE_S = 120

class GateError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail

def validation_hash(payload: Dict[str, Any]) -> str:
    raw = "|".join(str(payload.get(k, "")) for k in (
        "fixture", "market", "selection_role", "selection_name", "line", "price", "stake",
        "final_control_bounds", "timestamp_ms"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

def assert_not_duplicate(store: Dict[str, Any], instruction_id: str, validation_hash_value: str) -> None:
    prev = store.get(instruction_id)
    if prev and prev.get("validation_hash") == validation_hash_value and prev.get("terminal"):
        raise GateError("DUPLICATE", f"instruction {instruction_id} already terminal with same hash")

def assert_not_stale(cer: Dict[str, Any], now_ms: Optional[int] = None, max_age_s: int = DEFAULT_MAX_AGE_S) -> None:
    ts = int(cer.get("timestamp_ms") or 0)
    if ts <= 0:
        raise GateError("STATE_INVALID", "missing timestamp_ms")
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    age = (now - ts) / 1000.0
    if age > max_age_s:
        raise GateError("EXPIRED", f"COMPLETE_EXECUTION_READY age {age:.1f}s > {max_age_s}s")

def assert_price_ok(cer: Dict[str, Any], live_price: str) -> None:
    expected = str(cer.get("price"))
    if live_price != expected:
        raise GateError("PRICE_CHANGED", f"live {live_price} != prepared {expected}")
    try:
        if float(live_price) < float(cer.get("minimum_price") or 0):
            raise GateError("BELOW_MINIMUM", f"live {live_price} below minimum {cer.get('minimum_price')}")
    except (TypeError, ValueError) as e:
        raise GateError("STATE_INVALID", f"bad price fields: {e}") from e

def persist(path: Path, store: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2), encoding="utf-8")

def load(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def record_prepare(store: Dict[str, Any], instruction_id: str, cer: Dict[str, Any]) -> Dict[str, Any]:
    h = cer.get("validation_hash") or validation_hash(cer)
    assert_not_duplicate(store, instruction_id, h)
    assert_not_stale(cer)
    entry = {"validation_hash": h, "cer": cer, "terminal": False, "phase": "PREPARED", "updated_ms": int(time.time()*1000)}
    store[instruction_id] = entry
    return entry

def record_dispatch_result(store: Dict[str, Any], instruction_id: str, result: str, wager_submitted: bool) -> Dict[str, Any]:
    entry = store.get(instruction_id) or {}
    entry.update({
        "terminal": True,
        "phase": "DISPATCHED",
        "place_bet_result": result,
        "wager_submitted": wager_submitted,
        "updated_ms": int(time.time()*1000),
    })
    store[instruction_id] = entry
    return entry

def recover_after_restart(path: Path) -> Dict[str, Any]:
    """Load persisted store after process restart; non-terminal PREPARED rows remain actionable."""
    store = load(path)
    return {k: v for k, v in store.items() if isinstance(v, dict)}
