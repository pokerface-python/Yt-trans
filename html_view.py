"""Render a TranscriptionResult into a self-contained HTML page.

The page bundles:
    * the original YouTube video (privacy-enhanced nocookie embed, with the
      iframe-API enabled so we can drive it from JS) plus a click-to-load
      thumbnail fallback for browsers/extensions that block the embed
      (this is what triggers the "Error 153 / configuration error" message)
    * a 10-way theme switcher (Auto / Dark / Light / Sepia / Midnight /
      Solarized / Forest / Ubuntu / Matrix / Cyber) saved to localStorage
    * a font-family picker (built-in stacks + modern Google Fonts such as
      Inter, Poppins, Outfit, Space Grotesk, etc.) for UI + transcript,
      saved to localStorage (web fonts load when online)
    * a header row showing the video title (or just the id, as a chip,
      when the oEmbed title lookup fails) on the right of "Transcript"
    * the cleaned full-text transcript grouped into paragraphs
    * a timestamped view where every snippet is a clickable link that seeks
      the embedded player to that exact moment.
    * an "AI: Refine or Translate" split-button that POSTs to /api/refine.
      The dropdown offers four actions: Refine (clean up, keep language),
      Summarize (TL;DR + bullet key points), Translate -> English,
      Translate -> Hindi. The result is toggleable against the original
      via a pill switch; summaries render with a TL;DR callout and a
      themed bullet list.

The output is a single .html file with inlined CSS + JS. Google Fonts
load when online (built-in stacks still work offline). The embedded
YouTube player and AI features also need network / the local server.
"""

from __future__ import annotations

import html
import json
from typing import TYPE_CHECKING

from utils import format_timestamp

if TYPE_CHECKING:
    from transcriptor import TranscriptionResult


_FB_SANS = '"Noto Sans Devanagari", "Noto Sans", sans-serif'
_FB_SERIF = '"Noto Serif Devanagari", Georgia, serif'
_FB_MONO = "ui-monospace, Menlo, Consolas, monospace"

# id, label, optgroup, css font-family stack, Google Fonts family name (or None)
_FONT_ENTRIES: list[tuple[str, str, str, str, str | None]] = [
    ("system", "System", "Built-in",
     f'-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, {_FB_SANS}',
     None),
    ("serif", "Georgia Serif", "Built-in",
     f'Georgia, Cambria, "Times New Roman", Times, {_FB_SERIF}', None),
    ("mono", "System Mono", "Built-in",
     f"ui-monospace, SFMono-Regular, Menlo, Consolas, {_FB_MONO}", None),
    ("friendly", "Verdana", "Built-in",
     f'Verdana, Tahoma, "Trebuchet MS", {_FB_SANS}', None),
    ("classic", "Palatino", "Built-in",
     f'"Palatino Linotype", Palatino, "Book Antiqua", {_FB_SERIF}', None),
    ("compact", "Arial", "Built-in",
     f"Arial, Helvetica, {_FB_SANS}", None),
    ("inter", "Inter", "Modern sans",
     f'"Inter", {_FB_SANS}', "Inter"),
    ("dm-sans", "DM Sans", "Modern sans",
     f'"DM Sans", {_FB_SANS}', "DM Sans"),
    ("plus-jakarta", "Plus Jakarta Sans", "Modern sans",
     f'"Plus Jakarta Sans", {_FB_SANS}', "Plus Jakarta Sans"),
    ("outfit", "Outfit", "Modern sans",
     f'"Outfit", {_FB_SANS}', "Outfit"),
    ("manrope", "Manrope", "Modern sans",
     f'"Manrope", {_FB_SANS}', "Manrope"),
    ("sora", "Sora", "Modern sans",
     f'"Sora", {_FB_SANS}', "Sora"),
    ("space-grotesk", "Space Grotesk", "Modern sans",
     f'"Space Grotesk", {_FB_SANS}', "Space Grotesk"),
    ("urbanist", "Urbanist", "Modern sans",
     f'"Urbanist", {_FB_SANS}', "Urbanist"),
    ("figtree", "Figtree", "Modern sans",
     f'"Figtree", {_FB_SANS}', "Figtree"),
    ("geist", "Geist", "Modern sans",
     f'"Geist", "Inter", {_FB_SANS}', "Geist"),
    ("poppins", "Poppins", "Soft & rounded",
     f'"Poppins", {_FB_SANS}', "Poppins"),
    ("nunito", "Nunito", "Soft & rounded",
     f'"Nunito", {_FB_SANS}', "Nunito"),
    ("rubik", "Rubik", "Soft & rounded",
     f'"Rubik", {_FB_SANS}', "Rubik"),
    ("quicksand", "Quicksand", "Soft & rounded",
     f'"Quicksand", {_FB_SANS}', "Quicksand"),
    ("comfortaa", "Comfortaa", "Soft & rounded",
     f'"Comfortaa", {_FB_SANS}', "Comfortaa"),
    ("lexend", "Lexend", "Soft & rounded",
     f'"Lexend", {_FB_SANS}', "Lexend"),
    ("lora", "Lora", "Serif reading",
     f'"Lora", {_FB_SERIF}', "Lora"),
    ("merriweather", "Merriweather", "Serif reading",
     f'"Merriweather", {_FB_SERIF}', "Merriweather"),
    ("playfair", "Playfair Display", "Serif reading",
     f'"Playfair Display", {_FB_SERIF}', "Playfair Display"),
    ("source-serif", "Source Serif 4", "Serif reading",
     f'"Source Serif 4", {_FB_SERIF}', "Source Serif 4"),
    ("jetbrains", "JetBrains Mono", "Monospace",
     f'"JetBrains Mono", {_FB_MONO}', "JetBrains Mono"),
    ("fira-code", "Fira Code", "Monospace",
     f'"Fira Code", {_FB_MONO}', "Fira Code"),
    ("space-mono", "Space Mono", "Monospace",
     f'"Space Mono", {_FB_MONO}', "Space Mono"),
    ("ibm-plex-mono", "IBM Plex Mono", "Monospace",
     f'"IBM Plex Mono", {_FB_MONO}', "IBM Plex Mono"),
    ("synonym", "Synonym", "Display",
     f'"Synonym", {_FB_SANS}', "Synonym"),
    ("archivo", "Archivo", "Display",
     f'"Archivo", {_FB_SANS}', "Archivo"),
]

def _build_font_css() -> str:
    system_stack = next(s for i, _, _, s, _ in _FONT_ENTRIES if i == "system")
    lines = [
        "  html {",
        f"    --font-ui: {system_stack};",
        "    --font-transcript: var(--font-ui);",
        "  }",
    ]
    for fid, _, _, stack, _ in _FONT_ENTRIES:
        if fid == "system":
            continue
        lines += [
            f'  html[data-font="{fid}"] {{',
            f"    --font-ui: {stack};",
            "    --font-transcript: var(--font-ui);",
            "  }",
        ]
    return "\n".join(lines)


def _google_fonts_url() -> str:
    params: list[str] = []
    seen: set[str] = set()
    for _, _, _, _, google in _FONT_ENTRIES:
        if not google or google in seen:
            continue
        seen.add(google)
        q = google.replace(" ", "+")
        params.append(f"family={q}:wght@400;500;600;700")
    return "https://fonts.googleapis.com/css2?" + "&".join(params) + "&display=swap"


def _build_font_switcher_html() -> str:
    groups: list[str] = []
    current = ""
    for fid, label, group, _, _ in _FONT_ENTRIES:
        if group != current:
            if current:
                groups.append("</optgroup>")
            groups.append(f'<optgroup label="{html.escape(group)}">')
            current = group
        groups.append(
            f'<option value="{fid}">{html.escape(label)}</option>'
        )
    if current:
        groups.append("</optgroup>")
    opts = "\n      ".join(groups)
    return f"""
  <label class="font-switch" title="Font">
    <span class="font-switch-icon" aria-hidden="true">Aa</span>
    <select id="font-select" aria-label="Font family">
      {opts}
    </select>
  </label>
"""


_GOOGLE_FONTS_URL = _google_fonts_url()
_FONT_SWITCHER_HTML = _build_font_switcher_html()

_FONT_INIT_JS = """
  const FONT_KEY = 'yt-trans-font';
  const fontSelect = document.getElementById('font-select');
  if (fontSelect) {{
    const savedFont = localStorage.getItem(FONT_KEY) || 'system';
    const valid = [...fontSelect.options].some(o => o.value === savedFont);
    const font = valid ? savedFont : 'system';
    document.documentElement.setAttribute('data-font', font);
    fontSelect.value = font;
    fontSelect.addEventListener('change', () => {{
      const f = fontSelect.value;
      document.documentElement.setAttribute('data-font', f);
      localStorage.setItem(FONT_KEY, f);
    }});
  }}
"""

_SHARED_CSS_HEAD = """
  :root,
  html[data-theme="dark"] {
    --bg: #0f1115;     --panel: #161922;   --text: #e7e9ee;
    --muted: #9aa3b2;  --accent: #ff5252;  --link: #7cb7ff;
    --border: #262b36; --hover: #1f2330;
  }
  html[data-theme="light"] {
    --bg: #f7f8fa;     --panel: #ffffff;   --text: #1b1f27;
    --muted: #5b6675;  --accent: #d22d2d;  --link: #1559c2;
    --border: #e3e7ee; --hover: #f0f3f8;
  }
  html[data-theme="sepia"] {
    --bg: #f5ecd9;     --panel: #fbf5e6;   --text: #4b3a23;
    --muted: #8a755a;  --accent: #b35a1f;  --link: #8a4a14;
    --border: #e3d6b6; --hover: #efe3c6;
  }
  html[data-theme="midnight"] {
    --bg: #0a1024;     --panel: #111a36;   --text: #d6e1ff;
    --muted: #7a8bbf;  --accent: #4cc9ff;  --link: #82d3ff;
    --border: #1c2750; --hover: #16224a;
  }
  html[data-theme="solarized"] {
    --bg: #002b36;     --panel: #073642;   --text: #eee8d5;
    --muted: #93a1a1;  --accent: #b58900;  --link: #2aa198;
    --border: #0d4250; --hover: #0c3a47;
  }
  html[data-theme="forest"] {
    --bg: #102018;     --panel: #163024;   --text: #e0efe2;
    --muted: #8fb3a0;  --accent: #f5b14b;  --link: #7ddca4;
    --border: #21402f; --hover: #1c3a2a;
  }
  html[data-theme="ubuntu"] {
    --bg: #300a24;     --panel: #3d0f30;   --text: #eeeeec;
    --muted: #b8a0b0;  --accent: #e95420;  --link: #ff7b54;
    --border: #5c2048; --hover: #451838;
  }
  html[data-theme="matrix"] {
    --bg: #000000;     --panel: #0a120a;   --text: #8fbc8f;
    --transcript: #39ff14; --muted: #3d6b3d; --accent: #00ff41;
    --link: #7fff7f; --border: #1a3a1a; --hover: #0d1a0d;
  }
  html[data-theme="cyber"] {
    --bg: #0c0018;     --panel: #150028;   --text: #b8a8d8;
    --transcript: #ff4fd8; --muted: #6a5890; --accent: #00e8ff;
    --link: #00e8ff; --border: #3d2060; --hover: #1e0a36;
  }
  html { --transcript: var(--text); }
"""

_SHARED_CSS = _SHARED_CSS_HEAD + _build_font_css() + """
  @media (prefers-color-scheme: light) {
    html[data-theme="auto"] {
      --bg: #f7f8fa;     --panel: #ffffff;   --text: #1b1f27;
      --muted: #5b6675;  --accent: #d22d2d;  --link: #1559c2;
      --border: #e3e7ee; --hover: #f0f3f8;
    }
  }

  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text);
    font-family: var(--font-ui); font-size: 16px; line-height: 1.7;
    transition: background .2s ease, color .2s ease; }
  a { color: var(--link); text-decoration: none; }
  a:hover { text-decoration: underline; }

  header { padding: 8px 16px; border-bottom: 1px solid var(--border);
    background: var(--panel); position: sticky; top: 0; z-index: 5;
    display: flex; align-items: center; justify-content: flex-end; gap: 8px;
    min-height: 40px; backdrop-filter: blur(8px); }

  /* AI status pill, sits at the top-left of the sticky header so users
     can see live progress no matter how far they've scrolled. */
  .ai-status { display: none; margin-right: auto;
    align-items: center; gap: 8px;
    padding: 5px 12px; border-radius: 999px;
    background: var(--panel); border: 1px solid var(--border);
    font-size: 12px; color: var(--text); font-weight: 500;
    cursor: default; user-select: none;
    max-width: min(60vw, 380px);
    transition: background .2s ease, border-color .2s ease,
                color .2s ease, transform .12s ease; }
  .ai-status.visible { display: inline-flex; }
  .ai-status.clickable { cursor: pointer; }
  .ai-status.clickable:hover { background: var(--hover);
    transform: translateY(-1px); }
  .ai-status .ai-label { overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; flex: 1 1 auto; min-width: 0; }
  .ai-status .ai-dot { flex: 0 0 8px; width: 8px; height: 8px;
    border-radius: 50%; background: var(--accent);
    box-shadow: 0 0 0 3px
      color-mix(in srgb, var(--accent) 25%, transparent); }
  .ai-status .ai-spinner { display: none; flex: 0 0 13px;
    width: 13px; height: 13px;
    border: 2px solid color-mix(in srgb, var(--accent) 22%, transparent);
    border-top-color: var(--accent); border-radius: 50%;
    animation: ai-spin .7s linear infinite; }
  /* running: spinner replaces dot, accent-tinted background, animated */
  .ai-status.running { border-color: var(--accent); cursor: progress;
    background: color-mix(in srgb, var(--accent) 12%, var(--panel));
    color: var(--text); animation: ai-pulse-bg 1.6s ease-in-out infinite; }
  .ai-status.running .ai-spinner { display: inline-block; }
  .ai-status.running .ai-dot { display: none; }
  /* updated: AI output is being shown — strong accent border */
  .ai-status.updated { border-color: var(--accent); color: var(--text); }
  /* original: AI output exists but user toggled back to the source */
  .ai-status.original { color: var(--muted); }
  .ai-status.original .ai-dot { background: var(--muted);
    box-shadow: none; }
  @keyframes ai-spin { to { transform: rotate(360deg); } }
  @keyframes ai-pulse-bg {
    0%, 100% { background: color-mix(in srgb, var(--accent) 12%, var(--panel)); }
    50%      { background: color-mix(in srgb, var(--accent) 22%, var(--panel)); }
  }
  @media (prefers-reduced-motion: reduce) {
    .ai-status, .ai-status .ai-spinner { animation: none !important; }
    .ai-status.clickable:hover { transform: none; }
  }

  .header-tools { display: inline-flex; align-items: center; gap: 10px;
    flex-wrap: wrap; justify-content: flex-end; }
  .font-switch { display: inline-flex; align-items: center; gap: 5px;
    flex: 0 0 auto; }
  .font-switch-icon { font-size: 15px; font-weight: 700; color: var(--muted);
    line-height: 1; font-family: Georgia, "Times New Roman", serif; }
  .font-switch select { font: inherit; font-size: 12px; font-weight: 500;
    padding: 4px 24px 4px 8px; border-radius: 6px;
    border: 1px solid var(--border); background: var(--panel);
    color: var(--text); cursor: pointer; min-width: 118px; max-width: 168px;
    appearance: none;
    background-image: linear-gradient(45deg, transparent 50%, var(--muted) 50%),
      linear-gradient(135deg, var(--muted) 50%, transparent 50%);
    background-position: calc(100% - 14px) 55%, calc(100% - 9px) 55%;
    background-size: 5px 5px, 5px 5px;
    background-repeat: no-repeat; }
  .font-switch select:hover { border-color: var(--accent); }
  .font-switch select:focus-visible { outline: none;
    border-color: var(--accent); box-shadow: 0 0 0 2px
      color-mix(in srgb, var(--accent) 25%, transparent); }
  .theme-switch { display: inline-flex; align-items: center; gap: 6px; }
  .theme-swatch { width: 22px; height: 22px; border-radius: 50%;
    border: 2px solid transparent; cursor: pointer; padding: 0;
    position: relative; outline: none; flex: 0 0 22px;
    transition: transform .12s ease, border-color .12s ease,
                box-shadow .12s ease; }
  .theme-swatch:hover { transform: scale(1.15); }
  .theme-swatch:focus-visible { box-shadow: 0 0 0 2px var(--accent); }
  .theme-swatch.active { border-color: var(--text);
    box-shadow: 0 0 0 1px var(--panel) inset; }
  .theme-swatch::after { content: ""; position: absolute;
    right: -2px; bottom: -2px; width: 8px; height: 8px; border-radius: 50%;
    border: 1.5px solid var(--panel); }
  .theme-swatch[data-theme="auto"]      { background:
      linear-gradient(135deg, #f7f8fa 0 50%, #0f1115 50% 100%); }
  .theme-swatch[data-theme="auto"]::after      { background: #ff5252; }
  .theme-swatch[data-theme="dark"]      { background: #0f1115; }
  .theme-swatch[data-theme="dark"]::after      { background: #ff5252; }
  .theme-swatch[data-theme="light"]     { background: #f7f8fa; }
  .theme-swatch[data-theme="light"]::after     { background: #d22d2d; }
  .theme-swatch[data-theme="sepia"]     { background: #f5ecd9; }
  .theme-swatch[data-theme="sepia"]::after     { background: #b35a1f; }
  .theme-swatch[data-theme="midnight"]  { background: #0a1024; }
  .theme-swatch[data-theme="midnight"]::after  { background: #4cc9ff; }
  .theme-swatch[data-theme="solarized"] { background: #002b36; }
  .theme-swatch[data-theme="solarized"]::after { background: #b58900; }
  .theme-swatch[data-theme="forest"]    { background: #102018; }
  .theme-swatch[data-theme="forest"]::after    { background: #f5b14b; }
  .theme-swatch[data-theme="ubuntu"]    { background: #300a24; }
  .theme-swatch[data-theme="ubuntu"]::after    { background: #e95420; }
  .theme-swatch[data-theme="matrix"]   { background: #000000; }
  .theme-swatch[data-theme="matrix"]::after   { background: #39ff14;
    box-shadow: 0 0 5px #39ff14; }
  .theme-swatch[data-theme="cyber"]    { background: #0c0018; }
  .theme-swatch[data-theme="cyber"]::after    { background: linear-gradient(
      135deg, #00e8ff 0 50%, #ff4fd8 50% 100%); }

  .url-bar { max-width: 1100px; margin: 0 auto;
    padding: 18px 32px 0; }
  .url-bar form { display: flex; gap: 8px; flex-wrap: wrap; }
  .url-bar input, .url-bar button { font: inherit; font-size: 15px;
    padding: 11px 16px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--panel); color: var(--text);
    transition: border-color .15s ease, background .15s ease; }
  .url-bar input:focus { outline: none; border-color: var(--accent); }
  .url-bar input[name="url"] { flex: 1; min-width: 240px; }
  .url-bar input[name="lang"] { width: 160px; flex: 0 0 auto; }
  .url-bar button { background: var(--accent); color: white; border: 0;
    cursor: pointer; font-weight: 600; padding: 11px 22px;
    transition: opacity .15s ease; }
  .url-bar button:hover { opacity: .9; }
  .url-bar button:disabled { opacity: .6; cursor: wait; }
  .url-bar .notice, .url-bar .error-msg {
    margin-top: 10px; padding: 10px 14px; font-size: 13px;
    border-radius: 8px; border: 1px solid var(--border);
    background: var(--panel); color: var(--muted); }
  .url-bar .error-msg { color: var(--accent); border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 8%, var(--panel)); }
  .url-bar code { font-family: ui-monospace, Menlo, monospace;
    background: var(--hover); padding: 1px 6px; border-radius: 4px;
    font-size: 12px; color: var(--text); }

  main { max-width: 1100px; margin: 0 auto;
    padding: 28px 32px 32px; }

  /* Landing-page hero (when the server has no URL yet) */
  .landing { max-width: 760px; margin: 0 auto; padding: 80px 32px 64px;
    text-align: center; }
  .landing h1 { font-size: 38px; margin: 0 0 12px; font-weight: 700;
    letter-spacing: -0.02em; }
  .landing p.lead { font-size: 17px; color: var(--muted);
    margin: 0 0 36px; line-height: 1.6; }
  .landing .url-bar { padding: 0; }
  .landing .examples { margin-top: 28px; font-size: 13px; color: var(--muted); }
  .landing .examples a { font-family: ui-monospace, Menlo, monospace;
    font-size: 12px; }

  .transcript-col h2 { font-size: 13px; text-transform: uppercase;
    letter-spacing: .1em; color: var(--muted); margin: 0; }
  .transcript-col h2 .word-count {
    margin-left: 10px; font-size: 12px; font-weight: 500;
    color: var(--muted); text-transform: none; letter-spacing: 0;
    opacity: .85; }

  .transcript-head { display: flex; align-items: baseline;
    justify-content: space-between; gap: 16px; margin: 0 0 12px;
    flex-wrap: wrap; min-width: 0; }
  .transcript-head .video-info { display: inline-flex; align-items: baseline;
    gap: 8px; min-width: 0; max-width: 100%;
    font-size: 14px; color: var(--text); }
  .transcript-head .video-info .vt-title {
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    max-width: 60vw; font-weight: 500; color: var(--text);
    text-decoration: none; }
  .transcript-head .video-info .vt-title:hover { color: var(--link); }
  .transcript-head .video-info .vt-id {
    font-family: ui-monospace, Menlo, monospace; font-size: 12px;
    color: var(--muted); background: var(--hover);
    padding: 2px 8px; border-radius: 999px; flex: 0 0 auto; }
  @media (max-width: 640px) {
    .transcript-head .video-info .vt-title { max-width: 80vw; }
  }
  .tabs { display: inline-flex; background: var(--panel); border: 1px solid var(--border);
    border-radius: 999px; padding: 4px; margin-bottom: 20px; }
  .tabs button { background: transparent; border: 0; color: var(--muted);
    padding: 7px 16px; border-radius: 999px; cursor: pointer; font: inherit;
    font-size: 13px; transition: all .15s ease; }
  .tabs button.active { background: var(--accent); color: white; }

  .view { display: none; }
  .view.active { display: block; }

  #paragraph-view { font-size: 18px; line-height: 1.85;
    font-family: var(--font-transcript); }
  #paragraph-view p,
  #paragraph-view li,
  #paragraph-view strong,
  .snippet .t { color: var(--transcript); }
  #paragraph-view p { margin: 0 0 20px; }
  #paragraph-view ul { margin: 0 0 20px; padding-left: 1.25em; font-size: 17px; }
  #paragraph-view li { margin: 0 0 10px; line-height: 1.65; }
  #paragraph-view li::marker { color: var(--accent); }
  #paragraph-view .tldr { display: block; margin: 0 0 18px;
    padding: 14px 18px; border-radius: 10px;
    border-left: 4px solid var(--accent);
    background: color-mix(in srgb, var(--accent) 8%, var(--panel));
    color: var(--text); font-size: 17px; line-height: 1.55;
    font-weight: 500; }
  #paragraph-view .tldr-label { display: inline-block;
    font-size: 11px; font-weight: 700; letter-spacing: .08em;
    text-transform: uppercase; color: var(--accent);
    margin-right: 10px; vertical-align: 1px; }
  #paragraph-view strong { font-weight: 600; }
  html[data-theme="cyber"] #paragraph-view p,
  html[data-theme="cyber"] #paragraph-view li,
  html[data-theme="cyber"] .snippet .t {
    text-shadow: 0 0 24px color-mix(in srgb, var(--transcript) 35%, transparent);
  }

  .snippet { display: flex; gap: 14px; align-items: baseline;
    padding: 8px 12px; border-radius: 6px; cursor: pointer;
    transition: background .12s ease; font-size: 16px; line-height: 1.7;
    font-family: var(--font-transcript); }
  .snippet:hover { background: var(--hover); }
  .snippet.active { background: var(--hover);
    box-shadow: inset 3px 0 0 var(--accent); }
  .snippet time { flex: 0 0 64px; font-variant-numeric: tabular-nums;
    color: var(--link); font-size: 13px; padding-top: 3px; }
  .snippet .t { flex: 1; }

  .player-section { max-width: 920px; margin: 48px auto 24px;
    padding: 0 32px; }
  .player-section h2 { font-size: 13px; text-transform: uppercase;
    letter-spacing: .1em; color: var(--muted); margin: 0 0 12px; }
  .player { position: relative; width: 100%; padding-bottom: 56.25%;
    background: #000; border-radius: 12px; overflow: hidden;
    border: 1px solid var(--border); }
  .player iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }
  .player .thumb { position: absolute; inset: 0; width: 100%; height: 100%;
    object-fit: cover; cursor: pointer; }
  .player .play-btn { position: absolute; inset: 0; display: flex;
    align-items: center; justify-content: center; cursor: pointer;
    background: rgba(0,0,0,.25); transition: background .2s; }
  .player .play-btn:hover { background: rgba(0,0,0,.45); }
  .player .play-btn svg { width: 72px; height: 72px;
    filter: drop-shadow(0 2px 6px rgba(0,0,0,.5)); }
  .player.loaded .thumb, .player.loaded .play-btn { display: none; }

  /* Docked floating mini-player (appears once the user plays the video) */
  .player-section.docked { position: fixed;
    right: 16px; bottom: 16px;
    width: min(380px, 90vw); margin: 0; padding: 0; z-index: 50;
    box-shadow: 0 12px 40px rgba(0,0,0,.45);
    border-radius: 12px; background: var(--panel);
    transition: transform .2s ease, opacity .2s ease; }
  .player-section.docked h2 { display: none; }
  .player-section.docked .player { border-radius: 12px 12px 0 0; }
  .player-section.docked .dock-bar { display: flex; }

  .dock-bar { display: none; align-items: center; justify-content: space-between;
    padding: 6px 10px; background: var(--panel);
    border-radius: 0 0 12px 12px; }
  .dock-bar .label { font-size: 12px; color: var(--muted);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    padding-right: 8px; }
  .dock-bar .dock-actions { display: flex; gap: 4px; }
  .dock-bar button { background: transparent; border: 0; color: var(--muted);
    cursor: pointer; padding: 4px 8px; border-radius: 4px;
    font: inherit; font-size: 14px; line-height: 1; }
  .dock-bar button:hover { background: var(--hover); color: var(--text); }

  .actions { margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap;
    align-items: center; }
  .actions a, .actions button { background: var(--panel); border: 1px solid var(--border);
    color: var(--text); padding: 8px 14px; border-radius: 6px; font: inherit;
    font-size: 13px; cursor: pointer; text-decoration: none;
    transition: background .12s ease; }
  .actions a:hover, .actions button:hover { background: var(--hover); }
  .actions button.primary { background: var(--accent); color: white;
    border-color: var(--accent); font-weight: 600; }
  .actions button.primary:hover { opacity: .9; background: var(--accent); }
  .actions button:disabled { opacity: .6; cursor: wait; }
  .actions button[aria-pressed="true"] {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 12%, var(--panel)); }
  .actions .ai-meta { font-size: 12px; color: var(--muted); margin-left: 4px; }
  .actions .ai-toggle { display: inline-flex; background: var(--panel);
    border: 1px solid var(--border); border-radius: 999px; padding: 3px; }
  .actions .ai-toggle button { background: transparent; border: 0;
    color: var(--muted); padding: 5px 12px; border-radius: 999px;
    font-size: 12px; font-weight: 500; }
  .actions .ai-toggle button.active { background: var(--accent); color: white; }

  .ai-menu-wrap { position: relative; display: inline-block; }
  .ai-menu-wrap > button.primary { padding-right: 32px; position: relative; }
  .ai-menu-wrap > button.primary::after { content: "\\25be";
    position: absolute; right: 12px; top: 50%; transform: translateY(-50%);
    font-size: 11px; opacity: .85; }
  .ai-menu { position: absolute; top: calc(100% + 4px); right: 0;
    min-width: 200px; padding: 6px;
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; box-shadow: 0 12px 32px rgba(0,0,0,.35);
    z-index: 20; display: flex; flex-direction: column; gap: 2px; }
  .ai-menu[hidden] { display: none; }
  .ai-menu button { background: transparent; border: 0; color: var(--text);
    text-align: left; padding: 9px 12px; border-radius: 6px; cursor: pointer;
    font: inherit; font-size: 13px; line-height: 1.3;
    display: flex; flex-direction: column; gap: 2px; }
  .ai-menu button:hover, .ai-menu button:focus-visible {
    background: var(--hover); outline: none; }
  .ai-menu .label { color: var(--text); font-weight: 500; }
  .ai-menu .hint { color: var(--muted); font-size: 11px; font-weight: 400; }
  .ai-error { margin-top: 12px; padding: 12px 14px; border-radius: 8px;
    border: 1px solid var(--accent); background: var(--panel);
    color: var(--text); font-size: 13px; white-space: pre-wrap;
    font-family: ui-monospace, Menlo, monospace; line-height: 1.5; }
  .ai-error strong { color: var(--accent); font-family: inherit; }
  .ai-error code { background: var(--hover); padding: 1px 6px;
    border-radius: 4px; font-size: 12px; }

  footer { max-width: 1500px; margin: 0 auto; padding: 24px 28px 40px;
    border-top: 1px solid var(--border); color: var(--muted); font-size: 13px;
    display: flex; gap: 16px; flex-wrap: wrap; align-items: center;
    justify-content: space-between; }
  footer .video-link { display: flex; gap: 10px; flex-wrap: wrap;
    align-items: center; min-width: 0; }
  footer .video-link strong { color: var(--text); font-weight: 500; }
  footer .video-link a { word-break: break-all; }
  footer .meta-pills { display: flex; gap: 6px; flex-wrap: wrap; }
  footer .pill { background: var(--panel); border: 1px solid var(--border);
    padding: 3px 10px; border-radius: 999px; font-size: 12px; }
  footer .credit { font-size: 12px; opacity: .8; }
"""


_TEMPLATE = """<!doctype html>
<html lang="{lang}" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — transcript</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{google_fonts_url}" rel="stylesheet">
<style>{shared_css}</style>
</head>
<body>
<header>
  <div class="ai-status" id="ai-status" role="status" aria-live="polite"
       title="Click to switch between original and AI output">
    <span class="ai-spinner" aria-hidden="true"></span>
    <span class="ai-dot" aria-hidden="true"></span>
    <span class="ai-label">Idle</span>
  </div>
  <div class="header-tools">
    {font_switcher_html}
    <div class="theme-switch" role="radiogroup" aria-label="Theme">
      <button type="button" class="theme-swatch" data-theme="auto"      title="Auto"      aria-label="Auto theme"></button>
      <button type="button" class="theme-swatch" data-theme="dark"      title="Dark"      aria-label="Dark theme"></button>
      <button type="button" class="theme-swatch" data-theme="light"     title="Light"     aria-label="Light theme"></button>
      <button type="button" class="theme-swatch" data-theme="sepia"     title="Sepia"     aria-label="Sepia theme"></button>
      <button type="button" class="theme-swatch" data-theme="midnight"  title="Midnight"  aria-label="Midnight theme"></button>
      <button type="button" class="theme-swatch" data-theme="solarized" title="Solarized" aria-label="Solarized theme"></button>
      <button type="button" class="theme-swatch" data-theme="forest"    title="Forest"    aria-label="Forest theme"></button>
      <button type="button" class="theme-swatch" data-theme="ubuntu"    title="Ubuntu"    aria-label="Ubuntu terminal theme"></button>
      <button type="button" class="theme-swatch" data-theme="matrix"    title="Matrix"    aria-label="Matrix terminal theme"></button>
      <button type="button" class="theme-swatch" data-theme="cyber"     title="Cyber"     aria-label="Cyber neon theme"></button>
    </div>
  </div>
</header>

<section class="url-bar">
  <form action="/" method="get" id="url-form">
    <input type="text" name="url" id="url-input" required autocomplete="off"
      placeholder="Paste YouTube URL or 11-char video id…"
      value="{prefilled_url}">
    <input type="text" name="lang" id="lang-input" autocomplete="off"
      placeholder="languages e.g. en,hi" value="{prefilled_langs}">
    <button type="submit" id="submit-btn">Get transcript</button>
  </form>
  <div class="notice" id="offline-notice" style="display:none">
    This page is offline — run <code>python cli.py --serve</code> from the
    project folder, then open the printed URL to fetch new videos.
  </div>
</section>

<main>
  <section class="transcript-col">
    <div class="transcript-head">
      <h2>Transcript<span class="word-count" id="word-count"
        title="Total words in this transcript">· {word_count} words</span></h2>
      <span class="video-info">{video_info_html}</span>
    </div>
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

    <div class="actions" id="actions-bar" style="margin-top:24px">
      <a href="{url}" target="_blank" rel="noopener">Open on YouTube ↗</a>
      <button id="copy-btn">Copy full text</button>
      <a id="download-btn" download="{download_name}">Download .txt</a>
      <button id="noise-btn" type="button" aria-pressed="false"
        title="Remove [music] and >> [music] >> markers from the paragraph view">
        Hide [music]
      </button>
      <button id="summarize-btn" class="primary" type="button"
        title="Get a TL;DR + bullet-point key notes (powered by AI)">
        Summarize
      </button>
      <div class="ai-menu-wrap">
        <button id="ai-btn" class="primary" type="button"
          aria-haspopup="true" aria-expanded="false"
          title="Clean up or translate with AI">
          AI: Refine or Translate
        </button>
        <div class="ai-menu" id="ai-menu" hidden role="menu">
          <button type="button" role="menuitem"
            data-mode="refine" data-target="">
            <span class="label">Refine (clean up)</span>
            <span class="hint">Punctuation, paragraphs · keep source language</span>
          </button>
          <button type="button" role="menuitem"
            data-mode="translate" data-target="en">
            <span class="label">Translate → English</span>
            <span class="hint">Fast Google Translate · full text</span>
          </button>
          <button type="button" role="menuitem"
            data-mode="translate" data-target="hi">
            <span class="label">Translate → हिन्दी (Hindi)</span>
            <span class="hint">Fast Google Translate · Devanagari</span>
          </button>
        </div>
      </div>
      <div class="ai-toggle" id="ai-toggle" style="display:none">
        <button class="active" data-view="original">Original</button>
        <button data-view="refined">AI Output</button>
      </div>
      <span class="ai-meta" id="ai-meta" style="display:none"></span>
    </div>
    <div class="ai-error" id="ai-error" style="display:none"></div>
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
    {video_title_footer_html}<a href="{url}" target="_blank" rel="noopener">{url}</a>
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
  const savedTheme = localStorage.getItem(THEME_KEY) || 'auto';
  document.documentElement.setAttribute('data-theme', savedTheme);
  const swatches = document.querySelectorAll('.theme-swatch');
  swatches.forEach(btn => {{
    if (btn.dataset.theme === savedTheme) btn.classList.add('active');
    btn.addEventListener('click', () => {{
      const t = btn.dataset.theme;
      document.documentElement.setAttribute('data-theme', t);
      localStorage.setItem(THEME_KEY, t);
      swatches.forEach(b => b.classList.toggle('active', b === btn));
    }});
  }});
{font_init_js}

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

  if (window.location.protocol === 'file:') {{
    document.getElementById('offline-notice').style.display = 'block';
  }}
  const _form = document.getElementById('url-form');
  if (_form) _form.addEventListener('submit', () => {{
    if (window.location.protocol === 'file:') return;
    const btn = document.getElementById('submit-btn');
    btn.textContent = 'Fetching…'; btn.disabled = true;
  }});

  // ----- AI refine / translate / summarize -------------------------------
  const LANG = {language_code_json};
  const aiBtn        = document.getElementById('ai-btn');
  const summarizeBtn = document.getElementById('summarize-btn');
  const aiMenu       = document.getElementById('ai-menu');
  const aiToggle     = document.getElementById('ai-toggle');
  const aiMeta       = document.getElementById('ai-meta');
  const aiError      = document.getElementById('ai-error');
  const aiStatus     = document.getElementById('ai-status');
  const aiStatusLabel = aiStatus.querySelector('.ai-label');
  const paraView     = document.getElementById('paragraph-view');
  const originalHTML = paraView.innerHTML;
  const BASE_TITLE   = document.title;
  // Every top-level AI control — disabled together while one is running,
  // hidden together once any AI run succeeds (toggle takes over).
  const aiControls = [aiBtn, summarizeBtn];
  let aiOutputHTML = null;
  let aiOutputText = null;
  // What we'd call the AI output ("Summary", "AI Refined", "English"…)
  // so the header pill can show "Viewing: <thing>" after a successful run.
  let lastAILabel = null;

  const TARGET_LABELS = {{
    en: 'English',
    hi: 'हिन्दी',
  }};

  // Update the sticky header pill + tab title. `state` is one of:
  //   'hidden'   — no AI activity yet (pill not shown)
  //   'running'  — spinner + accent background, AI call in flight
  //   'updated'  — clickable badge, currently showing AI output
  //   'original' — clickable badge, viewer flipped back to source
  function setAiStatus(state, label) {{
    aiStatus.classList.remove(
      'visible', 'running', 'updated', 'original', 'clickable'
    );
    if (state === 'hidden') {{
      aiStatus.removeAttribute('aria-busy');
      document.title = BASE_TITLE;
      return;
    }}
    aiStatus.classList.add('visible');
    aiStatusLabel.textContent = label;
    if (state === 'running') {{
      aiStatus.classList.add('running');
      aiStatus.setAttribute('aria-busy', 'true');
      document.title = '⏳ ' + label + ' · ' + BASE_TITLE;
    }} else if (state === 'updated') {{
      aiStatus.classList.add('updated', 'clickable');
      aiStatus.removeAttribute('aria-busy');
      document.title = BASE_TITLE;
    }} else if (state === 'original') {{
      aiStatus.classList.add('original', 'clickable');
      aiStatus.removeAttribute('aria-busy');
      document.title = BASE_TITLE;
    }}
  }}

  // Click the pill -> flip between Original and the AI output, reusing
  // the existing actions-bar toggle so both stay in sync.
  aiStatus.addEventListener('click', () => {{
    if (!aiStatus.classList.contains('clickable')) return;
    const activeView = aiToggle.querySelector('button.active')?.dataset.view;
    const target = activeView === 'refined' ? 'original' : 'refined';
    const btn = aiToggle.querySelector(
      'button[data-view="' + target + '"]'
    );
    if (btn) btn.click();
  }});

  if (window.location.protocol === 'file:') {{
    aiBtn.disabled = true;
    aiBtn.title = 'AI only works when served. Run: python cli.py --serve';
    aiBtn.textContent = 'AI (server only)';
    summarizeBtn.disabled = true;
    summarizeBtn.title = aiBtn.title;
    summarizeBtn.textContent = 'Summarize (server only)';
  }}

  function escapeHTML(s) {{
    return s.replace(/[&<>"']/g, c => ({{
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }}[c]));
  }}

  // Render Markdown-ish inline: escape, then convert **bold**.
  function renderInline(s) {{
    return escapeHTML(s).replace(/\\*\\*(.+?)\\*\\*/g,
      '<strong>$1</strong>');
  }}

  function renderParagraphs(text) {{
    return text.split(/\\n{{2,}}/).map(p => p.trim()).filter(Boolean)
      .map(p => '<p>' + escapeHTML(p) + '</p>').join('\\n');
  }}

  // For summary mode: a TL;DR line (starts with **TL;DR:**) + a bullet
  // list (lines starting with -, *, or •). Anything else becomes <p>.
  function renderSummary(text) {{
    const lines = text.split('\\n').map(l => l.trim());
    const out = [];
    let bullets = [];
    const flush = () => {{
      if (!bullets.length) return;
      out.push('<ul>' + bullets.map(b =>
        '<li>' + renderInline(b) + '</li>').join('') + '</ul>');
      bullets = [];
    }};
    for (const line of lines) {{
      if (!line) {{ flush(); continue; }}
      const tldrMatch = line.match(/^\\*\\*TL;DR:?\\*\\*\\s*(.*)$/i);
      const bulletMatch = line.match(/^[-*•]\\s+(.+)$/);
      if (tldrMatch) {{
        flush();
        out.push('<div class="tldr"><span class="tldr-label">TL;DR</span>'
          + renderInline(tldrMatch[1]) + '</div>');
      }} else if (bulletMatch) {{
        bullets.push(bulletMatch[1]);
      }} else {{
        flush();
        out.push('<p>' + renderInline(line) + '</p>');
      }}
    }}
    flush();
    return out.join('\\n') || '<p>' + escapeHTML(text) + '</p>';
  }}

  function showAIError(msg) {{
    const isSetup = msg.indexOf('No AI provider') !== -1;
    aiError.innerHTML = isSetup
      ? '<strong>No AI provider configured.</strong>\\n\\n'
        + escapeHTML(msg.replace(/^[^\\n]*\\n?/, ''))
      : '<strong>AI request failed:</strong> ' + escapeHTML(msg);
    aiError.style.display = 'block';
  }}

  function setMenuOpen(open) {{
    aiMenu.hidden = !open;
    aiBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }}

  aiBtn.addEventListener('click', (e) => {{
    e.stopPropagation();
    if (aiBtn.disabled) return;
    setMenuOpen(aiMenu.hidden);
  }});
  document.addEventListener('click', (e) => {{
    if (!aiMenu.contains(e.target) && e.target !== aiBtn) setMenuOpen(false);
  }});
  document.addEventListener('keydown', (e) => {{
    if (e.key === 'Escape') setMenuOpen(false);
  }});

  async function runAI(mode, target) {{
    setMenuOpen(false);
    aiError.style.display = 'none';
    // Whichever button kicked this off shows the running text; the rest
    // just get disabled so the user can't double-fire while waiting.
    const actingBtn = (mode === 'summarize') ? summarizeBtn : aiBtn;
    const origActingLabel = actingBtn.textContent;
    aiControls.forEach(b => {{ b.disabled = true; }});
    let verb;
    if (mode === 'translate') {{
      verb = 'Translating to ' + (TARGET_LABELS[target] || target) + '…';
    }} else if (mode === 'summarize') {{
      verb = 'Summarising…';
    }} else {{
      verb = 'Refining…';
    }}
    actingBtn.textContent = verb + ' (this can take a minute)';
    setAiStatus('running', verb);
    try {{
      const resp = await fetch('/api/refine', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          text: FULL_TEXT, language: LANG,
          mode: mode, target_language: target || ''
        }})
      }});
      const data = await resp.json().catch(() => ({{ error: 'invalid server response' }}));
      if (!resp.ok || data.error) throw new Error(data.error || ('HTTP ' + resp.status));

      aiOutputText = data.refined || '';
      aiOutputHTML = (mode === 'summarize')
        ? renderSummary(aiOutputText)
        : renderParagraphs(aiOutputText);
      paraView.innerHTML = aiOutputHTML;
      refreshWordCountFromView();

      // Hide BOTH primary AI controls — the toggle below takes over.
      const aiBtnWrap = aiBtn.closest('.ai-menu-wrap');
      if (aiBtnWrap) aiBtnWrap.style.display = 'none';
      summarizeBtn.style.display = 'none';

      let outLabel;
      if (mode === 'translate') {{
        outLabel = TARGET_LABELS[target] || target.toUpperCase();
      }} else if (mode === 'summarize') {{
        outLabel = 'Summary';
      }} else {{
        outLabel = 'AI Refined';
      }}
      lastAILabel = outLabel;
      const outBtn = aiToggle.querySelector('button[data-view="refined"]');
      outBtn.textContent = outLabel;

      aiToggle.style.display = 'inline-flex';
      aiToggle.querySelectorAll('button').forEach(b =>
        b.classList.toggle('active', b.dataset.view === 'refined')
      );

      let modeTxt;
      if (data.mode === 'translate') {{
        modeTxt = 'translated to ' + (TARGET_LABELS[data.target_language]
          || data.target_language || target);
      }} else if (data.mode === 'summarize') {{
        modeTxt = 'summarised';
      }} else {{
        modeTxt = 'refined';
      }}
      aiMeta.textContent = modeTxt + ' via ' + data.provider
        + (data.model ? ' (' + data.model + ')' : '');
      aiMeta.style.display = 'inline';

      setAiStatus('updated', 'Viewing: ' + outLabel);

      document.querySelector('.tabs button[data-target="paragraph-view"]').click();
    }} catch (e) {{
      showAIError(e.message || String(e));
      actingBtn.textContent = origActingLabel;
      aiControls.forEach(b => {{ b.disabled = false; }});
      // If a previous AI run succeeded, restore that label; otherwise hide.
      if (lastAILabel != null) {{
        const showing = aiToggle.querySelector('button.active')?.dataset.view;
        setAiStatus(
          showing === 'refined' ? 'updated' : 'original',
          'Viewing: ' + (showing === 'refined' ? lastAILabel : 'Original')
        );
      }} else {{
        setAiStatus('hidden');
      }}
    }}
  }}

  summarizeBtn.addEventListener('click', () => runAI('summarize', ''));

  aiMenu.querySelectorAll('button[data-mode]').forEach(item => {{
    item.addEventListener('click', () => {{
      runAI(item.dataset.mode, item.dataset.target || '');
    }});
  }});

  aiToggle.querySelectorAll('button').forEach(btn => {{
    btn.addEventListener('click', () => {{
      if (btn.classList.contains('active')) return;
      aiToggle.querySelectorAll('button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const showingAI = btn.dataset.view === 'refined';
      paraView.innerHTML = showingAI ? aiOutputHTML : originalHTML;
      refreshWordCountFromView();
      document.querySelector('.tabs button[data-target="paragraph-view"]').click();
      // Keep the sticky header pill in lock-step with this toggle.
      if (lastAILabel != null) {{
        setAiStatus(
          showingAI ? 'updated' : 'original',
          'Viewing: ' + (showingAI ? lastAILabel : 'Original')
        );
      }}
    }});
  }});

  // Recount words from whatever the paragraph view currently shows
  // (original transcript, AI summary, refined, or translation) and
  // update the header counter next to "Transcript".
  function refreshWordCountFromView() {{
    const counter = document.getElementById('word-count');
    const view    = document.getElementById('paragraph-view');
    if (!counter || !view) return;
    const tokens = (view.textContent || '').match(/\\S+/g);
    const n = tokens ? tokens.length : 0;
    counter.textContent = '· ' + n.toLocaleString() + ' words';
  }}

  // ----- "Hide [music]" toggle ---------------------------------------------
  // Pure frontend: strips ONLY the literal `[music]` and `>> [music] >>`
  // patterns from the paragraph view. Toggle on to clean, off to restore.
  (function setupNoiseToggle() {{
    const btn       = document.getElementById('noise-btn');
    const view      = document.getElementById('paragraph-view');
    const counter   = document.getElementById('word-count');
    if (!btn || !view) return;
    // Snapshot the originals so "off" is always a perfect restore.
    const originalHTML        = view.innerHTML;
    const originalCounterText = counter ? counter.textContent : '';
    // The only two patterns we touch (case-insensitive, whitespace-tolerant).
    const NOISE_RE = /(?:>>\\s*)?\\[\\s*music\\s*\\](?:\\s*>>)?/gi;

    function hideMusicNoise() {{
      // Walk each <p>'s textContent — the paragraph view contains no
      // inline elements, so this is safe and avoids HTML re-parsing risk.
      const tmp = document.createElement('div');
      tmp.innerHTML = originalHTML;
      const out = [];
      let words = 0;
      tmp.querySelectorAll('p').forEach(p => {{
        const cleaned = (p.textContent || '')
          .replace(NOISE_RE, '')
          .replace(/\\s+/g, ' ')
          .trim();
        if (cleaned) {{
          out.push('<p>' + escapeHTML(cleaned) + '</p>');
          words += cleaned.split(/\\s+/).filter(Boolean).length;
        }}
      }});
      view.innerHTML = out.join('\\n') ||
        '<p><em>(only music markers in this transcript)</em></p>';
      if (counter) counter.textContent =
        '· ' + words.toLocaleString() + ' words';
    }}

    btn.addEventListener('click', () => {{
      const nowPressed = btn.getAttribute('aria-pressed') !== 'true';
      btn.setAttribute('aria-pressed', nowPressed ? 'true' : 'false');
      if (nowPressed) {{
        hideMusicNoise();
      }} else {{
        view.innerHTML = originalHTML;
        if (counter) counter.textContent = originalCounterText;
      }}
    }});
  }})();
</script>
</body>
</html>
"""


_LANDING_TEMPLATE = """<!doctype html>
<html lang="en" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YT Transcriptor</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{google_fonts_url}" rel="stylesheet">
<style>{shared_css}</style>
</head>
<body>
<header>
  <div class="header-tools">
    {font_switcher_html}
    <div class="theme-switch" role="radiogroup" aria-label="Theme">
      <button type="button" class="theme-swatch" data-theme="auto"      title="Auto"      aria-label="Auto theme"></button>
      <button type="button" class="theme-swatch" data-theme="dark"      title="Dark"      aria-label="Dark theme"></button>
      <button type="button" class="theme-swatch" data-theme="light"     title="Light"     aria-label="Light theme"></button>
      <button type="button" class="theme-swatch" data-theme="sepia"     title="Sepia"     aria-label="Sepia theme"></button>
      <button type="button" class="theme-swatch" data-theme="midnight"  title="Midnight"  aria-label="Midnight theme"></button>
      <button type="button" class="theme-swatch" data-theme="solarized" title="Solarized" aria-label="Solarized theme"></button>
      <button type="button" class="theme-swatch" data-theme="forest"    title="Forest"    aria-label="Forest theme"></button>
      <button type="button" class="theme-swatch" data-theme="ubuntu"    title="Ubuntu"    aria-label="Ubuntu terminal theme"></button>
      <button type="button" class="theme-swatch" data-theme="matrix"    title="Matrix"    aria-label="Matrix terminal theme"></button>
      <button type="button" class="theme-swatch" data-theme="cyber"     title="Cyber"     aria-label="Cyber neon theme"></button>
    </div>
  </div>
</header>

<section class="landing">
  <h1>Turn any YouTube video into clean text</h1>
  <p class="lead">Paste a YouTube URL (or just the 11-char video id) and
    we'll fetch the transcript, group it into paragraphs, and let you
    scrub through the original video with clickable timestamps.</p>

  <section class="url-bar">
    <form action="/" method="get" id="url-form">
      <input type="text" name="url" id="url-input" required autocomplete="off"
        placeholder="https://youtube.com/watch?v=…"
        value="{prefilled_url}" autofocus>
      <input type="text" name="lang" id="lang-input" autocomplete="off"
        placeholder="languages e.g. en,hi" value="{prefilled_langs}">
      <button type="submit" id="submit-btn">Get transcript</button>
    </form>
    {error_block}
  </section>

  <div class="examples">
    Try: <a href="?url=IjIVBleSfc4&lang=hi">IjIVBleSfc4 (Hindi)</a>
    &nbsp;·&nbsp; <a href="?url=jNQXAC9IVRw">jNQXAC9IVRw (first ever YouTube video)</a>
  </div>
</section>

<footer>
  <div class="video-link"><strong>YT Transcriptor</strong> · paste a URL above</div>
  <div class="credit">Powered by youtube-transcript-api</div>
</footer>

<script>
  const THEME_KEY = 'yt-trans-theme';
  const savedTheme = localStorage.getItem(THEME_KEY) || 'auto';
  document.documentElement.setAttribute('data-theme', savedTheme);
  const swatches = document.querySelectorAll('.theme-swatch');
  swatches.forEach(btn => {{
    if (btn.dataset.theme === savedTheme) btn.classList.add('active');
    btn.addEventListener('click', () => {{
      const t = btn.dataset.theme;
      document.documentElement.setAttribute('data-theme', t);
      localStorage.setItem(THEME_KEY, t);
      swatches.forEach(b => b.classList.toggle('active', b === btn));
    }});
  }});
{font_init_js}
  document.getElementById('url-form').addEventListener('submit', () => {{
    const btn = document.getElementById('submit-btn');
    btn.textContent = 'Fetching…'; btn.disabled = true;
  }});
</script>
</body>
</html>
"""


def _paragraphs_html(paragraphs: str) -> str:
    if not paragraphs.strip():
        return "<p><em>(empty transcript)</em></p>"
    chunks = [p.strip() for p in paragraphs.split("\n\n") if p.strip()]
    return "\n".join(f"<p>{html.escape(p)}</p>" for p in chunks)


def _video_info_html(
    *, title: str | None, video_id: str, url: str
) -> str:
    """Right-aligned 'what video am I looking at' chunk shown next to the
    Transcript heading. Falls back gracefully to just the id when no
    title is available."""
    vid = html.escape(video_id)
    safe_url = html.escape(url, quote=True)
    if title:
        return (
            f'<a class="vt-title" href="{safe_url}" target="_blank" '
            f'rel="noopener" title="{html.escape(title)}">'
            f"{html.escape(title)}</a>"
            f'<span class="vt-id" title="Video ID">{vid}</span>'
        )
    return (
        f'<a class="vt-title" href="{safe_url}" target="_blank" '
        f'rel="noopener" title="Open on YouTube">Video</a>'
        f'<span class="vt-id" title="Video ID">{vid}</span>'
    )


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


def render(
    result: "TranscriptionResult",
    *,
    title: str | None = None,
    prefilled_url: str = "",
    prefilled_langs: str = "",
) -> str:
    """Render a TranscriptionResult to a complete HTML document string."""
    page_title = title or f"YouTube transcript · {result.video_id}"
    duration_human = format_timestamp(result.duration) if result.duration else "?"
    kind = "auto-generated" if result.is_generated else "manual"

    video_title = getattr(result, "title", None)

    return _TEMPLATE.format(
        shared_css=_SHARED_CSS,
        google_fonts_url=_GOOGLE_FONTS_URL,
        font_switcher_html=_FONT_SWITCHER_HTML,
        font_init_js=_FONT_INIT_JS,
        lang=html.escape(result.language_code or "en"),
        title=html.escape(page_title),
        url=html.escape(result.url),
        video_id=html.escape(result.video_id),
        video_id_json=json.dumps(result.video_id),
        language=html.escape(result.language),
        language_code=html.escape(result.language_code),
        language_code_json=json.dumps(result.language_code or "en"),
        kind=kind,
        snippet_count=result.snippet_count,
        duration_human=duration_human,
        word_count=f"{len(result.full_text.split()):,}",
        paragraph_html=_paragraphs_html(result.paragraphs),
        timestamped_html=_timestamped_html(result.raw),
        snippets_json=json.dumps(result.raw, ensure_ascii=False),
        full_text_json=json.dumps(result.full_text, ensure_ascii=False),
        download_name=html.escape(f"{result.video_id}.{result.language_code}.txt"),
        prefilled_url=html.escape(prefilled_url or result.url, quote=True),
        prefilled_langs=html.escape(prefilled_langs, quote=True),
        video_info_html=_video_info_html(
            title=video_title,
            video_id=result.video_id,
            url=result.url,
        ),
        video_title_footer_html=(
            f'<strong title="{html.escape(video_title)}">'
            f"{html.escape(video_title)}</strong> · "
            if video_title
            else ""
        ),
    )


def render_landing(
    *,
    error: str | None = None,
    prefilled_url: str = "",
    prefilled_langs: str = "",
) -> str:
    """Render the empty-state landing page (no video fetched yet)."""
    error_block = (
        f'<div class="error-msg">{html.escape(error)}</div>'
        if error
        else ""
    )
    return _LANDING_TEMPLATE.format(
        shared_css=_SHARED_CSS,
        google_fonts_url=_GOOGLE_FONTS_URL,
        font_switcher_html=_FONT_SWITCHER_HTML,
        font_init_js=_FONT_INIT_JS,
        prefilled_url=html.escape(prefilled_url, quote=True),
        prefilled_langs=html.escape(prefilled_langs, quote=True),
        error_block=error_block,
    )
