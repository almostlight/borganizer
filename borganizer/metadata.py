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


SERIES_POSITION_PATTERN = r"\d+(?:\.\d+)?|companion|short stories|collection|box set"


def _series_position(value: str | None) -> tuple[float | None, str | None]:
    if not value:
        return None, None
    if re.fullmatch(r"\d+(?:\.\d+)?", value.strip()):
        return float(value), None
    return None, value.strip().title()


def parse_filename(path: Path) -> BookMetadata:
    name = re.sub(r"[_]+", " ", path.stem)
    name = re.sub(r"\s+(?:unabridged|abridged|unrated|complete|dramatized)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[._ -]+(?:part|track|cd|disc|disk)\s*\d+$", "", name, flags=re.IGNORECASE)
    # Conservative parsing of common series markers: "Series 01", "Series #1", "01 - Title".
    result = BookMetadata(media_type="audiobook" if path.suffix.lower() in AUDIO_EXTS else "ebook", source="filename")

    patterns = [
        rf"^(?P<series>.+?)\s*[-–—#]\s*(?P<position>{SERIES_POSITION_PATTERN})\s*[-–—]\s*(?P<title>.+)$",
        rf"^(?P<series>.+?)\s+(?P<position>{SERIES_POSITION_PATTERN})\s*[-–—]\s*(?P<title>.+)$",
        rf"^(?P<position>\d+(?:\.\d+)?)\s*[-–—]\s*(?P<title>.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, name, flags=re.IGNORECASE)
        if match:
            result.series = match.groupdict().get("series")
            result.series_number, result.series_position_label = _series_position(match.groupdict().get("position"))
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
            isbn = next((value for value, _ in identifiers if re.search(r"(?:ISBN|isbn)", value)), None)
            publisher = _first(book.get_metadata("DC", "publisher"))
            language = _first(book.get_metadata("DC", "language"))
            return BookMetadata(title=title, author=author, isbn=isbn, publisher=publisher, language=language, media_type="ebook", source="epub")
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
                    publisher=_first(tags.get("publisher")),
                    language=_first(tags.get("language")),
                    media_type="audiobook",
                    source="mutagen",
                )
        except Exception:
            pass

    parsed = parse_filename(path)
    parsed.media_type = media_type
    return parsed
