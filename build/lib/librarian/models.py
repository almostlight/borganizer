from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class BookMetadata:
    title: str | None = None
    author: str | None = None
    series: str | None = None
    series_number: float | None = None
    series_position_label: str | None = None
    narrator: str | None = None
    publisher: str | None = None
    language: str | None = None
    isbn: str | None = None
    publication_year: int | None = None
    season_number: int | None = None
    episode_number: int | None = None
    year: int | None = None
    cover_url: str | None = None
    media_type: str | None = None
    source: str | None = None


@dataclass
class FileCandidate:
    path: Path
    media_type: str
    sha256: str
    metadata: BookMetadata
    confidence: float
    notes: list[str]
    component_group: str | None = None


@dataclass
class Proposal:
    id: int | None
    source_path: Path
    destination_path: Path
    sha256: str
    confidence: float
    media_type: str
    title: str | None
    author: str | None
    series: str | None
    series_number: float | None
    status: str = "pending"
    reason: str = ""
    series_position_label: str | None = None
    match_kind: str | None = None
    match_method: str | None = None
    matched_path: Path | None = None
