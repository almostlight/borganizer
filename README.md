# Librarian

Safe, metadata-aware organizer for audiobook, ebook, and Jellyfin video libraries.

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

Video files use Jellyfin-friendly paths and are sorted by media type:

```text
Movies/
  Arrival (2016)/
    Arrival (2016).mkv
TV Shows/
  The Expanse/
    Season 01/
      The Expanse - S01E03 - Remember the Cant.mkv
```

The sorting rules are:

- `.mkv`, `.mp4`, `.m4v`, `.avi`, `.mov`, and `.webm` are recognized as video.
- A movie filename ending in `(YYYY)` is sorted into `Movies/Title (YYYY)/`.
- A filename containing `S01E03` is treated as a TV episode and sorted into
  `TV Shows/Series Name/Season 01/`.
- TV episode names are normalized to
  `Series Name - S01E03 - Episode Title.ext`.
- The original extension is preserved in lowercase.
- Files without a recognized episode marker are treated as movies. If no year
  is present, the movie folder uses the title alone.
- Sorting is proposal-based in safe mode. No video is moved until it is
  approved, and existing destinations are never overwritten.

Recommended input names are:

```text
Arrival (2016).mkv
The Expanse - S01E03 - Remember the Cant.mkv
```

Jellyfin should be pointed at the resulting `Movies` and `TV Shows` folders.

## Installation

The automated installer supports Debian/Ubuntu and Fedora. Run it from a
checked-out copy of this repository as root. It creates the `librarian`
service account, installs the project in `/opt/librarian/venv`, creates the
configured directories, and enables the daily systemd timer scheduled for
04:00 local time:

```bash
sudo ./scripts/install.sh
```

The installer also creates `/usr/local/bin/librarian`, adds the invoking user
to the `librarian` group, and configures the default paths. After installation,
start a new login session so the group membership is active. From then on, the
normal interface is simply:

```bash
librarian status
librarian review
librarian run
```

The service account is used by systemd; normal operator commands use the
installed `librarian` executable from `PATH`.

See the complete command reference at any time:

```bash
librarian --help
librarian review --help
librarian --version
```

Output is colored automatically in an interactive terminal. Disable ANSI
colors for logs or scripts with either `--no-color` or the `NO_COLOR`
environment variable.

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
all logical CPU cores in `/opt/librarian/config.yaml`. With `auto`, at least 12 GiB
available RAM selects `qwen3:8b-q8_0`; at least 6 GiB selects the default
`qwen3:8b` Q4_K_M package. You can override the choice explicitly:

```bash
sudo ./scripts/install-ollama.sh --quantization q4_k_m
sudo ./scripts/install-ollama.sh --quantization q8_0
```

### Manual Debian installation

The script above is recommended. If you need to install manually on Debian or
Ubuntu, use:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg sqlite3 git

sudo useradd --system --home /var/lib/librarian --create-home --shell /usr/sbin/nologin librarian || true
sudo mkdir -p /opt/librarian /var/lib/librarian /mnt/media/incoming /mnt/media/books
sudo chown -R librarian:librarian /opt/librarian /var/lib/librarian /mnt/media/incoming /mnt/media/books

sudo -u librarian python3 -m venv /opt/librarian/venv
sudo -u librarian /opt/librarian/venv/bin/pip install --upgrade pip
sudo -u librarian /opt/librarian/venv/bin/pip install /opt/librarian
sudo cp config/config.example.yaml /opt/librarian/config.yaml
sudo chown librarian:librarian /opt/librarian/config.yaml
```

Adjust `incoming_dir`, `library_dir`, and `database` in `/opt/librarian/config.yaml` if necessary.

For Fedora, install `python3`, `python3-pip`, `python3-devel`, `gcc`, `sqlite`,
and `curl` with `dnf`, then use the automated installer to create the service
account, virtual environment, permissions, and systemd units.

## First scan

The default `operation_mode: safe` only creates proposals. Set it to `automatic` when the library is ready for unattended operation; the timer will then apply only proposals at or above `auto_apply_threshold` and leave the rest in the review queue.

Use the installed command for all operations:

```bash
librarian scan
```

For a one-shot run using the configured mode:

```bash
librarian run
```

Then inspect proposals:

```bash
librarian review
```

Nothing has moved yet.

## Usage guide

### 1. Check configuration

Before the first run, confirm the three paths in the active configuration:

```bash
librarian status
```

The service account must be able to read the incoming directory and write the
database and library directory. Keep the incoming and library directories
separate. For a home-directory library, grant the `librarian` account a
targeted ACL rather than making the whole home directory public.

### 2. Scan safely

`scan` creates proposals and prints them without moving files:

```bash
librarian scan
```

`run` scans and then follows `operation_mode`. With the default `safe` mode it
only queues proposals:

```bash
librarian run
```

Each proposal includes confidence, source and destination paths, matching
evidence, AI/metadata notes, and the per-item processing time.

### 3. Review proposals

Review from the terminal:

```bash
librarian review
```

Or start the localhost dashboard:

```bash
librarian web --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765>. The dashboard supports individual and bulk
approval/rejection, a select-all control, scan progress with the current file,
stopping an active scan, undoing the latest batch, configuration editing, and
database reset. Database reset requires typing `RESET` and never deletes media
files.

### 4. Apply selected work

Approve and apply selected proposal IDs:

```bash
librarian approve 12 13
```

Reject proposals without moving files:

```bash
librarian reject 14 15
```

Apply already-approved or high-confidence work:

```bash
librarian apply 12 13

librarian apply --auto
```

The filesystem layer verifies hashes, refuses to overwrite existing files,
records every operation in SQLite, and supports undo.

### 5. Undo safely

Undo the newest completed batch:

```bash
librarian undo
```

Undo a specific batch ID:

```bash
librarian undo BATCH_ID
```

Use `status` to see pending, applied, rejected, undone, duplicate, and conflict
counts before and after an operation.

### 6. Inspect archives without extracting

ZIP archives are never extracted during a scan. Inspect their contents
explicitly:

```bash
librarian inspect /path/to/book.zip
```

### 7. Understand video destinations

Use filenames such as:

```text
Arrival (2016).mkv
The Expanse - S01E03 - Remember the Cant.mkv
```

They become:

```text
Movies/Arrival (2016)/Arrival (2016).mkv
TV Shows/The Expanse/Season 01/The Expanse - S01E03 - Remember the Cant.mkv
```

These layouts are designed for Jellyfin discovery. Keep movie and TV input
names descriptive; `SxxExx` is the signal used to identify TV episodes.

### 8. Run unattended at 04:00

The installed timer starts `librarian.service` every day at 04:00 local time.
It uses the configured `operation_mode`:

```bash
sudo systemctl status librarian.timer
sudo systemctl list-timers librarian.timer
sudo journalctl -u librarian.service
sudo systemctl start librarian.service  # run immediately, if needed
```

Keep safe mode enabled until the review queue is trusted. Automatic mode only
applies proposals at or above `safety.auto_apply_threshold`; lower-confidence
items remain in the queue.

### 9. AI behavior and performance

AI is a fallback for incomplete or low-confidence metadata. Fully tagged files
with strong metadata do not call the model. The local Ollama request contains
only the media type, filename, embedded fields, and a small candidate list;
thinking is disabled and JSON output is bounded. AI results are validated and
numeric-only titles or series values are rejected.

For local Qwen3 setup:

```bash
sudo ./scripts/install-ollama.sh --dry-run
sudo ./scripts/install-ollama.sh --quantization q4_k_m
```

Use Q4_K_M on constrained systems. The automatic installer selects a larger
quantization only when available RAM supports it. Ollama failures are recorded
on the proposal and do not grant the model filesystem access.

### 10. Recovery and troubleshooting

Check the active paths and database counts:

```bash
librarian status
```

If a scan appears stuck, open the web dashboard and use **Stop scan**. A stop
request takes effect immediately in the UI; an in-flight model request may
finish in the background before the worker exits.

If the queue contains stale failed proposals, reject them or use the confirmed
database reset in the dashboard. Reset clears proposals, operation history,
and metadata cache only; it never deletes incoming or library files.

## Service-account command reference

Start the local review dashboard with:

```bash
librarian web
```

Open http://127.0.0.1:8765 in a browser. The interface is bound to localhost by default and supports reviewing, approving, rejecting, and undoing audited batches. Use `--port` to select another local port.

#### LAN access

To make the dashboard reachable from another computer on the same network,
bind it to all interfaces:

```bash
librarian web --host 0.0.0.0 --port 8765
```

Then open `http://LIBRARIAN_HOST_IP:8765` from the other computer. On Fedora,
if `firewalld` is active, allow only the trusted LAN zone and port:

```bash
sudo firewall-cmd --permanent --zone=home --add-port=8765/tcp
sudo firewall-cmd --reload
```

The web UI has no login layer, so do not expose it to the public internet. Use
the default `127.0.0.1` bind when remote access is unnecessary. In WSL2, the
`172.*` address belongs to the virtual WSL network; access from another LAN
machine may require Windows port forwarding or WSL mirrored networking. The
Librarian process must still bind to `0.0.0.0`.

For a persistent installed deployment, use the bundled web service:

```bash
sudo systemctl enable --now librarian-web.service
sudo systemctl status librarian-web.service
```

It listens on `0.0.0.0:8765` and restarts automatically if it exits.

Review output labels each proposal `MOVE`, `REVIEW`, or `IGNORE`. Approve selected proposals or all proposals at or above the configured confidence threshold:

```bash
librarian approve 12 13

librarian approve-all-high-confidence
```

Apply approved proposals by ID:

```bash
librarian apply 12 13 14
```

Or apply all high-confidence proposals:

```bash
librarian apply --auto
```

Undo the most recent batch:

```bash
librarian undo

# Or reverse a specific recorded batch:
librarian undo BATCH_ID
```

Each move is recorded before filesystem changes begin and completed only after the destination hash is verified. The audit record includes the source and destination paths, hash, proposal ID, reason, confidence, timestamps, batch ID, and operation state. Existing destinations are never overwritten; cross-filesystem moves use a temporary destination and checksum verification.

Messy audiobook components are grouped using their containing book directory or conservative track/part/CD markers. Their original component names are preserved inside the one audiobook destination. ZIP files are never extracted automatically; inspect one safely with:

```bash
librarian inspect Book.zip
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
  # Omit threads to use all logical CPU cores.

scan:
  extensions:
    video: [".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm"]
```

Keep `operation_mode: safe` until review output is understood. In `automatic` mode, only pending proposals at or above `auto_apply_threshold` are moved; everything else remains available to `review`.

### Paths and permissions

`incoming_dir` is the only tree scanned for new media. `library_dir` is the
destination tree inspected for matches and receives approved moves. `database`
stores proposals, metadata cache, and the operation audit trail. The installer
defaults to `/mnt/media/incoming`, `/mnt/media/books`, and
`/var/lib/librarian/library.db`.

The systemd service runs as the `librarian` account. If you use a path below a
private home directory, grant only the required directory traversal/read/write
access with ACLs. Do not solve this by making the entire home directory
world-readable.

### Ollama

Install and start Ollama, then download a model:

```bash
ollama serve
ollama pull qwen3:8b
```

Enable it in the configuration above. Librarian sends compact requests to Ollama on `127.0.0.1:11434` using four CPU threads and does not require an API key. Fully tagged files bypass AI; ambiguous files receive only media type, filename, embedded metadata, and a small candidate list. Thinking is disabled and output is bounded for faster local processing.

### OpenAI key

The key is read from the environment variable named by `ai.api_key_env`; it is not stored in YAML or SQLite:

```bash
export OPENAI_API_KEY="your-key"
librarian run
```

For systemd, use an environment file instead of putting the key in the configuration file:

```ini
# /etc/librarian/openai.env
OPENAI_API_KEY=your-key
```

Add `EnvironmentFile=/etc/librarian/openai.env` to `systemd/librarian.service` and protect the file with `chmod 600`.

## Testing

Install the optional test dependencies and run the suite:

```bash
python3 -m pip install -e '.[test]'
python3 -m pytest
```

## systemd

Copy the units into `/etc/systemd/system/`, review the configuration, and enable the timer when ready:

```bash
sudo cp systemd/librarian.service systemd/librarian.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now librarian.timer
```

The timer invokes `librarian run` every day at 04:00 local time. Safe mode
creates proposals only; automatic mode also applies high-confidence proposals.
Every operation is audited and can be reversed with `librarian undo BATCH_ID`.
