from pathlib import Path

from librarian.config import Config
from librarian.db import Database
from librarian.metadata import parse_filename
from librarian.organizer import propose


def video_config(tmp_path: Path) -> Config:
    return Config(
        incoming_dir=tmp_path / "incoming",
        library_dir=tmp_path / "library",
        database=tmp_path / "library.db",
        audiobook_extensions=(),
        ebook_extensions=(),
        ignore_hidden=True,
        min_stable_age_seconds=0,
        series_number_width=2,
        invalid_replacement="_",
        overwrite_existing=False,
        allow_cross_device_move=False,
        auto_apply_threshold=0.95,
        video_extensions=(".mkv", ".mp4"),
    )


def test_jellyfin_tv_episode_destination(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "The Expanse - S01E03 - Remember the Cant.mkv").write_bytes(b"episode")

    config = video_config(tmp_path)
    proposals = propose(config, Database(config.database))

    assert proposals[0].destination_path == (
        tmp_path / "library" / "TV Shows" / "The Expanse" / "Season 01"
        / "The Expanse - S01E03 - Remember the Cant.mkv"
    )


def test_jellyfin_movie_destination_includes_year(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "Arrival (2016).mkv").write_bytes(b"movie")

    config = video_config(tmp_path)
    proposals = propose(config, Database(config.database))

    assert proposals[0].destination_path == tmp_path / "library" / "Movies" / "Arrival (2016)" / "Arrival (2016).mkv"


def test_video_filename_parser_extracts_episode_fields():
    metadata = parse_filename(Path("The Expanse - S02E05 - Home.mkv"))

    assert metadata.media_type == "video"
    assert metadata.series == "The Expanse"
    assert metadata.title == "Home"
    assert metadata.season_number == 2
    assert metadata.episode_number == 5