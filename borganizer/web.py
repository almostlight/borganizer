from __future__ import annotations

import html
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from .config import Config, save_runtime_settings
from .db import Database
from .organizer import apply_proposals, propose, undo_latest
from .providers import build_metadata_provider
from .ai import build_ai_resolver


PAGE_STYLE = """
:root { color-scheme: dark; --bg: #101315; --panel: #181d20; --line: #2b3438; --text: #edf2ef; --muted: #9eaaa8; --green: #a8d5ba; --amber: #e6c27a; --red: #e58f8f; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 15px/1.5 ui-sans-serif, system-ui, sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 42px 24px 64px; }
header { display: flex; justify-content: space-between; gap: 24px; align-items: end; margin-bottom: 32px; }
h1, h2, p { margin: 0; } h1 { font: 700 38px/1.05 Georgia, serif; letter-spacing: .01em; } h2 { font-size: 18px; }
.eyebrow { color: var(--green); font-size: 12px; letter-spacing: .14em; text-transform: uppercase; margin-bottom: 10px; }
.muted, small { color: var(--muted); } .mode { border: 1px solid var(--line); padding: 8px 12px; color: var(--green); }
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 28px; }
.stat, .proposal { background: var(--panel); border: 1px solid var(--line); }
.stat { padding: 18px; } .stat strong { display: block; font-size: 28px; } .stat span { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
.toolbar { display: flex; justify-content: space-between; align-items: center; margin: 28px 0 12px; } .toolbar form { display: inline; }
.proposal { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 22px; padding: 20px; margin: 10px 0; }
.proposal h3 { margin: 0 0 5px; font-size: 17px; } .proposal .path { color: var(--muted); overflow-wrap: anywhere; font-size: 13px; }
.meta { display: flex; flex-wrap: wrap; gap: 8px 16px; color: var(--muted); margin: 10px 0; font-size: 13px; }
.confidence { color: var(--green); font-weight: 700; } .reason { color: var(--amber); font-size: 13px; }
.actions { display: flex; flex-direction: column; gap: 8px; min-width: 108px; justify-content: center; } button { border: 1px solid var(--line); background: #222a2d; color: var(--text); padding: 9px 12px; cursor: pointer; font-weight: 650; } button:hover { border-color: var(--green); }
.approve { color: #102016; background: var(--green); border-color: var(--green); } .reject { color: var(--red); }
.settings { background: var(--panel); border: 1px solid var(--line); padding: 20px; margin-top: 34px; } .settings-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-top: 14px; } label { display: grid; gap: 5px; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; } input, select { width: 100%; border: 1px solid var(--line); background: #111719; color: var(--text); padding: 10px; font: inherit; } .settings-actions { margin-top: 16px; display: flex; justify-content: end; } .error { border: 1px solid var(--red); color: var(--red); background: #291b1d; padding: 12px 14px; margin-bottom: 20px; overflow-wrap: anywhere; }
@media (max-width: 720px) { main { padding: 28px 16px; } header { display: block; } .mode { display: inline-block; margin-top: 18px; } .stats { grid-template-columns: repeat(2, 1fr); } .proposal { grid-template-columns: 1fr; } .actions { flex-direction: row; } .settings-grid { grid-template-columns: 1fr; } }
"""


def _page(title: str, body: str) -> bytes:
    document = f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title><style>{PAGE_STYLE}</style></head><body><main>{body}</main></body></html>"
    return document.encode("utf-8")


def _redirect(handler: BaseHTTPRequestHandler, path: str = "/") -> None:
    handler.send_response(HTTPStatus.SEE_OTHER)
    handler.send_header("Location", path)
    handler.end_headers()


class BorganizerHandler(BaseHTTPRequestHandler):
    server_version = "borganizer-web/0.1"

    def _database(self) -> Database:
        return Database(self.server.config.database)  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        if urlparse(self.path).path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        database = self._database()
        counts = database.counts()
        pending = database.pending()
        config: Config = self.server.config  # type: ignore[attr-defined]
        query = parse_qs(urlparse(self.path).query)
        error = query.get("error", [""])[0]
        cards = []
        for row in pending:
            confidence = float(row["confidence"])
            title = row["title"] or Path(row["source_path"]).name
            identity = " / ".join(value for value in (row["author"], row["series"], title) if value) or "Unknown"
            reason = row["reason"] or "No additional notes"
            cards.append(
                f"<article class='proposal'><div><h3>{html.escape(title)}</h3>"
                f"<div class='muted'>{html.escape(identity)}</div>"
                f"<div class='meta'><span class='confidence'>{confidence:.0%} confidence</span><span>{html.escape(row['media_type'])}</span></div>"
                f"<div class='path'>From: {html.escape(row['source_path'])}</div>"
                f"<div class='path'>To: {html.escape(row['destination_path'])}</div>"
                f"<div class='reason'>{html.escape(reason)}</div></div>"
                f"<div class='actions'><form method='post' action='/approve'><input type='hidden' name='id' value='{row['id']}'><button class='approve'>Approve</button></form>"
                f"<form method='post' action='/reject'><input type='hidden' name='id' value='{row['id']}'><button class='reject'>Reject</button></form></div></article>"
            )
        latest = database.latest_batch()
        undo = ""
        if latest:
            undo = f"<form method='post' action='/undo'><input type='hidden' name='batch_id' value='{html.escape(latest)}'><button>Undo latest batch</button></form>"
        body = f"<header><div><div class='eyebrow'>Local library desk</div><h1>Borganizer</h1><p class='muted'>Review, approve, and reverse library operations.</p></div><div class='mode'>Mode: {html.escape(config.operation_mode)}</div></header>"
        if error:
            body += f"<div class='error'>Error: {html.escape(error)}</div>"
        body += "<section class='stats'>" + "".join(f"<div class='stat'><strong>{counts.get(status, 0)}</strong><span>{status}</span></div>" for status in ("pending", "applied", "rejected", "undone")) + "</section>"
        body += f"<div class='toolbar'><h2>Pending proposals</h2><div><form method='post' action='/scan'><button>Scan incoming</button></form>{undo}</div></div>"
        body += "".join(cards) or "<p class='muted'>Nothing needs review.</p>"
        body += f"""
        <section class='settings'><h2>Configuration</h2><p class='muted'>Changes are saved to the active YAML configuration.</p>
        <form method='post' action='/settings'><div class='settings-grid'>
        <label>Incoming directory<input name='incoming_dir' value='{html.escape(str(config.incoming_dir), quote=True)}'></label>
        <label>Library directory<input name='library_dir' value='{html.escape(str(config.library_dir), quote=True)}'></label>
        <label>Operation mode<select name='operation_mode'><option {'selected' if config.operation_mode == 'safe' else ''}>safe</option><option {'selected' if config.operation_mode == 'automatic' else ''}>automatic</option></select></label>
        <label>AI provider<select name='ai_provider'><option {'selected' if config.ai_provider == 'ollama' else ''}>ollama</option><option {'selected' if config.ai_provider == 'openai' else ''}>openai</option></select></label>
        <label>AI model<input name='ai_model' value='{html.escape(config.ai_model, quote=True)}'></label>
        <label>Ollama threads<input type='number' min='1' max='128' name='ai_threads' value='{config.ai_threads}'></label>
        <label>AI endpoint<input name='ai_endpoint' value='{html.escape(config.ai_endpoint, quote=True)}'></label>
        <label>AI enabled<select name='ai_enabled'><option value='0' {'selected' if not config.ai_enabled else ''}>disabled</option><option value='1' {'selected' if config.ai_enabled else ''}>enabled</option></select></label>
        </div><div class='settings-actions'><button class='approve'>Save configuration</button></div></form></section>"""
        self._send_html(_page("Borganizer", body))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        database = self._database()
        try:
            if self.path == "/approve":
                proposal_id = int(form["id"][0])
                apply_proposals(self.server.config, database, [proposal_id])  # type: ignore[attr-defined]
            elif self.path == "/reject":
                database.mark_rejected(int(form["id"][0]))
            elif self.path == "/undo":
                undo_latest(self.server.config, database, form["batch_id"][0])  # type: ignore[attr-defined]
            elif self.path == "/scan":
                config = self.server.config  # type: ignore[attr-defined]
                propose(config, database, build_metadata_provider(config, database), build_ai_resolver(config))
            elif self.path == "/settings":
                current = self.server.config  # type: ignore[attr-defined]
                updated = save_runtime_settings(
                    current,
                    incoming_dir=form["incoming_dir"][0],
                    library_dir=form["library_dir"][0],
                    operation_mode=form["operation_mode"][0],
                    ai_enabled=form.get("ai_enabled", ["0"])[0] == "1",
                    ai_provider=form["ai_provider"][0],
                    ai_endpoint=form["ai_endpoint"][0],
                    ai_model=form["ai_model"][0],
                    ai_threads=int(form["ai_threads"][0]),
                )
                self.server.config = updated  # type: ignore[attr-defined]
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
        except (KeyError, ValueError, OSError, RuntimeError) as exc:
            _redirect(self, "/?error=" + quote(str(exc)))
            return
        _redirect(self)

    def _send_html(self, payload: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(config: Config, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), BorganizerHandler)
    server.config = config  # type: ignore[attr-defined]
    print(f"Borganizer web UI: http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()