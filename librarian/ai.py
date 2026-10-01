from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any

from .models import BookMetadata


@dataclass(frozen=True)
class AIResolution:
    book: str
    author: str | None
    series: str | None = None
    series_number: float | None = None
    confidence: float = 0.80
    narrator: str | None = None
    publication_year: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    year: int | None = None

    def metadata(self) -> BookMetadata:
        return BookMetadata(
            title=self.book,
            author=self.author,
            series=self.series,
            series_number=self.series_number,
            narrator=self.narrator,
            publication_year=self.publication_year,
            season_number=self.season_number,
            episode_number=self.episode_number,
            year=self.year,
            source="ai",
        )


class AIResolver(ABC):
    name: str

    @abstractmethod
    def resolve(
        self,
        *,
        filename: str,
        embedded: BookMetadata,
        candidate_books: list[str],
        parent_path: str | None = None,
    ) -> AIResolution | None:
        raise NotImplementedError


def _resolution(value: Any, *, require_author: bool = True) -> AIResolution:
    if not isinstance(value, dict):
        raise ValueError("AI response must be an object")
    book = value.get("book")
    author = value.get("author")
    confidence = value.get("confidence", 0.80)
    if not isinstance(book, str) or not book.strip() or (require_author and (not isinstance(author, str) or not author.strip())):
        raise ValueError("AI response requires book and author strings")
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("AI confidence must be between 0 and 1")
    series_number = value.get("series_number")
    if series_number is not None and not isinstance(series_number, (int, float)):
        raise ValueError("AI series_number must be numeric")

    narrator = value.get("narrator")
    pub_year = value.get("publication_year")
    season = value.get("season_number")
    episode = value.get("episode_number")
    year = value.get("year")

    return AIResolution(
        book=book.strip(),
        author=author.strip() if isinstance(author, str) else None,
        series=value.get("series"),
        series_number=float(series_number) if series_number is not None else None,
        narrator=narrator.strip() if isinstance(narrator, str) else None,
        publication_year=int(pub_year) if isinstance(pub_year, (int, float)) else None,
        season_number=int(season) if isinstance(season, (int, float)) else None,
        episode_number=int(episode) if isinstance(episode, (int, float)) else None,
        year=int(year) if isinstance(year, (int, float)) else None,
        confidence=float(confidence),
    )


class OpenAIResolver(AIResolver):
    name = "openai"

    def __init__(self, endpoint: str, model: str, api_key: str, timeout_seconds: float = 30.0):
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def resolve(
        self,
        *,
        filename: str,
        embedded: BookMetadata,
        candidate_books: list[str],
        parent_path: str | None = None,
    ) -> AIResolution | None:
        prompt = {
            "filename": filename,
            "folder_context": parent_path,
            "embedded_title": embedded.title,
            "embedded_artist": embedded.author,
            "media_type": embedded.media_type,
            "candidate_books": candidate_books,
        }
        body = json.dumps({
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "Identify book/media details accurately from path and metadata. Return JSON with keys: book, author, series, series_number, narrator, publication_year, season_number, episode_number, year, confidence. Never return filesystem commands.",
                },
                {"role": "user", "content": json.dumps(prompt)},
            ],
        }).encode()
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.load(response)
            content = payload["choices"][0]["message"]["content"]
        return _resolution(json.loads(content), require_author=embedded.media_type != "video")


class OllamaResolver(AIResolver):
    name = "ollama"

    def __init__(self, endpoint: str, model: str, threads: int | None = None, timeout_seconds: float = 120.0):
        self.endpoint = endpoint
        self.model = model
        self.threads = threads if threads is not None else (os.cpu_count() or 1)
        self.timeout_seconds = timeout_seconds

    def resolve(
        self,
        *,
        filename: str,
        embedded: BookMetadata,
        candidate_books: list[str],
        parent_path: str | None = None,
    ) -> AIResolution | None:
        prompt = "\n".join(
            value for value in (
                f"filename: {filename}" if filename else "",
                f"folder_context: {parent_path}" if parent_path else "",
                f"media_type: {embedded.media_type}" if embedded.media_type else "",
                f"title: {embedded.title}" if embedded.title else "",
                f"author: {embedded.author}" if embedded.author else "",
                f"series: {embedded.series}" if embedded.series else "",
                f"season: {embedded.season_number}" if embedded.season_number is not None else "",
                f"episode: {embedded.episode_number}" if embedded.episode_number is not None else "",
                f"candidates: {', '.join(candidate_books)}" if candidate_books else "",
            )
        )
        body = json.dumps({
            "model": self.model,
            "stream": False,
            "think": False,
            "format": "json",
            "keep_alive": "30m",
            "messages": [
                {
                    "role": "system",
                    "content": "Return only JSON: book, author, series, series_number, narrator, publication_year, season_number, episode_number, year, confidence. For video, book is title and author may be null.",
                },
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": 0, "num_thread": self.threads, "num_predict": 64, "num_ctx": 1024},
        }).encode()
        request = urllib.request.Request(self.endpoint, data=body, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.load(response)
        content = payload["message"]["content"]
        return _resolution(json.loads(content), require_author=embedded.media_type != "video")


class CachedAIResolver(AIResolver):
    def __init__(self, resolver: AIResolver, database: Any, ttl_seconds: int = 30 * 24 * 3600):
        self.resolver = resolver
        self.database = database
        self.ttl_seconds = ttl_seconds
        self.name = resolver.name

    def resolve(
        self,
        *,
        filename: str,
        embedded: BookMetadata,
        candidate_books: list[str],
        parent_path: str | None = None,
    ) -> AIResolution | None:
        if not self.database:
            return self.resolver.resolve(
                filename=filename,
                embedded=embedded,
                candidate_books=candidate_books,
                parent_path=parent_path,
            )

        cache_data = {
            "filename": filename,
            "embedded": asdict(embedded),
            "parent_path": parent_path,
            "candidates": candidate_books,
        }
        cache_key = f"ai:{self.name}:" + hashlib.sha256(json.dumps(cache_data, sort_keys=True).encode()).hexdigest()

        cached_payload = self.database.get_metadata_cache(cache_key, self.ttl_seconds)
        if cached_payload:
            try:
                data = json.loads(cached_payload)
                if data:
                    return AIResolution(**data)
            except Exception:
                pass

        res = self.resolver.resolve(
            filename=filename,
            embedded=embedded,
            candidate_books=candidate_books,
            parent_path=parent_path,
        )
        if res:
            self.database.put_metadata_cache(cache_key, f"ai_{self.name}", json.dumps(asdict(res)))
        return res


def build_ai_resolver(config, database: Any = None) -> AIResolver | None:
    if not config.ai_enabled:
        return None
    resolver: AIResolver
    if config.ai_provider == "ollama":
        resolver = OllamaResolver(config.ai_endpoint, config.ai_model, config.ai_threads)
    elif config.ai_provider == "openai":
        api_key = os.environ.get(config.ai_api_key_env)
        if not api_key:
            raise ValueError(f"AI enabled but {config.ai_api_key_env} is not set")
        resolver = OpenAIResolver(config.ai_endpoint, config.ai_model, api_key)
    else:
        raise ValueError(f"Unknown AI provider: {config.ai_provider}")

    if database is not None:
        ttl = getattr(config, "metadata_cache_ttl_seconds", 30 * 24 * 3600)
        return CachedAIResolver(resolver, database, ttl)
    return resolver
