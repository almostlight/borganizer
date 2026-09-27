from __future__ import annotations

import os
import errno
import re
import shutil
import tempfile
import time
import uuid
from collections import Counter
from pathlib import Path

from rapidfuzz.fuzz import ratio

from .config import Config
from .db import Database
from .metadata import extract_metadata
from .matching import MatchResult, classify_match, normalize_text
from .models import BookMetadata, FileCandidate, Proposal
from .providers import CachedMetadataProvider, MetadataProvider, OpenLibraryProvider
from .ai import AIResolver
from .util import clean_component, format_series_position, sha256_file


AI_CONFIDENCE_THRESHOLD = 0.80


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
    if media_type == "audiobook" and re.fullmatch(r"(?:cd|disc|disk)\s*\d+", path.parent.name, re.IGNORECASE):
        if path.parent.parent != config.incoming_dir:
            meta.title = path.parent.parent.name
    confidence = calculate_confidence(meta)
    notes: list[str] = []
    if not meta.title:
        notes.append("missing title")
    if not meta.author:
        notes.append("missing author")
    if meta.source == "filename":
        notes.append("filename-derived metadata")
    return FileCandidate(path, media_type, digest, meta, confidence, notes, _infer_component_group(path, config.incoming_dir) if media_type == "audiobook" else None)


def _infer_component_group(path: Path, incoming_dir: Path) -> str:
    parent = path.parent
    if parent != incoming_dir and re.fullmatch(r"(?:cd|disc|disk)\s*\d+", parent.name, re.IGNORECASE):
        base = parent.parent.name if parent.parent != incoming_dir else path.stem
    elif parent != incoming_dir:
        base = parent.name
    else:
        base = path.stem
    base = re.sub(r"^\d{1,3}\s*[-_. ]+\s*", "", base)
    fallback = base
    base = re.sub(r"[._ -]*(?:part|track|chapter|cd|disc|disk)[._ -]*\d+\s*$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"[._ -]+\d+\s*$", "", base)
    if base.strip():
        return normalize_text(base)
    marker = re.match(r"(?:part|track|chapter|cd|disc|disk)\b", fallback, re.IGNORECASE)
    return normalize_text(marker.group(0) if marker else fallback) or normalize_text(path.stem)


def build_destination(candidate: FileCandidate, config: Config) -> Path:
    book_root = build_book_root(candidate, config)
    title = clean_component(candidate.metadata.title or candidate.path.stem, config.invalid_replacement)
    return book_root / f"{title}{candidate.path.suffix.lower()}"


def build_book_root(candidate: FileCandidate, config: Config) -> Path:
    meta = candidate.metadata
    author = clean_component(meta.author or "Unknown Author", config.invalid_replacement)
    title = clean_component(meta.title or candidate.path.stem, config.invalid_replacement)

    if meta.series:
        series = clean_component(meta.series, config.invalid_replacement)
        position = format_series_position(meta.series_number, meta.series_position_label, config.series_number_width)
        book_dir = f"{position} - {title}" if position else title
        return config.library_dir / author / series / book_dir

    return config.library_dir / author / title


def find_existing_match(candidate: FileCandidate, config: Config) -> tuple[Path, MatchResult] | None:
    if not config.library_dir.exists():
        return None
    best: tuple[Path, MatchResult] | None = None
    method_rank = {
        "ISBN / exact identifier": 0,
        "normalized title + author": 1,
        "series + series number": 2,
        "fuzzy matching": 3,
    }
    for path in config.library_dir.rglob("*"):
        if not path.is_file() or classify_extension(path, config) is None:
            continue
        try:
            duplicate = sha256_file(path) == candidate.sha256
            existing = extract_metadata(path, classify_extension(path, config) or candidate.media_type)
            result = classify_match(candidate.metadata, existing, duplicate=duplicate)
        except OSError:
            continue
        if result and (
            best is None
            or (method_rank.get(result.method, 99), -result.score)
            < (method_rank.get(best[1].method, 99), -best[1].score)
        ):
            best = (path, result)
            if result.kind == "duplicate file":
                break
    return best


def build_matched_destination(candidate: FileCandidate, matched_path: Path, match: MatchResult, config: Config) -> Path:
    title = clean_component(candidate.metadata.title or candidate.path.stem, config.invalid_replacement)
    suffix = candidate.path.suffix.lower()
    return matched_path.parent / f"{title}{suffix}"


def _same_book(left: BookMetadata, right: BookMetadata) -> bool:
    return classify_match(left, right) is not None


def _existing_audiobook_narrators(book_root: Path, config: Config) -> set[str]:
    narrators: set[str] = set()
    if not book_root.exists():
        return narrators
    for path in book_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in config.audiobook_extensions:
            continue
        metadata = extract_metadata(path, "audiobook")
        narrators.add(normalize_text(metadata.narrator) or "unknown narrator")
    return narrators


def build_edition_destination(
    candidate: FileCandidate,
    book_root: Path,
    sibling_candidates: list[FileCandidate],
    config: Config,
) -> Path:
    title = clean_component(candidate.metadata.title or candidate.path.stem, config.invalid_replacement)
    suffix = candidate.path.suffix.lower()
    if candidate.media_type != "audiobook":
        return book_root / f"{title}{suffix}"

    narrator_keys = _existing_audiobook_narrators(book_root, config)
    narrator_keys.update(
        normalize_text(sibling.metadata.narrator) or "unknown narrator"
        for sibling in sibling_candidates
        if sibling.media_type == "audiobook"
    )
    if len(narrator_keys) <= 1:
        return book_root / f"{title}{suffix}"

    narrator = clean_component(candidate.metadata.narrator or "Unknown Narrator", config.invalid_replacement)
    return book_root / "Audiobooks" / narrator / f"{title}{suffix}"


def build_source_named_destination(candidate: FileCandidate, directory: Path, config: Config) -> Path:
    name = clean_component(candidate.path.stem, config.invalid_replacement)
    return directory / f"{name}{candidate.path.suffix.lower()}"


def existing_equivalent(path: Path, digest: str) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        return sha256_file(path) == digest
    except OSError:
        return False


def _merge_metadata(local: BookMetadata, canonical: BookMetadata) -> BookMetadata:
    values = {
        field: getattr(canonical, field) or getattr(local, field)
        for field in BookMetadata.__dataclass_fields__
    }
    values["media_type"] = local.media_type
    values["source"] = f"{local.source or 'local'}+{canonical.source or 'metadata'}"
    return BookMetadata(**values)


def _lookup_metadata(candidate: FileCandidate, provider: MetadataProvider) -> None:
    results = provider.search(candidate.metadata)
    if not results:
        return
    candidate.metadata = _merge_metadata(candidate.metadata, results[0].metadata)
    candidate.confidence = calculate_confidence(candidate.metadata)
    candidate.notes.append(f"metadata lookup: {provider.name}")


def _library_book_candidates(config: Config) -> list[str]:
    if not config.library_dir.exists():
        return []
    return sorted({path.parent.name for path in config.library_dir.rglob("*") if path.is_file() and classify_extension(path, config)})[:24]


def _lookup_ai(candidate: FileCandidate, resolver: AIResolver, config: Config, provider: MetadataProvider | None = None) -> None:
    result = resolver.resolve(filename=candidate.path.name, embedded=candidate.metadata, candidate_books=_library_book_candidates(config))
    if not result:
        return
    if not re.search(r"[A-Za-z]{2,}", result.book):
        raise ValueError("AI returned an implausible book title")
    if result.series and not re.search(r"[A-Za-z]{2,}", result.series):
        raise ValueError("AI returned an implausible series")
    if provider:
        matches = provider.search(result.metadata())
        if not any(
            normalize_text(match.metadata.title) == normalize_text(result.book)
            and normalize_text(match.metadata.author) == normalize_text(result.author)
            for match in matches
        ):
            raise ValueError("AI book and author were not found by metadata provider")
    candidate.metadata = _merge_metadata(candidate.metadata, result.metadata())
    candidate.confidence = max(candidate.confidence, result.confidence)
    candidate.notes.append(f"AI resolver: {resolver.name}")


def propose(config: Config, db: Database, provider: MetadataProvider | None = None, ai_resolver: AIResolver | None = None, cancel_event=None) -> list[Proposal]:
    proposals: list[Proposal] = []
    ai_validation_provider = provider
    if ai_validation_provider is None and config.ai_enabled and ai_resolver and ai_resolver.name in {"ollama", "openai"}:
        ai_validation_provider = CachedMetadataProvider(OpenLibraryProvider(timeout_seconds=5), db, config.metadata_cache_ttl_seconds)
    candidates = [candidate_from_file(path, config) for path in scan_files(config)]
    candidates = [candidate for candidate in candidates if candidate]
    initial_destinations: dict[Path, int] = {}
    component_groups = Counter(
        candidate.component_group
        for candidate in candidates
        if candidate.media_type == "audiobook" and candidate.component_group
    )
    for candidate in candidates:
        initial_destinations[build_destination(candidate, config)] = initial_destinations.get(build_destination(candidate, config), 0) + 1

    for candidate in candidates:
        if cancel_event is not None and cancel_event.is_set():
            break
        item_started = time.perf_counter()
        path = candidate.path
        if not candidate:
            continue
        existing_match = find_existing_match(candidate, config)
        if not existing_match and provider:
            try:
                _lookup_metadata(candidate, provider)
                existing_match = find_existing_match(candidate, config)
            except Exception as exc:
                candidate.notes.append(f"metadata lookup unavailable: {exc.__class__.__name__}")
        # AI is a fallback for incomplete or low-confidence metadata, not a second pass over every tagged file.
        needs_ai = candidate.confidence < AI_CONFIDENCE_THRESHOLD or not candidate.metadata.title or not candidate.metadata.author
        if not existing_match and ai_resolver and needs_ai:
            try:
                _lookup_ai(candidate, ai_resolver, config, ai_validation_provider)
            except Exception as exc:
                candidate.notes.append(f"AI resolver unavailable: {exc}")
            existing_match = find_existing_match(candidate, config)
        if config.ai_enabled and ai_resolver and needs_ai and candidate.confidence < AI_CONFIDENCE_THRESHOLD:
            continue
        matched_path = existing_match[0] if existing_match else None
        match = existing_match[1] if existing_match else None
        book_root = matched_path.parent if matched_path and match else build_book_root(candidate, config)
        if matched_path and match and matched_path.parent.name == "Audiobooks":
            book_root = matched_path.parent.parent
        siblings = [other for other in candidates if other is not candidate and _same_book(candidate.metadata, other.metadata)]
        component_grouped = candidate.component_group and component_groups[candidate.component_group] > 1
        if component_grouped:
            anchor = next(other for other in candidates if other.component_group == candidate.component_group)
            book_root = build_book_root(anchor, config)
        destination = build_edition_destination(candidate, book_root, [candidate, *siblings], config)
        if component_grouped or initial_destinations.get(build_destination(candidate, config), 0) > 1:
            destination = build_source_named_destination(candidate, destination.parent, config)

        if path.resolve() == destination.resolve():
            continue

        reason_parts = list(candidate.notes)
        reason_parts.append(f"processing time: {time.perf_counter() - item_started:.2f}s")
        if match:
            reason_parts.append(f"{match.method}: {match.kind}")
        if match and match.kind == "duplicate file":
            status = "duplicate"
        elif destination.exists():
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
            series_position_label=candidate.metadata.series_position_label,
            reason="; ".join(reason_parts) or "metadata-derived proposal",
            status=status,
            match_kind=match.kind if match else None,
            match_method=match.method if match else None,
            matched_path=matched_path,
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

        operation_id = db.create_operation(batch_id, int(row["id"]))
        try:
            _move_file(source, dest, row["sha256"], config.allow_cross_device_move)
        except Exception as exc:
            raise RuntimeError(f"Operation batch {batch_id} interrupted: {exc}") from exc
        db.mark_operation_applied(operation_id, int(row["id"]))
        applied.append(int(row["id"]))

    return batch_id, applied


def _move_file(source: Path, dest: Path, digest: str, allow_cross_device_move: bool) -> None:
    try:
        os.link(source, dest)
        source.unlink()
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV or not allow_cross_device_move:
            raise

    with tempfile.NamedTemporaryFile(prefix=f".{dest.name}.", dir=dest.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        shutil.copy2(source, temporary_path)
        if sha256_file(temporary_path) != digest:
            raise RuntimeError(f"Checksum mismatch after copy: {dest}")
        os.link(temporary_path, dest)
        temporary_path.unlink()
        source.unlink()
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def undo_latest(config: Config, db: Database, requested_batch_id: str | None = None) -> str | None:
    batch_id = requested_batch_id or db.latest_batch()
    if not batch_id:
        return None
    operations = db.batch_operations(batch_id)
    for op in operations:
        if op["state"] == "undone":
            continue
        source = Path(op["source_path"])
        dest = Path(op["destination_path"])
        if op["state"] == "planned" and source.exists() and not dest.exists():
            continue
        if source.exists() and dest.exists():
            if op["state"] == "planned" and sha256_file(dest) == op["sha256"]:
                dest.unlink()
                continue
            raise FileExistsError(f"Cannot undo; source path occupied: {source}")
        if not dest.exists():
            raise FileNotFoundError(f"Cannot undo; destination missing: {dest}")
        if sha256_file(dest) != op["sha256"]:
            raise RuntimeError(f"Refusing undo; file has changed since apply: {dest}")
        source.parent.mkdir(parents=True, exist_ok=True)
        _move_file(dest, source, op["sha256"], True)
    db.mark_undone(batch_id)
    return batch_id


def score_existing_book(meta: BookMetadata, dest: Path) -> float:
    parts = dest.relative_to(dest.parents[0]).parts
    text = " ".join(parts)
    title_score = ratio(_norm(meta.title), _norm(dest.stem)) / 100 if meta.title else 0
    author_score = ratio(_norm(meta.author), _norm(dest.parts[-3] if len(dest.parts) >= 3 else "")) / 100 if meta.author else 0
    return 0.7 * title_score + 0.3 * author_score
