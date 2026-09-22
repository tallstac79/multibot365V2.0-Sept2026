"""READY_STATE schema and structured decision statuses."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


DEFAULT_STALE_SECONDS = 120

REQUIRED_FIELDS = (
    "instruction_id",
    "device_id",
    "fixture",
    "market",
    "selection_role",
    "selection_name",
    "current_price",
    "minimum_price",
    "stake",
    "validated_at",
    "validation_hash",
)


class DecisionStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    DUPLICATE = "DUPLICATE"
    PRICE_INVALID = "PRICE_INVALID"
    STATE_INVALID = "STATE_INVALID"
    TIMEOUT = "TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    PENDING = "PENDING"  # internal non-terminal


# Terminal statuses written to outbox (PENDING is not terminal)
TERMINAL_STATUSES = {
    DecisionStatus.APPROVED,
    DecisionStatus.REJECTED,
    DecisionStatus.EXPIRED,
    DecisionStatus.DUPLICATE,
    DecisionStatus.PRICE_INVALID,
    DecisionStatus.STATE_INVALID,
    DecisionStatus.TIMEOUT,
    DecisionStatus.INTERNAL_ERROR,
}


def _is_none_line(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().upper() in ("", "NONE", "NULL", "N/A"):
        return True
    return False


def normalize_line(value: Any) -> Optional[str]:
    """Canonical line: None for null/NONE; else stripped string."""
    if _is_none_line(value):
        return None
    return str(value).strip()


def lines_match(a: Any, b: Any) -> bool:
    """True if both null/NONE or equal as strings."""
    na, nb = normalize_line(a), normalize_line(b)
    return na == nb


@dataclass
class ReadyState:
    instruction_id: str
    device_id: str
    fixture: str
    market: str
    selection_role: str
    selection_name: str
    line: Optional[str]
    current_price: float
    minimum_price: float
    stake: float
    validated_at: str
    validation_hash: str
    # Optional expected line from instruction (for cross-check during normalize)
    expected_line: Optional[str] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("expected_line", None)
        return d

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ReadyState":
        missing = [k for k in REQUIRED_FIELDS if k not in data or data[k] is None or data[k] == ""]
        # line may be null — only treat as missing if key absent AND we need it; line is optional null
        missing = [k for k in missing if k != "line"]
        if "line" not in data:
            # allow absent line → None
            data = dict(data)
            data["line"] = None
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")

        def _float(name: str) -> float:
            try:
                return float(data[name])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid {name}: {data[name]!r}") from exc

        return cls(
            instruction_id=str(data["instruction_id"]).strip(),
            device_id=str(data["device_id"]).strip(),
            fixture=str(data["fixture"]).strip(),
            market=str(data["market"]).strip(),
            selection_role=str(data["selection_role"]).strip(),
            selection_name=str(data["selection_name"]).strip(),
            line=normalize_line(data.get("line")),
            current_price=_float("current_price"),
            minimum_price=_float("minimum_price"),
            stake=_float("stake"),
            validated_at=str(data["validated_at"]).strip(),
            validation_hash=str(data["validation_hash"]).strip(),
            expected_line=normalize_line(data.get("expected_line")),
        )


def validate_ready_state_dict(data: Mapping[str, Any]) -> tuple[Optional[ReadyState], Optional[str]]:
    """Return (ReadyState, None) or (None, reason)."""
    if not isinstance(data, Mapping):
        return None, "payload is not a JSON object"
    try:
        rs = ReadyState.from_mapping(data)
    except ValueError as exc:
        return None, str(exc)
    if not rs.instruction_id:
        return None, "instruction_id empty"
    if rs.stake < 0:
        return None, "stake must be >= 0"
    if rs.current_price < 0 or rs.minimum_price < 0:
        return None, "prices must be >= 0"
    if rs.expected_line is not None and not lines_match(rs.line, rs.expected_line):
        return None, f"line mismatch: got {rs.line!r} expected {rs.expected_line!r}"
    return rs, None
