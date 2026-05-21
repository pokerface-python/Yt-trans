"""Fast transcript translation without an LLM.

Uses Google Translate's public ``translate.googleapis.com`` endpoint via
stdlib :mod:`urllib` (same approach as many lightweight translators).
Chunked for long transcripts; much faster than local Ollama for EN↔HI.

Set ``YT_TRANS_TRANSLATE_ENGINE=llm`` to force the old AI-based translator.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("yt-trans.translate")

_GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
_MAX_CHUNK_CHARS = 4500
_USER_AGENT = "yt-trans/1.0"
_RETRYABLE = (TimeoutError, urllib.error.URLError)
_PAUSE_BETWEEN_CHUNKS = 0.15

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?।॥])\s+")


class TranslationError(RuntimeError):
    """Translation failed (network, rate limit, invalid language)."""


def use_fast_translator() -> bool:
    """True unless the user explicitly opted into LLM translation."""
    engine = os.environ.get("YT_TRANS_TRANSLATE_ENGINE", "google").strip().lower()
    return engine not in ("llm", "ai", "ollama")


def _google_lang(code: str) -> str:
    code = (code or "auto").strip().lower()
    if not code or code in ("auto", "unknown"):
        return "auto"
    return code.split("-", 1)[0]


def _request_translate(text: str, source: str, target: str, *, timeout: float) -> str:
    params = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": source,
            "tl": target,
            "dt": "t",
            "q": text,
        }
    )
    url = f"{_GOOGLE_URL}?{params}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    if not payload or not payload[0]:
        raise TranslationError("empty response from translation service")

    parts = [seg[0] for seg in payload[0] if seg and seg[0]]
    if not parts:
        raise TranslationError("could not parse translation response")
    return "".join(parts)


def _translate_chunk(
    text: str,
    source: str,
    target: str,
    *,
    timeout: float,
    retries: int,
) -> str:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return _request_translate(text, source, target, timeout=timeout)
        except _RETRYABLE as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(0.4 * (attempt + 1))
                continue
            raise TranslationError(
                f"translation timed out or network error after {retries + 1} "
                f"tries: {exc}"
            ) from exc
        except urllib.error.HTTPError as exc:
            raise TranslationError(
                f"translation HTTP {exc.code}: {exc.reason}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise TranslationError(f"invalid translation response: {exc}") from exc
    raise TranslationError(f"translation failed: {last_exc}")


def _split_oversized_paragraph(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    sentences = _SENTENCE_SPLIT.split(paragraph)
    out: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for sentence in sentences:
        if not sentence:
            continue
        add = len(sentence) + (1 if cur else 0)
        if cur_len + add > max_chars and cur:
            out.append(" ".join(cur))
            cur, cur_len = [sentence], len(sentence)
        else:
            cur.append(sentence)
            cur_len += add
    if cur:
        out.append(" ".join(cur))
    final: list[str] = []
    for piece in out:
        if len(piece) <= max_chars:
            final.append(piece)
        else:
            for i in range(0, len(piece), max_chars):
                final.append(piece[i : i + max_chars])
    return final


def chunk_for_translation(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
    """Split text for the Google API while keeping paragraph breaks."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0

    for para in paragraphs:
        pieces = _split_oversized_paragraph(para, max_chars)
        for piece in pieces:
            piece_len = len(piece)
            sep = 2 if current else 0
            if current_len + sep + piece_len > max_chars and current:
                flush()
            if piece_len > max_chars:
                flush()
                for i in range(0, piece_len, max_chars):
                    chunks.append(piece[i : i + max_chars])
                continue
            if current:
                current_len += 2
            current.append(piece)
            current_len += piece_len
    flush()
    return chunks


def translate_text(
    text: str,
    *,
    source_language: str = "en",
    target_language: str = "hi",
    timeout: float | None = None,
) -> str:
    """Translate *text* from *source_language* to *target_language*."""
    text = (text or "").strip()
    if not text:
        return ""

    target = _google_lang(target_language)
    if not target or target == "auto":
        raise TranslationError("target_language is required (e.g. 'en' or 'hi')")

    source = _google_lang(source_language)
    if source == target:
        return text

    timeout_sec = timeout if timeout is not None else float(
        os.environ.get("YT_TRANS_TRANSLATE_TIMEOUT", "45")
    )
    retries = int(os.environ.get("YT_TRANS_TRANSLATE_RETRIES", "2"))

    pieces = chunk_for_translation(text)
    if not pieces:
        return ""

    log.info(
        "fast-translate %d chunk(s) (%d chars) %s -> %s",
        len(pieces),
        len(text),
        source,
        target,
    )

    translated: list[str] = []
    for i, chunk in enumerate(pieces, 1):
        log.info("  translate chunk %d/%d (%d chars)", i, len(pieces), len(chunk))
        translated.append(
            _translate_chunk(
                chunk,
                source,
                target,
                timeout=timeout_sec,
                retries=retries,
            )
        )
        if i < len(pieces) and _PAUSE_BETWEEN_CHUNKS:
            time.sleep(_PAUSE_BETWEEN_CHUNKS)

    return "\n\n".join(translated).strip()
