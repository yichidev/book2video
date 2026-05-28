"""
Bilingual subtitle video builder for ebook mode.

Creates one MP4 per chapter. Each sentence becomes a clip:
  - Source text shown at top (visible from t=0)
  - Target text shown at bottom (fades in when source audio ends)
  - Audio: source sentence → 300ms pause → target sentence

Usage:
  from ebook.subtitle_video_builder import create_chapter_video
  create_chapter_video(sentences, book="mynovel", chapter_title="Chapter 1",
                       chapter_index=0, source_lang="de", target_lang="en")
"""
import re
import textwrap
from pathlib import Path

import numpy as np
import moviepy.config as mp_config
from moviepy.audio.AudioClip import AudioClip
from moviepy.editor import (
    AudioFileClip, CompositeVideoClip, ImageClip, TextClip, concatenate_videoclips
)
from pydub import AudioSegment

import config
from services.tts import generate_audio, get_audio_duration

mp_config.IMAGEMAGICK_BINARY = config.IMAGEMAGICK_BINARY

_PAUSE_MS = 300   # silence between source and target audio within one sentence clip


def _silent_audio(duration: float, fps: int = 44100) -> AudioClip:
    clip = AudioClip(make_frame=lambda t: np.zeros(1), duration=duration)
    clip.fps = fps
    return clip


def _wrap_text(text: str, width: int, font_size: int) -> str:
    max_chars = (width - 120) // (font_size // 2)
    sentences = re.split(r"(?<=\.)\s", text)
    wrapped = []
    for s in sentences:
        wrapped.extend(textwrap.wrap(s, max_chars))
    return "\n".join(wrapped) if wrapped else text


def _combine_sentence_audio(src_path: Path, tgt_path: Path, out_path: Path) -> None:
    src = AudioSegment.from_file(str(src_path))
    tgt = AudioSegment.from_file(str(tgt_path))
    combined = src + AudioSegment.silent(_PAUSE_MS) + tgt
    combined.export(str(out_path), format="mp3")


def _make_sentence_clip(
    source_text: str,
    target_text: str,
    audio_path: Path,
    src_audio_duration: float,
) -> CompositeVideoClip:
    w, h = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    font_size = 72
    total_duration = get_audio_duration(audio_path)

    src_wrapped = _wrap_text(source_text, w, font_size)
    tgt_wrapped = _wrap_text(target_text, w, font_size)

    src_clip = TextClip(
        src_wrapped, fontsize=font_size, font="Amiri-regular",
        color="black", size=(w - 120, None), method="caption",
    )
    tgt_clip = TextClip(
        tgt_wrapped, fontsize=font_size, font="Amiri-regular",
        color="gray20", size=(w - 120, None), method="caption",
    )

    bg = ImageClip(str(config.BACKGROUND_IMAGE)).set_duration(total_duration)

    # Position: source in upper half, target in lower half
    src_y = h // 4 - src_clip.h // 2
    tgt_y = h * 3 // 4 - tgt_clip.h // 2
    src_y = max(40, src_y)
    tgt_y = min(h - tgt_clip.h - 40, tgt_y)

    # Target text fades in when source audio ends (+ pause)
    transition_start = src_audio_duration + _PAUSE_MS / 1000.0

    src_clip = src_clip.set_position(("center", src_y)).set_duration(total_duration)
    tgt_clip = (
        tgt_clip
        .set_position(("center", tgt_y))
        .set_duration(total_duration - transition_start)
        .set_start(transition_start)
        .crossfadein(0.3)
    )

    clip = CompositeVideoClip([bg, src_clip, tgt_clip], size=(w, h))
    audio = AudioFileClip(str(audio_path)).set_duration(total_duration)
    return clip.set_duration(total_duration).set_audio(audio).on_color(color=(0, 0, 0), col_opacity=1)


def create_chapter_video(
    sentences: list[dict],
    book: str,
    chapter_title: str,
    chapter_index: int,
    source_lang: str = "de",
    target_lang: str = "en",
    tts_provider: str | None = None,
    reuse_audio: bool = False,
) -> Path:
    """
    Generate a subtitle-style bilingual video for one chapter.

    Args:
        sentences:     list of sentence dicts with source_sentence + target_sentence
        book:          book identifier (used for output paths)
        chapter_title: human-readable chapter title
        chapter_index: numeric chapter index (for file naming)
        source_lang:   TTS language for source sentences
        target_lang:   TTS language for target sentences
        tts_provider:  "openai" | "gtts" | None (uses config default)
        reuse_audio:   skip TTS if audio files already exist

    Returns:
        Path to the output MP4 file.
    """
    safe_title = re.sub(r"[^\w\-]", "_", chapter_title)
    output_dir = config.OUTPUT_DIR / book
    audio_dir = output_dir / "audio"
    video_dir = output_dir / "video"
    audio_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)

    clips = []

    for entry in sentences:
        if entry.get("chapter_index") != chapter_index:
            continue
        idx = entry["sentence_index"]
        src_text = entry.get("source_sentence", "")
        tgt_text = entry.get("target_sentence", "")

        if not src_text or not tgt_text:
            continue

        src_audio = audio_dir / f"{safe_title}_{idx}_src.mp3"
        tgt_audio = audio_dir / f"{safe_title}_{idx}_tgt.mp3"
        combined_audio = audio_dir / f"{safe_title}_{idx}_combined.mp3"

        if not (reuse_audio and src_audio.exists()):
            generate_audio(src_text, src_audio, lang=source_lang, provider=tts_provider)
        if not (reuse_audio and tgt_audio.exists()):
            generate_audio(tgt_text, tgt_audio, lang=target_lang, provider=tts_provider)
        if not (reuse_audio and combined_audio.exists()):
            _combine_sentence_audio(src_audio, tgt_audio, combined_audio)

        src_duration = get_audio_duration(src_audio)
        clip = _make_sentence_clip(src_text, tgt_text, combined_audio, src_duration)
        clips.append(clip)

    if not clips:
        raise ValueError(f"No sentences with translations found for chapter_index={chapter_index}")

    final = concatenate_videoclips(clips, method="compose")
    video_path = video_dir / f"{safe_title}_video.mp4"
    final.write_videofile(str(video_path), fps=24, codec="libx264", audio_codec="aac")
    print(f"[ebook] Chapter video → {video_path}")
    return video_path


def create_chapter_audio(
    sentences: list[dict],
    book: str,
    chapter_title: str,
    chapter_index: int,
    source_lang: str = "de",
    target_lang: str = "en",
    tts_provider: str | None = None,
    reuse_audio: bool = False,
) -> Path:
    """
    Generate a combined chapter MP3 (source sentence → pause → target sentence, for each sentence).

    Returns:
        Path to the combined chapter MP3.
    """
    safe_title = re.sub(r"[^\w\-]", "_", chapter_title)
    output_dir = config.OUTPUT_DIR / book
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    chapter_audio = AudioSegment.empty()

    for entry in sentences:
        if entry.get("chapter_index") != chapter_index:
            continue
        idx = entry["sentence_index"]
        src_text = entry.get("source_sentence", "")
        tgt_text = entry.get("target_sentence", "")

        if not src_text or not tgt_text:
            continue

        src_audio = audio_dir / f"{safe_title}_{idx}_src.mp3"
        tgt_audio = audio_dir / f"{safe_title}_{idx}_tgt.mp3"

        if not (reuse_audio and src_audio.exists()):
            generate_audio(src_text, src_audio, lang=source_lang, provider=tts_provider)
        if not (reuse_audio and tgt_audio.exists()):
            generate_audio(tgt_text, tgt_audio, lang=target_lang, provider=tts_provider)

        chapter_audio += AudioSegment.from_file(str(src_audio))
        chapter_audio += AudioSegment.silent(_PAUSE_MS)
        chapter_audio += AudioSegment.from_file(str(tgt_audio))
        chapter_audio += AudioSegment.silent(800)  # gap between sentences

    out_path = audio_dir / f"{safe_title}_chapter.mp3"
    chapter_audio.export(str(out_path), format="mp3")
    print(f"[ebook] Chapter audio → {out_path}")
    return out_path
