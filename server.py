"""Tiny stdlib HTTP server for the yt-trans HTML viewer.

Endpoints:

    GET  /                       -> landing page with a URL input bar
    GET  /?url=<url>&lang=en,hi  -> fetches the transcript and renders
                                    the full interactive HTML view
    POST /api/refine             -> AI clean-up / translation / summary
    POST /api/export             -> PDF / TXT / DOC export of visible transcript

Uses stdlib ``http.server`` plus optional ``fpdf2`` for Unicode PDF export.
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
from export_formats import ExportError, build_doc_html, build_pdf, build_txt
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

        def _send_bytes(
            self,
            data: bytes,
            content_type: str,
            *,
            filename: str = "download",
            status: int = 200,
        ) -> None:
            safe_name = filename.replace('"', "")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{safe_name}"',
            )
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _read_json_body(self) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                length = 0
            if length <= 0 or length > _MAX_REFINE_BODY:
                self._send_json(
                    {"error": f"body must be 1..{_MAX_REFINE_BODY} bytes"},
                    status=400,
                )
                return None
            try:
                raw = self.rfile.read(length)
                return json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._send_json(
                    {"error": f"invalid JSON: {exc}"}, status=400
                )
                return None

        def _handle_export(self, payload: dict) -> None:
            fmt = (payload.get("format") or "pdf").strip().lower()
            text = (payload.get("text") or "").strip()
            title = (payload.get("title") or "Transcript").strip() or "Transcript"
            video_url = (payload.get("url") or "").strip()

            if not text:
                self._send_json({"error": "field 'text' is required"}, status=400)
                return

            try:
                if fmt == "pdf":
                    data = build_pdf(text, title, video_url)
                    mime = "application/pdf"
                    ext = "pdf"
                elif fmt == "txt":
                    data = build_txt(text, title, video_url)
                    mime = "text/plain; charset=utf-8"
                    ext = "txt"
                elif fmt in ("doc", "word"):
                    data = build_doc_html(text, title, video_url)
                    mime = "application/msword; charset=utf-8"
                    ext = "doc"
                else:
                    self._send_json(
                        {"error": f"unknown format {fmt!r}; use pdf, txt, or doc"},
                        status=400,
                    )
                    return
            except ExportError as exc:
                self._send_json({"error": str(exc)}, status=503)
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("export %s failed", fmt)
                self._send_json(
                    {"error": f"export failed: {exc}"}, status=500
                )
                return

            filename = (payload.get("filename") or f"transcript.{ext}").strip()
            self._send_bytes(data, mime, filename=filename)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            payload = self._read_json_body()
            if payload is None:
                return

            if parsed.path == "/api/export":
                self._handle_export(payload)
                return

            if parsed.path != "/api/refine":
                self.send_error(404, "Not found")
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
            if mode not in ("refine", "translate", "summarize"):
                self._send_json(
                    {"error": f"invalid mode {mode!r}; "
                              "expected 'refine', 'translate', or 'summarize'"},
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
    try:
        import fpdf  # noqa: F401
    except ImportError:
        print(
            "warning: fpdf2 is not installed — PDF export will fail. "
            "Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
        )
    else:
        from export_formats import _find_indic_fallback_font, _find_latin_font

        try:
            _find_latin_font()
        except ExportError as exc:
            print(f"warning: PDF Latin font missing — {exc}")
        else:
            if _find_indic_fallback_font() is None:
                print(
                    "warning: no Devanagari font found — Hindi PDFs may show "
                    "missing glyphs. Install fonts-noto-core (apt) or "
                    "fonts-noto-devanagari."
                )

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
