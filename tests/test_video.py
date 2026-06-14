"""
Quick test: build a short video from the first N words.
Output goes to tests/output/<collection>/ to avoid overwriting real videos.

Usage:
  python test_video.py output/A1_A_1 --words 3               # reuse existing audio
  python test_video.py output/A1_A_1 --words 3 --new-audio   # generate fresh TTS audio
"""
import argparse
import json
import shutil
from pathlib import Path

import config
from vocab.video_builder import create_vocabulary_video

TEST_OUTPUT_DIR = Path("tests/output")

parser = argparse.ArgumentParser()
parser.add_argument("output_dir", help="e.g. output/A1_A_1")
parser.add_argument("--words", type=int, default=3)
parser.add_argument("--new-audio", action="store_true",
                    help="Generate fresh TTS audio instead of reusing existing files")
args = parser.parse_args()

src = Path(args.output_dir)
collection = src.name

json_files = list((src / "text").glob("*.json"))
if not json_files:
    raise FileNotFoundError(f"No JSON found in {src / 'text'}")

with open(json_files[0]) as f:
    data = json.load(f)

vocabulary = [
    {
        "file_name": lemma,
        "source_word": v["source_word"],
        "target_word": v.get("target_word", ""),
        "source_sentence": v.get("source_sentence", ""),
        "target_sentence": v.get("target_sentence", ""),
    }
    for lemma, v in list(data.items())[:args.words]
    if v.get("target_word", "").strip()
]

reuse_audio = not args.new_audio

if reuse_audio:
    # Copy existing audio files into test output dir
    test_audio_dir = TEST_OUTPUT_DIR / collection / "audio"
    test_audio_dir.mkdir(parents=True, exist_ok=True)
    src_audio_dir = src / "audio"
    if not src_audio_dir.exists():
        raise FileNotFoundError(f"No audio dir found at {src_audio_dir}. Run with --new-audio to generate.")
    for mp3 in src_audio_dir.glob("*.mp3"):
        dest = test_audio_dir / mp3.name
        if not dest.exists():
            shutil.copy2(mp3, dest)
    audio_mode = "reusing existing audio"
else:
    audio_mode = "generating new TTS audio"

# Redirect output to tests/output
config.OUTPUT_DIR = TEST_OUTPUT_DIR

print(f"[test] Building video for {len(vocabulary)} words from '{collection}' ({audio_mode})")
video_path = create_vocabulary_video(
    vocabulary, collection,
    source_lang="de", target_lang="en",
    tts_provider=None,
)
print(f"[test] Done: {video_path}")
