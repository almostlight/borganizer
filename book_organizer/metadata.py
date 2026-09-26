from __future__ import annotations

import re
from pathlib import Path

from ebooklib import epub
from mutagen import File as MutagenFile

from .models import BookMetadata

AUDIO_EXTS = {".mp3", ".m4a", ".m4b", ".flac", ".ogg", ".opus"}
EBOOK_EXTS = {".epub", ".pdf", ".azw3", ".mobi"}


def _first(value):
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else None
    return str(value) if value is not None else None


def _series_number(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group()) if match else None


def parse_filename(path: Path) -> BookMetadata:
    name = path.stem
    # Conservative parsing of common series markers: "Series 01", "Series #1", "01 - Title".
    result = BookMetadata(media_type="audiobook" if path.suffix.lower() in AUDIO_EXTS else "ebook", source="filename")

    patterns = [
        r"^(?P<series>.+?)\s*[-–—#]\s*(?P<number>\d+(?:\.\d+)?)\s*[-–—]\s*(?P<title>.+)$",
        r"^(?P<series>.+?)\s+(?P<number>\d+(?:\.\d+)?)\s*[-–—]\s*(?P<title>.+)$",
        r"^(?P<number>\d+(?:\.\d+)?)\s*[-–—]\s*(?P<title>.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, name)
        if match:
            result.series = match.groupdict().get("series")
            result.series_number = _series_number(match.groupdict().get("number"))
            result.title = match.groupdict().get("title")
            return result

    # Common "Author - Title" form.
    if " - " in name:
        left, right = name.split(" - ", 1)
        if 1 <= len(left.split()) <= 6:
            result.author = left.strip()
            result.title = right.strip()
            return result

    result.title = name
    return result


def extract_metadata(path: Path, media_type: str) -> BookMetadata:
    if media_type == "ebook" and path.suffix.lower() == ".epub":
        try:
            book = epub.read_epub(str(path), options={"ignore_ncx": True})
            title = _first(book.get_metadata("DC", "title"))
            authors = book.get_metadata("DC", "creator")
            author = _first(authors)
            identifiers = book.get_metadata("DC", "identifier")
            isbn = None
            for value, _ in identifiers:
                if re.search(r"(?:ISBN|isbn)", value):
                    digits = re.sub(r"[^0-9Xx]", "", value)
                    if digits:
                        isbn = digits
                        break
            return BookMetadata(title=title, author=author, isbn=isbn, media_type="ebook", source="epub")
        except Exception as exc:
            parsed = parse_filename(path)
            parsed.media_type = media_type
            parsed.source = f"filename_after_epub_error:{exc.__class__.__name__}"
            return parsed

    if media_type == "audiobook":
        try:
            audio = MutagenFile(str(path), easy=True)
            if audio is not None:
                tags = audio.tags or {}
                title = _first(tags.get("title"))
                artist = _first(tags.get("artist") or tags.get("albumartist"))
                album = _first(tags.get("album"))
                narrator = _first(tags.get("composer"))
                return BookMetadata(
                    title=title or album,
                    author=artist,
                    narrator=narrator,
                    media_type="audiobook",
                    source="mutagen",
                )
        except Exception:
            pass

    parsed = parse_filename(path)
    parsed.media_type = media_type
    return parsed
