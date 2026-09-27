from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

from borganizer.config import Config
from borganizer.config import load_config
from borganizer.db import Database
from borganizer.models import Proposal
from borganizer.web import BorganizerHandler
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