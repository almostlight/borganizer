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
    author: str
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


def _resolution(value: Any) -> AIResolution:
    if not isinstance(value, dict):
        raise ValueError("AI response must be an object")
    book = value.get("book")
    author = value.get("author")
    confidence = value.get("confidence")
    if not isinstance(book, str) or not book.strip() or not isinstance(author, str) or not author.strip():
        raise ValueError("AI response requires book and author strings")
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("AI confidence must be between 0 and 1")
    series_number = value.get("series_number")
    if series_number is not None and not isinstance(series_number, (int, float)):
        raise ValueError("AI series_number must be numeric")
    return AIResolution(book.strip(), author.strip(), value.get("series"), float(series_number) if series_number is not None else None, float(confidence))


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


def build_ai_resolver(config) -> AIResolver | None:
    if not config.ai_enabled:
        return None
    if config.ai_provider != "openai":
        raise ValueError(f"Unknown AI provider: {config.ai_provider}")
    api_key = os.environ.get(config.ai_api_key_env)
    if not api_key:
        raise ValueError(f"AI enabled but {config.ai_api_key_env} is not set")
    return OpenAIResolver(config.ai_endpoint, config.ai_model, api_key)
