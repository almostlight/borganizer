from __future__ import annotations

import os
import re
import shutil
import time
import uuid
from pathlib import Path

from rapidfuzz.fuzz import ratio

from .config import Config
from .db import Database
from .metadata import extract_metadata
from .models import BookMetadata, FileCandidate, Proposal
from .util import clean_component, format_series_number, sha256_file


def classify_extension(path: Path, config: Config) -> str | None:
    ext = path.suffix.lower()
    if ext in config.audiobook_extensions:
        return "audiobook"
    if ext in config.ebook_extensions:
        return "ebook"
    return None


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def calculate_confidence(meta: BookMetadata) -> float:
    score = 0.30 if meta.title else 0.0
    score += 0.30 if meta.author else 0.0
    score += 0.20 if meta.series else 0.0
    score += 0.10 if meta.series_number is not None else 0.0
    score += 0.10 if meta.isbn else 0.0
    return min(score, 0.99)


def scan_files(config: Config) -> list[Path]:
    results: list[Path] = []
    now = time.time()
    for path in config.incoming_dir.rglob("*"):
        if not path.is_file():
            continue
        if config.ignore_hidden and any(part.startswith(".") for part in path.relative_to(config.incoming_dir).parts):
            continue
        media_type = classify_extension(path, config)
        if not media_type:
            continue
        try:
            if now - path.stat().st_mtime < config.min_stable_age_seconds:
                continue
        except OSError:
            continue
        results.append(path)
    return sorted(results)


def candidate_from_file(path: Path, config: Config) -> FileCandidate | None:
    media_type = classify_extension(path, config)
    if not media_type:
        return None
    digest = sha256_file(path)
    meta = extract_metadata(path, media_type)
    confidence = calculate_confidence(meta)
    notes: list[str] = []
    if not meta.title:
        notes.append("missing title")
    if not meta.author:
        notes.append("missing author")
    if meta.source == "filename":
        notes.append("filename-derived metadata")
    return FileCandidate(path, media_type, digest, meta, confidence, notes)


def build_destination(candidate: FileCandidate, config: Config) -> Path:
    meta = candidate.metadata
    author = clean_component(meta.author or "Unknown Author", config.invalid_replacement)
    title = clean_component(meta.title or candidate.path.stem, config.invalid_replacement)
    ext = candidate.path.suffix.lower()

    if meta.series:
        series = clean_component(meta.series, config.invalid_replacement)
        number = format_series_number(meta.series_number, config.series_number_width)
        book_dir = f"{number} - {title}" if number else title
        return config.library_dir / author / series / book_dir / f"{title}{ext}"

    return config.library_dir / author / title / f"{title}{ext}"


def existing_equivalent(path: Path, digest: str) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        return sha256_file(path) == digest
    except OSError:
        return False


def propose(config: Config, db: Database) -> list[Proposal]:
    proposals: list[Proposal] = []
    for path in scan_files(config):
        candidate = candidate_from_file(path, config)
        if not candidate:
            continue
        destination = build_destination(candidate, config)

        if path.resolve() == destination.resolve():
            continue

        reason_parts = list(candidate.notes)
        if destination.exists():
            if existing_equivalent(destination, candidate.sha256):
                reason_parts.append("destination already contains identical file")
                status = "duplicate"
            else:
                reason_parts.append("destination exists with different content")
                status = "conflict"
        else:
            status = "pending"

        proposal = Proposal(
            id=None,
            source_path=path,
            destination_path=destination,
            sha256=candidate.sha256,
            confidence=candidate.confidence,
            media_type=candidate.media_type,
            title=candidate.metadata.title,
            author=candidate.metadata.author,
            series=candidate.metadata.series,
            series_number=candidate.metadata.series_number,
            reason="; ".join(reason_parts) or "metadata-derived proposal",
            status=status,
        )
        if status != "pending":
            # Persist non-actionable findings too, but don't leave them pending.
            proposal_id = db.add_proposal(proposal)
            db.conn.execute("UPDATE proposals SET status=? WHERE id=?", (status, proposal_id))
            db.conn.commit()
            proposal.id = proposal_id
        else:
            proposal.id = db.add_proposal(proposal)
        proposals.append(proposal)
    return proposals


def apply_proposals(config: Config, db: Database, ids: list[int], auto: bool = False) -> tuple[str, list[int]]:
    rows = []
    if auto:
        rows = [r for r in db.pending() if float(r["confidence"]) >= config.auto_apply_threshold]
    else:
        for proposal_id in ids:
            row = db.get(proposal_id)
            if row:
                rows.append(row)

    if not rows:
        return "", []

    batch_id = str(uuid.uuid4())
    applied: list[int] = []

    for row in rows:
        if row["status"] != "pending":
            continue
        source = Path(row["source_path"])
        dest = Path(row["destination_path"])
        if not source.exists():
            raise FileNotFoundError(f"Source no longer exists: {source}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            if existing_equivalent(dest, row["sha256"]):
                raise FileExistsError(f"Identical destination already exists; refusing to replace: {dest}")
            raise FileExistsError(f"Destination exists: {dest}")

        try:
            os.replace(source, dest)
        except OSError:
            if not config.allow_cross_device_move:
                raise
            shutil.copy2(source, dest)
            if sha256_file(dest) != row["sha256"]:
                dest.unlink(missing_ok=True)
                raise RuntimeError(f"Checksum mismatch after copy: {dest}")
            source.unlink()
        applied.append(int(row["id"]))

    db.mark_applied(applied, batch_id)
    return batch_id, applied


def undo_latest(config: Config, db: Database) -> str | None:
    batch_id = db.latest_batch()
    if not batch_id:
        return None
    operations = db.batch_operations(batch_id)
    for op in operations:
        source = Path(op["source_path"])
        dest = Path(op["destination_path"])
        if not dest.exists():
            raise FileNotFoundError(f"Cannot undo; destination missing: {dest}")
        if source.exists():
            raise FileExistsError(f"Cannot undo; source path occupied: {source}")
        if sha256_file(dest) != op["sha256"]:
            raise RuntimeError(f"Refusing undo; file has changed since apply: {dest}")
        source.parent.mkdir(parents=True, exist_ok=True)
        os.replace(dest, source)
    db.mark_undone(batch_id)
    return batch_id


def score_existing_book(meta: BookMetadata, dest: Path) -> float:
    parts = dest.relative_to(dest.parents[0]).parts
    text = " ".join(parts)
    title_score = ratio(_norm(meta.title), _norm(dest.stem)) / 100 if meta.title else 0
    author_score = ratio(_norm(meta.author), _norm(dest.parts[-3] if len(dest.parts) >= 3 else "")) / 100 if meta.author else 0
    return 0.7 * title_score + 0.3 * author_score
