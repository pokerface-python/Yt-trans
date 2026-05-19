"""Tiny stdlib HTTP server for the yt-trans HTML viewer.

Endpoints:

    GET  /                       -> landing page with a URL input bar
    GET  /?url=<url>&lang=en,hi  -> fetches the transcript and renders
                                    the full interactive HTML view
    POST /api/refine             -> AI clean-up / translation, JSON body:
        {
          "text":     "<full transcript>",
          "language": "en",                 # source BCP-47 (optional)
          "mode":     "refine" | "translate",
          "target_language": "en"|"hi"|...  # required if mode=translate
        }

No external dependencies — just `http.server` from the standard library.
"""

from __future__ import annotations

import json
import logging
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Sequence
from urllib.parse import parse_qs, urlparse

from ai_refine import RefinementError, refine
from html_view import render, render_landing
from transcriptor import DEFAULT_LANGUAGES, TranscriptionError, Transcriptor

log = logging.getLogger("yt-trans.server")

_MAX_REFINE_BODY = 5 * 1024 * 1024  # 5 MB cap on POST body to /api/refine


def _build_handler(default_langs: Sequence[str]):
    """Build a request handler class bound to a default language list."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "yt-trans/1.0"

        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            log.info("%s - " + fmt, self.address_string(), *args)

        def _send_html(self, body: str, status: int = 200) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload: dict, status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/refine":
                self.send_error(404, "Not found")
                return

            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                length = 0
            if length <= 0 or length > _MAX_REFINE_BODY:
                self._send_json(
                    {"error": f"body must be 1..{_MAX_REFINE_BODY} bytes"},
                    status=400,
                )
                return

            try:
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._send_json(
                    {"error": f"invalid JSON: {exc}"}, status=400
                )
                return

            text = (payload.get("text") or "").strip()
            language = (payload.get("language") or "en").strip() or "en"
            mode = (payload.get("mode") or "refine").strip().lower() or "refine"
            target_language = (
                payload.get("target_language") or ""
            ).strip().lower()

            if not text:
                self._send_json({"error": "field 'text' is required"}, status=400)
                return
            if mode not in ("refine", "translate"):
                self._send_json(
                    {"error": f"invalid mode {mode!r}; "
                              "expected 'refine' or 'translate'"},
                    status=400,
                )
                return
            if mode == "translate" and not target_language:
                self._send_json(
                    {"error": "translate mode requires 'target_language' "
                              "(e.g. 'en' or 'hi')"},
                    status=400,
                )
                return

            try:
                result = refine(
                    text,
                    language=language,
                    mode=mode,
                    target_language=target_language,
                )
            except RefinementError as exc:
                self._send_json({"error": str(exc)}, status=503)
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("AI %s crashed", mode)
                self._send_json(
                    {"error": f"unexpected: {exc}"}, status=500
                )
                return

            self._send_json(result)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path not in ("/", ""):
                self.send_error(404, "Not found")
                return

            qs = parse_qs(parsed.query, keep_blank_values=False)
            url = (qs.get("url") or [""])[0].strip()
            lang_raw = (qs.get("lang") or [""])[0].strip()
            langs = (
                [c.strip() for c in lang_raw.replace(";", ",").split(",") if c.strip()]
                or list(default_langs)
            )

            if not url:
                self._send_html(render_landing())
                return

            try:
                result = Transcriptor(languages=langs).transcribe(url)
            except TranscriptionError as exc:
                self._send_html(
                    render_landing(
                        error=str(exc),
                        prefilled_url=url,
                        prefilled_langs=",".join(langs),
                    ),
                    status=400,
                )
                return
            except ValueError as exc:
                self._send_html(
                    render_landing(
                        error=str(exc),
                        prefilled_url=url,
                        prefilled_langs=",".join(langs),
                    ),
                    status=400,
                )
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("unexpected error fetching %s", url)
                self._send_html(
                    render_landing(
                        error=f"unexpected error: {exc}",
                        prefilled_url=url,
                        prefilled_langs=",".join(langs),
                    ),
                    status=500,
                )
                return

            self._send_html(
                render(
                    result,
                    prefilled_url=url,
                    prefilled_langs=",".join(langs),
                )
            )

    return Handler


def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    languages: Optional[Sequence[str]] = None,
    open_browser: bool = False,
) -> None:
    """Start the HTTP server and block until interrupted.

    Parameters
    ----------
    host : interface to bind to (default ``127.0.0.1``; use ``0.0.0.0`` to
        accept connections from other machines on your network)
    port : TCP port (default ``8000``)
    languages : default language priority used when the form omits ``lang``
    open_browser : if True, open the landing page in the user's default
        browser once the server is ready
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    default_langs = list(languages) if languages else list(DEFAULT_LANGUAGES)
    handler_cls = _build_handler(default_langs)

    httpd = ThreadingHTTPServer((host, port), handler_cls)
    display_host = host if host not in ("0.0.0.0", "::") else "127.0.0.1"
    landing_url = f"http://{display_host}:{port}/"
    print(f"yt-trans serving on {landing_url}  (Ctrl-C to stop)")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(landing_url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        httpd.server_close()
