"""Render a TranscriptionResult into a self-contained HTML page.

The page bundles:
    * the original YouTube video (privacy-enhanced nocookie embed, with the
      iframe-API enabled so we can drive it from JS) plus a click-to-load
      thumbnail fallback for browsers/extensions that block the embed
      (this is what triggers the "Error 153 / configuration error" message)
    * a 7-way theme switcher (Auto / Dark / Light / Sepia / Midnight /
      Solarized / Forest) saved to localStorage
    * the cleaned full-text transcript grouped into paragraphs
    * a timestamped view where every snippet is a clickable link that seeks
      the embedded player to that exact moment.

The output is a single .html file with inlined CSS + JS — no external
assets, works offline (the embedded YouTube player itself is the only
network dependency).
"""

from __future__ import annotations

import html
import json
from typing import TYPE_CHECKING

from utils import format_timestamp

if TYPE_CHECKING:
    from transcriptor import TranscriptionResult


_TEMPLATE = """<!doctype html>
<html lang="{lang}" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — transcript</title>
<style>
  :root,
  html[data-theme="dark"] {{
    --bg: #0f1115;     --panel: #161922;   --text: #e7e9ee;
    --muted: #9aa3b2;  --accent: #ff5252;  --link: #7cb7ff;
    --border: #262b36; --hover: #1f2330;
  }}
  html[data-theme="light"] {{
    --bg: #f7f8fa;     --panel: #ffffff;   --text: #1b1f27;
    --muted: #5b6675;  --accent: #d22d2d;  --link: #1559c2;
    --border: #e3e7ee; --hover: #f0f3f8;
  }}
  html[data-theme="sepia"] {{
    --bg: #f5ecd9;     --panel: #fbf5e6;   --text: #4b3a23;
    --muted: #8a755a;  --accent: #b35a1f;  --link: #8a4a14;
    --border: #e3d6b6; --hover: #efe3c6;
  }}
  html[data-theme="midnight"] {{
    --bg: #0a1024;     --panel: #111a36;   --text: #d6e1ff;
    --muted: #7a8bbf;  --accent: #4cc9ff;  --link: #82d3ff;
    --border: #1c2750; --hover: #16224a;
  }}
  html[data-theme="solarized"] {{
    --bg: #002b36;     --panel: #073642;   --text: #eee8d5;
    --muted: #93a1a1;  --accent: #b58900;  --link: #2aa198;
    --border: #0d4250; --hover: #0c3a47;
  }}
  html[data-theme="forest"] {{
    --bg: #102018;     --panel: #163024;   --text: #e0efe2;
    --muted: #8fb3a0;  --accent: #f5b14b;  --link: #7ddca4;
    --border: #21402f; --hover: #1c3a2a;
  }}
  @media (prefers-color-scheme: light) {{
    html[data-theme="auto"] {{
      --bg: #f7f8fa;     --panel: #ffffff;   --text: #1b1f27;
      --muted: #5b6675;  --accent: #d22d2d;  --link: #1559c2;
      --border: #e3e7ee; --hover: #f0f3f8;
    }}
  }}

  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--text);
    font: 16px/1.7 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
      "Helvetica Neue", Arial, "Noto Sans", "Noto Sans Devanagari", sans-serif;
    transition: background .2s ease, color .2s ease; }}
  a {{ color: var(--link); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}

  header {{ padding: 16px 28px; border-bottom: 1px solid var(--border);
    background: var(--panel); position: sticky; top: 0; z-index: 5;
    display: flex; align-items: center; gap: 16px; }}
  header h1 {{ margin: 0; font-size: 17px; font-weight: 600;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }}

  .theme-switch {{ display: inline-flex; align-items: center; gap: 8px;
    color: var(--muted); font-size: 13px; }}
  .theme-switch select {{ background: var(--bg); color: var(--text);
    border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px;
    font: inherit; font-size: 13px; cursor: pointer; }}

  main {{ max-width: 1100px; margin: 0 auto;
    padding: 28px 32px 32px; }}

  .transcript-col h2 {{ font-size: 13px; text-transform: uppercase;
    letter-spacing: .1em; color: var(--muted); margin: 0 0 12px; }}
  .tabs {{ display: inline-flex; background: var(--panel); border: 1px solid var(--border);
    border-radius: 999px; padding: 4px; margin-bottom: 20px; }}
  .tabs button {{ background: transparent; border: 0; color: var(--muted);
    padding: 7px 16px; border-radius: 999px; cursor: pointer; font: inherit;
    font-size: 13px; transition: all .15s ease; }}
  .tabs button.active {{ background: var(--accent); color: white; }}

  .view {{ display: none; }}
  .view.active {{ display: block; }}

  #paragraph-view {{ font-size: 18px; line-height: 1.85; }}
  #paragraph-view p {{ margin: 0 0 20px; }}

  .snippet {{ display: flex; gap: 14px; align-items: baseline;
    padding: 8px 12px; border-radius: 6px; cursor: pointer;
    transition: background .12s ease; font-size: 16px; line-height: 1.7; }}
  .snippet:hover {{ background: var(--hover); }}
  .snippet.active {{ background: var(--hover);
    box-shadow: inset 3px 0 0 var(--accent); }}
  .snippet time {{ flex: 0 0 64px; font-variant-numeric: tabular-nums;
    color: var(--link); font-size: 13px; padding-top: 3px; }}
  .snippet .t {{ flex: 1; }}

  .player-section {{ max-width: 920px; margin: 48px auto 24px;
    padding: 0 32px; }}
  .player-section h2 {{ font-size: 13px; text-transform: uppercase;
    letter-spacing: .1em; color: var(--muted); margin: 0 0 12px; }}
  .player {{ position: relative; width: 100%; padding-bottom: 56.25%;
    background: #000; border-radius: 12px; overflow: hidden;
    border: 1px solid var(--border); }}
  .player iframe {{ position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }}
  .player .thumb {{ position: absolute; inset: 0; width: 100%; height: 100%;
    object-fit: cover; cursor: pointer; }}
  .player .play-btn {{ position: absolute; inset: 0; display: flex;
    align-items: center; justify-content: center; cursor: pointer;
    background: rgba(0,0,0,.25); transition: background .2s; }}
  .player .play-btn:hover {{ background: rgba(0,0,0,.45); }}
  .player .play-btn svg {{ width: 72px; height: 72px;
    filter: drop-shadow(0 2px 6px rgba(0,0,0,.5)); }}
  .player.loaded .thumb, .player.loaded .play-btn {{ display: none; }}

  /* Docked floating mini-player (appears once the user plays the video) */
  .player-section.docked {{ position: fixed;
    right: 16px; bottom: 16px;
    width: min(380px, 90vw); margin: 0; padding: 0; z-index: 50;
    box-shadow: 0 12px 40px rgba(0,0,0,.45);
    border-radius: 12px; background: var(--panel);
    transition: transform .2s ease, opacity .2s ease; }}
  .player-section.docked h2 {{ display: none; }}
  .player-section.docked .player {{ border-radius: 12px 12px 0 0; }}
  .player-section.docked .dock-bar {{ display: flex; }}

  .dock-bar {{ display: none; align-items: center; justify-content: space-between;
    padding: 6px 10px; background: var(--panel);
    border-radius: 0 0 12px 12px; }}
  .dock-bar .label {{ font-size: 12px; color: var(--muted);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    padding-right: 8px; }}
  .dock-bar .dock-actions {{ display: flex; gap: 4px; }}
  .dock-bar button {{ background: transparent; border: 0; color: var(--muted);
    cursor: pointer; padding: 4px 8px; border-radius: 4px;
    font: inherit; font-size: 14px; line-height: 1; }}
  .dock-bar button:hover {{ background: var(--hover); color: var(--text); }}

  .actions {{ margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap; }}
  .actions a, .actions button {{ background: var(--panel); border: 1px solid var(--border);
    color: var(--text); padding: 8px 14px; border-radius: 6px; font: inherit;
    font-size: 13px; cursor: pointer; text-decoration: none;
    transition: background .12s ease; }}
  .actions a:hover, .actions button:hover {{ background: var(--hover); }}

  footer {{ max-width: 1500px; margin: 0 auto; padding: 24px 28px 40px;
    border-top: 1px solid var(--border); color: var(--muted); font-size: 13px;
    display: flex; gap: 16px; flex-wrap: wrap; align-items: center;
    justify-content: space-between; }}
  footer .video-link {{ display: flex; gap: 10px; flex-wrap: wrap;
    align-items: center; min-width: 0; }}
  footer .video-link strong {{ color: var(--text); font-weight: 500; }}
  footer .video-link a {{ word-break: break-all; }}
  footer .meta-pills {{ display: flex; gap: 6px; flex-wrap: wrap; }}
  footer .pill {{ background: var(--panel); border: 1px solid var(--border);
    padding: 3px 10px; border-radius: 999px; font-size: 12px; }}
  footer .credit {{ font-size: 12px; opacity: .8; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <label class="theme-switch">
    Theme
    <select id="theme-select" aria-label="Theme">
      <option value="auto">Auto</option>
      <option value="dark">Dark</option>
      <option value="light">Light</option>
      <option value="sepia">Sepia</option>
      <option value="midnight">Midnight</option>
      <option value="solarized">Solarized</option>
      <option value="forest">Forest</option>
    </select>
  </label>
</header>

<main>
  <section class="transcript-col">
    <h2>Transcript</h2>
    <div class="tabs" role="tablist">
      <button class="active" data-target="paragraph-view">Paragraphs</button>
      <button data-target="timestamped-view">Timestamped</button>
    </div>

    <div id="paragraph-view" class="view active">
      {paragraph_html}
    </div>

    <div id="timestamped-view" class="view">
      {timestamped_html}
    </div>

    <div class="actions" style="margin-top:24px">
      <a href="{url}" target="_blank" rel="noopener">Open on YouTube ↗</a>
      <button id="copy-btn">Copy full text</button>
      <a id="download-btn" download="{download_name}">Download .txt</a>
    </div>
  </section>
</main>

<section class="player-section" id="player-section">
  <h2>Video</h2>
  <div class="player" id="player-box">
    <img class="thumb" alt=""
         src="https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
         onerror="this.style.display='none'">
    <div class="play-btn" id="play-btn" title="Play video">
      <svg viewBox="0 0 68 48" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <path d="M66.52 7.74A8 8 0 0 0 60.9 2.1C56 .8 34 .8 34 .8s-22 0-26.9 1.3A8 8 0 0 0 1.48 7.74 84 84 0 0 0 .2 24a84 84 0 0 0 1.28 16.26 8 8 0 0 0 5.62 5.64C12 47.2 34 47.2 34 47.2s22 0 26.9-1.3a8 8 0 0 0 5.62-5.64A84 84 0 0 0 67.8 24a84 84 0 0 0-1.28-16.26z" fill="#ff0000"/>
        <path d="M27 34l18-10-18-10z" fill="#ffffff"/>
      </svg>
    </div>
  </div>
  <div class="dock-bar" id="dock-bar">
    <span class="label">Mini player</span>
    <span class="dock-actions">
      <button id="undock-btn" title="Expand back to page">⤢</button>
      <button id="close-btn" title="Close player">×</button>
    </span>
  </div>
</section>

<footer>
  <div class="video-link">
    <strong>Video:</strong>
    <a href="{url}" target="_blank" rel="noopener">{url}</a>
    <span class="meta-pills">
      <span class="pill">{language} ({language_code})</span>
      <span class="pill">{kind}</span>
      <span class="pill">{snippet_count} snippets</span>
      <span class="pill">~{duration_human}</span>
    </span>
  </div>
  <div class="credit">Generated by yt-trans · powered by youtube-transcript-api</div>
</footer>

<script>
  const VIDEO_ID = {video_id_json};
  const SNIPPETS = {snippets_json};
  const FULL_TEXT = {full_text_json};

  const THEME_KEY = 'yt-trans-theme';
  const themeSelect = document.getElementById('theme-select');
  const savedTheme = localStorage.getItem(THEME_KEY) || 'auto';
  document.documentElement.setAttribute('data-theme', savedTheme);
  themeSelect.value = savedTheme;
  themeSelect.addEventListener('change', () => {{
    document.documentElement.setAttribute('data-theme', themeSelect.value);
    localStorage.setItem(THEME_KEY, themeSelect.value);
  }});

  let player = null;
  let playerReady = false;
  let pendingSeek = null;
  let userClosed = false;

  const playerSection = document.getElementById('player-section');
  const playerBox = document.getElementById('player-box');

  function loadIframeAPI() {{
    if (window.YT && window.YT.Player) return;
    if (document.getElementById('yt-api-script')) return;
    const tag = document.createElement('script');
    tag.id = 'yt-api-script';
    tag.src = 'https://www.youtube.com/iframe_api';
    document.head.appendChild(tag);
  }}

  function mountPlayer(startSeconds) {{
    if (playerBox.classList.contains('loaded')) return;
    playerBox.classList.add('loaded');

    const params = new URLSearchParams({{
      enablejsapi: '1',
      rel: '0',
      modestbranding: '1',
      playsinline: '1',
      autoplay: '1',
    }});
    if (startSeconds && startSeconds > 0) {{
      params.set('start', String(Math.floor(startSeconds)));
    }}

    const iframe = document.createElement('iframe');
    iframe.id = 'yt-player';
    iframe.src = 'https://www.youtube-nocookie.com/embed/' + VIDEO_ID + '?' + params.toString();
    iframe.allow = 'autoplay; encrypted-media; picture-in-picture';
    iframe.setAttribute('allowfullscreen', '');
    iframe.referrerPolicy = 'strict-origin-when-cross-origin';
    playerBox.appendChild(iframe);

    loadIframeAPI();
    const wait = setInterval(() => {{
      if (window.YT && window.YT.Player) {{
        clearInterval(wait);
        player = new YT.Player('yt-player', {{
          events: {{
            onReady: () => {{
              playerReady = true;
              if (pendingSeek != null) {{ player.seekTo(pendingSeek, true); pendingSeek = null; }}
            }}
          }}
        }});
      }}
    }}, 120);

    dockPlayer();
  }}

  function dockPlayer() {{
    if (userClosed) return;
    playerSection.classList.add('docked');
  }}
  function undockPlayer() {{
    playerSection.classList.remove('docked');
    playerSection.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
  }}
  function closePlayer() {{
    userClosed = true;
    playerSection.classList.remove('docked');
    playerSection.style.display = 'none';
    if (player && player.stopVideo) player.stopVideo();
  }}
  function reopenPlayer() {{
    userClosed = false;
    playerSection.style.display = '';
    dockPlayer();
  }}

  document.getElementById('play-btn').addEventListener('click', () => mountPlayer(0));
  document.querySelector('#player-box .thumb').addEventListener('click', () => mountPlayer(0));
  document.getElementById('undock-btn').addEventListener('click', undockPlayer);
  document.getElementById('close-btn').addEventListener('click', closePlayer);

  function seek(seconds) {{
    if (userClosed) reopenPlayer();
    if (!playerBox.classList.contains('loaded')) {{
      mountPlayer(seconds);
      return;
    }}
    dockPlayer();
    if (player && playerReady) {{
      player.seekTo(seconds, true);
      player.playVideo && player.playVideo();
    }} else {{
      pendingSeek = seconds;
    }}
  }}

  document.querySelectorAll('.snippet').forEach(el => {{
    el.addEventListener('click', () => {{
      document.querySelectorAll('.snippet.active').forEach(n => n.classList.remove('active'));
      el.classList.add('active');
      seek(parseFloat(el.dataset.start));
    }});
  }});

  document.querySelectorAll('.tabs button').forEach(btn => {{
    btn.addEventListener('click', () => {{
      document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(btn.dataset.target).classList.add('active');
    }});
  }});

  document.getElementById('copy-btn').addEventListener('click', async () => {{
    try {{
      await navigator.clipboard.writeText(FULL_TEXT);
      const b = document.getElementById('copy-btn');
      const old = b.textContent;
      b.textContent = 'Copied!';
      setTimeout(() => b.textContent = old, 1500);
    }} catch (e) {{ alert('Copy failed: ' + e); }}
  }});

  const blob = new Blob([FULL_TEXT], {{ type: 'text/plain;charset=utf-8' }});
  document.getElementById('download-btn').href = URL.createObjectURL(blob);
</script>
</body>
</html>
"""


def _paragraphs_html(paragraphs: str) -> str:
    if not paragraphs.strip():
        return "<p><em>(empty transcript)</em></p>"
    chunks = [p.strip() for p in paragraphs.split("\n\n") if p.strip()]
    return "\n".join(f"<p>{html.escape(p)}</p>" for p in chunks)


def _timestamped_html(snippets: list[dict]) -> str:
    rows = []
    for s in snippets:
        start = float(s.get("start", 0.0))
        text = html.escape((s.get("text") or "").strip())
        if not text:
            continue
        rows.append(
            f'<div class="snippet" data-start="{start:.2f}">'
            f'<time>{format_timestamp(start)}</time>'
            f'<span class="t">{text}</span>'
            f"</div>"
        )
    return "\n".join(rows) or "<p><em>(no snippets)</em></p>"


def render(result: "TranscriptionResult", *, title: str | None = None) -> str:
    """Render a TranscriptionResult to a complete HTML document string."""
    page_title = title or f"YouTube transcript · {result.video_id}"
    duration_human = format_timestamp(result.duration) if result.duration else "?"
    kind = "auto-generated" if result.is_generated else "manual"

    return _TEMPLATE.format(
        lang=html.escape(result.language_code or "en"),
        title=html.escape(page_title),
        url=html.escape(result.url),
        video_id=html.escape(result.video_id),
        video_id_json=json.dumps(result.video_id),
        language=html.escape(result.language),
        language_code=html.escape(result.language_code),
        kind=kind,
        snippet_count=result.snippet_count,
        duration_human=duration_human,
        paragraph_html=_paragraphs_html(result.paragraphs),
        timestamped_html=_timestamped_html(result.raw),
        snippets_json=json.dumps(result.raw, ensure_ascii=False),
        full_text_json=json.dumps(result.full_text, ensure_ascii=False),
        download_name=html.escape(f"{result.video_id}.{result.language_code}.txt"),
    )
