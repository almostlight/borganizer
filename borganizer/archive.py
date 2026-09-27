from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile, is_zipfile


@dataclass(frozen=True)
class ArchiveEntry:
    name: str
    size: int


def inspect_zip(path: Path) -> list[ArchiveEntry]:
    if not is_zipfile(path):
        raise ValueError(f"Not a readable ZIP archive: {path}")
    try:
        with ZipFile(path) as archive:
            return [ArchiveEntry(info.filename, info.file_size) for info in archive.infolist()]
    except BadZipFile as exc:
        raise ValueError(f"Not a readable ZIP archive: {path}") from exc