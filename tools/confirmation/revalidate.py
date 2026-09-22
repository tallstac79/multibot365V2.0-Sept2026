"""Revalidation: duplicate / stale / price / state checks → structured status."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from .schema import (
    DEFAULT_STALE_SECONDS,
    DecisionStatus,
    ReadyState,
    lines_match,
    validate_ready_state_dict,
)


def parse_iso8601(value: str) -> datetime:
    """Parse ISO8601; assume UTC if naive."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class RevalidationResult:
    status: DecisionStatus
    reason: str
    ready_state: Optional[ReadyState] = None

    @property
    def ok_for_pending(self) -> bool:
        return self.status == DecisionStatus.PENDING


def revalidate(
    payload: Mapping[str, Any],
    *,
    already_seen: Optional[Mapping[str, Any]] = None,
    now: Optional[datetime] = None,
    max_age_seconds: int = DEFAULT_STALE_SECONDS,
) -> RevalidationResult:
    """Validate READY_STATE and return structured status.

    already_seen: existing store row for this instruction_id (if any).
    """
    now = now or datetime.now(timezone.utc)

    # Duplicate / no-replay: any prior terminal decision blocks a new approval path
    if already_seen is not None:
        prev = str(already_seen.get("status") or "")
        if prev == DecisionStatus.APPROVED.value:
            return RevalidationResult(
                DecisionStatus.DUPLICATE,
                f"instruction_id already APPROVED at {already_seen.get('decided_at')}",
            )
        if prev == DecisionStatus.REJECTED.value:
            return RevalidationResult(
                DecisionStatus.DUPLICATE,
                f"instruction_id already REJECTED at {already_seen.get('decided_at')}",
            )
        if prev == DecisionStatus.PENDING.value:
            return RevalidationResult(
                DecisionStatus.DUPLICATE,
                "instruction_id already pending approval",
            )
        if prev in {
            DecisionStatus.EXPIRED.value,
            DecisionStatus.PRICE_INVALID.value,
            DecisionStatus.STATE_INVALID.value,
            DecisionStatus.TIMEOUT.value,
            DecisionStatus.DUPLICATE.value,
            DecisionStatus.INTERNAL_ERROR.value,
        }:
            return RevalidationResult(
                DecisionStatus.DUPLICATE,
                f"instruction_id already decided as {prev}",
            )

    rs, err = validate_ready_state_dict(payload)
    if err or rs is None:
        return RevalidationResult(DecisionStatus.STATE_INVALID, err or "invalid payload")

    # Line cross-check (expected_line from normalizer / instruction)
    if rs.expected_line is not None and not lines_match(rs.line, rs.expected_line):
        return RevalidationResult(
            DecisionStatus.STATE_INVALID,
            f"line mismatch: got {rs.line!r} expected {rs.expected_line!r}",
        )

    # Stake present (schema already requires; reinforce non-zero optional — stake may be 0 in dry-run)
    # Requirement: stake present — already enforced. Reject negative already in schema.

    # Price floor
    if rs.current_price < rs.minimum_price:
        return RevalidationResult(
            DecisionStatus.PRICE_INVALID,
            f"current_price {rs.current_price} < minimum_price {rs.minimum_price}",
            ready_state=rs,
        )

    # Staleness
    try:
        validated_at = parse_iso8601(rs.validated_at)
    except (TypeError, ValueError) as exc:
        return RevalidationResult(
            DecisionStatus.STATE_INVALID,
            f"invalid validated_at: {rs.validated_at!r} ({exc})",
            ready_state=rs,
        )

    age = now - validated_at
    if age > timedelta(seconds=max_age_seconds):
        return RevalidationResult(
            DecisionStatus.EXPIRED,
            f"validated_at age {int(age.total_seconds())}s exceeds max_age {max_age_seconds}s",
            ready_state=rs,
        )
    if age < timedelta(seconds=-5):
        # slightly future clock skew tolerated; large future → state invalid
        return RevalidationResult(
            DecisionStatus.STATE_INVALID,
            f"validated_at is in the future: {rs.validated_at}",
            ready_state=rs,
        )

    return RevalidationResult(DecisionStatus.PENDING, "awaiting human approval", ready_state=rs)


def is_stale_pending(
    row: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
    max_age_seconds: int = DEFAULT_STALE_SECONDS,
) -> bool:
    now = now or datetime.now(timezone.utc)
    validated_at = row.get("validated_at") or ""
    try:
        dt = parse_iso8601(str(validated_at))
    except (TypeError, ValueError):
        return True
    return (now - dt) > timedelta(seconds=max_age_seconds)
