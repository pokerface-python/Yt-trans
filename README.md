# yt-trans

> **Drop in any YouTube URL → get a clean, ready-to-read transcript back.**
> In your terminal, as `.txt` / `.srt` / `.vtt` / `.json`, or as an interactive
> HTML page with the video embedded and clickable timestamps.

Built on top of
[`youtube-transcript-api`](https://github.com/jdepoix/youtube-transcript-api),
so it does **not** need a YouTube API key, OAuth, or a headless browser.

---

## Table of contents

- [Features](#features)
- [Quick start](#quick-start)
- [Two ways to use it](#two-ways-to-use-it)
  - [1. Web UI (`--serve`)](#1-web-ui----serve)
  - [2. One-shot CLI](#2-one-shot-cli)
- [CLI reference](#cli-reference)
- [Output formats](#output-formats)
- [The interactive HTML viewer](#the-interactive-html-viewer)
- [AI Refine](#ai-refine)
- [Python API](#python-api)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## Features

- **Accepts every YouTube URL shape** — `watch?v=`, `youtu.be/`,
  `/shorts/`, `/embed/`, `/live/`, `m.youtube.com`, `music.youtube.com`,
  plus bare 11-char ids.
- **Smart language selection** — tries your preferred languages in
  priority order, prefers manually-created transcripts, falls back to
  auto-generated, and as a last resort uses YouTube's auto-translate.
- **Clean full-text output** — Unicode-safe, collapsed whitespace,
  paragraphs with proper sentence breaks (works for Hindi `।`/`॥` too).
- **Multiple export formats** — `text`, `paragraphs`, `srt`, `vtt`,
  `json`, `rich`, `html`.
- **Built-in web UI (`--serve`)** — tiny stdlib HTTP server with a URL
  input bar in the browser. Zero extra dependencies. Shareable deep
  links: `?url=...&lang=hi,en`.
- **Interactive HTML viewer (`--open`)** — self-contained page with the
  YouTube player embedded, clickable timestamps that seek the video in
  place, a docking floating mini-player, copy/download buttons, and a
  7-way theme switcher (Auto / Dark / Light / Sepia / Midnight /
  Solarized / Forest) saved to localStorage.
- **AI Refine button** — auto-generated captions are noisy (missing
  punctuation, run-on sentences, occasional word-recognition errors).
  One click sends the transcript through a free LLM that adds
  punctuation, fixes obvious mistakes, and breaks the wall-of-text into
  proper paragraphs. Toggle between *Original* and *AI Refined* views.
  Supports Ollama (local, $0), Groq, Google Gemini, and OpenRouter.
- **Friendly error messages** for `TranscriptsDisabled`,
  `VideoUnavailable`, `IpBlocked`, `NoTranscriptFound`, etc.
- **Both a Python API and a CLI** — embed it in your scripts or use it
  straight from the shell.

---

## Quick start

```bash
git clone https://github.com/pokerface-python/Yt-trans.git
cd Yt-trans

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Requires **Python 3.10+**.

---

## Two ways to use it

### 1. Web UI (`--serve`)

The easiest way — paste URLs into a form in your browser, no need to
re-run anything per video.

```bash
python cli.py --serve --open
```

Opens `http://127.0.0.1:8000/` in your default browser:

```
┌──────────────────────────────────────────────────────┐
│ YT Transcriptor                          Theme ▼    │
├──────────────────────────────────────────────────────┤
│                                                      │
│        Turn any YouTube video into clean text        │
│                                                      │
│   ┌──────────────────────────────────┐  ┌─────────┐ │
│   │ https://youtube.com/watch?v=…    │  │ en,hi   │ │
│   └──────────────────────────────────┘  └─────────┘ │
│                       ╔═══════════════╗              │
│                       ║ Get transcript ║              │
│                       ╚═══════════════╝              │
│                                                      │
│  Try: IjIVBleSfc4 (Hindi) · jNQXAC9IVRw (first ever) │
└──────────────────────────────────────────────────────┘
```

After submitting you land on the interactive transcript viewer — and the
same URL bar stays pinned at the top so you can keep swapping videos
without going back to `/`.

URLs are deep-linkable and shareable:

```
http://127.0.0.1:8000/?url=IjIVBleSfc4&lang=hi
http://127.0.0.1:8000/?url=https://youtu.be/jNQXAC9IVRw
```

Bind to your LAN so phones/tablets can use it too:

```bash
python cli.py --serve --host 0.0.0.0 --port 9000
```

### 2. One-shot CLI

For scripting, piping, batch jobs, or just printing the text once.

```bash
# print to stdout
python cli.py "https://youtu.be/IjIVBleSfc4"

# open an interactive HTML view in your browser
python cli.py "https://youtu.be/IjIVBleSfc4" --open

# save plain text to a file
python cli.py IjIVBleSfc4 -l hi en -o transcript.txt

# export SRT subtitles
python cli.py IjIVBleSfc4 --format srt -o out.srt

# see which transcripts a video has
python cli.py IjIVBleSfc4 --list
```

---

## CLI reference

```text
python cli.py [URL] [options]
```

| flag                       | meaning                                                |
| -------------------------- | ------------------------------------------------------ |
| positional `URL`           | YouTube URL or 11-char id (optional when `--serve`)    |
| `-l, --languages CODE ...` | preferred language codes in priority order             |
| `-f, --format FMT`         | one of `text`, `paragraphs` (default), `json`, `srt`, `vtt`, `rich`, `html` |
| `-o, --output PATH`        | write to file instead of stdout                        |
| `--open`                   | render the interactive HTML view and open it in your default browser (also auto-opens the served URL when combined with `--serve`) |
| `--serve`                  | start the local web UI on `http://127.0.0.1:8000/`     |
| `--host HOST`              | bind interface for `--serve` (default `127.0.0.1`; use `0.0.0.0` to expose on LAN) |
| `--port PORT`              | port for `--serve` (default `8000`)                    |
| `--list`                   | list available transcripts for the video and exit      |
| `--preserve-formatting`    | keep `<i>` / `<b>` tags from the captions              |
| `--prefer-generated`       | prefer auto-generated transcripts over manual ones     |
| `-q, --quiet`              | omit the metadata header                               |
| `-h, --help`               | full help                                              |

---

## Output formats

| `--format`   | what you get                                                  |
| ------------ | ------------------------------------------------------------- |
| `text`       | one continuous line of cleaned text                           |
| `paragraphs` | the same text, broken into ~3-sentence paragraphs *(default)* |
| `rich`       | YouTube-style block-text view with sparse line breaks         |
| `json`       | raw timed snippets `[{text, start, duration}, ...]`           |
| `srt`        | standard SubRip subtitle file                                 |
| `vtt`        | WebVTT subtitle file                                          |
| `html`       | the full self-contained interactive viewer (see below)        |

---

## The interactive HTML viewer

The `html` format (or `--open`) builds a single self-contained `.html`
file with:

- **Click-to-load YouTube player** — privacy-enhanced
  `youtube-nocookie.com` embed with a thumbnail preview shown until you
  click play. This avoids "Error 153 / Video player configuration error"
  issues seen with strict browsers, ad-blockers, or `file://` origins.
- **Two reading modes** — *Paragraphs* (wide, reading-optimised text)
  and *Timestamped* (every snippet with a `0:42`-style timestamp).
- **Click-to-seek** — every timestamped snippet is clickable; the
  embedded player jumps to that exact moment.
- **Docking mini-player** — once playback starts, the player docks
  itself as a small floating widget at the bottom-right of the viewport
  so the text stays full-width while you watch. `⤢` undocks, `×`
  closes.
- **Copy-to-clipboard** and **Download .txt** buttons.
- **7-way theme switcher** in the top right — Auto, Dark, Light, Sepia,
  Midnight, Solarized, Forest — your choice is remembered in
  localStorage.
- **URL input bar** pinned at the top (when served by `--serve`) so you
  can swap to a different video without leaving the page.

The file is fully offline (no external CSS/JS); only the embedded
YouTube player itself needs the network.

---

## AI Refine

YouTube's auto-generated captions are noisy — missing punctuation,
run-on sentences, lowercase everywhere, occasional word-recognition
errors. The viewer has a **Refine with AI** button (next to *Copy* and
*Download*) that sends the transcript through a free LLM and shows you
a cleaned-up version. Switching back is one click on the
*Original ⇄ AI Refined* toggle.

**Available only when running via `python cli.py --serve`** (the
button is disabled on offline `file://` pages because there's no server
to call).

### Supported providers (all free)

The first one that's configured wins, in this priority order:

| # | provider     | setup                                                                                                                            | model default                          |
|---|--------------|----------------------------------------------------------------------------------------------------------------------------------|----------------------------------------|
| 1 | **Ollama**   | `curl -fsSL https://ollama.com/install.sh \| sh` then `ollama pull llama3.2`                                                     | first installed chat model (auto-pick) |
| 2 | **Groq**     | grab a key at <https://console.groq.com/keys>, then `export GROQ_API_KEY=...`                                                    | `llama-3.3-70b-versatile`              |
| 3 | **Gemini**   | grab a key at <https://aistudio.google.com/app/apikey>, then `export GOOGLE_API_KEY=...`                                         | `gemini-2.0-flash-exp`                 |
| 4 | **OpenRouter** | grab a key at <https://openrouter.ai/keys>, then `export OPENROUTER_API_KEY=...`                                              | `meta-llama/llama-3.2-3b-instruct:free` |

Force a specific provider with `YT_TRANS_AI_PROVIDER=ollama|groq|gemini|openrouter`.
Force a specific model with `YT_TRANS_OLLAMA_MODEL` /
`YT_TRANS_GROQ_MODEL` / `YT_TRANS_GEMINI_MODEL` /
`YT_TRANS_OPENROUTER_MODEL`.

Recommended: **Ollama** if you don't mind a one-time ~2 GB model
download (full privacy, no rate limits, completely offline once
installed). **Groq** if you want zero local setup and the fastest
response.

### What it does (and doesn't)

The prompt asks the model to:

- add proper punctuation and capitalization
- fix obvious word-recognition errors using context
- break the text into readable paragraphs
- **preserve the speaker's original words, meaning, and language**
- *not* summarise, translate, or add commentary

Long transcripts are split into ~1200-word chunks so they fit in the
context window — chunks are processed sequentially, server-side, and
stitched back together.

### Programmatic use

```python
from ai_refine import refine

result = refine(
    "raw transcript text...",
    language="en",
    max_chunk_words=1200,
)
print(result["refined"])          # cleaned text
print(result["provider"])         # e.g. "ollama"
print(result["model"])            # e.g. "llama3.2:latest"
print(result["chunks"])           # number of pieces sent to the LLM
```

### HTTP API

```http
POST /api/refine
Content-Type: application/json

{"text": "raw transcript here...", "language": "en"}
```

Returns:

```json
{
  "refined":  "...",
  "provider": "ollama",
  "model":    "llama3.2:latest",
  "chunks":   3
}
```

Errors come back as `{"error": "..."}` with status `400` (bad request),
`503` (no provider configured / provider failed), or `500` (unexpected).

---

## Python API

```python
from transcriptor import Transcriptor

t = Transcriptor(languages=["en", "hi"])
result = t.transcribe("https://youtu.be/IjIVBleSfc4")

print(result.full_text)       # one cleaned-up string
print(result.paragraphs)      # the same text grouped into paragraphs
print(result.language)        # e.g. "English"
print(result.language_code)   # e.g. "en"
print(result.is_generated)    # True if auto-generated by YouTube
print(result.raw)             # [{text, start, duration}, ...]

# write a .txt with a metadata header
result.save("my_transcript.txt")

# convert to any other supported format on demand
srt  = t.to_format(result, "srt")
html = t.to_format(result, "html")
```

### One-shot helper

```python
from transcriptor import transcribe

text = transcribe("https://youtu.be/IjIVBleSfc4").full_text
```

### Run the web server programmatically

```python
from server import serve

serve(host="0.0.0.0", port=8000, languages=["en", "hi"], open_browser=True)
```

---

## Project layout

```
Yt-trans/
├── transcriptor.py   # Transcriptor class + TranscriptionResult
├── html_view.py      # render TranscriptionResult -> standalone HTML page
├── server.py         # tiny stdlib HTTP server (--serve web UI + /api/refine)
├── ai_refine.py      # LLM-backed transcript cleaner (Ollama/Groq/Gemini/OpenRouter)
├── utils.py          # URL/id parsing, text cleanup, timestamp formatting
├── cli.py            # argparse CLI entry-point (--serve, --open, --format, ...)
├── trans_api.py      # minimal usage example
├── requirements.txt  # single dep: youtube-transcript-api
├── .gitignore
└── README.md
```

No external dependencies beyond
[`youtube-transcript-api`](https://pypi.org/project/youtube-transcript-api/) —
the HTTP server is pure stdlib (`http.server`).

---

## Troubleshooting

**`IpBlocked` / `RequestBlocked`**
YouTube blocks many cloud-provider IPs (AWS, GCP, Azure, …). Run
locally, or configure a residential proxy. See the upstream
[Working around IP bans](https://github.com/jdepoix/youtube-transcript-api#working-around-ip-bans-requestblocked-or-ipblocked-exception)
section for proxy setup.

**`TranscriptsDisabled` / `NoTranscriptFound`**
The video either has no captions at all or none in the languages you
asked for. Try `python cli.py <id> --list` to see what's actually
available, then pass them with `-l`.

**Browser shows "Error 153 / Video player configuration error"**
Already worked around — the viewer uses `youtube-nocookie.com` and a
click-to-load thumbnail. If you still see it, the video itself has
embedding disabled by its owner; click *Open on YouTube ↗* in the
viewer.

**`Address already in use` when running `--serve`**
Pick another port: `python cli.py --serve --port 8765`.

**The CLI hangs on a long video**
Some very long videos take a while because YouTube returns a large
transcript blob. Use `--quiet` to skip the metadata header and stream
the body straight to a file: `python cli.py <id> -q -o out.txt`.

**AI Refine returns *"No AI provider is configured"***
Pick one (any is free):

- **Easiest, fully local:** install Ollama
  (`curl -fsSL https://ollama.com/install.sh | sh`), pull a model
  (`ollama pull llama3.2`), make sure it's running (`ollama serve`),
  then click *Refine with AI* again — the server auto-detects it.
- **Easiest, no local install:** sign up for free at
  [console.groq.com/keys](https://console.groq.com/keys), then run the
  server with `GROQ_API_KEY=... python cli.py --serve`.
- See [AI Refine](#ai-refine) for all four options.

**AI Refine returns *"Ollama HTTP 404: model not found"***
Your Ollama is running but doesn't have the model the picker chose.
Either `ollama pull <name>` it, or set `YT_TRANS_OLLAMA_MODEL` to one
you have (e.g. `export YT_TRANS_OLLAMA_MODEL=mistral`). Run
`curl -s http://localhost:11434/api/tags` to list what's installed.

**AI Refine takes forever on long videos**
LLM inference is sequential per chunk. A 30-minute video chunked into
~5 pieces typically takes 30–60 s on Groq/Gemini and 1–3 min on a
local 3B Ollama model. Use a smaller/faster model
(`YT_TRANS_OLLAMA_MODEL=llama3.2:3b`) or one of the cloud providers
for speed.

**Generic warning: undocumented YouTube endpoint**
`youtube-transcript-api` calls an undocumented part of the YouTube web
API, so it can break if YouTube changes things. If `pip install -U
youtube-transcript-api` doesn't fix it, check the upstream
[issues page](https://github.com/jdepoix/youtube-transcript-api/issues).

---

## Contributing

PRs welcome. Before submitting, please:

```bash
python -m compileall .                   # syntax check
python cli.py <some-video-id> --list     # quick smoke test
python cli.py --serve --port 8765 &      # web UI smoke test
curl -sI 'http://127.0.0.1:8765/' | head -1
kill %1
```

Areas that would be especially welcome:

- Summarisation / Q&A over the transcript (LLM-backed)
- Chapter detection
- Translation pipeline (beyond YouTube's auto-translate)
- A `POST /api/transcript` JSON endpoint for programmatic clients
- Docker image / GitHub Action

---

## License

No license file is included by default. If you intend to make this
repository public, add one — MIT is a safe choice. See
[choosealicense.com](https://choosealicense.com/) for help picking one.
