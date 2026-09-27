from pathlib import Path

from borganizer.cli import cmd_approve, cmd_approve_all_high_confidence, cmd_review, cmd_run
from borganizer.config import Config
from borganizer.db import Database
from borganizer.models import Proposal


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
        allow_cross_device_move=False,
        auto_apply_threshold=0.95,
    )


def test_run_safe_mode_leaves_proposals_pending(tmp_path, capsys):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    source = incoming / "Author - Book.m4b"
    source.write_bytes(b"book")
    database = Database(tmp_path / "library.db")

    assert cmd_run(config(tmp_path), database, None, None) == 0
    assert database.pending()
    assert source.exists()
    assert "Safe mode" in capsys.readouterr().out


def test_run_automatic_mode_applies_only_high_confidence(tmp_path, capsys):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    source = incoming / "Author - Book.m4b"
    low_source = incoming / "unknown.m4b"
    source.write_bytes(b"book")
    low_source.write_bytes(b"unknown")
    database = Database(tmp_path / "library.db")
    automatic = Config(**{**config(tmp_path).__dict__, "operation_mode": "automatic", "auto_apply_threshold": 0.5})

    assert cmd_run(automatic, database, None, None) == 0
    assert not source.exists()
    assert low_source.exists()
    assert database.counts()["applied"] == 1
    assert database.counts()["pending"] == 1
    assert "Automatic mode" in capsys.readouterr().out


def add_proposal(database, source, destination, confidence):
    return database.add_proposal(Proposal(
        id=None,
        source_path=source,
        destination_path=destination,
        sha256="digest-" + str(confidence),
        confidence=confidence,
        media_type="audiobook",
        title=source.stem,
        author="Tolkien" if confidence > 0.5 else None,
        series=None,
        series_number=None,
    ))


def test_review_prints_percent_identity_and_action(tmp_path, capsys):
    database = Database(tmp_path / "library.db")
    incoming = tmp_path / "incoming"
    destination = tmp_path / "library" / "The Hobbit.m4b"
    incoming.mkdir()
    add_proposal(database, incoming / "The Hobbit.m4b", destination, 0.97)
    add_proposal(database, incoming / "maybe.mp3", tmp_path / "library" / "maybe.mp3", 0.31)

    cmd_review(config(tmp_path), database)
    output = capsys.readouterr().out

    assert "[1] 97%  The Hobbit" in output
    assert "Tolkien / The Hobbit" in output
    assert "-> MOVE" in output
    assert "[2] 31%  maybe" in output
    assert "-> IGNORE" in output


def test_approve_uses_existing_apply_path(tmp_path, capsys):
    database = Database(tmp_path / "library.db")
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    source = incoming / "The Hobbit.m4b"
    destination = tmp_path / "library" / "The Hobbit.m4b"
    source.write_bytes(b"book")
    proposal_id = add_proposal(database, source, destination, 0.97)

    assert cmd_approve(config(tmp_path), database, [proposal_id]) == 0
    assert destination.read_bytes() == b"book"
    assert database.get(proposal_id)["status"] == "applied"
    assert "Approved batch" in capsys.readouterr().out


def test_approve_all_high_confidence_leaves_lower_confidence_pending(tmp_path):
    database = Database(tmp_path / "library.db")
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    high_source = incoming / "high.m4b"
    low_source = incoming / "low.m4b"
    high_destination = tmp_path / "library" / "high.m4b"
    low_destination = tmp_path / "library" / "low.m4b"
    high_source.write_bytes(b"high")
    low_source.write_bytes(b"low")
    high_id = add_proposal(database, high_source, high_destination, 0.97)
    low_id = add_proposal(database, low_source, low_destination, 0.74)

    assert cmd_approve_all_high_confidence(config(tmp_path), database) == 0
    assert database.get(high_id)["status"] == "applied"
    assert database.get(low_id)["status"] == "pending"