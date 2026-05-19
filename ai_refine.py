"""AI-powered transcript refinement.

Cleans up auto-generated YouTube transcripts:
    * adds proper punctuation and capitalization
    * fixes obvious word-recognition errors using context
    * breaks the wall-of-text into readable paragraphs
    * preserves the original language and the speaker's wording

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

    def refine_chunk(self, text: str, language: str) -> str:
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

    def refine_chunk(self, text: str, language: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "prompt": _build_prompt(text, language),
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

    def refine_chunk(self, text: str, language: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": _build_prompt(text, language)},
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

    def refine_chunk(self, text: str, language: str) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        body = json.dumps(
            {
                "contents": [{"parts": [{"text": _build_prompt(text, language)}]}],
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

_PROMPT_TEMPLATE = (
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


def _build_prompt(text: str, language: str) -> str:
    return _PROMPT_TEMPLATE.format(text=text, language=language or "unknown")


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

def refine(
    text: str,
    language: str = "en",
    *,
    provider: Optional[_Provider] = None,
    max_chunk_words: int = 1200,
) -> dict:
    """Refine a transcript with an AI provider.

    Returns ``{"refined": ..., "provider": ..., "model": ..., "chunks": N}``.
    Raises :class:`RefinementError` on failure (network, missing provider,
    bad response, etc.).
    """
    if not text or not text.strip():
        return {"refined": "", "provider": "", "model": "", "chunks": 0}

    provider = provider or get_provider()
    chunks = _chunk_text(text, max_chunk_words)
    log.info(
        "refining %d chunks (%d words total) via %s/%s",
        len(chunks),
        len(text.split()),
        provider.name,
        provider.model,
    )

    refined_parts: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        log.info("  chunk %d/%d (%d words)", i, len(chunks), len(chunk.split()))
        refined_parts.append(provider.refine_chunk(chunk, language))

    return {
        "refined": "\n\n".join(refined_parts).strip(),
        "provider": provider.name,
        "model": provider.model,
        "chunks": len(chunks),
    }
