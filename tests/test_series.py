from pathlib import Path

from borganizer.config import Config
from borganizer.metadata import parse_filename
from borganizer.models import BookMetadata, FileCandidate
from borganizer.organizer import build_destination


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


def test_decimal_series_position_is_structured():
    metadata = parse_filename(Path("Mistborn - 0.5 - The Eleventh Metal.m4b"))

    assert metadata.series == "Mistborn"
    assert metadata.series_number == 0.5
    assert metadata.series_position_label is None
    assert metadata.title == "The Eleventh Metal"


def test_named_series_positions_are_preserved():
    for position in ("Companion", "Short Stories", "Collection", "Box Set"):
        metadata = parse_filename(Path(f"Mistborn {position} - Extra Material.m4b"))
        assert metadata.series == "Mistborn"
        assert metadata.series_number is None
        assert metadata.series_position_label == position


def test_series_position_rendering_is_a_directory_detail(tmp_path):
    candidate = FileCandidate(
        path=tmp_path / "source.m4b",
        media_type="audiobook",
        sha256="digest",
        metadata=BookMetadata(
            title="The Eleventh Metal",
            author="Brandon Sanderson",
            series="Mistborn",
            series_number=0.5,
        ),
        confidence=0.9,
        notes=[],
    )

    assert build_destination(candidate, config(tmp_path)) == (
        tmp_path / "library" / "Brandon Sanderson" / "Mistborn" / "0.5 - The Eleventh Metal" / "The Eleventh Metal.m4b"
    )


def test_named_position_renders_without_fake_numeric_padding(tmp_path):
    candidate = FileCandidate(
        path=tmp_path / "source.m4b",
        media_type="audiobook",
        sha256="digest",
        metadata=BookMetadata(
            title="Extra Material",
            author="Brandon Sanderson",
            series="Mistborn",
            series_position_label="Companion",
        ),
        confidence=0.9,
        notes=[],
    )

    assert build_destination(candidate, config(tmp_path)).parts[-2] == "Companion - Extra Material"