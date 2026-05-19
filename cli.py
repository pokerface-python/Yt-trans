"""Command line interface for the all-text YouTube transcriptor.

Usage examples
--------------
    python cli.py https://youtu.be/IjIVBleSfc4
    python cli.py IjIVBleSfc4 -l hi en
    python cli.py <url> --format srt --output out.srt
    python cli.py <url> --list
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import Sequence

from transcriptor import (
    DEFAULT_LANGUAGES,
    TranscriptionError,
    Transcriptor,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yt-trans",
        description=(
            "Convert a YouTube video into a clean, full-text transcript. "
            "Accepts any YouTube URL or 11-char video id."
        ),
    )
    p.add_argument(
        "url",
        nargs="?",
        help=(
            "YouTube URL or 11-char video id "
            "(optional when --serve is used)"
        ),
    )
    p.add_argument(
        "-l",
        "--languages",
        nargs="+",
        default=list(DEFAULT_LANGUAGES),
        metavar="CODE",
        help=(
            "Preferred language codes in priority order "
            f"(default: {' '.join(DEFAULT_LANGUAGES)})"
        ),
    )
    p.add_argument(
        "-f",
        "--format",
        default="paragraphs",
        choices=["text", "paragraphs", "json", "srt", "vtt", "rich", "html"],
        help="Output format (default: paragraphs)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write the transcript to this file instead of stdout",
    )
    p.add_argument(
        "--open",
        dest="open_in_browser",
        action="store_true",
        help=(
            "Render a self-contained HTML view (embedded player + "
            "clickable timestamps) and open it in your default browser"
        ),
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="Only list the transcripts available for the video and exit",
    )
    p.add_argument(
        "--preserve-formatting",
        action="store_true",
        help="Keep HTML tags like <i>/<b> from the source captions",
    )
    p.add_argument(
        "--prefer-generated",
        action="store_true",
        help="Prefer auto-generated transcripts over manual ones",
    )
    p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress the metadata header; print only the transcript body",
    )
    p.add_argument(
        "--serve",
        action="store_true",
        help=(
            "Start a local web server with a URL input bar. Paste a YouTube "
            "URL into the page and the transcript will be fetched on demand. "
            "Combine with --open to auto-launch your browser."
        ),
    )
    p.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host/interface to bind the server to (default: 127.0.0.1)",
    )
    p.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind the server to (default: 8000)",
    )
    return p


def _print_header(result, stream=sys.stdout) -> None:
    flavour = "auto-generated" if result.is_generated else "manual"
    print(
        f"=== {result.url}\n"
        f"=== language: {result.language} ({result.language_code}) | "
        f"{flavour} | {result.snippet_count} snippets | "
        f"~{result.duration:.0f}s\n",
        file=stream,
    )


def _list_transcripts(transcriptor: Transcriptor, url: str) -> int:
    transcript_list = transcriptor.list_transcripts(url)
    rows = []
    for t in transcript_list:
        rows.append(
            (
                t.language_code,
                t.language,
                "auto" if t.is_generated else "manual",
                "yes" if getattr(t, "is_translatable", False) else "no",
            )
        )

    if not rows:
        print("No transcripts available for this video.")
        return 1

    widths = [max(len(r[i]) for r in rows + [("code", "language", "type", "translatable")]) for i in range(4)]
    headers = ("code", "language", "type", "translatable")
    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for row in rows:
        print(fmt.format(*row))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.serve:
        from server import serve

        serve(
            host=args.host,
            port=args.port,
            languages=args.languages,
            open_browser=args.open_in_browser,
        )
        return 0

    if not args.url:
        print(
            "error: url is required (or pass --serve to run the web UI)",
            file=sys.stderr,
        )
        return 2

    transcriptor = Transcriptor(
        languages=args.languages,
        prefer_manual=not args.prefer_generated,
    )

    try:
        if args.list:
            return _list_transcripts(transcriptor, args.url)

        result = transcriptor.transcribe(
            args.url,
            languages=args.languages,
            preserve_formatting=args.preserve_formatting,
        )

        if args.open_in_browser:
            html_body = transcriptor.to_format(result, "html")
            if args.output:
                target = args.output
                if target.suffix.lower() != ".html":
                    target = target.with_suffix(".html")
            else:
                tmp = tempfile.NamedTemporaryFile(
                    prefix=f"yt-trans-{result.video_id}-",
                    suffix=".html",
                    delete=False,
                    mode="w",
                    encoding="utf-8",
                )
                tmp.write(html_body)
                tmp.close()
                target = Path(tmp.name)
            if args.output:
                target.write_text(html_body, encoding="utf-8")
            if not args.quiet:
                _print_header(result, sys.stderr)
            url = target.resolve().as_uri()
            print(f"Opening {url}", file=sys.stderr)
            webbrowser.open(url)
            return 0

        body = transcriptor.to_format(result, args.format)

        if args.output:
            args.output.write_text(body, encoding="utf-8")
            if not args.quiet:
                _print_header(result, sys.stderr)
            print(f"Wrote {len(body):,} chars to {args.output}", file=sys.stderr)
        else:
            if not args.quiet:
                _print_header(result)
            print(body)
        return 0
    except TranscriptionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("aborted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
