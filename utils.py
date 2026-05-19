"""Helpers for parsing YouTube URLs and normalizing text."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_PATH_ID_RE = re.compile(
    r"^/(?:shorts|embed|live|v|e)/(?P<id>[A-Za-z0-9_-]{11})"
)

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
    "youtu.be",
}


def extract_video_id(url_or_id: str) -> str:
    """Extract the 11-char video id from a URL or bare id.

    Supports watch?v=, youtu.be/, /shorts/, /embed/, /live/, /v/, /e/
    as well as URLs with extra query params (pp, t, list, etc.).

    Raises ValueError if no valid id can be found.
    """
    if not url_or_id or not isinstance(url_or_id, str):
        raise ValueError("video url/id must be a non-empty string")

    candidate = url_or_id.strip()

    if _VIDEO_ID_RE.match(candidate):
        return candidate

    if "://" not in candidate:
        candidate = "https://" + candidate

    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()

    if host not in _YOUTUBE_HOSTS:
        raise ValueError(f"not a recognised YouTube URL: {url_or_id!r}")

    if host == "youtu.be":
        vid = parsed.path.lstrip("/").split("/", 1)[0]
        if _VIDEO_ID_RE.match(vid):
            return vid
        raise ValueError(f"could not parse video id from {url_or_id!r}")

    qs = parse_qs(parsed.query)
    if "v" in qs and qs["v"]:
        vid = qs["v"][0]
        if _VIDEO_ID_RE.match(vid):
            return vid

    m = _PATH_ID_RE.match(parsed.path)
    if m:
        return m.group("id")

    raise ValueError(f"could not parse video id from {url_or_id!r}")


def clean_text(text: str) -> str:
    """Tidy up transcript text for the 'all text' output.

    - collapse runs of whitespace (incl. newlines) into single spaces
    - remove leftover music/sound bracket noise like [Music] when standalone
    - strip leading/trailing whitespace
    """
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    return text.strip()


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?।॥])\s+")


def to_paragraphs(text: str, sentences_per_paragraph: int = 3) -> str:
    """Group sentences into short, readable paragraphs.

    Splits on Latin (``. ! ?``) *and* Devanagari (``। ॥``) sentence-enders so
    Hindi / mixed-language transcripts get broken up correctly.

    Transcripts (especially auto-generated ones) often contain very long
    sentences with sparse punctuation, so we keep paragraphs short — three
    sentences each by default — to give the text room to breathe.
    """
    text = clean_text(text)
    if not text:
        return ""

    parts = _SENTENCE_SPLIT_RE.split(text)
    if len(parts) <= 1:
        return text

    paragraphs = []
    for i in range(0, len(parts), sentences_per_paragraph):
        chunk = " ".join(parts[i : i + sentences_per_paragraph]).strip()
        if chunk:
            paragraphs.append(chunk)
    return "\n\n".join(paragraphs)


def safe_filename(name: str, max_length: int = 80) -> str:
    """Make a string safe to use as a filename component."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-")
    return (name or "transcript")[:max_length]


def format_timestamp(seconds: float) -> str:
    """Format seconds as H:MM:SS or M:SS for readability."""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def looks_like_video_id(value: Optional[str]) -> bool:
    return bool(value and _VIDEO_ID_RE.match(value))
