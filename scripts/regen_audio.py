"""
Re-generate audio for a single vocabulary word in a collection.

Usage:
    # regenerate audio for a specific lemma
    python scripts/regen_audio.py A1_A_1 Abfahrt

    # list all lemmas in a collection
    python scripts/regen_audio.py A1_A_1 --list
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.tts import generate_audio, generate_vocab_audio
from vocab.video_builder import _concatenate_audios


def regen_audio(collection: str, lemma: str) -> None:
    json_path = Path(f"output/{collection}/text/{collection}_de_en.json")
    if not json_path.exists():
        print(f"[error] JSON not found: {json_path}")
        sys.exit(1)

    vocab = json.loads(json_path.read_text())
    if lemma not in vocab:
        print(f"[error] '{lemma}' not found in {collection}. Run --list to see available lemmas.")
        sys.exit(1)

    entry = vocab[lemma]
    audio_dir = Path(f"output/{collection}/audio")
    audio_dir.mkdir(parents=True, exist_ok=True)

    print(f"[regen] {collection} / {lemma}")
    print(f"  source_word : {entry['source_word']}")
    print(f"  target_word : {entry['target_word']}")

    generate_vocab_audio(entry["source_word"], audio_dir / f"{lemma}_source_word.mp3", lang="de", silent=500)
    print(f"  ✓ source_word audio")

    generate_audio(entry["target_word"], audio_dir / f"{lemma}_target_word.mp3", lang="en", silent=1000)
    print(f"  ✓ target_word audio")

    _concatenate_audios([audio_dir / f"{lemma}_source_word.mp3", audio_dir / f"{lemma}_target_word.mp3"], audio_dir, lemma)
    print(f"  ✓ combined_audio")

    if entry.get("source_sentence") and entry.get("target_sentence"):
        print(f"  source_sentence : {entry['source_sentence']}")
        print(f"  target_sentence : {entry['target_sentence']}")
        generate_audio(entry["source_sentence"], audio_dir / f"{lemma}_source_sentence.mp3", lang="de", silent=500)
        print(f"  ✓ source_sentence audio")
        generate_audio(entry["target_sentence"], audio_dir / f"{lemma}_target_sentence.mp3", lang="en", silent=1000)
        print(f"  ✓ target_sentence audio")

        _concatenate_audios([audio_dir / f"{lemma}_source_sentence.mp3", audio_dir / f"{lemma}_target_sentence.mp3"], audio_dir, f"{lemma}_sentence")
        print(f"  ✓ sentence_combined_audio")

    print(f"[done] Re-run: python pipeline.py --collection {collection} --stage video")


def list_lemmas(collection: str) -> None:
    json_path = Path(f"output/{collection}/text/{collection}_de_en.json")
    if not json_path.exists():
        print(f"[error] JSON not found: {json_path}")
        sys.exit(1)
    vocab = json.loads(json_path.read_text())
    for lemma in sorted(vocab.keys()):
        print(lemma)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    collection = sys.argv[1]

    if len(sys.argv) == 2 or sys.argv[2] == "--list":
        list_lemmas(collection)
    else:
        regen_audio(collection, sys.argv[2])
