from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .db import Database
from .organizer import apply_proposals, propose, undo_latest
from .providers import build_metadata_provider
from .ai import build_ai_resolver
from .archive import inspect_zip
from .web import serve


def cmd_scan(config, db, provider, ai_resolver) -> int:
    proposals = propose(config, db, provider, ai_resolver)
    if not proposals:
        print("No new proposals.")
        return 0
    for p in proposals:
        print(f"[{p.id}] {p.status.upper():9} {p.confidence:5.2f}  {p.source_path}")
        print(f"      -> {p.destination_path}")
        if p.match_kind:
            print(f"      match: {p.match_kind} ({p.match_method})")
        print(f"      {p.reason}")
    return 0


def cmd_run(config, db, provider, ai_resolver) -> int:
    proposals = propose(config, db, provider, ai_resolver)
    pending = [proposal for proposal in proposals if proposal.status == "pending"]
    if config.operation_mode == "safe":
        print(f"Safe mode: {len(pending)} proposal(s) queued for review.")
        return 0
    if config.operation_mode != "automatic":
        print(f"ERROR: unknown operation mode: {config.operation_mode}", file=sys.stderr)
        return 1
    try:
        batch_id, applied = apply_proposals(config, db, [], auto=True)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Automatic mode: applied {len(applied)} high-confidence proposal(s).")
    if batch_id:
        print(f"Batch: {batch_id}")
    print(f"Review queue: {len(pending) - len(applied)} proposal(s)")
    return 0


def cmd_review(config, db) -> int:
    rows = db.pending()
    if not rows:
        print("No pending proposals.")
        return 0
    for r in rows:
        confidence = float(r["confidence"])
        action = "MOVE" if confidence >= config.auto_apply_threshold else "REVIEW" if confidence >= 0.5 else "IGNORE"
        title = r["title"] or r["source_path"].rsplit("/", 1)[-1]
        identity = " / ".join(value for value in (r["author"], r["series"], title) if value)
        print(f"[{r['id']}] {confidence:.0%}  {title}")
        print(f"    {identity or 'Unknown'}")
        print(f"    -> {r['destination_path']}")
        if r["match_kind"]:
            print(f"    match: {r['match_kind']} ({r['match_method']})")
        if r['reason']:
            print(f"    note: {r['reason']}")
        print(f"    -> {action}")
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


def cmd_approve(config, db, ids) -> int:
    try:
        batch_id, applied = apply_proposals(config, db, ids)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not applied:
        print("Nothing approved.")
        return 0
    print(f"Approved batch {batch_id}: {', '.join(map(str, applied))}")
    return 0


def cmd_approve_all_high_confidence(config, db) -> int:
    return cmd_apply(config, db, argparse.Namespace(ids=[], auto=True))


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


def cmd_undo(config, db, batch_id=None) -> int:
    try:
        batch_id = undo_latest(config, db, batch_id)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not batch_id:
        print("Nothing to undo.")
        return 0
    print(f"Undid batch {batch_id}")
    return 0


def cmd_inspect(path: str) -> int:
    try:
        entries = inspect_zip(Path(path))
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Archive: {path}")
    for entry in entries:
        print(f"{entry.size:10}  {entry.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="librarian")
    parser.add_argument("--config", help="Path to config YAML")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan")
    sub.add_parser("run", help="Scan and apply according to operation_mode")
    sub.add_parser("review")
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("ids", nargs="*", type=int)
    apply_parser.add_argument("--auto", action="store_true", help="Apply pending proposals at/above configured confidence threshold")
    undo_parser = sub.add_parser("undo")
    undo_parser.add_argument("batch_id", nargs="?", help="Batch ID to reverse; defaults to the latest batch")
    sub.add_parser("status")
    reject_parser = sub.add_parser("reject")
    reject_parser.add_argument("ids", nargs="+", type=int)
    approve_parser = sub.add_parser("approve")
    approve_parser.add_argument("ids", nargs="+", type=int)
    sub.add_parser("approve-all-high-confidence")
    inspect_parser = sub.add_parser("inspect", help="List ZIP contents without extracting")
    inspect_parser.add_argument("path")
    web_parser = sub.add_parser("web", help="Start the local review web UI")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8765)

    args = parser.parse_args()
    config = load_config(args.config)
    db = Database(config.database)
    provider = build_metadata_provider(config, db)
    ai_resolver = build_ai_resolver(config)

    if args.command == "scan":
        return cmd_scan(config, db, provider, ai_resolver)
    if args.command == "run":
        return cmd_run(config, db, provider, ai_resolver)
    if args.command == "review":
        return cmd_review(config, db)
    if args.command == "apply":
        if not args.auto and not args.ids:
            parser.error("apply requires proposal IDs or --auto")
        return cmd_apply(config, db, args)
    if args.command == "undo":
        return cmd_undo(config, db, args.batch_id)
    if args.command == "status":
        return cmd_status(config, db)
    if args.command == "reject":
        return cmd_reject(config, db, args.ids)
    if args.command == "approve":
        return cmd_approve(config, db, args.ids)
    if args.command == "approve-all-high-confidence":
        return cmd_approve_all_high_confidence(config, db)
    if args.command == "inspect":
        return cmd_inspect(args.path)
    if args.command == "web":
        serve(config, args.host, args.port)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
