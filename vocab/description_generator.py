"""
Generate a YouTube/social media description for a vocabulary video.

Output (description.txt, written next to summary.txt):

    Memorize German vocabulary for A1 (with English)

    Vocabulary comes from the A1 DEUTSCH WORTLISTE:
    https://...

    [AI-generated 2-3 sentence summary of vocabulary topics]

    ---
    die Familie · family
    fahren · drive
    für · for
    ...
"""
from pathlib import Path
import config

# ---------------------------------------------------------------------------
# Channel / resource defaults — edit these once, used in every description
# ---------------------------------------------------------------------------
_YOUTUBE_URL = "https://www.youtube.com/@yichi_learn"
_QUIZLET_URL = "https://quizlet.com/user/cychen1105/folders/goethe-zertifikat-ai?i=3zm5wp&x=1xqt"
_ANKI_URL    = "https://ankiweb.net/shared/info/1750219579?cb=1779721612823"

# Source PDF — always included, no override needed
_SOURCE_PDF_URL = "https://www.goethe.de/pro/relaunch/prf/de/A1_SD1_Wortliste_02.pdf"

# Transparency note — describes exactly what is and isn't AI in the pipeline
_HOW_MADE = f"""\
🛠 How this video was made:
• My open-source code used to create this video: https://github.com/yichidev/book2video
• Vocabulary list: from the official Goethe-Zertifikat A1 DEUTSCH WORTLISTE ({_SOURCE_PDF_URL})
• Extraction & structuring: OpenAI GPT reads the PDF 
• Translation: DeepL
• Voice narration: OpenAI text-to-speech
• Video editing & timing: automated (Python / MoviePy)
• Human review: vocabulary list and translations are manually proofread before publishing
"""
# ---------------------------------------------------------------------------

_LANG_NAMES = {
    "de": "German", "en": "English", "zh": "Chinese", "fr": "French",
    "es": "Spanish", "it": "Italian", "ja": "Japanese", "ko": "Korean",
    "pt": "Portuguese", "ru": "Russian", "nl": "Dutch", "pl": "Polish",
    "ar": "Arabic", "tr": "Turkish", "sv": "Swedish",
}



def _lang_name(code: str) -> str:
    return _LANG_NAMES.get(code.lower(), code.upper())



def generate_description(
    collection: str,
    book: str,
    source_lang: str = "de",
    target_lang: str = "en",
) -> Path:
    """
    Generate description.txt next to summary.txt, reading word pairs from
    the existing summary.txt rather than rebuilding them.

    Args:
        collection:  collection name, e.g. "A1_F_1"
        book:        book identifier, e.g. "A1"
        source_lang: source language code
        target_lang: target language code

    Returns:
        Path to the written description.txt
    """
    text_dir = config.OUTPUT_DIR / collection / "text"
    summary_path = text_dir / "summary.txt"
    if not summary_path.exists():
        raise FileNotFoundError(f"summary.txt not found at {summary_path} — run audio-and-video stage first.")

    word_pairs = [
        line.strip()
        for line in summary_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    if not word_pairs:
        raise ValueError("summary.txt is empty — run audio-and-video stage first.")

    src_name = _lang_name(source_lang)
    tgt_name = _lang_name(target_lang)

    # Infer the letter from the first word pair (strip leading article)
    first_source = word_pairs[0].split(" · ")[0] if word_pairs else ""
    for art in ("der ", "die ", "das ", "der/die "):
        if first_source.lower().startswith(art):
            first_source = first_source[len(art):]
            break
    letter = first_source[0].upper() if first_source else ""
    letter_part = f" (letter {letter}; with {tgt_name})" if letter else f" (with {tgt_name})"

    # Header
    lines = [
        f"Goethe {src_name} vocabulary for {book}{letter_part}",
        "",
    ]

    # Transparency — how the video was made
    lines += [_HOW_MADE, ""]

    # Practice resources & channel
    lines += [
        "📚 Resources for practice (whole collection of A1 vocabulary):",
        f"Quizlet: {_QUIZLET_URL}",
        f"Anki: {_ANKI_URL}",
        f"YouTube: {_YOUTUBE_URL}",
        "",
    ]

    # Word list (directly from summary.txt)
    lines += [f"{len(word_pairs)} German vocabularies in this video:", "---"] + word_pairs

    text_dir.mkdir(parents=True, exist_ok=True)
    out_path = text_dir / "description.txt"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[describe] Saved → {out_path}")
    return out_path
