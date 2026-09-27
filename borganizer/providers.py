from __future__ import annotations

import json
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass

from .config import Config
from .db import Database
from .models import BookMetadata


@dataclass(frozen=True)
class MetadataSearchResult:
    identifier: str
    metadata: BookMetadata


class MetadataProvider(ABC):
    name: str

    @abstractmethod
    def search(self, metadata: BookMetadata) -> list[MetadataSearchResult]:
        raise NotImplementedError

    @abstractmethod
    def get_book(self, identifier: str) -> BookMetadata | None:
        raise NotImplementedError


class OpenLibraryProvider(MetadataProvider):
    name = "openlibrary"

    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout_seconds = timeout_seconds

    def _request(self, path: str, params: dict[str, str] | None = None) -> dict:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        request = urllib.request.Request(
            f"https://openlibrary.org{path}{query}",
            headers={"User-Agent": "borganizer/0.1 (+metadata lookup)"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.load(response)

    @staticmethod
    def _metadata(doc: dict) -> BookMetadata:
        authors = doc.get("author_name") or []
        isbns = doc.get("isbn") or []
        publishers = doc.get("publisher") or []
        languages = doc.get("language") or []
        return BookMetadata(
            title=doc.get("title"),
            author=authors[0] if authors else None,
            series=(doc.get("series") or [None])[0],
            isbn=isbns[0] if isbns else None,
            publisher=publishers[0] if publishers else None,
            publication_year=doc.get("first_publish_year"),
            language=languages[0] if languages else None,
            cover_url=f"https://covers.openlibrary.org/b/id/{doc['cover_i']}-L.jpg" if doc.get("cover_i") else None,
            source="openlibrary",
        )

    def search(self, metadata: BookMetadata) -> list[MetadataSearchResult]:
        params: dict[str, str] = {"limit": "5"}
        if metadata.isbn:
            params["isbn"] = metadata.isbn
        else:
            if metadata.title:
                params["title"] = metadata.title
            if metadata.author:
                params["author"] = metadata.author
        payload = self._request("/search.json", params)
        return [
            MetadataSearchResult(doc.get("key", ""), self._metadata(doc))
            for doc in payload.get("docs", [])
            if doc.get("key") and doc.get("title")
        ]

    def get_book(self, identifier: str) -> BookMetadata | None:
        payload = self._request(identifier if identifier.startswith("/") else f"/works/{identifier}.json")
        return BookMetadata(title=payload.get("title"), source="openlibrary") if payload.get("title") else None


class CachedMetadataProvider(MetadataProvider):
    def __init__(self, provider: MetadataProvider, database: Database, ttl_seconds: int):
        self.provider = provider
        self.database = database
        self.ttl_seconds = ttl_seconds
        self.name = provider.name

    def _load(self, key: str) -> object | None:
        payload = self.database.get_metadata_cache(key, self.ttl_seconds)
        return json.loads(payload) if payload else None

    def _save(self, key: str, value: object) -> None:
        self.database.put_metadata_cache(key, self.name, json.dumps(value))

    @staticmethod
    def _from_dict(value: dict) -> BookMetadata:
        return BookMetadata(**value)

    def search(self, metadata: BookMetadata) -> list[MetadataSearchResult]:
        key = "search:" + json.dumps(asdict(metadata), sort_keys=True)
        cached = self._load(key)
        if cached is None:
            results = self.provider.search(metadata)
            self._save(key, [{"identifier": result.identifier, "metadata": asdict(result.metadata)} for result in results])
            return results
        return [MetadataSearchResult(item["identifier"], self._from_dict(item["metadata"])) for item in cached]

    def get_book(self, identifier: str) -> BookMetadata | None:
        key = f"book:{identifier}"
        cached = self._load(key)
        if cached is None:
            result = self.provider.get_book(identifier)
            self._save(key, asdict(result) if result else {})
            return result
        return self._from_dict(cached) if cached else None


def build_metadata_provider(config: Config, database: Database) -> MetadataProvider | None:
    if not config.metadata_enabled:
        return None
    if config.metadata_provider != "openlibrary":
        raise ValueError(f"Unknown metadata provider: {config.metadata_provider}")
    return CachedMetadataProvider(OpenLibraryProvider(), database, config.metadata_cache_ttl_seconds)