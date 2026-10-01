from __future__ import annotations

import json
import os
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .models import BookMetadata


@dataclass(frozen=True)
class AIResolution:
    book: str
    author: str | None
    series: str | None
    series_number: float | None
    confidence: float

    def metadata(self) -> BookMetadata:
        return BookMetadata(
            title=self.book,
            author=self.author,
            series=self.series,
            series_number=self.series_number,
            source="ai",
        )


class AIResolver(ABC):
    name: str

    @abstractmethod
    def resolve(self, *, filename: str, embedded: BookMetadata, candidate_books: list[str]) -> AIResolution | None:
        raise NotImplementedError


def _resolution(value: Any, *, require_author: bool = True) -> AIResolution:
    if not isinstance(value, dict):
        raise ValueError("AI response must be an object")
    book = value.get("book")
    author = value.get("author")
    confidence = value.get("confidence")
    if not isinstance(book, str) or not book.strip() or (require_author and (not isinstance(author, str) or not author.strip())):
        raise ValueError("AI response requires book and author strings")
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("AI confidence must be between 0 and 1")
    series_number = value.get("series_number")
    if series_number is not None and not isinstance(series_number, (int, float)):
        raise ValueError("AI series_number must be numeric")
    return AIResolution(book.strip(), author.strip() if isinstance(author, str) else None, value.get("series"), float(series_number) if series_number is not None else None, float(confidence))


class OpenAIResolver(AIResolver):
    name = "openai"

    def __init__(self, endpoint: str, model: str, api_key: str, timeout_seconds: float = 30.0):
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def resolve(self, *, filename: str, embedded: BookMetadata, candidate_books: list[str]) -> AIResolution | None:
        prompt = {
            "filename": filename,
            "embedded_title": embedded.title,
            "embedded_artist": embedded.author,
            "candidate_books": candidate_books,
        }
        body = json.dumps({
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Identify the book only. Return JSON with book, author, series, series_number, confidence. Never return filesystem commands."},
                {"role": "user", "content": json.dumps(prompt)},
            ],
        }).encode()
        request = urllib.request.Request(self.endpoint, data=body, method="POST", headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.load(response)
            content = payload["choices"][0]["message"]["content"]
        return _resolution(json.loads(content))


class OllamaResolver(AIResolver):
    name = "ollama"

    def __init__(self, endpoint: str, model: str, threads: int | None = None, timeout_seconds: float = 120.0):
        self.endpoint = endpoint
        self.model = model
        self.threads = threads if threads is not None else (os.cpu_count() or 1)
        self.timeout_seconds = timeout_seconds

    def resolve(self, *, filename: str, embedded: BookMetadata, candidate_books: list[str]) -> AIResolution | None:
        prompt = "\n".join(
            value for value in (
                f"filename: {filename}" if filename else "",
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
                {"role": "system", "content": "Return only JSON: book, author, series, series_number, confidence. For video, book is the movie or episode title and author may be null."},
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": 0, "num_thread": self.threads, "num_predict": 64, "num_ctx": 1024},
        }).encode()
        request = urllib.request.Request(self.endpoint, data=body, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.load(response)
        content = payload["message"]["content"]
        return _resolution(json.loads(content), require_author=embedded.media_type != "video")


def build_ai_resolver(config) -> AIResolver | None:
    if not config.ai_enabled:
        return None
    if config.ai_provider == "ollama":
        return OllamaResolver(config.ai_endpoint, config.ai_model, config.ai_threads)
    if config.ai_provider != "openai":
        raise ValueError(f"Unknown AI provider: {config.ai_provider}")
    api_key = os.environ.get(config.ai_api_key_env)
    if not api_key:
        raise ValueError(f"AI enabled but {config.ai_api_key_env} is not set")
    return OpenAIResolver(config.ai_endpoint, config.ai_model, api_key)
