from __future__ import annotations

import hashlib
import re
from pathlib import Path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def clean_component(value: str, replacement: str = "_") -> str:
    value = value.strip()
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", replacement, value)
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" .")
    return value or "Unknown"


def format_series_number(number: float | None, width: int = 2) -> str | None:
    if number is None:
        return None
    if float(number).is_integer():
        return f"{int(number):0{width}d}"
    return f"{number:0{width}.2f}".rstrip("0").rstrip(".")
