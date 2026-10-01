from pathlib import Path
from zipfile import ZipFile

from librarian.archive import inspect_zip
from librarian.config import Config
from librarian.db import Database
from librarian.organizer import propose


def config(tmp_path: Path) -> Config:
    return Config(
        incoming_dir=tmp_path / "incoming",
        library_dir=tmp_path / "library",
        database=tmp_path / "library.db",
        audiobook_extensions=(".mp3", ".m4b"),
        ebook_extensions=(".epub",),
        ignore_hidden=True,
        min_stable_age_seconds=0,
        series_number_width=2,
        invalid_replacement="_",
        overwrite_existing=False,
        allow_cross_device_move=False,
        auto_apply_threshold=0.95,
    )


def test_chapter_parts_share_one_group_and_keep_names(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    for name in ("01 - Chapter 01.mp3", "02 - Chapter 02.mp3", "03 - Chapter 03.mp3"):
        (incoming / name).write_bytes(name.encode())

    database = Database(tmp_path / "library.db")
    proposals = propose(config(tmp_path), database)

    assert len({proposal.destination_path.parent for proposal in proposals}) == 1
    assert {proposal.destination_path.name for proposal in proposals} == {
        "01 - Chapter 01.mp3", "02 - Chapter 02.mp3", "03 - Chapter 03.mp3"
    }


def test_part_suffixes_share_one_group(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    for name in ("Book.part01.mp3", "Book.part02.mp3"):
        (incoming / name).write_bytes(name.encode())

    database = Database(tmp_path / "library.db")
    proposals = propose(config(tmp_path), database)

    assert {proposal.destination_path.parent for proposal in proposals} == {
        tmp_path / "library" / "Unknown Author" / "Book"
    }


def test_cd_directories_share_parent_book(tmp_path):
    incoming = tmp_path / "incoming"
    (incoming / "Book" / "CD01").mkdir(parents=True)
    (incoming / "Book" / "CD02").mkdir(parents=True)
    (incoming / "Book" / "CD01" / "track.m4b").write_bytes(b"one")
    (incoming / "Book" / "CD02" / "track.m4b").write_bytes(b"two")

    database = Database(tmp_path / "library.db")
    proposals = propose(config(tmp_path), database)

    assert len({proposal.destination_path.parent for proposal in proposals}) == 1


def test_zip_inspection_does_not_extract(tmp_path):
    archive = tmp_path / "Book.zip"
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr("Book.m4b", b"audio")
        zip_file.writestr("cover.jpg", b"cover")

    entries = inspect_zip(archive)

    assert [(entry.name, entry.size) for entry in entries] == [("Book.m4b", 5), ("cover.jpg", 5)]
    assert not (tmp_path / "Book.m4b").exists()