"""CLI: ingest, pending, approve, reject, expire, status."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .schema import DEFAULT_STALE_SECONDS
from .worker import ConfirmationWorker


def _default_root() -> Path:
    # tools/confirmation/cli.py → package dir
    return Path(__file__).resolve().parent


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tools.confirmation",
        description="MultiBot365 confirmation worker companion (no Place Bet).",
    )
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help="confirmation package root (default: this package directory)",
    )
    p.add_argument(
        "--max-age-seconds",
        type=int,
        default=DEFAULT_STALE_SECONDS,
        help=f"stale window in seconds (default {DEFAULT_STALE_SECONDS})",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=None,
        help="SQLite path (default: <root>/data/confirmation.sqlite3)",
    )
    p.add_argument("-v", "--verbose", action="store_true")

    sub = p.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Ingest READY_STATE JSON file or all inbox/*.json")
    ingest.add_argument(
        "path",
        nargs="?",
        default=None,
        help="JSON file path; omit to drain inbox/",
    )
    ingest.add_argument(
        "--no-normalize",
        action="store_true",
        help="Skip normalizer (payload must already match target schema)",
    )

    sub.add_parser("pending", help="List PENDING instruction_ids")

    ap = sub.add_parser("approve", help="Human APPROVE a pending instruction")
    ap.add_argument("instruction_id")
    ap.add_argument("--note", default="human APPROVE")

    rj = sub.add_parser("reject", help="Human REJECT a pending instruction")
    rj.add_argument("instruction_id")
    rj.add_argument("--note", default="human REJECT")

    sub.add_parser("expire", help="Auto-expire stale PENDING payloads")
    sub.add_parser("status", help="Summary counts and pending ids")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    root = args.root or _default_root()
    worker = ConfirmationWorker(
        root,
        max_age_seconds=args.max_age_seconds,
        db_path=args.db,
    )
    try:
        if args.command == "ingest":
            if args.path:
                doc = worker.ingest_file(args.path, normalize=not args.no_normalize)
                print(json.dumps(doc, indent=2, sort_keys=True))
            else:
                docs = worker.ingest_inbox()
                print(json.dumps(docs, indent=2, sort_keys=True))
            return 0
        if args.command == "pending":
            rows = worker.pending()
            out = [
                {
                    "instruction_id": r["instruction_id"],
                    "device_id": r.get("device_id"),
                    "validated_at": r.get("validated_at"),
                    "validation_hash": r.get("validation_hash"),
                }
                for r in rows
            ]
            print(json.dumps(out, indent=2, sort_keys=True))
            return 0
        if args.command == "approve":
            doc = worker.approve(args.instruction_id, note=args.note)
            print(json.dumps(doc, indent=2, sort_keys=True))
            return 0 if doc["status"] == "APPROVED" else 1
        if args.command == "reject":
            doc = worker.reject(args.instruction_id, note=args.note)
            print(json.dumps(doc, indent=2, sort_keys=True))
            return 0 if doc["status"] == "REJECTED" else 1
        if args.command == "expire":
            docs = worker.expire()
            print(json.dumps(docs, indent=2, sort_keys=True))
            return 0
        if args.command == "status":
            print(json.dumps(worker.status_summary(), indent=2, sort_keys=True))
            return 0
        parser.error(f"unknown command {args.command}")
        return 2
    finally:
        worker.close()


if __name__ == "__main__":
    raise SystemExit(main())
