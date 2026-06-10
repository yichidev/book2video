"""
book2video pipeline

VOCAB MODE (default):
  # Individual stages
  python pipeline.py --collection A1_A --pdf input/books/A1.pdf --alphabet A --stage extract
  python pipeline.py --collection A1_A_1 --stage translate
  python pipeline.py --collection A1_A_1 --stage audio
  python pipeline.py --collection A1_A_1 --stage audio --tts gtts
  python pipeline.py --collection A1_A_1 --stage video
  python pipeline.py --collection A1_A_1 --stage audio-and-video   # audio + video in one go
  python pipeline.py --collection A1_A_1 --stage anki [--anki-connect]
  python pipeline.py --collection A1_A_1 --stage quizlet
  python pipeline.py --collection A1_A_1 --stage describe

  # Different target language
  python pipeline.py --collection B1_A --pdf input/books/B1.pdf --alphabet A --source-lang de --target-lang zh --stage extract

EBOOK MODE:
  # Individual stages
  python pipeline.py --mode ebook --book mynovel --pdf input/books/novel.pdf --stage extract
  python pipeline.py --mode ebook --book mynovel --stage translate
  python pipeline.py --mode ebook --book mynovel --stage audio
  python pipeline.py --mode ebook --book mynovel --stage video

  # Full pipeline at once
  python pipeline.py --mode ebook --book mynovel --pdf input/books/novel.pdf
"""

import argparse
import json
import math
import sys
from pathlib import Path

import config
from vocab.extractor import file_search_merged, parse_to_vocabulary
from services.translator import add_translation
from vocab.exporters.anki import create_anki_deck, push_to_ankiconnect
from vocab.exporters.quizlet import create_quizlet_export
from vocab.video_builder import create_vocabulary_video, generate_vocabulary_audio
from storage.mongodb import (
    get_collection, save_collection, mark_video_generated,
    list_similar_collections, delete_collection,
    save_ebook_sentences, get_ebook_sentences, update_ebook_translations, mark_ebook_audio_generated,
)


def _split_evenly(items: list, max_size: int = 30, min_last: int = 15) -> list[list]:
    total = len(items)
    if total <= max_size:
        return [items]
    n = math.ceil(total / max_size)
    chunk_size = math.ceil(total / n)
    last_chunk_size = total - (n - 1) * chunk_size
    if 0 < last_chunk_size < min_last:
        n -= 1
        chunk_size = math.ceil(total / n)
    return [items[i:i + chunk_size] for i in range(0, total, chunk_size)]


def _ask_split(collection: str, items: list) -> list[tuple[str, list]]:
    """Show word count + words per chunk, let the user decide. Returns (name, chunk) pairs."""
    total = len(items)
    print(f"[extract] Extracted {total} words.")

    if total <= 30:
        return [(collection, items)]

    suggested = _split_evenly(items)
    names = [f"{collection}_{i}" for i in range(1, len(suggested) + 1)]

    print(f"\n[split] Suggested: {len(suggested)} chunks\n")
    for name, chunk in zip(names, suggested):
        words = ", ".join(k for k, _ in chunk)
        print(f"  {name} ({len(chunk)} words): {words}")

    print(f"\n  [1] Accept suggested split")
    print(f"  [2] Custom chunk size")
    print(f"  [3] No split (keep all {total} in '{collection}')")

    try:
        choice = input("\nYour choice [1]: ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        choice = "1"

    if choice == "3":
        return [(collection, items)]

    if choice == "2":
        try:
            size = int(input(f"Words per chunk (total={total}): ").strip())
        except (ValueError, EOFError):
            size = 30
        chunks = [items[i:i + size] for i in range(0, total, size)]
    else:
        chunks = suggested

    if len(chunks) == 1:
        return [(collection, chunks[0])]
    return [(f"{collection}_{i}", chunk) for i, chunk in enumerate(chunks, 1)]


def _sync_from_json(collection: str) -> None:
    """Prompt user to sync the most recent local JSON into MongoDB before a stage runs."""
    text_dir = config.OUTPUT_DIR / collection / "text"
    if not text_dir.exists():
        return
    json_files = sorted(text_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not json_files:
        return
    latest = json_files[0]
    with open(latest, encoding="utf-8") as f:
        vocabulary = json.load(f)
    if not _confirm(f"[sync] Sync {len(vocabulary)} entries from {latest.name} into MongoDB?"):
        return
    existing = get_collection(collection)
    book, source_lang, target_lang = _meta_from_entries(existing)
    save_collection(collection, vocabulary, book=book, source_lang=source_lang, target_lang=target_lang)
    print(f"[sync] {len(vocabulary)} entries ← {latest}")


def _write_json(collection: str, entries: list[dict]) -> None:
    out_dir = config.OUTPUT_DIR / collection / "text"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Suffix reflects actual content: de.json after extract, de_en.json only after translation exists
    src = entries[0].get("source_lang", "de") if entries else "de"
    is_translated = any(e.get("target_word") for e in entries)
    tgt = entries[0].get("target_lang", "") if (entries and is_translated) else ""
    suffix = f"{src}_{tgt}" if tgt else src
    path = out_dir / f"{collection}_{suffix}.json"
    _skip = {"lemma", "collection", "updated_at", "book", "source_lang", "target_lang", "book_type"}
    data = {e["lemma"]: {k: v for k, v in e.items() if k not in _skip} for e in entries}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"[sync] Local JSON updated → {path}")


def _confirm(message: str, default_yes: bool = True) -> bool:
    hint = "[Y/n]" if default_yes else "[y/N]"
    try:
        answer = input(f"{message} {hint}: ").strip().lower()
        if not answer:
            return default_yes
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return default_yes


def _meta_from_entries(entries: list[dict]) -> tuple[str, str, str]:
    """Read book/source_lang/target_lang from existing MongoDB entries."""
    if entries:
        e = entries[0]
        return e.get("book", ""), e.get("source_lang", "de"), e.get("target_lang", "en")
    return "", "de", "en"


def run_extract(collection: str, pdf: str, alphabet: str, book: str, source_lang: str, target_lang: str) -> None:
    source_lang = source_lang or "de"
    target_lang = target_lang or "en"

    entries = get_collection(collection)
    if entries:
        if _confirm(f"[extract] '{collection}' already has {len(entries)} entries in MongoDB. Re-extract from PDF?", default_yes=False):
            print(f"[extract] {pdf} alphabet={alphabet}")
            raw = file_search_merged(pdf_path=pdf, alphabet=alphabet)
            vocabulary = parse_to_vocabulary(raw)
        else:
            # Use existing words but still allow re-splitting
            vocabulary = {e["lemma"]: {"source_word": e["source_word"], "source_sentence": e.get("source_sentence", "")} for e in entries}
    else:
        print(f"[extract] {pdf} alphabet={alphabet}")
        raw = file_search_merged(pdf_path=pdf, alphabet=alphabet)
        vocabulary = parse_to_vocabulary(raw)

    named_chunks = _ask_split(collection, list(vocabulary.items()))
    chunk_names = []
    for chunk_name, chunk_items in named_chunks:
        chunk_vocab = dict(chunk_items)
        save_collection(chunk_name, chunk_vocab, book=book, source_lang=source_lang, target_lang=target_lang)
        print(f"[extract] Saved {len(chunk_vocab)} entries to MongoDB collection '{chunk_name}'")
        _write_json(chunk_name, get_collection(chunk_name))
        chunk_names.append(chunk_name)
    for chunk_name in chunk_names:
        print(f"\n[next] Review the extracted words in output/{chunk_name}/text/{chunk_name}_de.json")
        print(f"[next] Then run: python pipeline.py --collection {chunk_name} --stage translate")


def run_translate(collection: str, source_lang: str, target_lang: str) -> None:
    _sync_from_json(collection)
    entries = get_collection(collection)
    if not entries:
        print(f"[translate] No entries found for '{collection}'. Run extract first.")
        sys.exit(1)

    translated_count = sum(1 for e in entries if e.get("target_word"))
    if translated_count > 0:
        if _confirm(f"[translate] '{collection}' already has translations for {translated_count}/{len(entries)} entries. Use existing?"):
            print(f"[translate] Skipping — using existing translations.")
            return

    book, src, tgt = _meta_from_entries(entries)
    source_lang = source_lang or src
    target_lang = target_lang or tgt

    # DeepL uses uppercase lang codes (e.g. "DE", "EN-US", "ZH")
    deepl_source = source_lang.upper()
    deepl_target = target_lang.upper()
    if deepl_target == "EN":
        deepl_target = "EN-US"

    print(f"[translate] Loading '{collection}' from MongoDB ({source_lang}→{target_lang})")
    vocabulary = {e["lemma"]: {"source_word": e["source_word"], "source_sentence": e.get("source_sentence", "")} for e in entries}
    translated = add_translation(vocabulary, source_lang=deepl_source, target_lang=deepl_target)
    save_collection(collection, translated, book=book, source_lang=source_lang, target_lang=target_lang)
    print(f"[translate] Updated {len(translated)} entries in MongoDB")
    _write_json(collection, get_collection(collection))
    print(f"\n[next] Review the translations in output/{collection}/text/{collection}_de_en.json")
    print(f"[next] Then run: python pipeline.py --collection {collection} --stage audio-and-video")


def _pos_key(entry: dict) -> int:
    lemma = entry.get("file_name", "")
    word = entry.get("source_word", "")
    if lemma and lemma[0].isupper():
        return 0  # noun
    if word.endswith(("en", "ern")) or "(sich)" in word:
        return 2  # verb
    return 1  # adjective / other


def run_audio(collection: str, tts_provider: str | None, source_lang: str, target_lang: str) -> None:
    audio_dir = config.OUTPUT_DIR / collection / "audio"
    reuse_audio = False
    if audio_dir.exists():
        audio_files = list(audio_dir.glob("*.mp3"))
        if audio_files:
            reuse_audio = _confirm(f"[audio] {len(audio_files)} audio files already exist for '{collection}'. Reuse existing audio?")

    _sync_from_json(collection)
    tts = tts_provider or config.DEFAULT_TTS_PROVIDER
    print(f"[audio] Loading '{collection}' from MongoDB (tts={tts})")
    entries = get_collection(collection)
    if not entries:
        print(f"[audio] No entries found for '{collection}'. Run extract + translate first.")
        sys.exit(1)

    _, src, tgt = _meta_from_entries(entries)
    source_lang = source_lang or src
    target_lang = target_lang or tgt

    vocabulary = [
        {
            "file_name": e["lemma"],
            "source_word": e["source_word"],
            "target_word": e.get("target_word", ""),
            "source_sentence": e.get("source_sentence", ""),
            "target_sentence": e.get("target_sentence", ""),
        }
        for e in entries
    ]
    vocabulary.sort(key=_pos_key)
    generate_vocabulary_audio(vocabulary, collection, source_lang=source_lang, target_lang=target_lang,
                              tts_provider=tts, reuse_audio=reuse_audio)
    print(f"\n[audio] Done. Audio files saved to output/{collection}/audio/")
    print(f"[next] Listen to a few files to check quality.")
    print(f"[next] To fix a broken word: python scripts/regen_audio.py {collection} <Lemma>")
    print(f"[next] Then run: python pipeline.py --collection {collection} --stage video")


def run_video(collection: str, tts_provider: str | None, source_lang: str, target_lang: str) -> None:
    video_path = config.OUTPUT_DIR / collection / "video" / "vocabulary_video.mp4"
    if video_path.exists():
        if _confirm(f"[video] Video already exists at {video_path}. Use existing?"):
            print(f"[video] Skipping — using existing video.")
            return

    _sync_from_json(collection)
    tts = tts_provider or config.DEFAULT_TTS_PROVIDER
    print(f"[video] Loading '{collection}' from MongoDB (tts={tts})")
    entries = get_collection(collection)
    if not entries:
        print(f"[video] No entries found for '{collection}'. Run extract + translate first.")
        sys.exit(1)

    _, src, tgt = _meta_from_entries(entries)
    source_lang = source_lang or src
    target_lang = target_lang or tgt

    vocabulary = [
        {
            "file_name": e["lemma"],
            "source_word": e["source_word"],
            "target_word": e.get("target_word", ""),
            "source_sentence": e.get("source_sentence", ""),
            "target_sentence": e.get("target_sentence", ""),
        }
        for e in entries
    ]

    book, _, _ = _meta_from_entries(entries)
    vocabulary.sort(key=_pos_key)
    create_vocabulary_video(
        vocabulary, collection,
        source_lang=source_lang, target_lang=target_lang,
        tts_provider=tts, reuse_audio=True,
        book=book,
    )
    mark_video_generated(collection)
    print(f"[video] Done: {video_path}")
    print(f"\n[next] Watch the video at {video_path}")
    print(f"[next] Then export: python pipeline.py --collection {collection} --stage anki")
    print(f"[next]          or: python pipeline.py --collection {collection} --stage quizlet")


def run_anki(collection: str, tts_provider: str | None, anki_connect: bool, source_lang: str, target_lang: str) -> None:
    _sync_from_json(collection)
    tts = tts_provider or config.DEFAULT_TTS_PROVIDER
    print(f"[anki] Loading '{collection}' from MongoDB (tts={tts})")
    entries = get_collection(collection)
    if not entries:
        print(f"[anki] No entries found for '{collection}'. Run extract + translate first.")
        sys.exit(1)

    _, src, tgt = _meta_from_entries(entries)
    source_lang = source_lang or src
    target_lang = target_lang or tgt

    vocabulary = [
        {
            "file_name": e["lemma"],
            "source_word": e["source_word"],
            "target_word": e.get("target_word", ""),
            "source_sentence": e.get("source_sentence", ""),
            "target_sentence": e.get("target_sentence", ""),
        }
        for e in entries
    ]

    apkg_path = config.OUTPUT_DIR / collection / "anki" / f"{collection}.apkg"
    if apkg_path.exists():
        if _confirm(f"[anki] Deck already exists at {apkg_path}. Regenerate?", default_yes=False):
            apkg_path = create_anki_deck(vocabulary, collection, source_lang=source_lang, target_lang=target_lang, tts_provider=tts)
        else:
            print(f"[anki] Using existing deck.")
    else:
        apkg_path = create_anki_deck(vocabulary, collection, source_lang=source_lang, target_lang=target_lang, tts_provider=tts)

    if anki_connect:
        push_to_ankiconnect(apkg_path, vocabulary=vocabulary, collection=collection)
        print(f"\n[next] Deck pushed to Anki via AnkiConnect.")
        print(f"[next] Open Anki → File → Sync to upload to AnkiWeb.")
    else:
        print(f"\n[next] Anki deck saved to {apkg_path}")
        print(f"[next] Import into Anki: File → Import → select the .apkg file")
        print(f"[next] Or push directly: python pipeline.py --collection {collection} --stage anki --anki-connect")


def run_describe(collection: str, source_lang: str, target_lang: str) -> None:
    from vocab.description_generator import generate_description

    _sync_from_json(collection)
    entries = get_collection(collection)
    if not entries:
        print(f"[describe] No entries found for '{collection}'. Run extract + translate first.")
        sys.exit(1)

    book, src, tgt = _meta_from_entries(entries)
    source_lang = source_lang or src
    target_lang = target_lang or tgt

    generate_description(
        collection=collection,
        book=book or collection.split("_")[0],
        source_lang=source_lang, target_lang=target_lang,
    )
    print(f"\n[next] Copy description.txt content into your YouTube/social media post.")


def run_quizlet(collection: str) -> None:
    out_path = config.OUTPUT_DIR / collection / "quizlet" / f"{collection}.txt"
    if out_path.exists():
        if _confirm(f"[quizlet] Export already exists at {out_path}. Use existing?"):
            print(f"[quizlet] Skipping — using existing export.")
            print(f"\n[next] Quizlet file: {out_path}")
            print("[next] Import into Quizlet: Create set → Import from → set separator to Tab / New line")
            return

    _sync_from_json(collection)
    print(f"[quizlet] Loading '{collection}' from MongoDB")
    entries = get_collection(collection)
    if not entries:
        print(f"[quizlet] No entries found for '{collection}'. Run extract + translate first.")
        sys.exit(1)

    vocabulary = [
        {
            "file_name": e["lemma"],
            "source_word": e["source_word"],
            "target_word": e.get("target_word", ""),
        }
        for e in entries
    ]
    create_quizlet_export(vocabulary, collection)
    print(f"\n[next] Quizlet file saved to output/{collection}/quizlet/{collection}.txt")
    print("[next] Import into Quizlet: Create set → Import from → set separator to Tab / New line")


# ---------------------------------------------------------------------------
# Ebook mode stage functions
# ---------------------------------------------------------------------------

def run_ebook_extract(book: str, pdf: str, source_lang: str, target_lang: str) -> None:
    from ebook.pdf_reader import read_pdf_chapters
    from ebook.segmenter import segment_chapters

    source_lang = source_lang or "de"
    target_lang = target_lang or "en"

    existing = get_ebook_sentences(book)
    if existing:
        if not _confirm(f"[ebook] '{book}' already has {len(existing)} sentences. Re-extract?", default_yes=False):
            print(f"[ebook] Keeping existing {len(existing)} sentences.")
            return

    print(f"[ebook] Reading PDF: {pdf}")
    chapters = read_pdf_chapters(pdf)
    print(f"[ebook] Detected {len(chapters)} chapters")

    sentences = segment_chapters(chapters, lang=source_lang)
    print(f"[ebook] Segmented into {len(sentences)} sentences")

    save_ebook_sentences(book, sentences, source_lang=source_lang, target_lang=target_lang)
    print(f"[ebook] Saved to MongoDB (book='{book}')")
    print(f"\n[next] Run: python pipeline.py --mode ebook --book {book} --stage translate")


def run_ebook_translate(book: str, source_lang: str, target_lang: str) -> None:
    import deepl

    sentences = get_ebook_sentences(book)
    if not sentences:
        print(f"[ebook] No sentences found for '{book}'. Run extract first.")
        sys.exit(1)

    already_translated = sum(1 for s in sentences if s.get("target_sentence"))
    if already_translated > 0:
        if _confirm(f"[ebook] {already_translated}/{len(sentences)} sentences already translated. Use existing?"):
            print("[ebook] Skipping translation.")
            return

    src = (source_lang or sentences[0].get("source_lang", "de")).upper()
    tgt = (target_lang or sentences[0].get("target_lang", "en")).upper()
    if tgt == "EN":
        tgt = "EN-US"

    print(f"[ebook] Translating {len(sentences)} sentences ({src}→{tgt})")
    translator = deepl.Translator(config.DEEPL_API_KEY)
    updates = []
    for s in sentences:
        try:
            translated = translator.translate_text(
                s["source_sentence"], source_lang=src, target_lang=tgt
            ).text
        except Exception as e:
            print(f"[warn] Translation failed for sentence {s['sentence_index']}: {e}")
            translated = ""
        updates.append({
            "chapter_index": s["chapter_index"],
            "sentence_index": s["sentence_index"],
            "target_sentence": translated,
        })

    update_ebook_translations(book, updates)
    print(f"[ebook] Updated {len(updates)} translations in MongoDB")
    print(f"\n[next] Run: python pipeline.py --mode ebook --book {book} --stage audio")


def run_ebook_audio(book: str, tts_provider: str | None, reuse_audio: bool) -> None:
    from ebook.subtitle_video_builder import create_chapter_audio

    sentences = get_ebook_sentences(book)
    if not sentences:
        print(f"[ebook] No sentences found for '{book}'. Run extract + translate first.")
        sys.exit(1)

    src_lang = sentences[0].get("source_lang", "de")
    tgt_lang = sentences[0].get("target_lang", "en")
    tts = tts_provider or config.DEFAULT_TTS_PROVIDER

    # Group by chapter
    chapters_seen = {}
    for s in sentences:
        ci = s["chapter_index"]
        if ci not in chapters_seen:
            chapters_seen[ci] = s["chapter"]

    print(f"[ebook] Generating audio for {len(chapters_seen)} chapters (tts={tts})")
    for chapter_index, chapter_title in sorted(chapters_seen.items()):
        create_chapter_audio(
            sentences, book=book,
            chapter_title=chapter_title, chapter_index=chapter_index,
            source_lang=src_lang, target_lang=tgt_lang,
            tts_provider=tts, reuse_audio=reuse_audio,
        )
        mark_ebook_audio_generated(book, chapter_index)

    print(f"\n[next] Run: python pipeline.py --mode ebook --book {book} --stage video")


def run_ebook_video(book: str, tts_provider: str | None, reuse_audio: bool) -> None:
    from ebook.subtitle_video_builder import create_chapter_video

    sentences = get_ebook_sentences(book)
    if not sentences:
        print(f"[ebook] No sentences found for '{book}'. Run extract + translate first.")
        sys.exit(1)

    src_lang = sentences[0].get("source_lang", "de")
    tgt_lang = sentences[0].get("target_lang", "en")
    tts = tts_provider or config.DEFAULT_TTS_PROVIDER

    chapters_seen = {}
    for s in sentences:
        ci = s["chapter_index"]
        if ci not in chapters_seen:
            chapters_seen[ci] = s["chapter"]

    print(f"[ebook] Building videos for {len(chapters_seen)} chapters (tts={tts})")
    for chapter_index, chapter_title in sorted(chapters_seen.items()):
        create_chapter_video(
            sentences, book=book,
            chapter_title=chapter_title, chapter_index=chapter_index,
            source_lang=src_lang, target_lang=tgt_lang,
            tts_provider=tts, reuse_audio=reuse_audio,
        )

    print(f"\n[done] Videos saved to output/{book}/video/")


def _resolve_collection(name: str) -> str:
    entries = get_collection(name)
    if entries:
        return name
    similar = list_similar_collections(name)
    if not similar:
        return name
    print(f"No data found for '{name}'. Similar collections:")
    for i, c in enumerate(similar, 1):
        print(f"  {i}) {c}")
    choice = input(f"Pick a number [1-{len(similar)}] or press Enter to keep '{name}': ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(similar):
        return similar[int(choice) - 1]
    return name


def main():
    parser = argparse.ArgumentParser(
        description=(
            "book2video pipeline — extract vocabulary from PDFs, translate, generate TTS audio, and build flashcard videos.\n\n"
            "VOCAB MODE (default):\n"
            "  python pipeline.py --collection A1_A --pdf A1.pdf --alphabet A --stage extract\n"
            "  python pipeline.py --collection A1_A_1 --stage translate\n"
            "  python pipeline.py --collection A1_A_1 --stage audio\n"
            "  python pipeline.py --collection A1_A_1 --stage video\n"
            "  python pipeline.py --collection A1_A_1 --stage audio-and-video   # audio + video in one go\n"
            "  python pipeline.py --collection A1_A_1 --stage anki [--anki-connect]\n"
            "  python pipeline.py --collection A1_A_1 --stage quizlet\n"
            "  python pipeline.py --collection A1_A_1 --stage describe\n\n"
            "EBOOK MODE:\n"
            "  python pipeline.py --mode ebook --book mynovel --pdf novel.pdf --stage extract\n"
            "  python pipeline.py --mode ebook --book mynovel --stage translate\n"
            "  python pipeline.py --mode ebook --book mynovel --stage audio\n"
            "  python pipeline.py --mode ebook --book mynovel --stage video\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mode", choices=["vocab", "ebook"], default="vocab",
                        help="Pipeline mode: 'vocab' (default) for vocabulary flashcards, 'ebook' for full ebook bilingual subtitles")
    parser.add_argument("--book", default="",
                        help="Book/level identifier — vocab: e.g. A1, B1 (inferred from collection if omitted) | ebook: any short name, e.g. mynovel")
    parser.add_argument("--collection", default="",
                        help="[vocab] Collection name including letter, e.g. A1_A or A1_A_1 (chunk). Used as MongoDB collection key and output folder name.")
    parser.add_argument("--stage", help=(
        "[vocab] extract | translate | audio | video | audio-and-video | anki | quizlet | describe | delete\n"
        "        audio: generate TTS files only (check quality before rendering)\n"
        "        video: render video (reuses existing audio by default)\n"
        "        audio-and-video: both in one go (no check prompt)\n"
        "[ebook] extract | translate | audio | video\n"
        "Omit to run the full pipeline end-to-end."
    ))
    parser.add_argument("--pdf", help="Path to the source PDF file (required for extract stage)")
    parser.add_argument("--alphabet", help="[vocab] Single letter to extract from the wordlist PDF, e.g. A, B, F")
    parser.add_argument("--source-lang", default=None, help="Source language code, e.g. de, fr, es (default: de)")
    parser.add_argument("--target-lang", default=None, help="Target language code, e.g. en, zh, ja (default: en)")
    parser.add_argument("--tts", choices=["openai", "gtts"], help="TTS provider: 'openai' (higher quality) or 'gtts' (free). Default from config.")
    parser.add_argument("--anki-connect", action="store_true",
                        help="[vocab] After building the .apkg, push cards directly to the running Anki app via AnkiConnect plugin (port 8765)")
    parser.add_argument("--reuse-audio", action="store_true", help="[ebook] Skip TTS generation and reuse existing audio files in the output folder")
    args = parser.parse_args()

    # ------------------------------------------------------------------ ebook
    if args.mode == "ebook":
        if not args.book:
            parser.error("--book is required for ebook mode")

        if args.stage == "extract":
            if not args.pdf:
                parser.error("--pdf is required for ebook extract stage")
            run_ebook_extract(args.book, args.pdf, args.source_lang, args.target_lang)

        elif args.stage == "translate":
            run_ebook_translate(args.book, args.source_lang, args.target_lang)

        elif args.stage == "audio":
            run_ebook_audio(args.book, args.tts, reuse_audio=args.reuse_audio)

        elif args.stage == "video":
            run_ebook_video(args.book, args.tts, reuse_audio=args.reuse_audio)

        elif args.stage is None:
            # Full ebook pipeline
            if not args.pdf:
                parser.error("--pdf is required for full ebook pipeline")
            run_ebook_extract(args.book, args.pdf, args.source_lang, args.target_lang)
            run_ebook_translate(args.book, args.source_lang, args.target_lang)
            run_ebook_audio(args.book, args.tts, reuse_audio=False)
            run_ebook_video(args.book, args.tts, reuse_audio=True)

        else:
            parser.error(f"Unknown ebook stage: {args.stage}. Choose from: extract, translate, audio, video")
        return

    # ------------------------------------------------------------------ vocab (default)
    if not args.collection:
        parser.error("--collection is required for vocab mode")

    if args.stage == "delete":
        count = delete_collection(args.collection)
        print(f"[delete] Removed {count} entries from MongoDB collection '{args.collection}'")
        return

    if args.stage not in ("extract",):
        args.collection = _resolve_collection(args.collection)

    if args.stage == "extract" or args.stage is None:
        if not args.pdf or not args.alphabet:
            parser.error("--pdf and --alphabet are required for the extract stage")
        run_extract(args.collection, args.pdf, args.alphabet, args.book, args.source_lang, args.target_lang)

    if args.stage == "translate" or args.stage is None:
        run_translate(args.collection, args.source_lang, args.target_lang)

    if args.stage == "audio":
        run_audio(args.collection, args.tts, args.source_lang, args.target_lang)

    if args.stage == "video":
        run_video(args.collection, args.tts, args.source_lang, args.target_lang)

    if args.stage == "audio-and-video" or args.stage is None:
        run_audio(args.collection, args.tts, args.source_lang, args.target_lang)
        run_video(args.collection, args.tts, args.source_lang, args.target_lang)

    if args.stage == "anki":
        run_anki(args.collection, args.tts, args.anki_connect, args.source_lang, args.target_lang)

    if args.stage == "quizlet":
        run_quizlet(args.collection)

    if args.stage == "describe":
        run_describe(args.collection, args.source_lang, args.target_lang)


if __name__ == "__main__":
    main()
