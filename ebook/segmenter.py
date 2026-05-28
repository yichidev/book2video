"""
Sentence boundary detection for ebook mode.

Takes a list of chapter dicts (from pdf_reader.read_pdf_chapters) and returns
a flat list of sentence dicts, one per sentence:

  [
    {
      "chapter": str,
      "chapter_index": int,
      "sentence_index": int,   # global index across the whole book
      "source_sentence": str,
    },
    ...
  ]

Uses pysbd for language-aware sentence splitting.
Filters out fragments shorter than 5 words and header-like lines.
"""
import re

try:
    import pysbd
    _PYSBD_AVAILABLE = True
except ImportError:
    _PYSBD_AVAILABLE = False


_MIN_WORDS = 5


def _split_sentences(text: str, lang: str) -> list[str]:
    if _PYSBD_AVAILABLE:
        seg = pysbd.Segmenter(language=lang, clean=True)
        return seg.segment(text)
    # Fallback: naive split on sentence-ending punctuation
    raw = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in raw if s.strip()]


def _is_valid_sentence(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    words = text.split()
    if len(words) < _MIN_WORDS:
        return False
    # Skip all-caps headers (e.g. "KAPITEL DREI")
    if text.isupper():
        return False
    # Skip lines that look like page numbers, headers, or metadata
    if re.match(r"^\d+$", text):
        return False
    return True


def segment_chapters(chapters: list[dict], lang: str = "de") -> list[dict]:
    """
    Split chapter text into individual sentences.

    Args:
        chapters: output of pdf_reader.read_pdf_chapters()
        lang:     2-letter language code used by pysbd (e.g. 'de', 'en', 'fr')

    Returns:
        Flat list of sentence dicts with chapter metadata.
    """
    results = []
    global_idx = 0

    for chapter in chapters:
        sentences = _split_sentences(chapter["raw_text"], lang)
        for sentence in sentences:
            sentence = sentence.strip()
            if not _is_valid_sentence(sentence):
                continue
            results.append({
                "chapter": chapter["chapter_title"],
                "chapter_index": chapter["chapter_index"],
                "sentence_index": global_idx,
                "source_sentence": sentence,
            })
            global_idx += 1

    return results
