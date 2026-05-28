"""
Full-text PDF extraction with chapter detection for ebook mode.

Returns a list of chapter dicts:
  [{"chapter_title": str, "chapter_index": int, "raw_text": str}, ...]

Chapter detection uses heading heuristics:
  - Lines matching /^(Chapter|Kapitel|Teil|CHAPTER|Lektion|Unit|Lesson)\s*\d+/i
  - Lines that are all-uppercase and short (≤ 60 chars)
  - Lines starting with a digit followed by a dot (e.g. "1. Einleitung")

Falls back to page-grouped chunks (every 5 pages) when no chapter markers are found.
"""
import re
import pdfplumber


_CHAPTER_PATTERNS = [
    re.compile(r"^(chapter|kapitel|teil|lektion|unit|lesson|abschnitt)\s*\d+", re.IGNORECASE),
    re.compile(r"^\d+\.\s+\S"),           # "1. Introduction"
]


def _is_chapter_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if any(p.match(stripped) for p in _CHAPTER_PATTERNS):
        return True
    # Short all-caps line (likely a heading, not body text)
    if stripped.isupper() and 3 <= len(stripped) <= 60:
        return True
    return False


def read_pdf_chapters(path: str) -> list[dict]:
    """
    Extract full text from a PDF and split into chapters.

    Returns:
        [{"chapter_title": str, "chapter_index": int, "raw_text": str}, ...]
    """
    pages_text: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages_text.append(text)

    full_text = "\n".join(pages_text)
    lines = full_text.splitlines()

    # Try to detect chapter boundaries
    chapter_starts: list[tuple[int, str]] = []  # (line_index, heading_text)
    for i, line in enumerate(lines):
        if _is_chapter_heading(line):
            chapter_starts.append((i, line.strip()))

    if len(chapter_starts) >= 2:
        return _split_by_headings(lines, chapter_starts)
    else:
        return _split_by_pages(pages_text)


def _split_by_headings(lines: list[str], chapter_starts: list[tuple[int, str]]) -> list[dict]:
    chapters = []
    for idx, (start_line, title) in enumerate(chapter_starts):
        end_line = chapter_starts[idx + 1][0] if idx + 1 < len(chapter_starts) else len(lines)
        body = "\n".join(lines[start_line + 1:end_line]).strip()
        if body:
            chapters.append({
                "chapter_title": title,
                "chapter_index": idx,
                "raw_text": body,
            })
    return chapters


def _split_by_pages(pages_text: list[str], pages_per_chunk: int = 5) -> list[dict]:
    """Fallback: group pages into chunks when no chapter headings are detected."""
    chunks = []
    for i in range(0, len(pages_text), pages_per_chunk):
        group = pages_text[i:i + pages_per_chunk]
        body = "\n".join(group).strip()
        if body:
            chunk_idx = i // pages_per_chunk
            chunks.append({
                "chapter_title": f"Pages {i + 1}–{i + len(group)}",
                "chapter_index": chunk_idx,
                "raw_text": body,
            })
    return chunks
