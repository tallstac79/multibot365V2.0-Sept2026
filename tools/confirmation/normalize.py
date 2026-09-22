"""Best-effort normalizer: coordinator / Bet365LiveAdapter shapes → READY_STATE schema.

Lives entirely in the confirmation package so main-bot code need not change.
Requires instruction_id (top-level or nested).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, MutableMapping, Optional


def _dig(obj: Any, *keys: str) -> Any:
    cur = obj
    for k in keys:
        if not isinstance(cur, Mapping) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _first(*vals: Any) -> Any:
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return v
    return None


def _as_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fixture_from(parts: Mapping[str, Any], nested: Mapping[str, Any]) -> Optional[str]:
    direct = _first(parts.get("fixture"), nested.get("fixture"), nested.get("fixture_name"))
    if direct:
        return str(direct).strip()
    home = _first(
        parts.get("fixture_home"),
        nested.get("fixture_home"),
        nested.get("home"),
    )
    away = _first(
        parts.get("fixture_away"),
        nested.get("fixture_away"),
        nested.get("away"),
    )
    if home and away:
        return f"{home} v {away}"
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_payload(raw: Mapping[str, Any]) -> dict:
    """Map observed coordinator result/evidence ready_state into target schema.

    Accepts:
    - already-flat READY_STATE
    - { "ready_state": {...}, "instruction_id": "...", ... }
    - { "result": { "ready_state": {...} }, "instruction": {...} }
    - Bet365LiveAdapter final_state style: home/away/market/side/line/price/stake

    Raises ValueError if instruction_id cannot be found.
    """
    if not isinstance(raw, Mapping):
        raise ValueError("payload must be a JSON object")

    instruction = raw.get("instruction") if isinstance(raw.get("instruction"), Mapping) else {}
    result = raw.get("result") if isinstance(raw.get("result"), Mapping) else {}
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), Mapping) else {}

    nested = {}
    for candidate in (
        raw.get("ready_state"),
        result.get("ready_state") if isinstance(result, Mapping) else None,
        evidence.get("ready_state") if isinstance(evidence, Mapping) else None,
        raw.get("final_state"),
        result.get("final_state") if isinstance(result, Mapping) else None,
        evidence.get("final_state") if isinstance(evidence, Mapping) else None,
    ):
        if isinstance(candidate, Mapping):
            nested = candidate
            break

    # Flatten preference: nested ready_state fields overlayable by top-level
    bag: MutableMapping[str, Any] = {}
    bag.update(nested)
    # top-level non-container keys win
    for k, v in raw.items():
        if k in ("ready_state", "result", "evidence", "instruction", "final_state"):
            continue
        if isinstance(v, (dict, list)):
            continue
        bag[k] = v

    instruction_id = _first(
        bag.get("instruction_id"),
        raw.get("instruction_id"),
        instruction.get("instruction_id") if isinstance(instruction, Mapping) else None,
        result.get("instruction_id") if isinstance(result, Mapping) else None,
    )
    if not instruction_id:
        raise ValueError("instruction_id is required (normalizer cannot proceed without it)")

    device_id = _first(
        bag.get("device_id"),
        raw.get("device_id"),
        instruction.get("device_id") if isinstance(instruction, Mapping) else None,
        result.get("device_id") if isinstance(result, Mapping) else None,
        "unknown-device",
    )

    fixture = _fixture_from(bag, nested) or _fixture_from(raw, {})
    market = _first(bag.get("market"), instruction.get("market") if instruction else None)
    selection_role = _first(
        bag.get("selection_role"),
        bag.get("side"),
        instruction.get("side") if instruction else None,
        instruction.get("selection_role") if instruction else None,
    )
    selection_name = _first(
        bag.get("selection_name"),
        bag.get("selection"),
        bag.get("side"),
        selection_role,
    )
    line = bag.get("line", nested.get("line"))
    if "line" not in bag and "line" not in nested:
        line = instruction.get("line") if instruction else None

    current_price = _as_float(
        _first(bag.get("current_price"), bag.get("price"), nested.get("price"))
    )
    minimum_price = _as_float(
        _first(
            bag.get("minimum_price"),
            instruction.get("minimum_price") if instruction else None,
            raw.get("minimum_price"),
        )
    )
    stake = _as_float(
        _first(
            bag.get("stake"),
            instruction.get("stake") if instruction else None,
            raw.get("stake"),
        )
    )

    validated_at = _first(
        bag.get("validated_at"),
        raw.get("validated_at"),
        result.get("validated_at") if isinstance(result, Mapping) else None,
        _now_iso(),
    )
    validation_hash = _first(
        bag.get("validation_hash"),
        raw.get("validation_hash"),
        result.get("validation_hash") if isinstance(result, Mapping) else None,
        "",
    )

    expected_line = _first(
        instruction.get("line") if instruction else None,
        raw.get("expected_line"),
    )

    out = {
        "instruction_id": str(instruction_id).strip(),
        "device_id": str(device_id).strip(),
        "fixture": str(fixture).strip() if fixture else "",
        "market": str(market).strip() if market else "",
        "selection_role": str(selection_role).strip() if selection_role else "",
        "selection_name": str(selection_name).strip() if selection_name else "",
        "line": line,
        "current_price": current_price if current_price is not None else "",
        "minimum_price": minimum_price if minimum_price is not None else "",
        "stake": stake if stake is not None else "",
        "validated_at": str(validated_at).strip(),
        "validation_hash": str(validation_hash).strip(),
    }
    if expected_line is not None:
        out["expected_line"] = expected_line
    return out
