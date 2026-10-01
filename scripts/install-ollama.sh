#!/usr/bin/env bash
set -Eeuo pipefail

MODEL="${LIBRARIAN_OLLAMA_MODEL:-qwen3:8b}"
QUANTIZATION="${LIBRARIAN_OLLAMA_QUANTIZATION:-auto}"
CONFIG_PATH="${LIBRARIAN_CONFIG:-/opt/librarian/config.yaml}"
SERVICE_USER="${LIBRARIAN_USER:-librarian}"
DRY_RUN=no

usage() {
    cat <<'EOF'
Usage: sudo ./scripts/install-ollama.sh [options]

Install Ollama, choose a Qwen3 8B quantization from available RAM, and enable it in librarian's YAML config.

Options:
  --config PATH        Librarian config (default: /opt/librarian/config.yaml)
  --service-user USER  Librarian service account (default: librarian)
  --model NAME         Ollama model (default: qwen3:8b)
    --quantization MODE   auto, q4_k_m, or q8_0 (default: auto)
    --dry-run             Show the selection without installing or downloading
    -h, --help            Show this help
EOF
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --config) (($# >= 2)) || die "--config requires a path"; CONFIG_PATH=$2; shift 2 ;;
        --service-user) (($# >= 2)) || die "--service-user requires a user"; SERVICE_USER=$2; shift 2 ;;
        --model) (($# >= 2)) || die "--model requires a model"; MODEL=$2; shift 2 ;;
        --quantization) (($# >= 2)) || die "--quantization requires auto, q4_k_m, or q8_0"; QUANTIZATION=${2,,}; shift 2 ;;
        --dry-run) DRY_RUN=yes; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

if [[ "$DRY_RUN" != yes ]]; then
    [[ $EUID -eq 0 ]] || die "run this script as root, for example: sudo $0"
    command -v curl >/dev/null || die "curl is required to install Ollama"
    command -v systemctl >/dev/null || die "systemd/systemctl is required"
fi

select_quantization() {
    [[ "$MODEL" == "qwen3:8b" ]] || {
        [[ "$QUANTIZATION" == auto ]] || die "--quantization currently supports the default qwen3:8b model only"
        printf 'Using explicitly selected model %s; quantization selection is unavailable for custom models.\n' "$MODEL"
        return
    }
    case "$QUANTIZATION" in
        q4_k_m) MODEL="qwen3:8b" ;;
        q8_0) MODEL="qwen3:8b-q8_0" ;;
        auto)
            local available_mib
            available_mib=$(awk '/^MemAvailable:/ {print int($2 / 1024); exit}' /proc/meminfo)
            [[ -n "$available_mib" ]] || die "cannot determine available system memory"
            if ((available_mib >= 12288)); then
                QUANTIZATION=q8_0
                MODEL="qwen3:8b-q8_0"
            elif ((available_mib >= 6144)); then
                QUANTIZATION=q4_k_m
                MODEL="qwen3:8b"
            else
                die "only ${available_mib} MiB RAM is available; qwen3:8b needs at least 6144 MiB for Q4_K_M"
            fi
            printf 'Selected %s from %s MiB available RAM.\n' "$QUANTIZATION" "$available_mib"
            ;;
        *) die "quantization must be auto, q4_k_m, or q8_0" ;;
    esac
}

select_quantization

if [[ "$DRY_RUN" == yes ]]; then
    printf 'Dry run: would pull %s (%s) using 4 threads.\n' "$MODEL" "$QUANTIZATION"
    exit 0
fi

if ! command -v ollama >/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
fi

systemctl enable --now ollama 2>/dev/null || true
if ! curl --fail --silent --max-time 5 http://127.0.0.1:11434/api/tags >/dev/null; then
    printf 'Ollama is installed but its service is not reachable. Start it with: systemctl start ollama\n' >&2
    exit 1
fi

ollama pull "$MODEL"

CONFIG_DIR=$(dirname -- "$CONFIG_PATH")
CONFIG_PYTHON="$CONFIG_DIR/venv/bin/python"
[[ -x "$CONFIG_PYTHON" ]] || CONFIG_PYTHON=python3
OLLAMA_CONFIG="$CONFIG_PATH" OLLAMA_MODEL="$MODEL" OLLAMA_QUANTIZATION="$QUANTIZATION" "$CONFIG_PYTHON" - <<'PY'
from pathlib import Path
import os
import yaml

path = Path(os.environ["OLLAMA_CONFIG"])
with path.open("r", encoding="utf-8") as stream:
    data = yaml.safe_load(stream) or {}
ai = data.setdefault("ai", {})
ai.update({
    "enabled": True,
    "provider": "ollama",
    "endpoint": "http://127.0.0.1:11434/api/chat",
    "model": os.environ["OLLAMA_MODEL"],
    "quantization": os.environ["OLLAMA_QUANTIZATION"],
    "threads": 4,
})
with path.open("w", encoding="utf-8") as stream:
    yaml.safe_dump(data, stream, sort_keys=False)
PY
chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_PATH"
chmod 0640 "$CONFIG_PATH"
systemctl restart librarian.timer 2>/dev/null || true
printf 'Ollama is ready with %s (%s); librarian AI is enabled with 4 threads.\n' "$MODEL" "$QUANTIZATION"