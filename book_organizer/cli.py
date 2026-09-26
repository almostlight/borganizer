from __future__ import annotations

import argparse
import sys

from .config import load_config
from .db import Database
from .organizer import apply_proposals, propose, undo_latest


def cmd_scan(config, db) -> int:
    proposals = propose(config, db)
    if not proposals:
        print("No new proposals.")
        return 0
    for p in proposals:
        print(f"[{p.id}] {p.status.upper():9} {p.confidence:5.2f}  {p.source_path}")
        print(f"      -> {p.destination_path}")
        print(f"      {p.reason}")
    return 0


def cmd_review(config, db) -> int:
    rows = db.pending()
    if not rows:
        print("No pending proposals.")
        return 0
    for r in rows:
        print(f"[{r['id']}] confidence={float(r['confidence']):.2f} type={r['media_type']}")
        print(f"  {r['source_path']}")
        print(f"  -> {r['destination_path']}")
        if r['reason']:
            print(f"  note: {r['reason']}")
    return 0


def cmd_apply(config, db, args) -> int:
    try:
        batch_id, applied = apply_proposals(config, db, args.ids, auto=args.auto)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not applied:
        print("Nothing applied.")
        return 0
    print(f"Applied batch {batch_id}: {', '.join(map(str, applied))}")
    return 0


def cmd_status(config, db) -> int:
    counts = db.counts()
    print(f"Database: {config.database}")
    print(f"Incoming: {config.incoming_dir}")
    print(f"Library:  {config.library_dir}")
    for status in ("pending", "applied", "rejected", "undone", "duplicate", "conflict"):
        print(f"{status:10} {counts.get(status, 0)}")
    return 0


def cmd_reject(config, db, ids) -> int:
    for proposal_id in ids:
        row = db.get(proposal_id)
        if not row:
            print(f"[{proposal_id}] not found")
            continue
        if row["status"] != "pending":
            print(f"[{proposal_id}] not pending (status={row['status']})")
            continue
        db.mark_rejected(proposal_id)
        print(f"[{proposal_id}] rejected")
    return 0


def cmd_undo(config, db) -> int:
    try:
        batch_id = undo_latest(config, db)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not batch_id:
        print("Nothing to undo.")
        return 0
    print(f"Undid batch {batch_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="book-organizer")
    parser.add_argument("--config", help="Path to config YAML")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan")
    sub.add_parser("review")
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("ids", nargs="*", type=int)
    apply_parser.add_argument("--auto", action="store_true", help="Apply pending proposals at/above configured confidence threshold")
    sub.add_parser("undo")
    sub.add_parser("status")
    reject_parser = sub.add_parser("reject")
    reject_parser.add_argument("ids", nargs="+", type=int)

    args = parser.parse_args()
    config = load_config(args.config)
    db = Database(config.database)

    if args.command == "scan":
        return cmd_scan(config, db)
    if args.command == "review":
        return cmd_review(config, db)
    if args.command == "apply":
        if not args.auto and not args.ids:
            parser.error("apply requires proposal IDs or --auto")
        return cmd_apply(config, db, args)
    if args.command == "undo":
        return cmd_undo(config, db)
    if args.command == "status":
        return cmd_status(config, db)
    if args.command == "reject":
        return cmd_reject(config, db, args.ids)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
