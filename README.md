# Audiobookshelf Book Organizer

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

sudo useradd --system --home /var/lib/book-organizer --create-home --shell /usr/sbin/nologin bookorganizer || true
sudo mkdir -p /opt/book-organizer /var/lib/book-organizer /mnt/media/incoming /mnt/media/books
sudo chown -R bookorganizer:bookorganizer /opt/book-organizer /var/lib/book-organizer /mnt/media/incoming /mnt/media/books

sudo -u bookorganizer python3 -m venv /opt/book-organizer/venv
sudo -u bookorganizer /opt/book-organizer/venv/bin/pip install --upgrade pip
sudo -u bookorganizer /opt/book-organizer/venv/bin/pip install /opt/book-organizer
sudo cp config/config.example.yaml /opt/book-organizer/config.yaml
sudo chown bookorganizer:bookorganizer /opt/book-organizer/config.yaml
```

Adjust `incoming_dir`, `library_dir`, and `database` in `/opt/book-organizer/config.yaml` if necessary.

## First scan

Use the service account for all operations:

```bash
sudo -u bookorganizer BOOK_ORGANIZER_CONFIG=/opt/book-organizer/config.yaml \
  /opt/book-organizer/venv/bin/book-organizer scan
```

Then inspect proposals:

```bash
sudo -u bookorganizer BOOK_ORGANIZER_CONFIG=/opt/book-organizer/config.yaml \
  /opt/book-organizer/venv/bin/book-organizer review
```

Nothing has moved yet.

Apply approved proposals by ID:

```bash
sudo -u bookorganizer BOOK_ORGANIZER_CONFIG=/opt/book-organizer/config.yaml \
  /opt/book-organizer/venv/bin/book-organizer apply 12 13 14
```

Or apply all high-confidence proposals:

```bash
sudo -u bookorganizer BOOK_ORGANIZER_CONFIG=/opt/book-organizer/config.yaml \
  /opt/book-organizer/venv/bin/book-organizer apply --auto
```

Undo the most recent batch:

```bash
sudo -u bookorganizer BOOK_ORGANIZER_CONFIG=/opt/book-organizer/config.yaml \
  /opt/book-organizer/venv/bin/book-organizer undo
```

## systemd

Copy `systemd/book-organizer.service` into `/etc/systemd/system/` and enable it only when you are happy with the manual workflow.
