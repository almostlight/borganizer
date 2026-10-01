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
            headers={"User-Agent": "librarian/0.1 (+metadata lookup)"},
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
    p_name = config.metadata_provider.lower().strip()
    provider: MetadataProvider
    if p_name == "openlibrary":
        provider = OpenLibraryProvider()
    elif p_name == "googlebooks":
        provider = GoogleBooksProvider()
    elif p_name == "itunes":
        provider = ITunesProvider()
    elif p_name in {"composite", "multi", "all"}:
        provider = CompositeMetadataProvider([
            OpenLibraryProvider(),
            GoogleBooksProvider(),
            ITunesProvider(),
        ])
    else:
        raise ValueError(f"Unknown metadata provider: {config.metadata_provider}")
    return CachedMetadataProvider(provider, database, config.metadata_cache_ttl_seconds)


class GoogleBooksProvider(MetadataProvider):
    name = "googlebooks"

    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout_seconds = timeout_seconds

    def _request(self, params: dict[str, str]) -> dict:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"https://www.googleapis.com/books/v1/volumes?{query}",
            headers={"User-Agent": "librarian/0.1 (+metadata lookup)"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            return json.load(response)


    @staticmethod
    def _metadata(item: dict) -> BookMetadata:
        vol = item.get("volumeInfo") or {}
        authors = vol.get("authors") or []
        industry_ids = vol.get("industryIdentifiers") or []
        isbn = None
        for i_id in industry_ids:
            if i_id.get("type") in ("ISBN_13", "ISBN_10"):
                isbn = i_id.get("identifier")
                break

        pub_date = vol.get("publishedDate", "")
        pub_year = int(pub_date[:4]) if pub_date and len(pub_date) >= 4 and pub_date[:4].isdigit() else None
        images = vol.get("imageLinks") or {}
        cover_url = images.get("thumbnail") or images.get("smallThumbnail")

        return BookMetadata(
            title=vol.get("title"),
            author=authors[0] if authors else None,
            publisher=vol.get("publisher"),
            publication_year=pub_year,
            isbn=isbn,
            language=vol.get("language"),
            cover_url=cover_url,
            media_type="ebook",
            source="googlebooks",
        )

    def search(self, metadata: BookMetadata) -> list[MetadataSearchResult]:
        q_parts = []
        if metadata.isbn:
            q_parts.append(f"isbn:{metadata.isbn}")
        else:
            if metadata.title:
                q_parts.append(f"intitle:{metadata.title}")
            if metadata.author:
                q_parts.append(f"inauthor:{metadata.author}")
        if not q_parts:
            return []

        params = {"q": " ".join(q_parts), "maxResults": "5"}
        try:
            payload = self._request(params)
            results = []
            for item in payload.get("items", []):
                item_id = item.get("id")
                if item_id:
                    results.append(MetadataSearchResult(f"googlebooks:{item_id}", self._metadata(item)))
            return results
        except Exception:
            return []

    def get_book(self, identifier: str) -> BookMetadata | None:
        clean_id = identifier.replace("googlebooks:", "")
        try:
            request = urllib.request.Request(
                f"https://www.googleapis.com/books/v1/volumes/{clean_id}",
                headers={"User-Agent": "librarian/0.1 (+metadata lookup)"},
            )
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
                return self._metadata(payload)
        except Exception:
            return None


class ITunesProvider(MetadataProvider):
    name = "itunes"

    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout_seconds = timeout_seconds

    def search(self, metadata: BookMetadata) -> list[MetadataSearchResult]:
        term_parts = [p for p in (metadata.title, metadata.author) if p]
        if not term_parts:
            return []

        media = "all"
        entity = None
        if metadata.media_type == "audiobook":
            media = "audiobook"
            entity = "audiobook"
        elif metadata.media_type == "ebook":
            media = "ebook"
            entity = "ebook"
        elif metadata.media_type == "video":
            entity = "movie" if not metadata.season_number else "tvSeason"

        params = {"term": " ".join(term_parts), "limit": "5"}
        if media != "all":
            params["media"] = media
        if entity:
            params["entity"] = entity

        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"https://itunes.apple.com/search?{query}",
            headers={"User-Agent": "librarian/0.1 (+metadata lookup)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
            results = []
            for item in payload.get("results", []):
                track_id = item.get("trackId") or item.get("collectionId")
                if not track_id:
                    continue
                title = item.get("trackName") or item.get("collectionName")
                artist = item.get("artistName")
                rel_date = item.get("releaseDate", "")
                year = int(rel_date[:4]) if rel_date and len(rel_date) >= 4 and rel_date[:4].isdigit() else None
                cover = item.get("artworkUrl100")
                if cover:
                    cover = cover.replace("100x100bb", "600x600bb")

                results.append(
                    MetadataSearchResult(
                        f"itunes:{track_id}",
                        BookMetadata(
                            title=title,
                            author=artist,
                            narrator=artist if metadata.media_type == "audiobook" else None,
                            publication_year=year,
                            cover_url=cover,
                            media_type=metadata.media_type or "audiobook",
                            source="itunes",
                        ),
                    )
                )
            return results
        except Exception:
            return []

    def get_book(self, identifier: str) -> BookMetadata | None:
        clean_id = identifier.replace("itunes:", "")
        params = {"id": clean_id}
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"https://itunes.apple.com/lookup?{query}",
            headers={"User-Agent": "librarian/0.1 (+metadata lookup)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
            results = payload.get("results", [])
            if not results:
                return None
            item = results[0]
            title = item.get("trackName") or item.get("collectionName")
            artist = item.get("artistName")
            return BookMetadata(title=title, author=artist, source="itunes")
        except Exception:
            return None


class CompositeMetadataProvider(MetadataProvider):
    name = "composite"

    def __init__(self, providers: list[MetadataProvider]):
        self.providers = providers

    def search(self, metadata: BookMetadata) -> list[MetadataSearchResult]:
        results: list[MetadataSearchResult] = []
        seen_titles = set()
        for provider in self.providers:
            try:
                prov_results = provider.search(metadata)
                for res in prov_results:
                    key = (res.metadata.title or "").lower().strip(), (res.metadata.author or "").lower().strip()
                    if key not in seen_titles:
                        seen_titles.add(key)
                        results.append(res)
            except Exception:
                continue
        return results

    def get_book(self, identifier: str) -> BookMetadata | None:
        for provider in self.providers:
            if identifier.startswith(f"{provider.name}:"):
                return provider.get_book(identifier)
        for provider in self.providers:
            try:
                res = provider.get_book(identifier)
                if res:
                    return res
            except Exception:
                continue
        return None