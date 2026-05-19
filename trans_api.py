"""Minimal example: convert a YouTube video URL into a clean full-text transcript.

For the full-featured CLI run:
    python cli.py <youtube-url-or-id> [--languages hi en] [--format paragraphs|srt|json]
"""

from transcriptor import Transcriptor

URL = "https://www.youtube.com/watch?v=IjIVBleSfc4"

if __name__ == "__main__":
    transcriptor = Transcriptor(languages=["hi", "en"])
    result = transcriptor.transcribe(URL)

    print(
        f"video : {result.url}\n"
        f"lang  : {result.language} ({result.language_code})"
        f"  [{'auto' if result.is_generated else 'manual'}]\n"
        f"length: {result.snippet_count} snippets, ~{result.duration:.0f}s\n"
    )
    print(result.paragraphs)

    out = result.save()
    print(f"\nsaved to {out}")
