import hashlib
from pathlib import Path

import genanki

import config
from services.tts import generate_vocab_audio

# Anki uses numeric IDs to distinguish between different note types (card templates).
# Stable model ID — must not change or Anki will treat cards as new type
_MODEL_ID = 1607392319

_VOCAB_MODEL = genanki.Model(
    _MODEL_ID,
    "Vocabulary Card",
    fields=[
        {"name": "SourceWord"},
        {"name": "SourceAudio"},
        {"name": "TargetWord"},
        {"name": "TargetAudio"},
        {"name": "SourceSentence"},
        {"name": "TargetSentence"},
    ],
    templates=[{
        "name": "Card 1",
        "qfmt": (
            "<div class='word'>{{SourceWord}}</div>"
            "{{SourceAudio}}"
            "<div class='sentence'>{{SourceSentence}}</div>"
        ),
        "afmt": (
            "{{FrontSide}}<hr>"
            "<div class='word'>{{TargetWord}}</div>"
            "{{TargetAudio}}"
            "<div class='sentence'>{{TargetSentence}}</div>"
        ),
    }],
    css="""
.card {
    font-family: Arial, sans-serif;
    font-size: 20px;
    text-align: center;
}
.word {
    font-size: 20px;
    font-weight: bold;
    margin-bottom: 8px;
}
.sentence {
    font-size: 20px;
    margin-top: 12px;
    }
""",
)


def _stable_id(name: str) -> int:
    return int(hashlib.md5(name.encode()).hexdigest()[:8], 16)


def _default_deck_name(collection: str) -> str:
    # e.g. "A1_F_1"  → "Goethe A1 Wordlist::F"   (digit chunk index dropped)
    # e.g. "A1_J_I"  → "Goethe A1 Wordlist::J_I"  (multi-letter parts joined with _ not ::)
    parts = collection.split("_")
    book = parts[0]  # e.g. "A1"
    rest = [p for p in parts[1:] if not p.isdigit()]
    base = f"Goethe {book} Wordlist"
    return f"{base}::{'_'.join(rest)}" if rest else base


def create_anki_deck(
    vocabulary: list[dict],
    collection: str,
    source_lang: str = "de",
    target_lang: str = "en",
    tts_provider: str | None = None,
    deck_name: str = "",
) -> Path:
    audio_dir = config.OUTPUT_DIR / collection / "audio"
    anki_dir = config.OUTPUT_DIR / collection / "anki"
    audio_dir.mkdir(parents=True, exist_ok=True)
    anki_dir.mkdir(parents=True, exist_ok=True)

    deck_name = deck_name or _default_deck_name(collection)
    deck = genanki.Deck(_stable_id(deck_name), deck_name)
    media_files = []

    for entry in vocabulary:
        lemma = entry["file_name"]
        source_word = entry["source_word"]
        target_word = entry.get("target_word", "")
        source_sentence = entry.get("source_sentence", "")
        target_sentence = entry.get("target_sentence", "")

        if not target_word or not target_word.strip():
            print(f"[skip] '{lemma}' has no translation, skipping")
            continue

        src_audio = audio_dir / f"{lemma}_source_word.mp3"
        tgt_audio = audio_dir / f"{lemma}_target_word.mp3"

        if not src_audio.exists():
            generate_vocab_audio(source_word, src_audio, lang=source_lang, provider=tts_provider)
        if not tgt_audio.exists():
            generate_vocab_audio(target_word, tgt_audio, lang=target_lang, provider=tts_provider)

        media_files.extend([str(src_audio), str(tgt_audio)])

        note = genanki.Note(
            model=_VOCAB_MODEL,
            guid=genanki.guid_for(collection, lemma),
            fields=[
                source_word,
                f"[sound:{src_audio.name}]",
                target_word,
                f"[sound:{tgt_audio.name}]",
                source_sentence,
                target_sentence,
            ],
        )
        deck.add_note(note)

    apkg_path = anki_dir / f"{collection}.apkg"
    genanki.Package(deck, media_files=media_files).write_to_file(str(apkg_path))
    print(f"[anki] Saved {len(deck.notes)} cards → {apkg_path}")
    return apkg_path


def _ankiconnect(action: str, **params) -> dict:
    import requests
    resp = requests.post("http://localhost:8765", json={
        "action": action, "version": 6, "params": params,
    }, timeout=10)
    return resp.json()


def push_to_ankiconnect(
    apkg_path: Path,
    vocabulary: list[dict] | None = None,
    collection: str = "",
    deck_name: str = "",
) -> bool:
    """Push cards directly to Anki via AnkiConnect API (createDeck + storeMediaFile + addNotes)."""
    import requests
    import base64

    if not vocabulary or not collection:
        print(f"[anki] AnkiConnect requires vocabulary data — import manually: File → Import → {apkg_path}")
        return False

    deck_name = deck_name or _default_deck_name(collection)

    try:
        # 1. Create deck (no-op if already exists)
        result = _ankiconnect("createDeck", deck=deck_name)
        if result.get("error"):
            print(f"[anki] AnkiConnect error (createDeck): {result['error']}")
            return False

        # 2. Ensure model exists
        models = _ankiconnect("modelNames").get("result", [])
        if "Vocabulary Card" not in models:
            _ankiconnect(
                "createModel",
                modelName="Vocabulary Card",
                inOrderFields=["SourceWord", "SourceAudio", "TargetWord", "TargetAudio", "SourceSentence", "TargetSentence"],
                css=_VOCAB_MODEL.css,
                cardTemplates=[{
                    "Name": "Card 1",
                    "Front": "<div class='word'>{{SourceWord}}</div>{{SourceAudio}}<div class='sentence'>{{SourceSentence}}</div>",
                    "Back": "{{FrontSide}}<hr><div class='word'>{{TargetWord}}</div>{{TargetAudio}}<div class='sentence'>{{TargetSentence}}</div>",
                }],
            )

        audio_dir = apkg_path.parent.parent / "audio"
        notes = []
        for entry in vocabulary:
            lemma = entry["file_name"]
            source_word = entry["source_word"]
            target_word = entry.get("target_word", "")
            if not target_word or not target_word.strip():
                continue
            source_sentence = entry.get("source_sentence", "")
            target_sentence = entry.get("target_sentence", "")

            src_audio = audio_dir / f"{lemma}_source_word.mp3"
            tgt_audio = audio_dir / f"{lemma}_target_word.mp3"

            # 3. Upload audio files
            for audio_file in [src_audio, tgt_audio]:
                if audio_file.exists():
                    with open(audio_file, "rb") as f:
                        _ankiconnect("storeMediaFile",
                            filename=audio_file.name,
                            data=base64.b64encode(f.read()).decode(),
                        )

            notes.append({
                "deckName": deck_name,
                "modelName": "Vocabulary Card",
                "fields": {
                    "SourceWord": source_word,
                    "SourceAudio": f"[sound:{src_audio.name}]",
                    "TargetWord": target_word,
                    "TargetAudio": f"[sound:{tgt_audio.name}]",
                    "SourceSentence": source_sentence,
                    "TargetSentence": target_sentence,
                },
                "options": {"allowDuplicate": False, "duplicateScope": "deck"},
                "tags": [collection],
            })

        # 4. Clear existing notes so re-runs replace rather than skip
        find_result = _ankiconnect("findNotes", query=f"deck:\"{deck_name}\"")
        existing_ids = find_result.get("result") or []
        if existing_ids:
            _ankiconnect("deleteNotes", notes=existing_ids)
            print(f"[anki] Cleared {len(existing_ids)} existing notes from '{deck_name}'")

        # 5. Add notes
        result = _ankiconnect("addNotes", notes=notes)
        error = result.get("error")
        if error:
            print(f"[anki] AnkiConnect error (addNotes): {error}")
            return False
        print(f"[anki] Pushed {len(notes)} cards to '{deck_name}' via AnkiConnect")
        return True

    except Exception as e:
        print(f"[anki] AnkiConnect unavailable: {e}")
        print(f"[anki] Import manually: File → Import → {apkg_path}")
        return False
