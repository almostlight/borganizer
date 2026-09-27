import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from borganizer.ai import OllamaResolver, _resolution
from borganizer.models import BookMetadata


def test_ai_response_is_strictly_validated():
    result = _resolution({"book": "The Final Empire", "author": "Brandon Sanderson", "series": "Mistborn", "series_number": 1, "confidence": 0.97})
    assert result.book == "The Final Empire"
    assert result.confidence == 0.97


def test_ai_response_rejects_filesystem_instead_of_metadata():
    with pytest.raises(ValueError):
        _resolution({"move": "/tmp/file", "confidence": 1.0})


def test_ollama_resolver_uses_local_chat_contract():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            request = json.loads(self.rfile.read(length))
            assert request["model"] == "qwen3:8b"
            assert request["stream"] is False
            assert request["format"] == "json"
            assert request["options"]["num_thread"] == 4
            response = {"message": {"content": json.dumps({
                "book": "The Final Empire",
                "author": "Brandon Sanderson",
                "series": "Mistborn",
                "series_number": 1,
                "confidence": 0.97,
            })}}
            payload = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        resolver = OllamaResolver(f"http://127.0.0.1:{server.server_port}/api/chat", "qwen3:8b", threads=4)
        result = resolver.resolve(
            filename="Sanderson_Mistborn_FinalEmpire.m4b",
            embedded=BookMetadata(title="Mistborn"),
            candidate_books=["The Final Empire"],
        )
        assert result.book == "The Final Empire"
        assert result.confidence == 0.97
    finally:
        server.shutdown()