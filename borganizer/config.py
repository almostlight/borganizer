from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Config:
    incoming_dir: Path
    library_dir: Path
    database: Path
    audiobook_extensions: tuple[str, ...]
    ebook_extensions: tuple[str, ...]
    ignore_hidden: bool
    min_stable_age_seconds: int
    series_number_width: int
    invalid_replacement: str
    overwrite_existing: bool
    allow_cross_device_move: bool
    auto_apply_threshold: float


def load_config(path: str | Path | None = None) -> Config:
    config_path = Path(path or os.environ.get("BORGANIZER_CONFIG", "/opt/borganizer/config.yaml"))
    with config_path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    scan = data.get("scan", {})
    naming = data.get("naming", {})
    safety = data.get("safety", {})

    return Config(
        incoming_dir=Path(data["incoming_dir"]).expanduser().resolve(),
        library_dir=Path(data["library_dir"]).expanduser().resolve(),
        database=Path(data["database"]).expanduser().resolve(),
        audiobook_extensions=tuple(x.lower() for x in scan.get("extensions", {}).get("audiobook", [])),
        ebook_extensions=tuple(x.lower() for x in scan.get("extensions", {}).get("ebook", [])),
        ignore_hidden=bool(scan.get("ignore_hidden", True)),
        min_stable_age_seconds=int(scan.get("min_stable_age_seconds", 30)),
        series_number_width=int(naming.get("series_number_width", 2)),
        invalid_replacement=str(naming.get("invalid_replacement", "_")),
        overwrite_existing=bool(safety.get("overwrite_existing", False)),
        allow_cross_device_move=bool(safety.get("allow_cross_device_move", False)),
        auto_apply_threshold=float(safety.get("auto_apply_threshold", 0.95)),
    )
