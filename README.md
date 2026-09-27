# Audiobookshelf Borganizer

Safe, metadata-aware organizer for audiobook + ebook libraries.

## Design

The logical unit is a **book**. Audiobook and ebook files belonging to the same book are kept together:

```text
Author/
  Series/
    01 - Book Title/
      Book Title.m4b
      Book Title.epub
```

Standalone books omit the series directory.

The organizer extracts embedded metadata, parses filenames, hashes files, stores proposals and audit records in SQLite, and supports optional external metadata and AI resolution. Safe mode keeps an explicit review step; automatic mode applies only high-confidence proposals.

Book matching is ordered from strongest to weakest evidence: ISBN or exact identifier, normalized title and author, series and number, then fuzzy title matching. A match is classified as the same edition, a different edition, or a duplicate file. Metadata lookup and AI are reserved fallback stages and are not enabled by default.

Series positions are stored separately from their directory rendering. Numeric positions such as `0.5`, `2.5`, and `3.1` use `series_number`; named positions such as `Companion`, `Short Stories`, `Collection`, and `Box Set` use `series_position_label`. Numeric positions render as `0.5 - Title`, while named positions render as `Companion - Title`.

When enabled, the AI resolver receives only filename, embedded metadata, and candidate book names. It returns validated book metadata; Python converts that metadata into a destination path and the filesystem layer performs the move. The AI cannot issue filesystem commands. Multi-file books retain unique source track names inside the shared book directory. Ollama is supported as a local provider; OpenAI remains available when a hosted model is preferred.

## Install on Debian

The automated installer supports Debian/Ubuntu and Fedora. Run it from a
checked-out copy of this repository as root. It creates the `borganizer`
service account, installs the project in `/opt/borganizer/venv`, creates the
configured directories, and enables the ten-minute systemd timer:

```bash
sudo ./scripts/install.sh
```

The installer keeps `operation_mode: safe` and asks whether Ollama should be
installed. To install the local `qwen3:8b` profile without prompting:

```bash
sudo ./scripts/install.sh --with-ollama --yes
```

To install only the organizer and skip the Ollama offer:

```bash
sudo ./scripts/install.sh --without-ollama
```

Set media locations during installation with `--incoming` and `--library`.
The standalone Ollama step can be rerun later:

```bash
sudo ./scripts/install-ollama.sh
```

It installs Ollama using the official installer, selects a Qwen3 8B
quantization from available RAM, pulls it, and enables the Ollama provider with
four threads in `/opt/borganizer/config.yaml`. With `auto`, at least 12 GiB
available RAM selects `qwen3:8b-q8_0`; at least 6 GiB selects the default
`qwen3:8b` Q4_K_M package. You can override the choice explicitly:

```bash
sudo ./scripts/install-ollama.sh --quantization q4_k_m
sudo ./scripts/install-ollama.sh --quantization q8_0
```

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg sqlite3 git

sudo useradd --system --home /var/lib/borganizer --create-home --shell /usr/sbin/nologin borganizer || true
sudo mkdir -p /opt/borganizer /var/lib/borganizer /mnt/media/incoming /mnt/media/books
sudo chown -R borganizer:borganizer /opt/borganizer /var/lib/borganizer /mnt/media/incoming /mnt/media/books

sudo -u borganizer python3 -m venv /opt/borganizer/venv
sudo -u borganizer /opt/borganizer/venv/bin/pip install --upgrade pip
sudo -u borganizer /opt/borganizer/venv/bin/pip install /opt/borganizer
sudo cp config/config.example.yaml /opt/borganizer/config.yaml
sudo chown borganizer:borganizer /opt/borganizer/config.yaml
```

Adjust `incoming_dir`, `library_dir`, and `database` in `/opt/borganizer/config.yaml` if necessary.

## First scan

The default `operation_mode: safe` only creates proposals. Set it to `automatic` when the library is ready for unattended operation; the timer will then apply only proposals at or above `auto_apply_threshold` and leave the rest in the review queue.

Use the service account for all operations:

```bash
sudo -u borganizer BORGANIZER_CONFIG=/opt/borganizer/config.yaml \
  /opt/borganizer/venv/bin/borganizer scan
```

For a one-shot run using the configured mode:

```bash
sudo -u borganizer BORGANIZER_CONFIG=/opt/borganizer/config.yaml \
  /opt/borganizer/venv/bin/borganizer run
```

Then inspect proposals:

```bash
sudo -u borganizer BORGANIZER_CONFIG=/opt/borganizer/config.yaml \
  /opt/borganizer/venv/bin/borganizer review
```

Nothing has moved yet.

## Local web UI

Start the local review dashboard with:

```bash
sudo -u borganizer BORGANIZER_CONFIG=/opt/borganizer/config.yaml \
  /opt/borganizer/venv/bin/borganizer web
```

Open http://127.0.0.1:8765 in a browser. The interface is bound to localhost by default and supports reviewing, approving, rejecting, and undoing audited batches. Use `--port` to select another local port.

Review output labels each proposal `MOVE`, `REVIEW`, or `IGNORE`. Approve selected proposals or all proposals at or above the configured confidence threshold:

```bash
sudo -u borganizer BORGANIZER_CONFIG=/opt/borganizer/config.yaml \
  /opt/borganizer/venv/bin/borganizer approve 12 13

sudo -u borganizer BORGANIZER_CONFIG=/opt/borganizer/config.yaml \
  /opt/borganizer/venv/bin/borganizer approve-all-high-confidence
```

Apply approved proposals by ID:

```bash
sudo -u borganizer BORGANIZER_CONFIG=/opt/borganizer/config.yaml \
  /opt/borganizer/venv/bin/borganizer apply 12 13 14
```

Or apply all high-confidence proposals:

```bash
sudo -u borganizer BORGANIZER_CONFIG=/opt/borganizer/config.yaml \
  /opt/borganizer/venv/bin/borganizer apply --auto
```

Undo the most recent batch:

```bash
sudo -u borganizer BORGANIZER_CONFIG=/opt/borganizer/config.yaml \
  /opt/borganizer/venv/bin/borganizer undo

# Or reverse a specific recorded batch:
sudo -u borganizer BORGANIZER_CONFIG=/opt/borganizer/config.yaml \
  /opt/borganizer/venv/bin/borganizer undo BATCH_ID
```

Each move is recorded before filesystem changes begin and completed only after the destination hash is verified. The audit record includes the source and destination paths, hash, proposal ID, reason, confidence, timestamps, batch ID, and operation state. Existing destinations are never overwritten; cross-filesystem moves use a temporary destination and checksum verification.

Messy audiobook components are grouped using their containing book directory or conservative track/part/CD markers. Their original component names are preserved inside the one audiobook destination. ZIP files are never extracted automatically; inspect one safely with:

```bash
borganizer inspect Book.zip
```

## Configuration

The complete example is in `config/config.example.yaml`. The important controls are:

```yaml
operation_mode: safe       # safe or automatic

safety:
  auto_apply_threshold: 0.95

metadata:
  enabled: false           # Open Library, cached in SQLite
  provider: openlibrary

ai:
  enabled: false
  provider: ollama
  endpoint: http://127.0.0.1:11434/api/chat
  model: qwen3:8b
  threads: 4
```

Keep `operation_mode: safe` until review output is understood. In `automatic` mode, only pending proposals at or above `auto_apply_threshold` are moved; everything else remains available to `review`.

### Ollama

Install and start Ollama, then download a model:

```bash
ollama serve
ollama pull qwen3:8b
```

Enable it in the configuration above. Borganizer sends requests to Ollama on `127.0.0.1:11434` using four CPU threads and does not require an API key. The Ollama `qwen3:8b` package uses the Q4_K_M quantization requested here.

### OpenAI key

The key is read from the environment variable named by `ai.api_key_env`; it is not stored in YAML or SQLite:

```bash
export OPENAI_API_KEY="your-key"
borganizer run
```

For systemd, use an environment file instead of putting the key in the configuration file:

```ini
# /etc/borganizer/openai.env
OPENAI_API_KEY=your-key
```

Add `EnvironmentFile=/etc/borganizer/openai.env` to `systemd/borganizer.service` and protect the file with `chmod 600`.

## Testing

Install the optional test dependencies and run the suite:

```bash
python3 -m pip install -e '.[test]'
python3 -m pytest
```

## systemd

Copy the units into `/etc/systemd/system/`, review the configuration, and enable the timer when ready:

```bash
sudo cp systemd/borganizer.service systemd/borganizer.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now borganizer.timer
```

The timer invokes `borganizer run` every ten minutes. Safe mode creates proposals only; automatic mode also applies high-confidence proposals. Every operation is audited and can be reversed with `borganizer undo BATCH_ID`.
