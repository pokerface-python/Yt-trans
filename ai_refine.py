"""AI-powered transcript refinement, translation, and summarisation.

Three modes are supported through the single :func:`refine` entry point:

* ``mode="refine"`` (default) — clean up an auto-generated transcript:
    * add proper punctuation and capitalization
    * fix obvious word-recognition errors using context
    * break the wall-of-text into readable paragraphs
    * preserve the ORIGINAL language and the speaker's wording

* ``mode="translate"`` — translate the whole transcript into
  ``target_language`` (``"en"`` and ``"hi"`` are first-class) via fast
  Google Translate (stdlib, no LLM). Set ``YT_TRANS_TRANSLATE_ENGINE=llm``
  to use the AI provider instead.

* ``mode="summarize"`` — produce a one-line ``**TL;DR:**`` plus 5–12
  bullet-point key notes in the source language. For long transcripts
  the summariser uses map-reduce (per-chunk bullets, then a combine
  pass) so the final output stays coherent rather than reading like a
  pile of disjoint mini-summaries.

Supports four LLM providers, picked automatically based on what is
configured. Priority order (highest first):

    1. Ollama       -- $0, local, no API key (just install + pull a model)
    2. Groq         -- free tier, very fast            (env: GROQ_API_KEY)
    3. Google Gemini-- generous free tier              (env: GOOGLE_API_KEY)
    4. OpenRouter   -- has :free model variants        (env: OPENROUTER_API_KEY)

Override the auto-pick with ``YT_TRANS_AI_PROVIDER=ollama|groq|gemini|openrouter``.
Override the model per provider with ``YT_TRANS_<PROVIDER>_MODEL``.

Uses stdlib ``urllib`` only — no new dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Optional

log = logging.getLogger("yt-trans.ai")


class RefinementError(RuntimeError):
    """Friendly wrapper around provider/network errors."""


# ---------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------

class _Provider:
    name: str = "abstract"
    model: str = ""

    def generate(self, prompt: str) -> str:
        """Send a prompt to the LLM and return the raw text response."""
        raise NotImplementedError

    @classmethod
    def is_available(cls) -> bool:
        return False


_OLLAMA_PREFERRED = (
    "llama3.2", "llama3.1", "llama3", "qwen2.5", "qwen2",
    "mistral", "gemma2", "gemma", "phi3", "phi", "llama2",
)


class OllamaProvider(_Provider):
    name = "ollama"

    def __init__(self, url: Optional[str] = None, model: Optional[str] = None):
        self.url = (
            url
            or os.environ.get("YT_TRANS_OLLAMA_URL", "http://localhost:11434")
        ).rstrip("/")
        self.model = (
            model
            or os.environ.get("YT_TRANS_OLLAMA_MODEL")
            or self._pick_installed_model()
            or "llama3.2"
        )

    def _pick_installed_model(self) -> Optional[str]:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=2) as resp:
                data = json.loads(resp.read())
        except Exception:  # noqa: BLE001
            return None
        names = [
            m.get("name", "")
            for m in data.get("models", [])
            if "embed" not in m.get("name", "").lower()
        ]
        if not names:
            return None
        for fam in _OLLAMA_PREFERRED:
            for n in names:
                if n.startswith(fam + ":") or n == fam:
                    return n
        return names[0]

    @classmethod
    def is_available(cls) -> bool:
        url = os.environ.get(
            "YT_TRANS_OLLAMA_URL", "http://localhost:11434"
        ).rstrip("/")
        try:
            with urllib.request.urlopen(f"{url}/api/tags", timeout=1.5) as resp:
                data = json.loads(resp.read())
        except Exception:  # noqa: BLE001
            return False
        has_chat = any(
            "embed" not in m.get("name", "").lower()
            for m in data.get("models", [])
        )
        return has_chat

    def generate(self, prompt: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 4096},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.url}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise RefinementError(
                f"Ollama HTTP {exc.code}: "
                f"{exc.read().decode('utf-8', 'replace')[:200]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RefinementError(f"Ollama request failed: {exc.reason}") from exc
        return _strip_wrapping(data.get("response", "").strip())


class _OpenAICompatible(_Provider):
    """Shared OpenAI-style chat-completions client (Groq, OpenRouter, ...)."""

    endpoint: str = ""
    api_key_env: str = ""
    extra_headers: dict[str, str] = {}

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.environ.get(self.api_key_env, "")
        self.model = model or self._default_model()

    def _default_model(self) -> str:
        raise NotImplementedError

    @classmethod
    def is_available(cls) -> bool:
        return bool(os.environ.get(cls.api_key_env))

    def generate(self, prompt: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            }
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            **self.extra_headers,
        }
        req = urllib.request.Request(self.endpoint, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise RefinementError(
                f"{self.name} HTTP {exc.code}: "
                f"{exc.read().decode('utf-8', 'replace')[:200]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RefinementError(
                f"{self.name} request failed: {exc.reason}"
            ) from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RefinementError(
                f"{self.name} returned unexpected payload: {str(data)[:200]}"
            ) from exc
        return _strip_wrapping(content.strip())


class GroqProvider(_OpenAICompatible):
    name = "groq"
    endpoint = "https://api.groq.com/openai/v1/chat/completions"
    api_key_env = "GROQ_API_KEY"

    def _default_model(self) -> str:
        return os.environ.get(
            "YT_TRANS_GROQ_MODEL", "llama-3.3-70b-versatile"
        )


class OpenRouterProvider(_OpenAICompatible):
    name = "openrouter"
    endpoint = "https://openrouter.ai/api/v1/chat/completions"
    api_key_env = "OPENROUTER_API_KEY"
    extra_headers = {
        "HTTP-Referer": "https://github.com/pokerface-python/Yt-trans",
        "X-Title": "yt-trans",
    }

    def _default_model(self) -> str:
        return os.environ.get(
            "YT_TRANS_OPENROUTER_MODEL",
            "meta-llama/llama-3.2-3b-instruct:free",
        )


class GeminiProvider(_Provider):
    name = "gemini"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = (
            api_key
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY", "")
        )
        self.model = model or os.environ.get(
            "YT_TRANS_GEMINI_MODEL", "gemini-2.0-flash-exp"
        )

    @classmethod
    def is_available(cls) -> bool:
        return bool(
            os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        )

    def generate(self, prompt: str) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        body = json.dumps(
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise RefinementError(
                f"Gemini HTTP {exc.code}: "
                f"{exc.read().decode('utf-8', 'replace')[:200]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RefinementError(f"Gemini request failed: {exc.reason}") from exc
        try:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RefinementError(
                f"Gemini returned unexpected payload: {str(data)[:200]}"
            ) from exc
        return _strip_wrapping(content.strip())


PROVIDERS = {
    "ollama": OllamaProvider,
    "groq": GroqProvider,
    "gemini": GeminiProvider,
    "openrouter": OpenRouterProvider,
}

# Order matters: first available wins when auto-detecting.
_AUTODETECT_ORDER = (
    OllamaProvider,
    GroqProvider,
    GeminiProvider,
    OpenRouterProvider,
)


_SETUP_HINT = (
    "No AI provider is configured. Pick one (any of these is free):\n"
    "  1. Ollama (local, no API key):\n"
    "       curl -fsSL https://ollama.com/install.sh | sh\n"
    "       ollama pull llama3.2:3b\n"
    "       ollama serve   # if not already running\n"
    "  2. Groq        -> https://console.groq.com/keys"
    "  ->  export GROQ_API_KEY=...\n"
    "  3. Gemini      -> https://aistudio.google.com/app/apikey"
    "  ->  export GOOGLE_API_KEY=...\n"
    "  4. OpenRouter  -> https://openrouter.ai/keys"
    "  ->  export OPENROUTER_API_KEY=...\n"
    "Then restart the server."
)


def get_provider(name: Optional[str] = None) -> _Provider:
    """Return a ready-to-use provider instance.

    If ``name`` (or env var ``YT_TRANS_AI_PROVIDER``) is given, that
    provider is used unconditionally. Otherwise we auto-pick the first
    one in priority order that looks configured.
    """
    name = name or os.environ.get("YT_TRANS_AI_PROVIDER")
    if name:
        cls = PROVIDERS.get(name.lower())
        if cls is None:
            raise RefinementError(
                f"Unknown provider {name!r}. Valid: {sorted(PROVIDERS)}"
            )
        return cls()

    for cls in _AUTODETECT_ORDER:
        if cls.is_available():
            log.info("Using AI provider: %s", cls.name)
            return cls()

    raise RefinementError(_SETUP_HINT)


# ---------------------------------------------------------------------------
# prompt + chunking
# ---------------------------------------------------------------------------

_REFINE_PROMPT_TEMPLATE = (
    "You are a meticulous transcript editor. The text below is an "
    "AUTO-GENERATED YouTube transcript. It typically has missing "
    "punctuation, wrong/missing capitalization, run-on sentences, and "
    "occasional word-recognition errors (homophones, mis-segmented words).\n"
    "\n"
    "Your task:\n"
    "1. Add proper punctuation (., ?, !, commas) and capitalization.\n"
    "2. Fix obvious word-recognition errors using context.\n"
    "3. Break the text into readable paragraphs (one topic each).\n"
    "4. Preserve the ORIGINAL language: {language}. Do not translate.\n"
    "5. Keep ALL of the speaker's original words and meaning. Do NOT "
    "summarise, do NOT add commentary, do NOT remove content.\n"
    "6. Return ONLY the cleaned transcript text. No preamble, no "
    "explanation, no 'Here is the cleaned transcript:' line. Just the text.\n"
    "\n"
    "Transcript:\n"
    '"""\n'
    "{text}\n"
    '"""\n'
)


_TRANSLATE_PROMPT_TEMPLATE = (
    "You are a professional translator. The text below is a YouTube "
    "transcript in {source_language}. Translate it into {target_language}.\n"
    "\n"
    "Rules:\n"
    "1. Translate the FULL text — do not summarise, omit, or add anything.\n"
    "2. Use natural, fluent {target_language}; not a literal word-for-word "
    "translation.\n"
    "3. Add proper punctuation and break the output into readable "
    "paragraphs (one topic per paragraph).\n"
    "4. Preserve the speaker's meaning, tone, and any technical terms.\n"
    "5. If the source already contains {target_language}, leave those "
    "sections untouched.\n"
    "6. Return ONLY the translated text. No preamble, no notes, no "
    "'Here is the translation:' line. Just the translation.\n"
    "\n"
    "Transcript:\n"
    '"""\n'
    "{text}\n"
    '"""\n'
)


# Full-pass summary (used when the transcript fits in one chunk).
_SUMMARY_PROMPT_TEMPLATE = (
    "You are an expert note-taker. The text below is a YouTube transcript "
    "in {language}. Produce a concise, well-structured summary in "
    "{language} formatted as KEY POINTS.\n"
    "\n"
    "Rules:\n"
    "1. Start with ONE line beginning exactly with '**TL;DR:** ' — a "
    "single-sentence summary of at most 25 words. Leave a blank line "
    "after it.\n"
    "2. Then 5–12 Markdown bullet points (each line starts with '- '), "
    "one specific fact/idea per bullet. Short and concrete.\n"
    "3. Follow the chronological/logical flow of the video.\n"
    "4. Capture: main topic, key arguments, examples, "
    "numbers/statistics, conclusions, action items.\n"
    "5. Skip filler, repetition, greetings, and self-promotion.\n"
    "6. Use the SAME language as the source: {language}.\n"
    "7. Return ONLY the TL;DR line and bullets. No preamble, no closing "
    "remarks, no 'Here is the summary:' line.\n"
    "\n"
    "Transcript:\n"
    '"""\n'
    "{text}\n"
    '"""\n'
)

# Per-chunk pass for very long transcripts. Output is a flat bullet list
# with NO TL;DR — the combine step adds the final TL;DR.
_SUMMARY_CHUNK_PROMPT_TEMPLATE = (
    "You are an expert note-taker. The text below is ONE SEGMENT of a "
    "longer YouTube transcript in {language}. Extract the key points "
    "from THIS SEGMENT ONLY.\n"
    "\n"
    "Rules:\n"
    "1. 3–8 Markdown bullet points (each line starts with '- ').\n"
    "2. One specific fact/idea per bullet.\n"
    "3. Use the SAME language as the source: {language}.\n"
    "4. Do NOT add a TL;DR — only bullets.\n"
    "5. Return ONLY the bullets. No preamble, no closing remarks.\n"
    "\n"
    "Segment:\n"
    '"""\n'
    "{text}\n"
    '"""\n'
)

# Reduce step: merge per-chunk bullet lists into one coherent summary
# with a TL;DR.
_SUMMARY_COMBINE_PROMPT_TEMPLATE = (
    "You are an expert note-taker. Below are bullet-point key notes "
    "extracted from consecutive segments of a YouTube transcript in "
    "{language}. Synthesize them into ONE coherent summary in "
    "{language}.\n"
    "\n"
    "Rules:\n"
    "1. Start with ONE line beginning exactly with '**TL;DR:** ' — a "
    "single-sentence summary of at most 25 words. Leave a blank line "
    "after it.\n"
    "2. Then 5–12 Markdown bullet points (each line starts with '- '), "
    "ordered to follow the original video.\n"
    "3. Deduplicate overlapping points; merge related ideas.\n"
    "4. Drop trivial bullets; keep what a viewer would actually want "
    "to remember.\n"
    "5. Use the SAME language as the source: {language}.\n"
    "6. Return ONLY the TL;DR line and bullets. No preamble, no closing "
    "remarks.\n"
    "\n"
    "Segment notes:\n"
    '"""\n'
    "{text}\n"
    '"""\n'
)


# BCP-47 codes -> human-friendly names used in prompts and UI labels.
_LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi (Devanagari script)",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese (Simplified)",
    "ar": "Arabic",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "gu": "Gujarati",
    "pa": "Punjabi (Gurmukhi)",
    "ur": "Urdu",
}


def _human_language(code: str) -> str:
    """Best-effort 'en' -> 'English' lookup; falls back to the raw code."""
    if not code:
        return "the source language"
    code = code.strip().lower()
    if code in _LANGUAGE_NAMES:
        return _LANGUAGE_NAMES[code]
    # Strip region suffix: 'en-US' -> 'en'
    base = code.split("-", 1)[0]
    return _LANGUAGE_NAMES.get(base, code)


def _build_prompt(
    text: str,
    language: str,
    *,
    mode: str = "refine",
    target_language: str = "",
    summary_role: str = "single",
) -> str:
    """Build the LLM prompt for the requested mode.

    ``summary_role`` is only meaningful when ``mode == "summarize"``:
        * ``"single"``  -> full summary with TL;DR + bullets
        * ``"chunk"``   -> per-segment bullets (no TL;DR), used in the
                           map step of map-reduce
        * ``"combine"`` -> reduce step: merge per-chunk bullets into the
                           final TL;DR + bullets
    """
    lang_human = _human_language(language)
    if mode == "translate":
        return _TRANSLATE_PROMPT_TEMPLATE.format(
            text=text,
            source_language=lang_human,
            target_language=_human_language(target_language),
        )
    if mode == "summarize":
        if summary_role == "chunk":
            tpl = _SUMMARY_CHUNK_PROMPT_TEMPLATE
        elif summary_role == "combine":
            tpl = _SUMMARY_COMBINE_PROMPT_TEMPLATE
        else:
            tpl = _SUMMARY_PROMPT_TEMPLATE
        return tpl.format(text=text, language=lang_human)
    return _REFINE_PROMPT_TEMPLATE.format(
        text=text, language=language or "unknown"
    )


_WRAPPER_RE = re.compile(
    r"^(?:here(?:'s| is)[^\n:]*[:\n]|sure[!.,]?|okay[!.,]?|"
    r"the cleaned transcript[^\n:]*[:\n]|cleaned transcript[^\n:]*[:\n])",
    re.IGNORECASE,
)
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$", re.MULTILINE)


def _strip_wrapping(text: str) -> str:
    """Remove common LLM preambles and stray code fences."""
    text = _FENCE_RE.sub("", text).strip()
    if (text.startswith('"""') and text.endswith('"""')) or (
        text.startswith("```") and text.endswith("```")
    ):
        text = text.strip("`").strip('"').strip()
    text = _WRAPPER_RE.sub("", text, count=1).strip()
    return text


_SENTENCE_RE = re.compile(r"(?<=[.!?।॥])\s+")


def _chunk_text(text: str, max_words: int) -> list[str]:
    """Split text into chunks ~max_words long, preferring paragraph then
    sentence boundaries."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    cur: list[str] = []
    cw = 0
    for p in paragraphs:
        pw = len(p.split())
        if cw + pw > max_words and cur:
            chunks.append("\n\n".join(cur))
            cur, cw = [p], pw
        else:
            cur.append(p)
            cw += pw
    if cur:
        chunks.append("\n\n".join(cur))

    final: list[str] = []
    for c in chunks:
        if len(c.split()) <= int(max_words * 1.25):
            final.append(c)
            continue
        sentences = _SENTENCE_RE.split(c)
        sub: list[str] = []
        sw = 0
        for s in sentences:
            ws = len(s.split())
            if sw + ws > max_words and sub:
                final.append(" ".join(sub))
                sub, sw = [s], ws
            else:
                sub.append(s)
                sw += ws
        if sub:
            final.append(" ".join(sub))
    return final


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------

# Summary mode can use a larger chunk size because the LLM only needs to
# OUTPUT a few bullet points, not the whole input back. Bigger chunks =
# fewer round-trips = better global coherence.
_SUMMARY_CHUNK_WORDS = 4000

_VALID_MODES = ("refine", "translate", "summarize")


def refine(
    text: str,
    language: str = "en",
    *,
    mode: str = "refine",
    target_language: str = "",
    provider: Optional[_Provider] = None,
    max_chunk_words: int = 1200,
) -> dict:
    """Run an AI transformation over a transcript.

    Parameters
    ----------
    text : full transcript text (paragraph-formatted is fine).
    language : BCP-47 code of the source transcript (``"en"``, ``"hi"`` …).
    mode : one of
        * ``"refine"`` (default) — clean up punctuation/capitalization,
          keep the original language.
        * ``"translate"`` — translate the full text into
          ``target_language``.
        * ``"summarize"`` — produce a TL;DR + 5–12 bullet-point key
          notes. Long transcripts are summarised via map-reduce so the
          output stays coherent end-to-end.
    target_language : BCP-47 code (``"en"``, ``"hi"`` …). Required when
        ``mode == "translate"``; ignored otherwise.
    provider : explicit provider instance, or ``None`` to auto-pick.
    max_chunk_words : split the input into chunks of at most this many
        words so the LLM context window isn't blown. ``summarize`` mode
        uses its own larger chunk size internally.

    Returns
    -------
    dict with keys ``refined``, ``provider``, ``model``, ``chunks``,
    ``mode``, ``target_language``. (``refined`` holds the AI output for
    any mode — kept for backwards compatibility.)

    Raises
    ------
    RefinementError : provider/network failure or invalid arguments.
    """
    mode = (mode or "refine").lower()
    target_language = (target_language or "").strip().lower()

    if mode not in _VALID_MODES:
        raise RefinementError(
            f"unknown mode {mode!r}; expected one of {list(_VALID_MODES)}"
        )
    if mode == "translate" and not target_language:
        raise RefinementError(
            "translate mode requires target_language (e.g. 'en' or 'hi')"
        )

    if not text or not text.strip():
        return {
            "refined": "",
            "provider": "",
            "model": "",
            "chunks": 0,
            "mode": mode,
            "target_language": target_language,
        }

    if mode == "translate":
        from fast_translate import (
            TranslationError,
            chunk_for_translation,
            translate_text,
            use_fast_translator,
        )

        if use_fast_translator():
            try:
                output = translate_text(
                    text,
                    source_language=language,
                    target_language=target_language,
                )
            except TranslationError as exc:
                raise RefinementError(str(exc)) from exc
            chunks_n = len(chunk_for_translation(text)) or 1
            log.info(
                "fast translation complete (%d chunks, %s -> %s)",
                chunks_n,
                language,
                target_language,
            )
            return {
                "refined": output,
                "provider": "google-translate",
                "model": "gtx",
                "chunks": chunks_n,
                "mode": mode,
                "target_language": target_language,
            }
        log.info("YT_TRANS_TRANSLATE_ENGINE=llm — using AI provider for translate")

    provider = provider or get_provider()

    if mode == "summarize":
        output, chunks_used = _run_summarize(text, language, provider)
        return {
            "refined": output,
            "provider": provider.name,
            "model": provider.model,
            "chunks": chunks_used,
            "mode": mode,
            "target_language": "",
        }

    chunks = _chunk_text(text, max_chunk_words)
    log.info(
        "%s %d chunks (%d words total) via %s/%s%s",
        "translating" if mode == "translate" else "refining",
        len(chunks),
        len(text.split()),
        provider.name,
        provider.model,
        f" -> {target_language}" if mode == "translate" else "",
    )

    out_parts: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        log.info("  chunk %d/%d (%d words)", i, len(chunks), len(chunk.split()))
        prompt = _build_prompt(
            chunk, language, mode=mode, target_language=target_language
        )
        out_parts.append(provider.generate(prompt))

    return {
        "refined": "\n\n".join(out_parts).strip(),
        "provider": provider.name,
        "model": provider.model,
        "chunks": len(chunks),
        "mode": mode,
        "target_language": target_language,
    }


def _run_summarize(
    text: str, language: str, provider: _Provider
) -> tuple[str, int]:
    """Map-reduce summary. Returns (summary_text, chunk_count).

    Single chunk: one LLM call, full summary.
    Multiple chunks: per-chunk bullet extraction, then one combine call.
    """
    chunks = _chunk_text(text, _SUMMARY_CHUNK_WORDS)
    n_words = len(text.split())
    log.info(
        "summarising %d words in %d chunk(s) via %s/%s",
        n_words, len(chunks), provider.name, provider.model,
    )

    if len(chunks) <= 1:
        prompt = _build_prompt(
            chunks[0] if chunks else text, language, mode="summarize"
        )
        return provider.generate(prompt), max(1, len(chunks))

    log.info("  map: extracting bullets from %d chunks", len(chunks))
    partials: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        log.info(
            "    chunk %d/%d (%d words)", i, len(chunks), len(chunk.split())
        )
        prompt = _build_prompt(
            chunk, language, mode="summarize", summary_role="chunk"
        )
        partials.append(provider.generate(prompt))

    log.info("  reduce: combining %d partial summaries", len(partials))
    joined = "\n\n".join(
        f"--- Segment {i + 1} ---\n{p.strip()}"
        for i, p in enumerate(partials)
    )
    combine_prompt = _build_prompt(
        joined, language, mode="summarize", summary_role="combine"
    )
    return provider.generate(combine_prompt), len(chunks)
