from __future__ import annotations

import html
import json
import secrets
from threading import Event, Lock, Thread
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
:root { color-scheme: dark; --bg: #0e1015; --sidebar: #151820; --panel: #1b1f29; --panel-raised: #232936; --line: #303746; --text: #f3f4f8; --muted: #9ba3b5; --accent: #8b7cff; --accent-soft: #29254b; --green: #8cddb5; --amber: #f0c674; --red: #ef8f9c; }
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: var(--bg); color: var(--text); font: 15px/1.5 ui-sans-serif, system-ui, sans-serif; }
.app-shell { min-height: 100vh; display: grid; grid-template-columns: 228px minmax(0, 1fr); }
.sidebar { position: sticky; top: 0; height: 100vh; padding: 28px 16px; background: var(--sidebar); border-right: 1px solid var(--line); }
.brand { display: flex; align-items: center; gap: 10px; padding: 0 12px 34px; color: var(--text); text-decoration: none; font-weight: 750; letter-spacing: .01em; }
.brand-mark { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px; background: var(--accent); color: #12101e; font-weight: 900; }
.nav-label { padding: 0 12px 8px; color: #687184; font-size: 11px; font-weight: 750; letter-spacing: .12em; text-transform: uppercase; }
.nav-link { display: block; margin: 3px 0; padding: 10px 12px; border-radius: 7px; color: var(--muted); text-decoration: none; }
.nav-link:hover, .nav-link:focus { background: var(--panel-raised); color: var(--text); }
main { width: min(1180px, 100%); padding: 42px 44px 68px; }
header { display: flex; justify-content: space-between; gap: 24px; align-items: end; margin-bottom: 32px; }
h1, h2, p { margin: 0; } h1 { font-size: 34px; line-height: 1.1; letter-spacing: -.02em; } h2 { font-size: 18px; letter-spacing: -.01em; }
.eyebrow { color: var(--accent); font-size: 11px; font-weight: 750; letter-spacing: .14em; text-transform: uppercase; margin-bottom: 10px; }
.muted, small { color: var(--muted); } .mode { border: 1px solid #4a4380; border-radius: 999px; padding: 7px 12px; color: var(--accent); background: var(--accent-soft); font-size: 13px; font-weight: 700; }
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 30px; }
.stat, .proposal { background: var(--panel); border: 1px solid var(--line); border-radius: 9px; }
.stat { padding: 17px 18px; } .stat strong { display: block; font-size: 27px; letter-spacing: -.03em; } .stat span { color: var(--muted); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .1em; }
.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin: 28px 0 12px; } .toolbar form { display: inline; } .bulk-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.proposal { display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; gap: 16px; padding: 20px; margin: 10px 0; }
.proposal-select { display: flex; align-items: flex-start; justify-content: center; padding-top: 3px; color: var(--muted); } .proposal-select input, .select-all input { width: 16px; height: 16px; margin: 0; accent-color: var(--accent); }
.proposal h3 { margin: 0 0 5px; font-size: 17px; } .proposal .path { color: var(--muted); overflow-wrap: anywhere; font-size: 13px; }
.meta { display: flex; flex-wrap: wrap; gap: 8px 16px; color: var(--muted); margin: 10px 0; font-size: 13px; }
.confidence { color: var(--green); font-weight: 700; } .reason { color: var(--amber); font-size: 13px; }
.actions { display: flex; flex-direction: column; gap: 8px; min-width: 108px; justify-content: center; } button { border: 1px solid var(--line); border-radius: 6px; background: var(--panel-raised); color: var(--text); padding: 9px 13px; cursor: pointer; font: inherit; font-weight: 700; transition: border-color .15s, background .15s; } button:hover, button:focus { border-color: var(--accent); background: #2c3342; } button:disabled { cursor: not-allowed; opacity: .45; }
.approve { color: #12101e; background: var(--accent); border-color: var(--accent); } .approve:hover, .approve:focus { background: #a096ff; border-color: #a096ff; } .reject { color: var(--red); } .danger { border-color: var(--red); color: var(--red); }
.section-dropdown { background: var(--panel); border: 1px solid var(--line); border-radius: 9px; margin-top: 28px; overflow: hidden; } .section-dropdown summary { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 18px 22px; cursor: pointer; list-style: none; font-size: 18px; font-weight: 750; } .section-dropdown summary::-webkit-details-marker { display: none; } .section-dropdown summary::after { content: '+'; color: var(--accent); font-size: 24px; font-weight: 400; } .section-dropdown[open] summary::after { content: '−'; } .section-body { padding: 0 22px 22px; } .settings-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-top: 14px; } label { display: grid; gap: 5px; color: var(--muted); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; } input, select { width: 100%; border: 1px solid var(--line); border-radius: 5px; background: #12151c; color: var(--text); padding: 10px; font: inherit; } input:focus, select:focus { outline: 2px solid var(--accent); outline-offset: 1px; } .settings-actions { margin-top: 16px; display: flex; justify-content: end; } .error { border: 1px solid var(--red); border-radius: 7px; color: var(--red); background: #321e27; padding: 12px 14px; margin-bottom: 20px; overflow-wrap: anywhere; }
.scan-progress { display: flex; align-items: center; gap: 12px; margin: 18px 0; padding: 12px 14px; border: 1px solid #4a4380; border-radius: 7px; color: var(--accent); background: var(--accent-soft); } .progress-track { width: min(280px, 45vw); height: 6px; overflow: hidden; border-radius: 999px; background: #17152c; } .progress-track span { display: block; width: 42%; height: 100%; border-radius: inherit; background: var(--accent); animation: scan-progress 1.2s ease-in-out infinite; } @keyframes scan-progress { 0% { transform: translateX(-140%); } 100% { transform: translateX(340%); } }
@media (max-width: 780px) { .app-shell { display: block; } .sidebar { position: static; height: auto; padding: 16px; border-right: 0; border-bottom: 1px solid var(--line); } .brand { display: inline-flex; padding: 0 8px 14px; } .nav-label { display: none; } .nav-link { display: inline-block; margin: 0 2px; padding: 8px 10px; } main { padding: 30px 20px 52px; } header { display: block; } .mode { display: inline-block; margin-top: 18px; } .stats { grid-template-columns: repeat(2, 1fr); } .proposal { grid-template-columns: 24px minmax(0, 1fr); } .proposal .actions { grid-column: 2; flex-direction: row; } .settings-grid { grid-template-columns: 1fr; } }
"""


def _page(title: str, body: str) -> bytes:
    document = f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title><style>{PAGE_STYLE}</style></head><body><div class='app-shell'><aside class='sidebar'><a class='brand' href='/'><span class='brand-mark'>B</span><span>Borganizer</span></a><div class='nav-label'>Library desk</div><a class='nav-link' href='#scanning'>Scanning</a><a class='nav-link' href='#review-queue'>Review queue</a><a class='nav-link' href='#configuration'>Configuration</a></aside><main>{body}</main></div><script>const selectAll=document.getElementById('select-all');const boxes=[...document.querySelectorAll('.proposal-checkbox')];if(selectAll){{selectAll.addEventListener('change',()=>boxes.forEach(box=>box.checked=selectAll.checked));boxes.forEach(box=>box.addEventListener('change',()=>{{selectAll.checked=boxes.length>0&&boxes.every(item=>item.checked);selectAll.indeterminate=boxes.some(item=>item.checked)&&!selectAll.checked;}}));}}let lastScanStatus=null;const pollScan=()=>fetch('/scan-status',{{cache:'no-store'}}).then(response=>response.json()).then(state=>{{const progressVisible=Boolean(document.querySelector('.scan-progress'));const currentFile=document.getElementById('scan-current-file');if(currentFile&&state.current_file)currentFile.textContent=state.current_file;if(state.status==='running'&&!progressVisible){{location.reload();return;}}if(lastScanStatus==='running'&&state.status!=='running'){{location.reload();return;}}lastScanStatus=state.status;setTimeout(pollScan,1000);}}).catch(()=>setTimeout(pollScan,2000));pollScan();document.querySelectorAll('.error').forEach(error=>setTimeout(()=>error.remove(),10000));</script></body></html>"
    return document.encode("utf-8")


def _redirect(handler: BaseHTTPRequestHandler, path: str = "/") -> None:
    handler.send_response(HTTPStatus.SEE_OTHER)
    handler.send_header("Location", path)
    handler.end_headers()


def _scan_snapshot(server) -> dict[str, str | bool]:
    lock = getattr(server, "scan_lock", None)
    if lock is None:
        return {"status": "idle", "message": ""}
    with lock:
        return dict(server.scan_state)


class BorganizerHandler(BaseHTTPRequestHandler):
    server_version = "borganizer-web/0.1"

    def _database(self) -> Database:
        return Database(self.server.config.database)  # type: ignore[attr-defined]

    def _set_scan_state(self, status: str, message: str = "", current_file: str = "") -> None:
        with self.server.scan_lock:  # type: ignore[attr-defined]
            self.server.scan_state = {"status": status, "message": message, "current_file": current_file}  # type: ignore[attr-defined]

    def _run_scan(self) -> None:
        try:
            config = self.server.config  # type: ignore[attr-defined]
            database = self._database()
            propose(config, database, build_metadata_provider(config, database), build_ai_resolver(config), cancel_event=self.server.scan_cancel_event, progress_callback=lambda path: self._set_scan_state("running", current_file=str(path)))  # type: ignore[attr-defined]
            if self.server.scan_cancel_event.is_set():  # type: ignore[attr-defined]
                self._set_scan_state("stopped", "Scan stopped by user")
            else:
                self._set_scan_state("complete")
        except Exception as exc:
            if self.server.scan_cancel_event.is_set():  # type: ignore[attr-defined]
                self._set_scan_state("stopped", "Scan stopped by user")
            else:
                self._set_scan_state("error", str(exc))

    def do_GET(self) -> None:
        request_path = urlparse(self.path).path
        if request_path == "/scan-status":
            self._send_json(_scan_snapshot(self.server))
            return
        if request_path != "/":
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
                f"<article class='proposal'><label class='proposal-select'><input class='proposal-checkbox' type='checkbox' name='id' value='{row['id']}' form='bulk-actions' aria-label='Select {html.escape(title, quote=True)}'></label><div><h3>{html.escape(title)}</h3>"
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
        scan = _scan_snapshot(self.server)
        body += "<section class='stats'>" + "".join(f"<div class='stat'><strong>{counts.get(status, 0)}</strong><span>{status}</span></div>" for status in ("pending", "applied", "rejected", "undone")) + "</section>"
        scan_open = " open" if scan["status"] == "running" else ""
        current_file = html.escape(str(scan.get("current_file", "")))
        scan_content = "<div class='scan-progress' role='status'><div class='progress-track'><span></span></div><span>Scanning incoming files...</span></div>" if scan["status"] == "running" else "<p class='muted'>Ready to scan incoming files.</p>"
        if scan["status"] == "error":
            scan_content = f"<div class='error'>Scan error: {html.escape(str(scan['message']))}</div>"
        if scan["status"] == "running":
            scan_content += f"<p class='path'>Current file: <span id='scan-current-file'>{current_file}</span></p>"
        stop_disabled = "" if scan["status"] == "running" else " disabled"
        body += f"<details class='section-dropdown' id='scanning'{scan_open}><summary>Scanning</summary><div class='section-body'>{scan_content}<div class='bulk-actions'><form method='post' action='/scan'><button>Scan incoming</button></form><form method='post' action='/scan-stop'><button class='danger'{stop_disabled}>Stop scan</button></form></div></div></details>"
        body += "<details class='section-dropdown' id='review-queue' open><summary>Pending proposals</summary><div class='section-body'>"
        body += f"<div class='toolbar'><span class='muted'>Review and organize incoming files.</span><div class='bulk-actions'><label class='select-all'><input id='select-all' type='checkbox'> Select all</label>{undo}<form id='bulk-actions' method='post' action='/bulk'><button class='approve' name='action' value='approve'>Approve selected</button><button class='reject' name='action' value='reject'>Reject selected</button></form></div></div>"
        body += "".join(cards) or "<p class='muted'>Nothing needs review.</p>"
        body += "</div></details>"
        body += f"""
        <details class='section-dropdown' id='configuration'><summary>Configuration</summary><div class='section-body'><p class='muted'>Changes are saved to the active YAML configuration.</p>
        <form method='post' action='/settings'><div class='settings-grid'>
        <label>Incoming directory<input name='incoming_dir' value='{html.escape(str(config.incoming_dir), quote=True)}'></label>
        <label>Library directory<input name='library_dir' value='{html.escape(str(config.library_dir), quote=True)}'></label>
        <label>Operation mode<select name='operation_mode'><option {'selected' if config.operation_mode == 'safe' else ''}>safe</option><option {'selected' if config.operation_mode == 'automatic' else ''}>automatic</option></select></label>
        <label>AI provider<select name='ai_provider'><option {'selected' if config.ai_provider == 'ollama' else ''}>ollama</option><option {'selected' if config.ai_provider == 'openai' else ''}>openai</option></select></label>
        <label>AI model<input name='ai_model' value='{html.escape(config.ai_model, quote=True)}'></label>
        <label>Ollama threads<input type='number' min='1' max='128' name='ai_threads' value='{config.ai_threads}'></label>
        <label>AI endpoint<input name='ai_endpoint' value='{html.escape(config.ai_endpoint, quote=True)}'></label>
        <label>AI enabled<select name='ai_enabled'><option value='0' {'selected' if not config.ai_enabled else ''}>disabled</option><option value='1' {'selected' if config.ai_enabled else ''}>enabled</option></select></label>
        </div><div class='settings-actions'><button class='approve'>Save configuration</button></div></form>
        <form method='post' action='/reset' style='margin-top:28px' onsubmit="return confirm('Reset all proposals, operation history, and metadata cache? Media files will not be deleted.');">
        <h2>Reset database</h2><p class='muted'>Clears organizer history and cached metadata. Files in your incoming and library directories are not changed.</p>
        <label style='max-width:320px;margin-top:12px'>Type RESET to confirm<input name='confirmation' autocomplete='off' required></label>
        <div class='settings-actions'><button class='danger' type='submit'>Reset database</button></div></form></div></details>"""
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
                if _scan_snapshot(self.server)["status"] == "running":
                    raise RuntimeError("a scan is already in progress")
                self.server.scan_cancel_event = Event()  # type: ignore[attr-defined]
                self._set_scan_state("running")
                Thread(target=self._run_scan, daemon=True).start()
            elif self.path == "/scan-stop":
                if _scan_snapshot(self.server)["status"] != "running":
                    raise RuntimeError("no scan is in progress")
                self.server.scan_cancel_event.set()  # type: ignore[attr-defined]
                self._set_scan_state("stopped", "Scan stop requested")
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
            elif self.path == "/reset":
                if form.get("confirmation", [""])[0] != "RESET":
                    raise ValueError("type RESET to confirm the database reset")
                database.reset()
            elif self.path == "/bulk":
                proposal_ids = [int(value) for value in form.get("id", [])]
                if not proposal_ids:
                    raise ValueError("select at least one proposal")
                action = form.get("action", [""])[0]
                if action == "approve":
                    apply_proposals(self.server.config, database, proposal_ids)  # type: ignore[attr-defined]
                elif action == "reject":
                    for proposal_id in proposal_ids:
                        row = database.get(proposal_id)
                        if not row or row["status"] != "pending":
                            raise ValueError(f"proposal {proposal_id} is not pending")
                        database.mark_rejected(proposal_id)
                else:
                    raise ValueError("unknown bulk action")
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

    def _send_json(self, payload: dict[str, str | bool]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(config: Config, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), BorganizerHandler)
    server.config = config  # type: ignore[attr-defined]
    server.scan_lock = Lock()  # type: ignore[attr-defined]
    server.scan_state = {"status": "idle", "message": "", "current_file": ""}  # type: ignore[attr-defined]
    server.scan_cancel_event = Event()  # type: ignore[attr-defined]
    print(f"Borganizer web UI: http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()