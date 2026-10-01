import json
from pathlib import Path
from librarian.models import BookMetadata
from librarian.metadata import extract_metadata, parse_filename, _clean_isbn, _parse_year
from librarian.providers import (
    GoogleBooksProvider,
    ITunesProvider,
    CompositeMetadataProvider,
    build_metadata_provider,
)
from librarian.ai import (
    AIResolution,
    CachedAIResolver,
    build_ai_resolver,
)
from librarian.db import Database


def test_clean_isbn_and_parse_year():
    assert _clean_isbn("ISBN 978-0-7653-2635-5") == "9780765326355"
    assert _clean_isbn("0345339711") == "0345339711"
    assert _clean_isbn("invalid") is None

    assert _parse_year("2021-05-12") == 2021
    assert _parse_year("Published in 1999") == 1999
    assert _parse_year(None) is None


def test_video_filename_parsing():
    meta = parse_filename(Path("Breaking.Bad.S02E05.1080p.WEB-DL.x264.mkv"))
    assert meta.media_type == "video"
    assert meta.series == "Breaking Bad"
    assert meta.season_number == 2
    assert meta.episode_number == 5

    movie = parse_filename(Path("Inception (2010).1080p.mkv"))
    assert movie.media_type == "video"
    assert movie.title == "Inception"
    assert movie.year == 2010


def test_google_books_provider_search():
    provider = GoogleBooksProvider()

    class MockResponse:
        def __init__(self, data):
            self.data = json.dumps(data).encode("utf-8")

        def read(self):
            return self.data

        def read(self):
            return self.data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    mock_data = {
        "items": [
            {
                "id": "vol123",
                "volumeInfo": {
                    "title": "Dune",
                    "authors": ["Frank Herbert"],
                    "publishedDate": "1965",
                    "publisher": "Chilton Books",
                    "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780441172719"}],
                    "imageLinks": {"thumbnail": "http://example.com/cover.jpg"},
                    "language": "en",
                },
            }
        ]
    }

    import urllib.request
    orig_urlopen = urllib.request.urlopen
    try:
        urllib.request.urlopen = lambda req, **kwargs: MockResponse(mock_data)
        results = provider.search(BookMetadata(title="Dune", author="Frank Herbert"))
        assert len(results) == 1
        assert results[0].identifier == "googlebooks:vol123"
        assert results[0].metadata.title == "Dune"
        assert results[0].metadata.author == "Frank Herbert"
        assert results[0].metadata.isbn == "9780441172719"
        assert results[0].metadata.publication_year == 1965
    finally:
        urllib.request.urlopen = orig_urlopen


def test_itunes_provider_search():
    provider = ITunesProvider()

    class MockResponse:
        def __init__(self, data):
            self.data = json.dumps(data).encode("utf-8")

        def read(self):
            return self.data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    mock_data = {
        "results": [
            {
                "trackId": 999,
                "trackName": "The Hobbit",
                "artistName": "J.R.R. Tolkien",
                "releaseDate": "1937-09-21T00:00:00Z",
                "artworkUrl100": "http://example.com/100x100bb.jpg",
            }
        ]
    }

    import urllib.request
    orig_urlopen = urllib.request.urlopen
    try:
        urllib.request.urlopen = lambda req, **kwargs: MockResponse(mock_data)
        results = provider.search(BookMetadata(title="The Hobbit", media_type="audiobook"))
        assert len(results) == 1
        assert results[0].identifier == "itunes:999"
        assert results[0].metadata.title == "The Hobbit"
        assert results[0].metadata.author == "J.R.R. Tolkien"
        assert results[0].metadata.cover_url == "http://example.com/600x600bb.jpg"
    finally:
        urllib.request.urlopen = orig_urlopen


def test_composite_provider():
    class DummyProvider1:
        name = "p1"
        def search(self, meta):
            return [type("Res", (), {"metadata": BookMetadata(title="Book 1", author="Author 1"), "identifier": "p1:1"})()]
        def get_book(self, id): return None

    class DummyProvider2:
        name = "p2"
        def search(self, meta):
            return [type("Res", (), {"metadata": BookMetadata(title="Book 2", author="Author 2"), "identifier": "p2:2"})()]
        def get_book(self, id): return None

    composite = CompositeMetadataProvider([DummyProvider1(), DummyProvider2()])
    results = composite.search(BookMetadata(title="Test"))
    assert len(results) == 2
    assert results[0].metadata.title == "Book 1"
    assert results[1].metadata.title == "Book 2"


def test_cached_ai_resolver(tmp_path):
    db = Database(tmp_path / "test.db")

    class DummyAIResolver:
        name = "dummy"
        def __init__(self):
            self.calls = 0

        def resolve(self, *, filename, embedded, candidate_books, parent_path=None):
            self.calls += 1
            return AIResolution(book="Cached Book", author="Author", confidence=0.9)

    dummy = DummyAIResolver()
    cached = CachedAIResolver(dummy, db)

    res1 = cached.resolve(filename="test.mp3", embedded=BookMetadata(), candidate_books=[])
    res2 = cached.resolve(filename="test.mp3", embedded=BookMetadata(), candidate_books=[])

    assert res1.book == "Cached Book"
    assert res2.book == "Cached Book"
    assert dummy.calls == 1  # Second call hit cache!
