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

The current release is deliberately non-AI. It extracts embedded metadata, parses filenames, hashes files, stores proposals in SQLite, and requires an explicit apply step. AI can later be added as an ambiguity resolver.

## Install on Debian

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

Use the service account for all operations:

```bash
sudo -u borganizer BORGANIZER_CONFIG=/opt/borganizer/config.yaml \
  /opt/borganizer/venv/bin/borganizer scan
```

Then inspect proposals:

```bash
sudo -u borganizer BORGANIZER_CONFIG=/opt/borganizer/config.yaml \
  /opt/borganizer/venv/bin/borganizer review
```

Nothing has moved yet.

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
```

## systemd

Copy `systemd/borganizer.service` into `/etc/systemd/system/` and enable it only when you are happy with the manual workflow.
