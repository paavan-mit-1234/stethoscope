"""Read-only HTTP/JSON API over the trace store (Phase 3).

Runs in the same process as the OTLP/gRPC receiver and shares its single
DuckDB connection + lock — this mirrors the PRD architecture where the
ingestion service and the Workbench share one in-process store (PRD 3.2),
and sidesteps DuckDB's single-writer-per-file limit.

The canonical transport is Tauri IPC (see apps/desktop/src-tauri); this HTTP
surface is what the browser-run Workbench uses until the Rust shell compiles.
Endpoints map 1:1 to the Tauri commands.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .store import Store

_log = logging.getLogger("stethoscope.api")

DEFAULT_API_ADDR = ("127.0.0.1", 4318)


def _json_default(o: Any):
    if dataclasses.is_dataclass(o):
        return dataclasses.asdict(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


# (compiled regex, handler-name) — handler receives captured groups.
_ROUTES = [
    (re.compile(r"^/health$"), "health"),
    (re.compile(r"^/projects$"), "projects"),
    (re.compile(r"^/traces$"), "traces"),
    (re.compile(r"^/traces/([0-9a-fA-F]+)/spans$"), "spans"),
    (re.compile(r"^/spans/([0-9a-fA-F]+)$"), "span"),
    (re.compile(r"^/spans/([0-9a-fA-F]+)/messages$"), "messages"),
    (re.compile(r"^/spans/([0-9a-fA-F]+)/tool_call$"), "tool_call"),
    (re.compile(r"^/spans/([0-9a-fA-F]+)/state$"), "state"),
    (re.compile(r"^/breakpoints$"), "breakpoints"),
    (re.compile(r"^/traces/([0-9a-fA-F]+)/export$"), "export"),
]


def make_handler(store: Store, lock: threading.Lock):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):  # quiet; ingestion logs are enough
            pass

        def _send(self, code: int, payload: Any):
            body = json.dumps(payload, default=_json_default).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            # Browser Workbench runs on :1420 (dev) — allow cross-origin GET.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):  # CORS preflight
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.end_headers()

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception as exc:
                self._send(400, {"error": f"bad body: {exc}"})
                return

            if path == "/branch":
                try:
                    from tools.ref_replay import branch  # lazy: import cycle

                    # branch() locks internally only while reading; must NOT
                    # be under the blanket lock (replay subprocess re-enters).
                    result = branch(
                        store,
                        lock,
                        body["source_trace_id"],
                        body["branch_point_span_id"],
                        body["mutation"],
                    )
                    self._send(200, result)
                except Exception as exc:
                    _log.exception("branch failed")
                    self._send(500, {"error": str(exc)})
                return

            if path == "/breakpoints":
                from . import bp

                dsl = body.get("condition_dsl", "")
                try:
                    bp.parse(dsl)  # validate before storing
                except ValueError as exc:
                    self._send(400, {"error": f"bad predicate: {exc}"})
                    return
                with lock:
                    projects = store.list_projects()
                    pid = body.get("project_id") or (
                        projects[0][0] if projects else store.ensure_project("default")
                    )
                    bid = store.add_breakpoint(pid, body.get("name"), dsl)
                self._send(200, {"id": bid})
                return

            if path == "/breakpoints/delete":
                with lock:
                    store.delete_breakpoint(body["id"])
                self._send(200, {"ok": True})
                return

            self._send(404, {"error": f"no route: {path}"})

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            for rx, name in _ROUTES:
                m = rx.match(path)
                if m:
                    try:
                        with lock:
                            payload = getattr(self, f"r_{name}")(*m.groups(),
                                                                 query=query)
                        self._send(200, payload)
                    except Exception as exc:  # never crash the server
                        _log.exception("api error on %s", path)
                        self._send(500, {"error": str(exc)})
                    return
            self._send(404, {"error": f"no route: {path}"})

        # ---- route handlers ------------------------------------------
        def r_health(self, query=""):
            return {"ok": True}

        def r_projects(self, query=""):
            return [{"id": i, "name": n} for i, n in store.list_projects()]

        def r_traces(self, query=""):
            pid = None
            if query:
                for kv in query.split("&"):
                    if kv.startswith("project_id="):
                        pid = kv.split("=", 1)[1] or None
            return [dataclasses.asdict(t) for t in store.list_traces(pid)]

        def r_spans(self, trace_id, query=""):
            return store.get_spans(trace_id)

        def r_span(self, span_id, query=""):
            return store.get_span(span_id)

        def r_messages(self, span_id, query=""):
            return store.get_messages(span_id)

        def r_tool_call(self, span_id, query=""):
            return store.get_tool_call(span_id)

        def r_state(self, span_id, query=""):
            return store.get_state(span_id)

        def r_breakpoints(self, query=""):
            return store.list_breakpoints()

        def r_export(self, trace_id, query=""):
            return store.export_trace(trace_id)

    return Handler


def serve_api(
    store: Store,
    lock: threading.Lock,
    addr: tuple[str, int] = DEFAULT_API_ADDR,
) -> ThreadingHTTPServer:
    """Start the read API on a daemon thread; returns the server."""
    httpd = ThreadingHTTPServer(addr, make_handler(store, lock))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    _log.info("Stethoscope read API on http://%s:%d", *addr)
    return httpd
