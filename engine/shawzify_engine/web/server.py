"""SHAWZIFY in a browser, on this machine only.

The desktop app is one shell around the engine; this is another. Same engine,
same methods, same payloads -- only the transport differs, so the React app
runs unchanged against either.

Security, since this one does open a socket:

* It binds **127.0.0.1** only. Never 0.0.0.0, and there is no option to.
* Every request must carry a token generated at startup and printed in the
  launch URL, so another program on the machine cannot drive it by guessing
  the port.
* Cross-origin requests are refused outright, and the Origin header is checked
  on every API call, so a web page you happen to have open cannot reach it.
* File paths in requests go through the same validation as everywhere else.

Built on the standard library: a background thread per request, and
server-sent events for progress. That keeps the web UI a zero-dependency
addition rather than another framework to install.
"""

from __future__ import annotations

import json
import mimetypes
import os
import queue
import secrets
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ..common.errors import ShawzifyError
from ..common.logging import get_logger
from ..version import APP_VERSION

#: Where the built React app lives, relative to the repository root.
_FRONTEND_CANDIDATES = (
    Path("apps") / "desktop" / "dist",
    Path("dist"),
)

_MAX_BODY_BYTES = 4 * 1024 * 1024


def find_frontend(root: Path | None = None) -> Path | None:
    """Locate the built frontend, walking up from here in a source checkout."""
    override = os.environ.get("SHAWZIFY_WEB_ROOT")
    if override and (Path(override) / "index.html").exists():
        return Path(override)
    start = root or Path(__file__).resolve()
    for base in [start, *start.parents]:
        for candidate in _FRONTEND_CANDIDATES:
            path = base / candidate
            if (path / "index.html").exists():
                return path
    return None


class EventHub:
    """Fan-out of progress events to connected browsers."""

    def __init__(self) -> None:
        self._subscribers: list[queue.Queue[str]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue(maxsize=256)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[str]) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, default=str)
        with self._lock:
            targets = list(self._subscribers)
        for q in targets:
            try:
                q.put_nowait(line)
            except queue.Full:
                # A browser that has stopped reading must not stall the engine.
                pass


class WebApp:
    """Holds the engine session and the event hub for one server."""

    def __init__(self, *, token: str, frontend: Path | None) -> None:
        self.token = token
        self.frontend = frontend
        self.hub = EventHub()
        self.log = get_logger("web")
        self.started = time.time()

    def dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Run an engine method, publishing its progress to browsers."""
        from .. import server as rpc

        request_id = int(params.get("requestId") or 0)
        if not request_id:
            request_id = int(time.time() * 1000) % 2_000_000_000
            params = {**params, "requestId": request_id}

        handler = rpc.METHODS.get(method)
        if handler is None:
            raise ShawzifyError("The engine does not support '" + method + "'.")

        # Route this call's progress events to the browsers instead of stdout.
        original_emit = rpc._emit

        def emit(payload: dict[str, Any]) -> None:
            if payload.get("type") == "event":
                self.hub.publish(payload)

        rpc._emit = emit  # type: ignore[assignment]
        try:
            return handler(params, request_id)
        finally:
            rpc._emit = original_emit  # type: ignore[assignment]
            rpc.SESSION.release(request_id)


class Handler(BaseHTTPRequestHandler):
    server_version = "SHAWZIFY/" + APP_VERSION
    protocol_version = "HTTP/1.1"
    app: WebApp  # set on the server instance

    # -- plumbing -------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        self.app.log.event("web.request", line=fmt % args)

    def _origin_ok(self) -> bool:
        """Refuse anything that did not originate from this server's own page."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True  # same-origin fetches and curl send no Origin
        host = self.headers.get("Host", "")
        allowed = {"http://" + host, "https://" + host}
        return origin in allowed

    def _authorised(self, query: dict[str, list[str]]) -> bool:
        header = self.headers.get("X-Shawzify-Token")
        if header and secrets.compare_digest(header, self.app.token):
            return True
        supplied = (query.get("token") or [""])[0]
        return bool(supplied) and secrets.compare_digest(supplied, self.app.token)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status: int, body: bytes, content_type: str, *, cache: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Cache-Control", "public, max-age=3600" if cache else "no-store"
        )
        self.end_headers()
        self.wfile.write(body)

    # -- routes ---------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = unquote(parsed.path)

        if path == "/api/health":
            self._send_json(
                HTTPStatus.OK,
                {"ok": True, "version": APP_VERSION, "uptime": time.time() - self.app.started},
            )
            return

        if path.startswith("/api/"):
            if not self._origin_ok() or not self._authorised(query):
                self._send_json(HTTPStatus.FORBIDDEN, {"error": {"message": "Not authorised."}})
                return
            if path == "/api/events":
                self._stream_events()
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "No such endpoint."}})
            return

        if path == "/media" or path == "/api/media":
            if not self._authorised(query):
                self._send_json(HTTPStatus.FORBIDDEN, {"error": {"message": "Not authorised."}})
                return
            self._serve_media((query.get("path") or [""])[0])
            return

        self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        # Read the body before answering anything -- refusals included. The
        # connection is kept alive, so a body left unread is parsed as the next
        # request line: one rejected call would turn every later call on that
        # connection into 501 Unsupported method.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            self.close_connection = True
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": {"message": "Malformed request."}})
            return
        if length > _MAX_BODY_BYTES:
            # Draining megabytes to stay polite is worse than hanging up.
            self.close_connection = True
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": {"message": "Request too large."}}
            )
            return
        raw = self.rfile.read(length) if length else b""

        if not parsed.path.startswith("/api/"):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "No such endpoint."}})
            return
        if not self._origin_ok() or not self._authorised(query):
            self._send_json(HTTPStatus.FORBIDDEN, {"error": {"message": "Not authorised."}})
            return

        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": {"message": "Malformed request."}})
            return

        method = str(body.get("method") or parsed.path.rsplit("/", 1)[-1])
        params = body.get("params") or {}
        try:
            result = self.app.dispatch(method, params)
            self._send_json(HTTPStatus.OK, {"result": result})
        except ShawzifyError as exc:
            self.app.log.error("web." + method, exc)
            self._send_json(HTTPStatus.OK, {"error": exc.to_dict()})
        except Exception as exc:  # noqa: BLE001 - one bad call must not kill the server
            self.app.log.error("web." + method, exc)
            self._send_json(
                HTTPStatus.OK,
                {
                    "error": {
                        "code": "internal_error",
                        "message": "SHAWZIFY hit an unexpected problem running '"
                        + method
                        + "'.",
                        "hint": None,
                        "technical": traceback.format_exc(),
                    }
                },
            )

    # -- server-sent events ---------------------------------------------

    def _stream_events(self) -> None:
        q = self.app.hub.subscribe()
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    line = q.get(timeout=15.0)
                except queue.Empty:
                    # A comment line keeps proxies and the browser from timing out.
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(b"data: " + line.encode("utf-8") + b"\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.app.hub.unsubscribe(q)

    # -- files ------------------------------------------------------------

    def _serve_media(self, raw_path: str) -> None:
        """Serve a rendered preview or a fetched track back to the browser.

        Only files inside SHAWZIFY's own cache are served, so a crafted request
        cannot read arbitrary files off the machine.
        """
        from ..common.paths import cache_dir

        if not raw_path:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": {"message": "No path given."}})
            return
        try:
            target = Path(raw_path).resolve(strict=True)
            root = Path(cache_dir()).resolve()
            target.relative_to(root)
        except (OSError, ValueError):
            self._send_json(
                HTTPStatus.FORBIDDEN,
                {"error": {"message": "That file is outside SHAWZIFY's cache."}},
            )
            return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = target.read_bytes()
        self._send_bytes(HTTPStatus.OK, data, content_type)

    def _serve_static(self, path: str) -> None:
        root = self.app.frontend
        if root is None:
            self._send_bytes(
                HTTPStatus.OK,
                _NO_FRONTEND.encode("utf-8"),
                "text/html; charset=utf-8",
            )
            return

        relative = path.lstrip("/") or "index.html"
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            self._send_bytes(HTTPStatus.FORBIDDEN, b"Forbidden", "text/plain")
            return

        if not candidate.is_file():
            # Single-page app: unknown routes fall back to the shell.
            candidate = root / "index.html"
            if not candidate.is_file():
                self._send_bytes(HTTPStatus.NOT_FOUND, b"Not found", "text/plain")
                return

        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if candidate.suffix in (".html", ".json"):
            content_type += "; charset=utf-8"
        body = candidate.read_bytes()
        if candidate.name == "index.html":
            # Mark the page as served by this server, so the app knows which
            # transport it is on. Deliberately no token: the document is not
            # itself authorised (the browser fetches its assets without one),
            # so anything written into it is readable by any local process.
            # The page takes its token from its own URL instead.
            body = body.replace(
                b"</head>",
                (
                    '<script>window.__SHAWZIFY_WEB__={server:"shawzify",version:"'
                    + APP_VERSION
                    + '"};</script></head>'
                ).encode("utf-8"),
                1,
            )
        self._send_bytes(
            HTTPStatus.OK, body, content_type, cache=candidate.name != "index.html"
        )


_NO_FRONTEND = """<!doctype html>
<html><head><meta charset="utf-8"><title>SHAWZIFY</title>
<style>
 body{background:#0B0B0D;color:#EDEBE6;font:15px/1.6 Inter,Segoe UI,system-ui,sans-serif;
      display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
 main{max-width:34rem;padding:2rem}
 h1{font-size:1.4rem;letter-spacing:.16em;margin:0 0 1rem}
 code{background:#1B1B20;padding:.15rem .4rem;border-radius:4px;color:#E8A84C}
 p{color:#A9A69F}
</style></head>
<body><main>
<h1>SHAWZIFY</h1>
<p>The engine is running, but the web interface has not been built yet.</p>
<p>Build it once with <code>npm run build</code> inside <code>apps/desktop</code>,
then reload this page. The API at <code>/api/</code> works either way.</p>
</main></body></html>
"""


def token_path() -> Path:
    """Where the reusable access token lives (a per-user directory)."""
    from ..common.paths import app_dir

    return Path(app_dir()) / "web-token"


def stored_token(*, rotate: bool = False) -> str:
    """The token to serve with, reused across restarts unless rotated.

    A fresh token every run means every page left open dies with the server,
    which in practice means hunting for a new link after each restart. The
    token is already in the URL -- the address bar, the shell history -- so
    keeping a copy in the user's own app directory does not widen who can read
    it, and it lets an open tab reconnect on its own.
    """
    path = token_path()
    if not rotate:
        try:
            existing = path.read_text(encoding="utf-8").strip()
        except OSError:
            existing = ""
        if len(existing) >= 16 and existing.isascii() and existing.isprintable():
            return existing

    token = secrets.token_urlsafe(24)
    try:
        path.write_text(token, encoding="utf-8")
        os.chmod(path, 0o600)
    except OSError:
        # An unwritable app directory is not worth refusing to start over;
        # the token simply lasts for this run.
        pass
    return token


class WebServer:
    """A running local server. Use as a context manager or call ``stop()``."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8733,
        token: str | None = None,
        frontend: Path | None = None,
        rotate_token: bool = False,
    ) -> None:
        if host not in ("127.0.0.1", "localhost", "::1"):
            # Not a configuration mistake to tolerate: binding elsewhere would
            # expose a machine's music library and file paths to the network.
            raise ShawzifyError(
                "The SHAWZIFY web interface only ever binds to localhost.",
                technical="refused host: " + repr(host),
            )
        self.app = WebApp(
            token=token or stored_token(rotate=rotate_token),
            frontend=frontend if frontend is not None else find_frontend(),
        )
        handler = type("BoundHandler", (Handler,), {"app": self.app})
        self._server = ThreadingHTTPServer((host, port), handler)
        self._server.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def token(self) -> str:
        return self.app.token

    @property
    def url(self) -> str:
        return "http://127.0.0.1:" + str(self.port) + "/?token=" + self.token

    def start(self) -> WebServer:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.app.log.event("web.start", port=self.port, frontend=str(self.app.frontend))
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self.app.log.event("web.stop")

    def __enter__(self) -> WebServer:
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def serve(
    *,
    port: int = 8733,
    open_browser: bool = True,
    frontend: Path | None = None,
    rotate_token: bool = False,
) -> int:
    """Run the web interface until interrupted."""
    server = WebServer(port=port, frontend=frontend, rotate_token=rotate_token).start()
    print()
    print("  SHAWZIFY " + APP_VERSION + " - web interface")
    print()
    print("    " + server.url)
    print()
    if server.app.frontend is None:
        print("    The interface is not built. Run 'npm run build' in apps/desktop,")
        print("    then reload. The API works regardless.")
        print()
    print("    Bound to 127.0.0.1 only. Every API request needs the token in")
    print("    that link, so keep it to yourself -- it is the whole key.")
    print("    The link keeps working across restarts; --new-token replaces it.")
    print("    Press Ctrl+C to stop.")
    print()
    if open_browser:
        try:
            webbrowser.open(server.url)
        except Exception:  # noqa: BLE001 - a headless box has no browser
            pass
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n  Stopping.")
    finally:
        server.stop()
    return 0
