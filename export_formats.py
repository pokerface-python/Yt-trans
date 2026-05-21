"""Build transcript export files (PDF with Unicode, plain text, Word HTML)."""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path

_MODULE_DIR = Path(__file__).resolve().parent

# Devanagari and common Indic punctuation (danda, etc.)
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F\uA8E0-\uA8FF\u1CD0-\u1CFF]")


class ExportError(RuntimeError):
    """Export generation failed."""


def _font_candidates(names: tuple[str, ...]) -> list[Path]:
    paths: list[Path] = []
    for name in names:
        paths.append(_MODULE_DIR / "fonts" / name)
    return paths


def _find_latin_font() -> str:
    """TTF with Latin (and most European scripts) for PDF body text."""
    candidates: list[Path] = _font_candidates(
        ("DejaVuSans.ttf", "NotoSans-Regular.ttf")
    )
    candidates.extend(
        [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
            Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ]
    )
    try:
        import fpdf  # noqa: F401

        pkg = Path(fpdf.__file__).resolve().parent
        candidates.extend(
            [
                pkg / "font" / "DejaVuSans.ttf",
                pkg / "font" / "unifont" / "DejaVuSans.ttf",
            ]
        )
    except ImportError:
        pass

    for path in candidates:
        if path.is_file():
            return str(path)

    raise ExportError(
        "PDF needs a Latin font (DejaVu or Noto Sans). "
        "Install fpdf2 (pip install fpdf2) or fonts-dejavu-core on Ubuntu."
    )


def _find_indic_fallback_font() -> str | None:
    """Optional TTF for Devanagari / Hindi when the primary font lacks those glyphs."""
    candidates: list[Path] = _font_candidates(
        (
            "NotoSansDevanagari-Regular.ttf",
            "Lohit-Devanagari.ttf",
        )
    )
    candidates.extend(
        [
            Path(
                "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"
            ),
            Path(
                "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf"
            ),
            Path(
                "/usr/share/fonts/truetype/noto/NotoSerifDevanagari-Regular.ttf"
            ),
        ]
    )
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def _text_needs_indic_font(text: str) -> bool:
    return bool(_DEVANAGARI_RE.search(text))


def build_txt(text: str, title: str, video_url: str = "") -> bytes:
    header = title
    if video_url:
        header += f"\n{video_url}"
    header += "\n\n"
    return (header + text).encode("utf-8")


def build_doc_html(text: str, title: str, video_url: str = "") -> bytes:
    safe_title = html.escape(title)
    safe_url = html.escape(video_url) if video_url else ""
    body = html.escape(text).replace("\n", "<br>\n")
    doc = (
        '<html xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:w="urn:schemas-microsoft-com:office:word">'
        f"<head><meta charset=\"utf-8\"><title>{safe_title}</title></head>"
        "<body style=\"font-family:Georgia,serif;font-size:15px;line-height:1.75;"
        "max-width:720px;margin:36px auto;color:#111\">"
        f"<h1 style=\"font-size:20px;margin:0 0 8px\">{safe_title}</h1>"
    )
    if safe_url:
        doc += f"<p style=\"font-size:12px;color:#555;margin:0 0 24px\">{safe_url}</p>"
    doc += f"<div>{body}</div></body></html>"
    return "\ufeff".encode("utf-8") + doc.encode("utf-8")


def build_pdf(text: str, title: str, video_url: str = "") -> bytes:
    """Render a readable UTF-8 PDF using fpdf2 + Unicode fonts with Indic fallback."""
    # fpdf2/fontTools log every glyph subset at INFO — quiet for large transcripts.
    for logger_name in ("fontTools", "fontTools.subset"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    try:
        from fpdf import FPDF
    except ImportError as exc:
        raise ExportError(
            "PDF export requires fpdf2. From the project folder run:\n"
            "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt\n"
            "Then start the server with: .venv/bin/python cli.py --serve"
        ) from exc

    latin_path = _find_latin_font()
    indic_path = _find_indic_fallback_font()
    combined = f"{title}\n{video_url}\n{text}"
    if _text_needs_indic_font(combined) and not indic_path:
        raise ExportError(
            "This transcript contains Hindi/Devanagari text but no Indic font "
            "was found. Install fonts-noto-core or fonts-noto-devanagari "
            "(e.g. sudo apt install fonts-noto-core)."
        )

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(20, 20, 20)
    pdf.add_font("Body", "", latin_path)
    if indic_path:
        pdf.add_font("Indic", "", indic_path)
        pdf.set_fallback_fonts(["Indic"])
    pdf.add_page()

    page_w = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_font("Body", size=16)
    pdf.multi_cell(page_w, 9, title, new_x="LMARGIN", new_y="NEXT")

    if video_url:
        pdf.set_font("Body", size=9)
        pdf.set_text_color(100, 100, 100)
        pdf.multi_cell(page_w, 5, video_url, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

    pdf.ln(5)
    pdf.set_font("Body", size=11)

    # One multi_cell keeps fpdf2 fallback fonts working for mixed Hindi + Latin.
    # Splitting into per-paragraph cells breaks Latin text after Devanagari lines.
    body = text.strip()
    if body:
        pdf.multi_cell(page_w, 6, body, new_x="LMARGIN", new_y="NEXT")

    out = pdf.output()
    if isinstance(out, str):
        return out.encode("latin-1", errors="replace")
    return bytes(out)
