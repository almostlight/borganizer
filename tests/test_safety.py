from pathlib import Path

import pytest

from borganizer.config import Config
from borganizer.db import Database
from borganizer.models import Proposal
from borganizer.organizer import apply_proposals, undo_latest


def config(tmp_path: Path) -> Config:
    return Config(
        incoming_dir=tmp_path / "incoming",
        library_dir=tmp_path / "library",
        database=tmp_path / "library.db",
        audiobook_extensions=(".m4b",),
        ebook_extensions=(".epub",),
        ignore_hidden=True,
        min_stable_age_seconds=0,
        series_number_width=2,
        invalid_replacement="_",
        overwrite_existing=False,
        allow_cross_device_move=True,
        auto_apply_threshold=0.95,
    )


def add_proposal(database, source, destination, reason="manual approval", confidence=0.97):
    return database.add_proposal(Proposal(
        id=None,
        source_path=source,
        destination_path=destination,
        sha256=__import__("hashlib").sha256(source.read_bytes()).hexdigest(),
        confidence=confidence,
        media_type="audiobook",
        title=source.stem,
        author="Author",
        series=None,
        series_number=None,
        reason=reason,
    ))


def test_apply_audits_every_move_and_undoes_explicit_batch(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    source = incoming / "book.m4b"
    destination = tmp_path / "library" / "book.m4b"
    source.write_bytes(b"book")
    database = Database(tmp_path / "library.db")
    proposal_id = add_proposal(database, source, destination)

    batch_id, applied = apply_proposals(config(tmp_path), database, [proposal_id])
    operation = database.batch_operations(batch_id)[0]
    assert applied == [proposal_id]
    assert operation["source_path"] == str(source)
    assert operation["destination_path"] == str(destination)
    assert operation["sha256"]
    assert operation["reason"] == "manual approval"
    assert operation["confidence"] == 0.97
    assert operation["state"] == "applied"

    assert undo_latest(config(tmp_path), database, batch_id) == batch_id
    assert source.read_bytes() == b"book"
    assert not destination.exists()
    assert database.batch_operations(batch_id)[0]["state"] == "undone"
    assert database.get(proposal_id)["status"] == "undone"


def test_apply_refuses_to_overwrite_existing_destination(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    source = incoming / "book.m4b"
    destination = tmp_path / "library" / "book.m4b"
    source.write_bytes(b"new")
    destination.parent.mkdir()
    destination.write_bytes(b"existing")
    database = Database(tmp_path / "library.db")
    proposal_id = add_proposal(database, source, destination)

    with pytest.raises(FileExistsError):
        apply_proposals(config(tmp_path), database, [proposal_id])
    assert source.read_bytes() == b"new"
    assert destination.read_bytes() == b"existing"
    assert database.batch_operations(database.latest_batch() or "") == []


def test_undo_recovers_planned_operation_after_interruption(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    source = incoming / "book.m4b"
    destination = tmp_path / "library" / "book.m4b"
    source.write_bytes(b"book")
    destination.parent.mkdir()
    database = Database(tmp_path / "library.db")
    proposal_id = add_proposal(database, source, destination)
    batch_id = "interrupted-batch"
    database.create_operation(batch_id, proposal_id)
    destination.write_bytes(b"book")

    undo_latest(config(tmp_path), database, batch_id)
    assert source.exists()
    assert not destination.exists()
    assert database.get(proposal_id)["status"] == "undone"