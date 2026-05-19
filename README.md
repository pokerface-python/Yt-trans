# yt-trans — YouTube full-text transcriptor

Drop in any YouTube URL (or 11-char video id) and get a clean, ready-to-read
transcript back — in your terminal, as a `.txt` / `.srt` / `.vtt` / `.json`
file, or as an interactive HTML page with the video embedded and clickable
timestamps.

Built on top of
[`youtube-transcript-api`](https://github.com/jdepoix/youtube-transcript-api),
so it does **not** need a YouTube API key, OAuth, or a headless browser.

## Features

- Accepts any YouTube URL shape: `watch?v=`, `youtu.be/`, `/shorts/`,
  `/embed/`, `/live/`, `m.youtube.com`, `music.youtube.com`, plus bare ids.
- Smart language selection: tries your preferred languages, prefers
  manually-created transcripts, falls back to auto-generated, and as a last
  resort uses YouTube's auto-translate.
- Clean full-text output — Unicode-safe, collapsed whitespace, paragraphs
  with proper sentence breaks (works for Hindi `।`/`॥` too).
- Multiple export formats: `text`, `paragraphs`, `srt`, `vtt`, `json`,
  `rich`, `html`.
- One-flag browser view (`--open`): self-contained HTML page with embedded
  YouTube player, clickable timestamps, copy/download buttons, and a 7-way
  theme switcher (Auto / Dark / Light / Sepia / Midnight / Solarized / Forest).
- Built-in **local web UI** (`--serve`): launches a tiny HTTP server with a
  URL input bar so you can fetch new videos right from the browser — no
  external dependencies.
- Friendly error messages for `TranscriptsDisabled`, `VideoUnavailable`,
  `IpBlocked`, etc.
- Both a Python API (`Transcriptor`) and a CLI (`cli.py`).

## Quick start

```bash
git clone https://github.com/pokerface-python/Yt-trans.git
cd Yt-trans

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Then pick one of these two ways to use it:

```bash
# 1) Web UI — paste URLs into a form in your browser
python cli.py --serve --open
#    -> opens http://127.0.0.1:8000/ with a URL input bar

# 2) One-shot CLI — fetch a single video and open the HTML view
python cli.py "https://youtu.be/IjIVBleSfc4" --open
```

## CLI

```bash
# default: prints paragraph-formatted full text to stdout
python cli.py https://www.youtube.com/watch?v=IjIVBleSfc4

# launch the local web UI (paste URLs into a form in your browser)
python cli.py --serve --open
python cli.py --serve --host 0.0.0.0 --port 9000   # bind to LAN, custom port

# open a browser view (player + clickable timestamps + paragraphs)
python cli.py https://youtu.be/IjIVBleSfc4 -l hi en --open

# save that browser view to a specific .html instead of a temp file
python cli.py IjIVBleSfc4 -l hi --open -o transcript.html

# or just generate the HTML without auto-opening
python cli.py IjIVBleSfc4 --format html -o transcript.html

# pick languages (priority order) and save plain text
python cli.py IjIVBleSfc4 -l hi en -o transcript.txt

# export SRT subtitles
python cli.py https://youtu.be/IjIVBleSfc4 --format srt -o out.srt

# list every available transcript for a video
python cli.py IjIVBleSfc4 --list

# get raw JSON with timing data
python cli.py IjIVBleSfc4 --format json -o out.json
```

Flags:

| flag                       | meaning                                                |
| -------------------------- | ------------------------------------------------------ |
| `-l, --languages CODE ...` | preferred language codes in priority order             |
| `-f, --format FMT`         | `text`, `paragraphs` (default), `json`, `srt`, `vtt`, `rich`, `html` |
| `-o, --output PATH`        | write to file instead of stdout                        |
| `--open`                   | render an interactive HTML view and open it in your default browser (also auto-opens the served URL when combined with `--serve`) |
| `--serve`                  | start the local web UI on `http://127.0.0.1:8000/`     |
| `--host HOST`              | bind interface for `--serve` (default `127.0.0.1`; use `0.0.0.0` for LAN) |
| `--port PORT`              | port for `--serve` (default `8000`)                    |
| `--list`                   | list available transcripts and exit                    |
| `--preserve-formatting`    | keep `<i>` / `<b>` tags from the captions              |
| `--prefer-generated`       | prefer auto-generated transcripts over manual ones     |
| `-q, --quiet`              | omit the metadata header                               |

### Browser view

`--open` builds a single self-contained HTML file with:

- the original YouTube video as a click-to-load player
  (privacy-enhanced `youtube-nocookie.com` embed, with a thumbnail
  preview shown until you click play — avoids "Error 153 / Video player
  configuration error" issues),
- the transcript shown both as paragraphs *and* as a timestamped list
  (the paragraph view is wide and reading-optimised),
- every snippet clickable — clicking it seeks the embedded player to that
  exact moment,
- copy-to-clipboard and download-as-`.txt` buttons,
- a 7-way **theme switcher** in the top right — Auto, Dark, Light, Sepia,
  Midnight, Solarized, Forest — your choice is remembered in localStorage,
- the full video URL and metadata pinned in the footer.

The file is fully offline (no external CSS/JS); only the embedded YouTube
player needs the network.

### Web UI (`--serve`)

```bash
python cli.py --serve --open
```

This starts a tiny stdlib HTTP server (no Flask, no extra dependencies)
on `http://127.0.0.1:8000/`. The landing page is just a single input bar:
paste any YouTube URL (or 11-char id), optionally a comma-separated list of
language codes (e.g. `en,hi`), hit *Get transcript*, and the same
interactive viewer described above renders in place.

URLs are also shareable: `http://127.0.0.1:8000/?url=IjIVBleSfc4&lang=hi`
works as a direct deep link.

The same input bar is present at the top of every rendered transcript page,
so you can keep swapping videos without going back to the home page.

Bind to your LAN with `--host 0.0.0.0` to make it reachable from other
devices on your network (phones, tablets, etc.).

## Python API

```python
from transcriptor import Transcriptor

transcriptor = Transcriptor(languages=["en", "hi"])
result = transcriptor.transcribe("https://youtu.be/IjIVBleSfc4")

print(result.full_text)        # one cleaned-up string
print(result.paragraphs)       # the same text grouped into paragraphs
print(result.language_code)    # e.g. "en"
print(result.is_generated)     # True if auto-generated by YouTube
print(result.raw)              # list[{text, start, duration}] for further processing

result.save("my_transcript.txt")

# convert to any supported format on demand
srt = transcriptor.to_format(result, "srt")
```

### One-shot helper

```python
from transcriptor import transcribe
text = transcribe("https://youtu.be/IjIVBleSfc4").full_text
```

## Project layout

```
yt-trans/
├── transcriptor.py   # Transcriptor class + TranscriptionResult
├── html_view.py      # render TranscriptionResult -> standalone HTML page
├── server.py         # tiny stdlib HTTP server backing the --serve web UI
├── utils.py          # URL/id parsing, text cleanup, timestamp formatting
├── cli.py            # argparse CLI entry-point (--serve, --open, etc.)
├── trans_api.py      # minimal usage example
├── requirements.txt
└── README.md
```

## Notes

- YouTube blocks many cloud-provider IPs. If you see `IpBlocked` or
  `RequestBlocked`, run locally or configure a residential proxy
  (see the upstream
  [README](https://github.com/jdepoix/youtube-transcript-api#working-around-ip-bans-requestblocked-or-ipblocked-exception)).
- This relies on an undocumented YouTube endpoint, so it can break if YouTube
  changes things — keep `youtube-transcript-api` up to date.

## Contributing

PRs welcome. Before submitting:

```bash
python -m compileall .             # syntax check
python cli.py <some-video-id> --list   # smoke test
```

## License

No license file is included by default — add one (e.g. `MIT`) before making
the repository public if you want others to be able to reuse the code.
