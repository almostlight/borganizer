from pathlib import Path

from borganizer.config import Config
from borganizer.db import Database
from borganizer.models import BookMetadata, FileCandidate
from borganizer.organizer import propose
from borganizer.providers import MetadataProvider, MetadataSearchResult
from borganizer.ai import AIResolver, AIResolution


class FakeMetadataProvider(MetadataProvider):
    name = "fake"

    def search(self, metadata):
        return [MetadataSearchResult("book-1", BookMetadata(title="The Hobbit", author="Tolkien", source="fake"))]

    def get_book(self, identifier):
        return None


class FakeAIResolver(AIResolver):
    name = "fake-ai"

    def resolve(self, *, filename, embedded, candidate_books):
        return AIResolution("The Final Empire", "Brandon Sanderson", "Mistborn", 1, 0.97)


def config(incoming: Path, library: Path, database: Path, *, ai_enabled: bool = False) -> Config:
    return Config(
        incoming_dir=incoming,
        library_dir=library,
        database=database,
        audiobook_extensions=(".mp3", ".m4b"),
        ebook_extensions=(".epub",),
        ignore_hidden=True,
        min_stable_age_seconds=0,
        series_number_width=2,
        invalid_replacement="_",
        overwrite_existing=False,
        allow_cross_device_move=False,
        auto_apply_threshold=0.95,
        ai_enabled=ai_enabled,
    )


def test_propose_reuses_existing_book_directory(tmp_path):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    existing = library / "Tolkien" / "The Hobbit"
    existing.mkdir(parents=True)
    (existing / "Tolkien - The Hobbit.m4b").write_bytes(b"existing")
    (incoming / "The_Hobbit_Unabridged.mp3").write_bytes(b"new")

    database = Database(tmp_path / "library.db")
    proposals = propose(config(incoming, library, tmp_path / "library.db"), database)

    assert len(proposals) == 1
    assert proposals[0].match_kind == "same edition"
    assert proposals[0].match_method == "fuzzy matching"
    assert proposals[0].destination_path == existing / "The Hobbit.mp3"


def test_propose_marks_identical_content_as_duplicate(tmp_path):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    existing = library / "Tolkien" / "The Hobbit"
    existing.mkdir(parents=True)
    content = b"same audiobook"
    (existing / "The Hobbit.m4b").write_bytes(content)
    (incoming / "The Hobbit.mp3").write_bytes(content)

    database = Database(tmp_path / "library.db")
    proposals = propose(config(incoming, library, tmp_path / "library.db"), database)

    assert proposals[0].status == "duplicate"
    assert proposals[0].match_kind == "duplicate file"


def test_propose_prefers_exact_title_author_over_fuzzy_match(tmp_path):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    (library / "Tolkien" / "The Hobbit").mkdir(parents=True)
    (library / "Other" / "The Hobbit Unabridged").mkdir(parents=True)
    (library / "Tolkien" / "The Hobbit" / "Tolkien - The Hobbit.m4b").write_bytes(b"exact")
    (library / "Other" / "The Hobbit Unabridged" / "Other - The Hobbit Unabridged.m4b").write_bytes(b"fuzzy")
    (incoming / "Tolkien - The Hobbit.mp3").write_bytes(b"new")

    database = Database(tmp_path / "library.db")
    proposals = propose(config(incoming, library, tmp_path / "library.db"), database)

    assert proposals[0].match_method == "normalized title + author"
    assert proposals[0].destination_path.parent == library / "Tolkien" / "The Hobbit"


def test_provider_enriches_filename_only_candidate(tmp_path):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    (incoming / "The_Hobbit_Unabridged.mp3").write_bytes(b"new")

    database = Database(tmp_path / "library.db")
    proposals = propose(config(incoming, library, tmp_path / "library.db"), database, FakeMetadataProvider())

    assert proposals[0].destination_path == library / "Tolkien" / "The Hobbit" / "The Hobbit.mp3"
    assert "metadata lookup: fake" in proposals[0].reason
    assert "processing time:" in proposals[0].reason


def test_ai_resolver_enriches_candidate_without_filesystem_access(tmp_path):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    (incoming / "Sanderson_Mistborn_FinalEmpire_unabridged.m4b").write_bytes(b"new")

    database = Database(tmp_path / "library.db")
    proposals = propose(config(incoming, library, tmp_path / "library.db", ai_enabled=True), database, ai_resolver=FakeAIResolver())

    assert proposals[0].destination_path == library / "Brandon Sanderson" / "Mistborn" / "01 - The Final Empire" / "The Final Empire.m4b"
    assert "AI resolver: fake-ai" in proposals[0].reason


def test_ai_resolver_skips_complete_embedded_metadata(tmp_path, monkeypatch):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    source = incoming / "Tagged.m4b"
    source.write_bytes(b"new")

    def tagged_metadata(path, media_type):
        return BookMetadata(title="Tagged Book", author="Tagged Author", series="Tagged Series", series_number=1, isbn="9780000000001", media_type=media_type, source="tags")

    class FailingAIResolver:
        name = "should-not-run"

        def resolve(self, **kwargs):
            raise AssertionError("AI should not run for complete embedded metadata")

    monkeypatch.setattr("borganizer.organizer.extract_metadata", tagged_metadata)
    database = Database(tmp_path / "library.db")
    proposals = propose(config(incoming, library, tmp_path / "library.db", ai_enabled=True), database, ai_resolver=FailingAIResolver())

    assert len(proposals) == 1
    assert "AI resolver" not in proposals[0].reason


def test_low_confidence_metadata_is_escalated_to_ai(tmp_path):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    (incoming / "Joseph Conrad - 003 - Heart of Darkness.mp3").write_bytes(b"new")

    database = Database(tmp_path / "library.db")
    proposals = propose(config(incoming, library, tmp_path / "library.db", ai_enabled=True), database, ai_resolver=FakeAIResolver())

    assert proposals[0].confidence == 0.97
    assert proposals[0].title == "The Final Empire"
    assert "AI resolver: fake-ai" in proposals[0].reason


def test_low_confidence_metadata_is_not_proposed_without_ai_result(tmp_path):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    (incoming / "Joseph Conrad - 003 - Heart of Darkness.mp3").write_bytes(b"new")

    class LowConfidenceAI:
        name = "low-confidence"

        def resolve(self, **kwargs):
            return AIResolution("003", "Joseph Conrad", None, None, 0.6)

    database = Database(tmp_path / "library.db")
    proposals = propose(config(incoming, library, tmp_path / "library.db", ai_enabled=True), database, ai_resolver=LowConfidenceAI())

    assert proposals == []


def test_ai_result_must_exist_in_metadata_provider(tmp_path):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    (incoming / "Joseph Conrad - 003 - Heart of Darkness.mp3").write_bytes(b"new")

    class EmptyMetadataProvider(MetadataProvider):
        name = "empty"

        def search(self, metadata):
            return []

        def get_book(self, identifier):
            return None

    database = Database(tmp_path / "library.db")
    proposals = propose(
        config(incoming, library, tmp_path / "library.db", ai_enabled=True),
        database,
        provider=EmptyMetadataProvider(),
        ai_resolver=FakeAIResolver(),
    )

    assert proposals == []


def test_numeric_ai_series_is_rejected(tmp_path):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    (incoming / "Joseph Conrad - 003 - Heart of Darkness.mp3").write_bytes(b"new")

    class NumericSeriesAI:
        name = "numeric-series"

        def resolve(self, **kwargs):
            return AIResolution("Heart of Darkness", "Joseph Conrad", "3", 3, 0.95)

    database = Database(tmp_path / "library.db")
    proposals = propose(config(incoming, library, tmp_path / "library.db", ai_enabled=True), database, ai_resolver=NumericSeriesAI())

    assert proposals == []


def test_duplicate_book_destinations_preserve_track_names(tmp_path, monkeypatch):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    (incoming / "01 - Chapter One.mp3").write_bytes(b"one")
    (incoming / "02 - Chapter Two.mp3").write_bytes(b"two")

    def same_album(path, media_type):
        return BookMetadata(title="The Hobbit", author="Tolkien", media_type=media_type, source="tags")

    monkeypatch.setattr("borganizer.organizer.extract_metadata", same_album)
    database = Database(tmp_path / "library.db")
    proposals = propose(config(incoming, library, tmp_path / "library.db"), database)

    assert {proposal.destination_path.name for proposal in proposals} == {"01 - Chapter One.mp3", "02 - Chapter Two.mp3"}


def test_single_audiobook_edition_stays_flat(tmp_path, monkeypatch):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    (incoming / "The Hobbit.m4b").write_bytes(b"hobbit")

    def tagged(path, media_type):
        return BookMetadata(title="The Hobbit", author="Tolkien", narrator="Andy Serkis", media_type=media_type, source="tags")

    monkeypatch.setattr("borganizer.organizer.extract_metadata", tagged)
    database = Database(tmp_path / "library.db")
    proposals = propose(config(incoming, library, tmp_path / "library.db"), database)

    assert proposals[0].destination_path == library / "Tolkien" / "The Hobbit" / "The Hobbit.m4b"


def test_multiple_audiobook_narrators_use_conditional_hierarchy(tmp_path, monkeypatch):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    (incoming / "hobbit-andy.m4b").write_bytes(b"andy")
    (incoming / "hobbit-rob.m4b").write_bytes(b"rob")

    def tagged(path, media_type):
        narrator = "Andy Serkis" if "andy" in path.stem else "Rob Inglis"
        return BookMetadata(title="The Hobbit", author="Tolkien", narrator=narrator, media_type=media_type, source="tags")

    monkeypatch.setattr("borganizer.organizer.extract_metadata", tagged)
    database = Database(tmp_path / "library.db")
    proposals = propose(config(incoming, library, tmp_path / "library.db"), database)

    destinations = {proposal.destination_path for proposal in proposals}
    assert destinations == {
        library / "Tolkien" / "The Hobbit" / "Audiobooks" / "Andy Serkis" / "hobbit-andy.m4b",
        library / "Tolkien" / "The Hobbit" / "Audiobooks" / "Rob Inglis" / "hobbit-rob.m4b",
    }


def test_ebook_and_single_audiobook_share_flat_book_directory(tmp_path, monkeypatch):
    incoming = tmp_path / "incoming"
    library = tmp_path / "library"
    incoming.mkdir()
    (incoming / "The Hobbit.epub").write_bytes(b"ebook")
    (incoming / "The Hobbit.m4b").write_bytes(b"audio")

    def tagged(path, media_type):
        return BookMetadata(title="The Hobbit", author="Tolkien", narrator="Andy Serkis" if media_type == "audiobook" else None, media_type=media_type, source="tags")

    monkeypatch.setattr("borganizer.organizer.extract_metadata", tagged)
    database = Database(tmp_path / "library.db")
    proposals = propose(config(incoming, library, tmp_path / "library.db"), database)

    assert {proposal.destination_path for proposal in proposals} == {
        library / "Tolkien" / "The Hobbit" / "The Hobbit.epub",
        library / "Tolkien" / "The Hobbit" / "The Hobbit.m4b",
    }