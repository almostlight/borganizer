from __future__ import annotations

import re
from pathlib import Path

from ebooklib import epub
from mutagen import File as MutagenFile

from .models import BookMetadata

AUDIO_EXTS = {".mp3", ".m4a", ".m4b", ".flac", ".ogg", ".opus"}
EBOOK_EXTS = {".epub", ".pdf", ".azw3", ".mobi"}
VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm"}

VIDEO_RELEASE_TAGS_PATTERN = r"[._ -]+(?:1080p|720p|2160p|4k|hdtv|web-?dl|bluray|brrip|dvdrip|x264|x265|hevc|aac|xvid|repack|proper|remux|hdr)"


def _first(value):
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else None
    return str(value) if value is not None else None


SERIES_POSITION_PATTERN = r"\d+(?:\.\d+)?|companion|short stories|collection|box set"


def _series_position(value: str | None) -> tuple[float | None, str | None]:
    if not value:
        return None, None
    cleaned = re.sub(r"^(?:vol(?:ume)?|book|part|pt|v|#)\.?\s*", "", value.strip(), flags=re.IGNORECASE)
    if re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
        return float(cleaned), None
    if re.fullmatch(r"\d+(?:\.\d+)?", value.strip()):
        return float(value.strip()), None
    return None, value.strip().title()


def _parse_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\b(19|20)\d{2}\b", str(value))
    return int(match.group(0)) if match else None


def _clean_isbn(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^\dX]", "", raw.upper())
    if len(cleaned) in (10, 13):
        return cleaned
    match = re.search(r"\b(97[89]\d{10}|\d{9}[\dX])\b", cleaned)
    return match.group(0) if match else None


def parse_filename(path: Path) -> BookMetadata:
    name = re.sub(r"[_]+", " ", path.stem)
    name = re.sub(r"\s+(?:unabridged|abridged|unrated|complete|dramatized)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[._ -]+(?:part|track|cd|disc|disk)\s*\d+$", "", name, flags=re.IGNORECASE)

    media_type = "audiobook" if path.suffix.lower() in AUDIO_EXTS else "ebook"
    if path.suffix.lower() in VIDEO_EXTS:
        media_type = "video"
    result = BookMetadata(media_type=media_type, source="filename")

    # ISBN in filename check
    found_isbn = _clean_isbn(name)
    if found_isbn:
        result.isbn = found_isbn

    # Video S01E02 or 1x02
    clean_video_name = re.sub(VIDEO_RELEASE_TAGS_PATTERN, " ", name, flags=re.IGNORECASE).strip()
    clean_video_name = re.sub(r"[._]+", " ", clean_video_name)
    episode = re.match(
        r"^(?P<show>.+?)\s*[._ -]+(?:S(?P<season>\d{1,2})E(?P<episode>\d{1,3})|(?P<season2>\d{1,2})x(?P<episode2>\d{1,3}))(?:\s*[._ -]+(?P<title>.+))?$",
        clean_video_name,
        re.IGNORECASE,
    )
    if episode:
        result.series = episode.group("show").strip()
        season = episode.group("season") or episode.group("season2")
        ep = episode.group("episode") or episode.group("episode2")
        result.season_number = int(season)
        result.episode_number = int(ep)
        result.title = episode.group("title") or f"Episode {result.episode_number:02d}"
        return result

    movie = re.match(r"^(?P<title>.+?)\s*[\(\.]?(?P<year>(?:19|20)\d{2})[\)\.]?$", clean_video_name)
    if movie and media_type == "video":
        result.title = movie.group("title").strip()
        result.year = int(movie.group("year"))
        return result

    patterns = [
        rf"^(?P<series>.+?)\s*[-–—#]\s*(?:vol(?:ume)?|book|part|v|#)?\s*(?P<position>{SERIES_POSITION_PATTERN})\s*[-–—]\s*(?P<title>.+)$",
        rf"^(?P<series>.+?)\s+(?:vol(?:ume)?|book|part|v|#)\s*(?P<position>{SERIES_POSITION_PATTERN})\s*[-–—]\s*(?P<title>.+)$",
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

    result.title = clean_video_name if media_type == "video" else name
    return result


def _extract_pdf_metadata(path: Path) -> BookMetadata | None:
    try:
        with path.open("rb") as f:
            header = f.read(10000)
            f.seek(-10000, 2) if path.stat().st_size > 10000 else f.seek(0)
            trailer = f.read(10000)
        content = (header + trailer).decode("latin-1", errors="ignore")

        title_m = re.search(r"/Title\s*\((.*?)\)", content)
        author_m = re.search(r"/Author\s*\((.*?)\)", content)

        title = title_m.group(1).strip() if title_m else None
        author = author_m.group(1).strip() if author_m else None

        if title and not title.startswith("Untitled") and not title.endswith(".pdf"):
            isbn = _clean_isbn(content)
            return BookMetadata(title=title, author=author, isbn=isbn, media_type="ebook", source="pdf")
    except Exception:
        pass
    return None


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
                cleaned = _clean_isbn(value)
                if cleaned:
                    isbn = cleaned
                    break

            publisher = _first(book.get_metadata("DC", "publisher"))
            language = _first(book.get_metadata("DC", "language"))
            date_raw = _first(book.get_metadata("DC", "date"))
            publication_year = _parse_year(date_raw)

            series = None
            series_number = None

            # Calibre and EPUB3 metadata extraction for series
            meta_items = book.get_metadata("OPF", "meta") or book.get_metadata("DC", "meta")
            for item in meta_items:
                if isinstance(item, tuple) and len(item) > 1:
                    opts = item[1] if isinstance(item[1], dict) else {}
                    if opts.get("name") == "calibre:series":
                        series = opts.get("content")
                    elif opts.get("name") == "calibre:series_index":
                        try:
                            series_number = float(opts.get("content"))
                        except (ValueError, TypeError):
                            pass

            return BookMetadata(
                title=title,
                author=author,
                series=series,
                series_number=series_number,
                isbn=isbn,
                publisher=publisher,
                publication_year=publication_year,
                language=language,
                media_type="ebook",
                source="epub",
            )
        except Exception as exc:
            parsed = parse_filename(path)
            parsed.media_type = media_type
            parsed.source = f"filename_after_epub_error:{exc.__class__.__name__}"
            return parsed

    if media_type == "ebook" and path.suffix.lower() == ".pdf":
        pdf_meta = _extract_pdf_metadata(path)
        if pdf_meta and pdf_meta.title:
            return pdf_meta

    if media_type == "audiobook":
        try:
            audio = MutagenFile(str(path), easy=True)
            if audio is not None:
                tags = audio.tags or {}
                title = _first(tags.get("title"))
                artist = _first(tags.get("artist") or tags.get("albumartist"))
                album = _first(tags.get("album"))
                narrator = _first(tags.get("composer") or tags.get("writer") or tags.get("performer"))
                date_raw = _first(tags.get("date") or tags.get("year"))
                publication_year = _parse_year(date_raw)
                isbn = _clean_isbn(_first(tags.get("isbn") or tags.get("asin")))
                series = _first(tags.get("series") or tags.get("grouping") or tags.get("movementname"))
                series_num_raw = _first(tags.get("series-part") or tags.get("movementnumber"))
                series_number = float(series_num_raw) if series_num_raw and re.fullmatch(r"\d+(?:\.\d+)?", series_num_raw) else None

                return BookMetadata(
                    title=title or album,
                    author=artist,
                    series=series,
                    series_number=series_number,
                    narrator=narrator,
                    publisher=_first(tags.get("publisher")),
                    language=_first(tags.get("language")),
                    publication_year=publication_year,
                    isbn=isbn,
                    media_type="audiobook",
                    source="mutagen",
                )
        except Exception:
            pass

    if media_type == "video":
        try:
            audio = MutagenFile(str(path))
            if audio is not None and hasattr(audio, "tags") and audio.tags:
                tags = audio.tags
                title = _first(tags.get("\xa9nam") or tags.get("title"))
                show = _first(tags.get("tvsh") or tags.get("show"))
                season = tags.get("tvsn") or tags.get("season")
                episode = tags.get("tves") or tags.get("episode")
                year = _parse_year(_first(tags.get("\xa9day") or tags.get("year") or tags.get("date")))

                season_num = int(season[0]) if isinstance(season, (list, tuple)) and season else (int(season) if isinstance(season, (int, str)) and str(season).isdigit() else None)
                episode_num = int(episode[0]) if isinstance(episode, (list, tuple)) and episode else (int(episode) if isinstance(episode, (int, str)) and str(episode).isdigit() else None)

                if title or show:
                    return BookMetadata(
                        title=title,
                        series=show,
                        season_number=season_num,
                        episode_number=episode_num,
                        year=year,
                        media_type="video",
                        source="mutagen_video",
                    )
        except Exception:
            pass

    parsed = parse_filename(path)
    parsed.media_type = media_type
    return parsed
