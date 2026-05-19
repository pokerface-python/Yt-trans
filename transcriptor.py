"""High-level YouTube transcription helpers.

Built on top of `youtube-transcript-api`. Goals:
    * accept any YouTube URL or bare 11-char id
    * pick the best transcript automatically (manual > generated, language preference)
    * return a clean full-text transcript plus rich metadata
    * write the transcript to .txt / .json / .srt / .vtt on demand
    * surface helpful, user-friendly errors

This is intentionally a thin, well-documented wrapper so it stays easy to
extend later (translation, summarisation, chaptering, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Union

from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    FetchedTranscript,
    FetchedTranscriptSnippet,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)
from youtube_transcript_api.formatters import (
    JSONFormatter,
    SRTFormatter,
    TextFormatter,
    WebVTTFormatter,
)

from utils import (
    clean_text,
    extract_video_id,
    safe_filename,
    to_paragraphs,
)

DEFAULT_LANGUAGES: Sequence[str] = ("en", "en-US", "en-GB", "hi")


class TranscriptionError(RuntimeError):
    """Friendly wrapper around youtube-transcript-api errors."""


@dataclass
class TranscriptionResult:
    """Everything we know about a fetched transcript."""

    video_id: str
    url: str
    language: str
    language_code: str
    is_generated: bool
    full_text: str
    paragraphs: str
    snippet_count: int
    duration: float
    raw: list = field(default_factory=list)

    def save(
        self,
        path: Union[str, Path, None] = None,
        *,
        as_paragraphs: bool = True,
    ) -> Path:
        """Write the transcript to a .txt file and return its path."""
        out = Path(path) if path else Path(
            f"{safe_filename(self.video_id)}.{self.language_code}.txt"
        )
        body = self.paragraphs if as_paragraphs else self.full_text
        header = (
            f"# Transcript for {self.url}\n"
            f"# language: {self.language} ({self.language_code})"
            f" | {'auto-generated' if self.is_generated else 'manual'}"
            f" | {self.snippet_count} snippets"
            f" | ~{self.duration:.0f}s\n\n"
        )
        out.write_text(header + body, encoding="utf-8")
        return out


class Transcriptor:
    """High-level façade for fetching YouTube transcripts.

    Example
    -------
    >>> t = Transcriptor()
    >>> result = t.transcribe("https://youtu.be/IjIVBleSfc4")
    >>> print(result.full_text[:200])
    """

    def __init__(
        self,
        languages: Sequence[str] = DEFAULT_LANGUAGES,
        *,
        prefer_manual: bool = True,
        api: Optional[YouTubeTranscriptApi] = None,
    ) -> None:
        self.languages = list(languages)
        self.prefer_manual = prefer_manual
        self._api = api or YouTubeTranscriptApi()

    def list_transcripts(self, url_or_id: str):
        """Return the raw TranscriptList for the given video."""
        video_id = extract_video_id(url_or_id)
        try:
            return self._api.list(video_id)
        except Exception as exc:  # noqa: BLE001 - re-raised below
            raise self._friendly(exc, video_id) from exc

    def transcribe(
        self,
        url_or_id: str,
        *,
        languages: Optional[Sequence[str]] = None,
        preserve_formatting: bool = False,
    ) -> TranscriptionResult:
        """Fetch the best available transcript for ``url_or_id``.

        Strategy:
            1. Try the requested languages (manual first, then generated).
            2. Fall back to any available transcript (manual first).
            3. As a last resort, translate the first translatable
               transcript into the top requested language.
        """
        video_id = extract_video_id(url_or_id)
        wanted = list(languages) if languages else list(self.languages)

        try:
            transcript_list = self._api.list(video_id)
            transcript = self._pick_transcript(transcript_list, wanted)
            fetched = transcript.fetch(preserve_formatting=preserve_formatting)
        except CouldNotRetrieveTranscript as exc:
            raise self._friendly(exc, video_id) from exc
        except Exception as exc:  # noqa: BLE001
            raise self._friendly(exc, video_id) from exc

        snippets = list(fetched)
        full_text = clean_text(" ".join(s.text for s in snippets))
        duration = 0.0
        if snippets:
            last = snippets[-1]
            duration = float(last.start) + float(last.duration)

        return TranscriptionResult(
            video_id=video_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
            language=getattr(fetched, "language", transcript.language),
            language_code=getattr(
                fetched, "language_code", transcript.language_code
            ),
            is_generated=bool(
                getattr(fetched, "is_generated", transcript.is_generated)
            ),
            full_text=full_text,
            paragraphs=to_paragraphs(full_text),
            snippet_count=len(snippets),
            duration=duration,
            raw=fetched.to_raw_data(),
        )

    def to_format(
        self,
        result: TranscriptionResult,
        fmt: str,
    ) -> str:
        """Render a TranscriptionResult into a supported text format.

        Supported: ``text`` (default cleaned full text), ``paragraphs``,
        ``json``, ``srt``, ``vtt``.
        """
        fmt = fmt.lower().strip()
        if fmt in {"text", "txt"}:
            return result.full_text
        if fmt == "paragraphs":
            return result.paragraphs

        fetched = FetchedTranscript(
            snippets=[
                FetchedTranscriptSnippet(
                    text=s["text"],
                    start=s["start"],
                    duration=s["duration"],
                )
                for s in result.raw
            ],
            video_id=result.video_id,
            language=result.language,
            language_code=result.language_code,
            is_generated=result.is_generated,
        )

        if fmt == "json":
            return JSONFormatter().format_transcript(fetched, indent=2)
        if fmt == "srt":
            return SRTFormatter().format_transcript(fetched)
        if fmt in {"vtt", "webvtt"}:
            return WebVTTFormatter().format_transcript(fetched)
        if fmt == "rich":
            return TextFormatter().format_transcript(fetched)
        if fmt == "html":
            from html_view import render as render_html
            return render_html(result)

        raise ValueError(
            f"unknown format {fmt!r}; expected one of: "
            "text, paragraphs, json, srt, vtt, rich, html"
        )

    def _pick_transcript(self, transcript_list, wanted: List[str]):
        finders = (
            ("find_manually_created_transcript", "find_generated_transcript")
            if self.prefer_manual
            else ("find_generated_transcript", "find_manually_created_transcript")
        )

        for finder_name in finders:
            try:
                return getattr(transcript_list, finder_name)(wanted)
            except NoTranscriptFound:
                continue

        try:
            return transcript_list.find_transcript(wanted)
        except NoTranscriptFound:
            pass

        available = list(transcript_list)
        if available:
            manual = [t for t in available if not t.is_generated]
            ordered = manual + [t for t in available if t.is_generated]
            any_codes = [t.language_code for t in ordered]
            try:
                return transcript_list.find_transcript(any_codes)
            except NoTranscriptFound:
                pass

            translatable = next(
                (t for t in ordered if getattr(t, "is_translatable", False)),
                None,
            )
            if translatable is not None and wanted:
                return translatable.translate(wanted[0])

            return ordered[0]

        return transcript_list.find_transcript(wanted)

    @staticmethod
    def _friendly(exc: Exception, video_id: str) -> TranscriptionError:
        if isinstance(exc, TranscriptsDisabled):
            msg = "transcripts are disabled for this video"
        elif isinstance(exc, NoTranscriptFound):
            msg = "no transcript could be found in the requested languages"
        elif isinstance(exc, VideoUnavailable):
            msg = "video is unavailable (private, removed, or region-blocked)"
        elif isinstance(exc, CouldNotRetrieveTranscript):
            msg = str(exc).splitlines()[0] or "could not retrieve transcript"
        else:
            msg = f"{type(exc).__name__}: {exc}"
        return TranscriptionError(f"[{video_id}] {msg}")


def transcribe(url_or_id: str, **kwargs) -> TranscriptionResult:
    """Convenience one-shot helper."""
    return Transcriptor().transcribe(url_or_id, **kwargs)
