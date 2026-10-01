#!/usr/bin/env bash
set -Eeuo pipefail

APP_ROOT="${LIBRARIAN_APP_ROOT:-/opt/librarian}"
STATE_ROOT="${LIBRARIAN_STATE_ROOT:-/var/lib/librarian}"
SERVICE_USER="${LIBRARIAN_USER:-librarian}"
INCOMING_DIR="${LIBRARIAN_INCOMING_DIR:-/mnt/media/incoming}"
LIBRARY_DIR="${LIBRARIAN_LIBRARY_DIR:-/mnt/media/books}"
CONFIG_PATH="${LIBRARIAN_CONFIG:-$APP_ROOT/config.yaml}"
WITH_OLLAMA="${LIBRARIAN_WITH_OLLAMA:-auto}"

usage() {
    cat <<'EOF'
Usage: sudo ./scripts/install.sh [options]

Install librarian and its systemd timer on Debian or Fedora.

Options:
  --incoming DIR    Incoming media directory (default: /mnt/media/incoming)
  --library DIR     Organized library directory (default: /mnt/media/books)
  --with-ollama     Install Ollama and pull qwen3:8b after librarian setup
  --without-ollama  Skip the Ollama offer
  --yes              Accept the Ollama offer without prompting
  -h, --help         Show this help

Environment overrides: LIBRARIAN_APP_ROOT, LIBRARIAN_STATE_ROOT,
LIBRARIAN_USER, LIBRARIAN_CONFIG, LIBRARIAN_INCOMING_DIR,
LIBRARIAN_LIBRARY_DIR, LIBRARIAN_WITH_OLLAMA.
EOF
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

while (($#)); do
    case "$1" in
        --incoming) (($# >= 2)) || die "--incoming requires a directory"; INCOMING_DIR=$2; shift 2 ;;
        --library) (($# >= 2)) || die "--library requires a directory"; LIBRARY_DIR=$2; shift 2 ;;
        --with-ollama) WITH_OLLAMA=yes; shift ;;
        --without-ollama) WITH_OLLAMA=no; shift ;;
        --yes) WITH_OLLAMA=yes; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1" ;;
    esac
done

[[ $EUID -eq 0 ]] || die "run this script as root, for example: sudo $0"

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
command -v systemctl >/dev/null || die "systemd/systemctl is required"

install_packages() {
    if command -v apt-get >/dev/null; then
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y \
            python3 python3-venv python3-pip python3-dev build-essential sqlite3 curl
    elif command -v dnf >/dev/null; then
        dnf install -y python3 python3-pip python3-devel gcc sqlite curl
    else
        die "unsupported distribution: install.sh supports Debian/Ubuntu and Fedora"
    fi
}

create_service_user() {
    if ! id "$SERVICE_USER" >/dev/null 2>&1; then
        useradd --system --home-dir "$STATE_ROOT" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    fi
}

install_application() {
    install -d -m 0755 "$APP_ROOT" "$STATE_ROOT" "$INCOMING_DIR" "$LIBRARY_DIR"
    cp -a "$SOURCE_ROOT/librarian" "$SOURCE_ROOT/pyproject.toml" "$APP_ROOT/"
    cp "$SOURCE_ROOT/config/config.example.yaml" "$APP_ROOT/config.example.yaml"

    python3 -m venv "$APP_ROOT/venv"
    "$APP_ROOT/venv/bin/python" -m pip install --upgrade pip
    "$APP_ROOT/venv/bin/pip" install "$APP_ROOT"

    if [[ ! -f "$CONFIG_PATH" ]]; then
        cp "$APP_ROOT/config.example.yaml" "$CONFIG_PATH"
    fi
    "$APP_ROOT/venv/bin/python" - "$CONFIG_PATH" "$INCOMING_DIR" "$LIBRARY_DIR" "$STATE_ROOT" <<'PY'
from pathlib import Path
import sys
import yaml

config_path, incoming, library, state = sys.argv[1:]
with Path(config_path).open("r", encoding="utf-8") as stream:
    data = yaml.safe_load(stream) or {}
data["incoming_dir"] = incoming
data["library_dir"] = library
data["database"] = str(Path(state) / "library.db")
data.setdefault("operation_mode", "safe")
data.setdefault("ai", {})
data["ai"].setdefault("provider", "ollama")
data["ai"].setdefault("endpoint", "http://127.0.0.1:11434/api/chat")
data["ai"].setdefault("model", "qwen3:8b")
data["ai"].setdefault("threads", 4)
with Path(config_path).open("w", encoding="utf-8") as stream:
    yaml.safe_dump(data, stream, sort_keys=False)
PY
    chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_ROOT" "$STATE_ROOT" "$INCOMING_DIR" "$LIBRARY_DIR"
    chmod 0750 "$APP_ROOT" "$STATE_ROOT"
    chmod 0640 "$CONFIG_PATH"
}

install_systemd_units() {
    install -m 0644 "$SOURCE_ROOT/systemd/librarian.service" /etc/systemd/system/librarian.service
    install -m 0644 "$SOURCE_ROOT/systemd/librarian.timer" /etc/systemd/system/librarian.timer
    systemctl daemon-reload
    systemctl enable --now librarian.timer
}

install_packages
create_service_user
install_application
install_systemd_units

printf '\nLibrarian installed.\n'
printf 'Config: %s\n' "$CONFIG_PATH"
printf 'Timer:  systemctl status librarian.timer\n'
printf 'Logs:   journalctl -u librarian.service\n'

if [[ "$WITH_OLLAMA" == auto ]]; then
    read -r -p "Install Ollama and pull qwen3:8b now? [y/N] " answer || answer=n
    [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]] && WITH_OLLAMA=yes || WITH_OLLAMA=no
fi

if [[ "$WITH_OLLAMA" == yes ]]; then
    "$SCRIPT_DIR/install-ollama.sh" --config "$CONFIG_PATH" --service-user "$SERVICE_USER"
fi