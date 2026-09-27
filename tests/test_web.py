from pathlib import Path
from threading import Event, Thread
from urllib.request import Request, urlopen

from borganizer.config import Config
from borganizer.config import load_config
from borganizer.db import Database
from borganizer.models import Proposal
from borganizer.web import BorganizerHandler
import borganizer.web as web_module
from http.server import ThreadingHTTPServer


def config(tmp_path: Path) -> Config:
    return Config(
        incoming_dir=tmp_path / "incoming",
        library_dir=tmp_path / "library",
        database=tmp_path / "library.db",
        audiobook_extensions=(".m4b",),
        ebook_extensions=(".epub",),
        ignore_hidden=True,
        min_stable_age_seconds=0,
        series_number_width=2,
        invalid_replacement="_",
        overwrite_existing=False,
        allow_cross_device_move=False,
        auto_apply_threshold=0.95,
    )


def test_web_dashboard_renders_and_approves(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    source = incoming / "The Hobbit.m4b"
    destination = tmp_path / "library" / "The Hobbit.m4b"
    source.write_bytes(b"book")
    database = Database(tmp_path / "library.db")
    proposal_id = database.add_proposal(Proposal(
        id=None, source_path=source, destination_path=destination, sha256="b" * 64,
        confidence=0.97, media_type="audiobook", title="The Hobbit", author="Tolkien",
        series=None, series_number=None,
    ))
    # Use the real digest so the audited apply path can verify it.
    database.conn.execute("UPDATE proposals SET sha256=? WHERE id=?", ("".join(__import__("hashlib").sha256(b"book").hexdigest()), proposal_id))
    database.conn.commit()

    server = ThreadingHTTPServer(("127.0.0.1", 0), BorganizerHandler)
    server.config = config(tmp_path)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        page = urlopen(url).read().decode()
        assert "Borganizer" in page
        assert "The Hobbit" in page
        urlopen(Request(f"{url}/approve", data=f"id={proposal_id}".encode(), method="POST"))
        assert destination.read_bytes() == b"book"
    finally:
        server.shutdown()


def test_web_settings_persist_directories_model_threads_and_mode(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"""incoming_dir: {tmp_path / 'old-in'}
library_dir: {tmp_path / 'old-lib'}
database: {tmp_path / 'library.db'}
operation_mode: safe
ai:
  enabled: false
  provider: ollama
  endpoint: http://127.0.0.1:11434/api/chat
  model: llama3.2:3b
  threads: 4
""")
    server = ThreadingHTTPServer(("127.0.0.1", 0), BorganizerHandler)
    server.config = load_config(config_path)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        payload = "&".join([
            "incoming_dir=/srv/incoming",
            "library_dir=/srv/books",
            "operation_mode=automatic",
            "ai_enabled=1",
            "ai_provider=ollama",
            "ai_endpoint=http%3A%2F%2F127.0.0.1%3A11434%2Fapi%2Fchat",
            "ai_model=qwen3%3A8b",
            "ai_threads=4",
        ]).encode()
        urlopen(Request(f"{url}/settings", data=payload, method="POST"))
        updated = load_config(config_path)
        assert updated.incoming_dir == Path("/srv/incoming")
        assert updated.library_dir == Path("/srv/books")
        assert updated.operation_mode == "automatic"
        assert updated.ai_model == "qwen3:8b"
        assert updated.ai_threads == 4
    finally:
        server.shutdown()


def test_web_settings_error_is_reported(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), BorganizerHandler)
    server.config = config(tmp_path)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        payload = "incoming_dir=x&library_dir=y&operation_mode=invalid&ai_enabled=0&ai_provider=ollama&ai_endpoint=x&ai_model=qwen3%3A8b&ai_threads=4".encode()
        page = urlopen(Request(f"{url}/settings", data=payload, method="POST")).read().decode()
        assert "operation mode must be safe or automatic" in page
    finally:
        server.shutdown()


def test_web_database_reset_requires_confirmation_and_keeps_files(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    source = incoming / "keep.m4b"
    source.write_bytes(b"keep")
    database = Database(tmp_path / "library.db")
    database.add_proposal(Proposal(
        id=None, source_path=source, destination_path=tmp_path / "library" / "keep.m4b",
        sha256="a" * 64, confidence=0.9, media_type="audiobook", title="Keep", author=None,
        series=None, series_number=None,
    ))

    server = ThreadingHTTPServer(("127.0.0.1", 0), BorganizerHandler)
    server.config = config(tmp_path)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        page = urlopen(Request(f"{url}/reset", data=b"confirmation=NO", method="POST")).read().decode()
        assert "type RESET to confirm" in page
        assert Database(tmp_path / "library.db").pending()

        urlopen(Request(f"{url}/reset", data=b"confirmation=RESET", method="POST"))
        assert not Database(tmp_path / "library.db").pending()
        assert source.read_bytes() == b"keep"
    finally:
        server.shutdown()


def test_web_bulk_reject_selected_proposals(tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    database = Database(tmp_path / "library.db")
    for number in (1, 2):
        database.add_proposal(Proposal(
            id=None, source_path=incoming / f"book-{number}.m4b", destination_path=tmp_path / "library" / f"book-{number}.m4b",
            sha256=str(number) * 64, confidence=0.6, media_type="audiobook", title=f"Book {number}", author=None,
            series=None, series_number=None,
        ))

    server = ThreadingHTTPServer(("127.0.0.1", 0), BorganizerHandler)
    server.config = config(tmp_path)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        page = urlopen(url).read().decode()
        assert "id='select-all'" in page
        assert "name='id' value='1'" in page
        assert "name='id' value='2'" in page
        urlopen(Request(f"{url}/bulk", data=b"id=1&id=2&action=reject", method="POST"))
        assert not Database(tmp_path / "library.db").pending()
    finally:
        server.shutdown()


def test_web_scan_reports_progress_while_running(tmp_path, monkeypatch):
    started = Event()
    release = Event()
    finished = Event()

    def slow_scan(*args, **kwargs):
        started.set()
        release.wait(timeout=5)
        finished.set()
        return []

    monkeypatch.setattr(web_module, "propose", slow_scan)
    server = ThreadingHTTPServer(("127.0.0.1", 0), BorganizerHandler)
    server.config = config(tmp_path)
    server.scan_lock = __import__("threading").Lock()
    server.scan_state = {"status": "idle", "message": ""}
    server.scan_cancel_event = Event()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        response = urlopen(Request(f"{url}/scan", data=b"", method="POST")).read().decode()
        assert "Scanning incoming files" in response
        assert "lastScanStatus" in response
        assert "cache:'no-store'" in response
        assert started.wait(timeout=2)
        status = urlopen(f"{url}/scan-status").read().decode()
        assert '"status": "running"' in status
        urlopen(Request(f"{url}/scan-stop", data=b"", method="POST"))
        status = urlopen(f"{url}/scan-status").read().decode()
        assert '"status": "stopped"' in status
        assert "Scan stop requested" in status
        release.set()
        assert finished.wait(timeout=2)
        status = urlopen(f"{url}/scan-status").read().decode()
        assert '"status": "stopped"' in status
        release.set()
    finally:
        release.set()
        server.shutdown()