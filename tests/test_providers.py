from borganizer.db import Database
from borganizer.models import BookMetadata
from borganizer.providers import CachedMetadataProvider, MetadataProvider, MetadataSearchResult


class FakeProvider(MetadataProvider):
    name = "fake"

    def __init__(self):
        self.search_calls = 0
        self.book_calls = 0

    def search(self, metadata):
        self.search_calls += 1
        return [MetadataSearchResult("book-1", BookMetadata(title="The Hobbit", author="Tolkien", source="fake"))]

    def get_book(self, identifier):
        self.book_calls += 1
        return BookMetadata(title="The Hobbit", source="fake")


def test_cached_provider_avoids_repeated_search_and_get(tmp_path):
    database = Database(tmp_path / "library.db")
    fake = FakeProvider()
    provider = CachedMetadataProvider(fake, database, 3600)
    metadata = BookMetadata(title="The Hobbit")

    provider.search(metadata)
    provider.search(metadata)
    provider.get_book("book-1")
    provider.get_book("book-1")

    assert fake.search_calls == 1
    assert fake.book_calls == 1