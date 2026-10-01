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
    operation_mode: str = "safe"
    metadata_enabled: bool = False
    metadata_provider: str = "openlibrary"
    metadata_cache_ttl_seconds: int = 30 * 24 * 60 * 60
    ai_enabled: bool = False
    ai_provider: str = "openai"
    ai_endpoint: str = "https://api.openai.com/v1/chat/completions"
    ai_model: str = "gpt-4o-mini"
    ai_threads: int = 4
    ai_agent_host: str = "127.0.0.1"
    ai_agent_port: int = 11434
    ai_api_key_env: str = "OPENAI_API_KEY"
    config_path: Path | None = None
    video_extensions: tuple[str, ...] = ()


def load_config(path: str | Path | None = None) -> Config:
    config_path = Path(path or os.environ.get("LIBRARIAN_CONFIG", "/opt/librarian/config.yaml"))
    with config_path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    scan = data.get("scan", {})
    naming = data.get("naming", {})
    safety = data.get("safety", {})
    metadata = data.get("metadata", {})
    ai = data.get("ai", {})

    return Config(
        incoming_dir=Path(data["incoming_dir"]).expanduser().resolve(),
        library_dir=Path(data["library_dir"]).expanduser().resolve(),
        database=Path(data["database"]).expanduser().resolve(),
        audiobook_extensions=tuple(x.lower() for x in scan.get("extensions", {}).get("audiobook", [])),
        ebook_extensions=tuple(x.lower() for x in scan.get("extensions", {}).get("ebook", [])),
        video_extensions=tuple(x.lower() for x in scan.get("extensions", {}).get("video", [])),
        ignore_hidden=bool(scan.get("ignore_hidden", True)),
        min_stable_age_seconds=int(scan.get("min_stable_age_seconds", 30)),
        series_number_width=int(naming.get("series_number_width", 2)),
        invalid_replacement=str(naming.get("invalid_replacement", "_")),
        overwrite_existing=bool(safety.get("overwrite_existing", False)),
        allow_cross_device_move=bool(safety.get("allow_cross_device_move", False)),
        auto_apply_threshold=float(safety.get("auto_apply_threshold", 0.95)),
        operation_mode=str(data.get("operation_mode", "safe")).lower(),
        metadata_enabled=bool(metadata.get("enabled", False)),
        metadata_provider=str(metadata.get("provider", "openlibrary")),
        metadata_cache_ttl_seconds=int(metadata.get("cache_ttl_seconds", 30 * 24 * 60 * 60)),
        ai_enabled=bool(ai.get("enabled", False)),
        ai_provider=str(ai.get("provider", "openai")),
        ai_endpoint=str(ai.get("endpoint", "https://api.openai.com/v1/chat/completions")),
        ai_model=str(ai.get("model", "gpt-4o-mini")),
        ai_threads=int(ai.get("threads", 4)),
        ai_agent_host=str(ai.get("agent_host", "127.0.0.1")),
        ai_agent_port=int(ai.get("agent_port", 11434)),
        ai_api_key_env=str(ai.get("api_key_env", "OPENAI_API_KEY")),
        config_path=config_path,
    )


def save_runtime_settings(
    config: Config,
    *,
    incoming_dir: str,
    library_dir: str,
    operation_mode: str,
    ai_enabled: bool,
    ai_provider: str,
    ai_endpoint: str,
    ai_model: str,
    ai_threads: int,
    ai_agent_host: str = "127.0.0.1",
    ai_agent_port: int = 11434,
) -> Config:
    if operation_mode not in {"safe", "automatic"}:
        raise ValueError("operation mode must be safe or automatic")
    if ai_provider not in {"ollama", "openai"}:
        raise ValueError("AI provider must be ollama or openai")
    if not incoming_dir.strip() or not library_dir.strip() or not ai_model.strip():
        raise ValueError("directories and AI model are required")
    if not 1 <= ai_threads <= 128:
        raise ValueError("AI threads must be between 1 and 128")

    values = {
        "incoming_dir": str(Path(incoming_dir).expanduser()),
        "library_dir": str(Path(library_dir).expanduser()),
        "operation_mode": operation_mode,
        "ai": {
            "enabled": ai_enabled,
            "provider": ai_provider,
            "endpoint": ai_endpoint.strip(),
            "model": ai_model.strip(),
            "threads": ai_threads,
            "agent_host": ai_agent_host,
            "agent_port": ai_agent_port,
            "api_key_env": config.ai_api_key_env,
        },
    }
    if config.config_path:
        with config.config_path.open("r", encoding="utf-8") as stream:
            data: dict[str, Any] = yaml.safe_load(stream) or {}
        data.update({key: value for key, value in values.items() if key != "ai"})
        data["ai"] = {**data.get("ai", {}), **values["ai"]}
        temporary = config.config_path.with_suffix(config.config_path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            yaml.safe_dump(data, stream, sort_keys=False)
        temporary.replace(config.config_path)
        return load_config(config.config_path)
    from dataclasses import replace
    return replace(
        config,
        incoming_dir=Path(values["incoming_dir"]).resolve(),
        library_dir=Path(values["library_dir"]).resolve(),
        operation_mode=operation_mode,
        ai_enabled=ai_enabled,
        ai_provider=ai_provider,
        ai_endpoint=ai_endpoint.strip(),
        ai_model=ai_model.strip(),
        ai_threads=ai_threads,
        ai_agent_host=ai_agent_host,
        ai_agent_port=ai_agent_port,
    )

