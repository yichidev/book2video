# book2video

A bilingual language-learning toolkit that turns PDFs into audio and video study materials.
Operates in two modes — **vocab** for flashcard decks, **ebook** for full reading comprehension.

**Shared library:** `services/` (translator, TTS) is importable by any downstream repo.

---

## Repository layout

```
book2video/
├── pipeline.py          ← CLI entry point (--mode vocab | ebook)
├── config.py
├── input/
│   ├── books/           ← Source PDFs (gitignored)
│   └── assets/          ← background.png, cover-A1.png, background-music-A1.mp3
├── output/              ← Generated files (gitignored)
├── tests/
│   └── test_video.py    ← Quick video test script
├── scripts/             ← Dev/utility scripts
├── services/            ← Shared library: translator, TTS
├── vocab/               ← Vocab mode: extractor, video builder, Anki/Quizlet exporters
├── ebook/               ← Ebook mode: PDF reader, segmenter, subtitle video builder
└── storage/             ← MongoDB (vocabulary + sentence-level schemas)
```

---

## Prerequisites

### 1. System dependencies

```bash
brew install ffmpeg imagemagick
```

### 2. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **Note:** `moviepy==1.0.3` is pinned. MoviePy 2.x removed the `moviepy.editor` module and is not compatible.

### 3. API keys

Create a `.env` file at the project root:

```
OPENAI_API_KEY=...     # Required: vocab extraction + (optional) TTS
DEEPL_API_KEY=...      # Required: translation
MONGODB_URI=...        # Required: MongoDB Atlas connection string
TTS_PROVIDER=openai    # Optional: "openai" (default) or "gtts" (free, lower quality)
```

| Key | Where to get it | Free tier |
|-----|----------------|-----------|
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) → API keys | Pay-per-use |
| `DEEPL_API_KEY` | [deepl.com/pro](https://www.deepl.com/pro) → Free API | 500k chars/month |
| `MONGODB_URI` | [cloud.mongodb.com](https://cloud.mongodb.com) → Connect → Drivers | M0 free forever |

**MongoDB Atlas setup:**
1. Create a free **M0** cluster
2. **Database Access** → add a user with a password
3. **Network Access** → Allow Access from Anywhere (`0.0.0.0/0`) for local dev
4. **Connect** → **Drivers** → copy the URI → paste into `.env`

---

## Vocab mode

Extracts vocabulary words from a PDF textbook (one alphabet letter at a time), translates them, and produces an Anki deck, Quizlet file, and bilingual flashcard video.

**Pipeline:** PDF → extract words → translate → generate audio → export to video / Anki / Quizlet

### How extraction works

1. `pdfplumber` extracts full PDF text locally (free, deterministic)
2. Lines containing words starting with the target letter are filtered
3. GPT-4.1 structures them into `[lemma, plural, example_sentence]` triples, covering all parts of speech — nouns (with `der/die/das`), verbs (lowercase infinitive), adjectives, adverbs, prepositions
4. A letter filter removes false positives; a plural dedup step removes redundant entries
5. **GPT-5-mini cleanup pass** fixes missing articles, capitalised verbs, non-sentence examples, and missing plurals

### Run stages individually

```bash
source .venv/bin/activate

# 1. Extract words starting with "A" — prompts for split if > 30 words
python pipeline.py --collection A1_A --pdf input/books/A1.pdf --alphabet A --stage extract

# 2. Translate (German → English by default)
python pipeline.py --collection A1_A_1 --stage translate

# 3. Generate TTS audio (source + target word and sentence for each entry)
python pipeline.py --collection A1_A_1 --stage audio
# → Audio saved to output/A1_A_1/audio/
# → Listen to spot-check quality. Fix broken words if needed:
#   python scripts/regen_audio.py A1_A_1 --list          # see all lemmas
#   python scripts/regen_audio.py A1_A_1 Abfahrt         # re-generate one word

# 4. Render video (reuses audio generated in step 3)
python pipeline.py --collection A1_A_1 --stage video

# 5. Export as Anki deck
python pipeline.py --collection A1_A_1 --stage anki

# 5. Export as Quizlet import file
python pipeline.py --collection A1_A_1 --stage quizlet

# 6. Generate/regenerate description.txt for YouTube
python pipeline.py --collection A1_A_1 --stage describe
```

### Interactive split prompt

After extraction, if a letter yields more than 30 words the pipeline shows suggested chunks:

```
[extract] Extracted 55 words.
[split] Suggested: 2 chunks

  A1_F_1 (28 words): für, Familie, Farbe, ...
  A1_F_2 (27 words): Freizeit, fremd, Freund, ...

  [1] Accept suggested split
  [2] Custom chunk size
  [3] No split (keep all 55 in 'A1_F')

Your choice [1]:
```

Split naming: `A1_F_1`, `A1_F_2`, … Each chunk becomes its own MongoDB collection and JSON file. Both chunks land in the same Anki deck (`Goethe A1 Wordlist::F`).

### Export formats

#### Anki

Cards are organised into nested decks: `Goethe A1 Wordlist::A`, `Goethe A1 Wordlist::F`, etc.

**Push directly to Anki (recommended):**
1. Install [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on (code `2055492159`)
2. Keep Anki open, then run:

```bash
python pipeline.py --collection A1_A_1 --stage anki --anki-connect
```

**Manual import:**
```bash
python pipeline.py --collection A1_A_1 --stage anki
# Then: Anki → File → Import → select output/A1_A_1/anki/A1_A_1.apkg
```

#### Quizlet

```bash
python pipeline.py --collection A1_A_1 --stage quizlet
# Import: Create set → "Import from" → paste → separator: Tab / New line
```

### Local JSON and manual edits

The pipeline writes JSON files under `output/<collection>/text/`:

| File | When created | Contents |
|------|-------------|----------|
| `A1_A_1_de.json` | After extract | Source words only |
| `A1_A_1_de_en.json` | After translate | Source + target words |

Before each downstream stage, the pipeline prompts to sync your edits back into MongoDB:

```
[sync] Sync 28 entries from A1_A_1_de_en.json into MongoDB? [Y/n]:
```

### Description file

After generating the video, `description.txt` is automatically written to `output/<collection>/text/description.txt`.

It contains:
- Title: `Memorize German vocabulary for A1! (with English translation)`
- Word count and letter summary
- Source attribution (Goethe-Zertifikat wordlist URL)
- Transparency note on what is AI vs human in the pipeline
- Practice resource links (Quizlet / Anki / YouTube — hardcoded defaults)
- Full word list

**Regenerate description only** (no video re-render needed):

```bash
python pipeline.py --collection A1_A_1 --stage describe
```

### Vocab mode arguments

| Argument | Description | Required for |
|----------|-------------|--------------|
| `--collection` | Collection name, e.g. `A1_A_1` | All stages |
| `--pdf` | Path to the PDF file | `extract` |
| `--alphabet` | Letter to extract, e.g. `A` | `extract` |
| `--stage` | `extract`, `translate`, `audio`, `video`, `audio-and-video`, `anki`, `quizlet`, `describe`, `delete` | Optional (omit to run all) |
| `--tts` | `openai` (default) or `gtts` | Optional |
| `--anki-connect` | Push deck to Anki via AnkiConnect | `anki` |
| `--source-lang` | Source language code (default: `de`) | Optional |
| `--target-lang` | Target language code (default: `en`) | Optional |

### Test video (no API calls)

```bash
# Reuse existing audio (fast, no API cost)
python tests/test_video.py output/A1_A_1 --words 3

# Generate fresh TTS audio
python tests/test_video.py output/A1_A_1 --words 3 --new-audio
```

Output goes to `tests/output/<collection>/video/vocabulary_video.mp4`.

### Vocab output structure

```
output/A1_A_1/
├── audio/    individual .mp3 files per word/sentence
├── anki/     A1_A_1.apkg
├── quizlet/  A1_A_1.txt
├── image/    resized cover/background images
├── text/     A1_A_1_de.json, A1_A_1_de_en.json, summary.txt, description.txt
└── video/    vocabulary_video.mp4
```

---

## Ebook mode

Reads a full PDF book in the source language, splits it into sentences, translates each sentence, and generates:
- **Per-chapter MP3** — source sentence → pause → target sentence (for listening)
- **Per-chapter MP4** — subtitle-style video with source text on top, target text fading in below

**Pipeline:** PDF → detect chapters → split into sentences → translate → generate audio → subtitle video

### Run stages individually

```bash
source .venv/bin/activate

# 1. Extract chapters and sentences from the PDF
python pipeline.py --mode ebook --book mynovel --pdf input/books/novel.pdf --stage extract

# 2. Translate all sentences
python pipeline.py --mode ebook --book mynovel --stage translate

# 3. Generate bilingual chapter audio (source → pause → target, per sentence)
python pipeline.py --mode ebook --book mynovel --stage audio

# 4. Generate subtitle-style chapter videos
python pipeline.py --mode ebook --book mynovel --stage video
```

### Run the full pipeline at once

```bash
python pipeline.py --mode ebook --book mynovel --pdf input/books/novel.pdf
```

### Chapter detection

`ebook/pdf_reader.py` detects chapter boundaries using:
- Lines matching patterns like `Chapter 1`, `Kapitel 3`, `Lektion 2`, `1. Introduction`
- Short all-caps lines (≤ 60 characters)

Falls back to 5-page chunks when no chapter headings are found.

### Sentence filtering

`ebook/segmenter.py` uses [pysbd](https://github.com/nipunsadvilkar/pySBD) for language-aware sentence splitting, then filters out:
- Fragments shorter than 5 words
- All-caps lines (headers)
- Lines that are pure numbers (page numbers)

### Ebook mode arguments

| Argument | Description | Required for |
|----------|-------------|--------------|
| `--mode ebook` | Enable ebook mode | All ebook stages |
| `--book` | Book identifier, e.g. `mynovel` | All stages |
| `--pdf` | Path to the PDF file | `extract` |
| `--stage` | `extract`, `translate`, `audio`, `video` | Optional (omit to run all) |
| `--tts` | `openai` (default) or `gtts` | Optional |
| `--reuse-audio` | Skip TTS if audio files already exist | `audio`, `video` |
| `--source-lang` | Source language code (default: `de`) | Optional |
| `--target-lang` | Target language code (default: `en`) | Optional |

### Ebook output structure

```
output/mynovel/
├── audio/    Chapter_1_chapter.mp3, Chapter_2_chapter.mp3, ...
└── video/    Chapter_1_video.mp4, Chapter_2_video.mp4, ...
```

---

## TTS options

| Flag | Audio engine |
|------|-------------|
| `--tts openai` | OpenAI `gpt-4o-mini-tts` (**default**, higher quality, uses API credits) |
| `--tts gtts` | Google TTS (free, lower quality) |

```bash
# Use free Google TTS
python pipeline.py --collection A1_A_1 --stage audio --tts gtts
# Or set TTS_PROVIDER=gtts in .env
```

---

## Using as a library

Other repos can import the shared services directly:

```python
import sys
sys.path.insert(0, "../book2video")

from services.translator import add_translation
from services.tts import generate_audio, get_audio_duration
```

---

## ImageMagick path

If video generation fails with an ImageMagick error, update the path in [config.py](config.py):

```python
IMAGEMAGICK_BINARY = "/opt/homebrew/bin/convert"  # default for macOS/Homebrew
```

Find yours with: `which convert`
