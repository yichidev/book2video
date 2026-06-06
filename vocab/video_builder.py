import re
import textwrap
from pathlib import Path

import numpy as np
import moviepy.config as mp_config
from moviepy.audio.AudioClip import AudioClip
from moviepy.audio.fx.audio_fadein import audio_fadein
from moviepy.audio.fx.audio_fadeout import audio_fadeout
from moviepy.audio.fx.audio_loop import audio_loop
from moviepy.editor import (
    AudioFileClip, CompositeAudioClip, CompositeVideoClip, ImageClip, TextClip, concatenate_videoclips
)
from PIL import Image
from pydub import AudioSegment

import config
from services.tts import generate_audio, generate_vocab_audio, get_audio_duration
from vocab.description_generator import generate_description

mp_config.IMAGEMAGICK_BINARY = config.IMAGEMAGICK_BINARY


def _silent_audio(duration: float, fps: int = 44100) -> AudioClip:
    """Return a mono silent audio clip — needed for clips without speech so
    the audio timeline stays aligned across all concatenated clips."""
    clip = AudioClip(make_frame=lambda t: np.zeros(1), duration=duration)
    clip.fps = fps
    return clip


def _resize_image_to_fit(img_path, img_dir, max_width, max_height):
    img_path = Path(img_path)
    with Image.open(img_path) as img:
        aspect_ratio = img.width / img.height
        if img.width > max_width or img.height > max_height:
            if aspect_ratio > 1:
                new_width = max_width
                new_height = int(new_width / aspect_ratio)
            else:
                new_height = max_height
                new_width = int(new_height * aspect_ratio)
        else:
            new_width, new_height = img.width, img.height
        resized = img.resize((new_width, new_height), Image.LANCZOS)
        out_path = img_dir / f"{img_path.stem}_resized{img_path.suffix}"
        resized.save(str(out_path))
    return out_path, new_width, new_height


def _wrap_text(text: str, width: int, font_size: int):
    sentences = re.split(r"(?<=\.)\s", text)
    wrapped = []
    for sentence in sentences:
        max_chars = (width - 100) // (font_size // 2)
        wrapped.extend(textwrap.wrap(sentence, max_chars))
    is_cut = len(wrapped) > 1
    return is_cut, "\n".join(wrapped)


def _concatenate_audios(audio_files: list, output_path: Path, output_filename: str) -> Path:
    combined = AudioSegment.empty()
    for f in audio_files:
        combined += AudioSegment.from_file(str(f))
    out = output_path / f"{output_filename}_combined_audio.mp3"
    combined.export(str(out), format="mp3")
    return out


def _create_text_clip(
    source_text: str,
    target_text: str,
    duration: float,
    font_size: int,
    transition_start: float,
    img_dir: Path,
    background_image_path,
):
    w, h = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    src_cut, src_wrapped = _wrap_text(source_text, w, font_size)
    tgt_cut, tgt_wrapped = _wrap_text(target_text, w, font_size)

    if src_cut or tgt_cut:
        font_size -= 30

    src_clip = TextClip(src_wrapped, fontsize=font_size, font="Amiri-regular", color="black", size=(w, None), method="caption")
    tgt_clip = TextClip(tgt_wrapped, fontsize=font_size, font="Amiri-regular", color="black", size=(w, None), method="caption")

    bg_paper = ImageClip(str(config.BACKGROUND_IMAGE)).set_duration(duration)
    layers = [bg_paper]

    if background_image_path and Path(background_image_path).exists():
        resized_path, _, img_h = _resize_image_to_fit(background_image_path, img_dir, w // 2, h // 2)
        img_clip = ImageClip(str(resized_path)).set_duration(duration).set_position(("center", 70))
        layers.append(img_clip)
        src_y = 70 + img_h + 30  # 70 = image top offset, 30 = gap below image
    else:
        total_h = src_clip.h + tgt_clip.h + 10
        src_y = (h - total_h) // 2

    tgt_y = src_y + src_clip.h + 10
    src_clip = src_clip.set_position(("center", src_y)).set_duration(duration)
    tgt_clip = (
        tgt_clip
        .set_position(("center", tgt_y))
        .set_duration(duration)
        .set_start(src_clip.end - transition_start)
        .crossfadein(0.3)
    )
    layers.extend([src_clip, tgt_clip])

    final = CompositeVideoClip(layers, size=(w, h))
    return final.set_duration(duration).on_color(color=(0, 0, 0), col_opacity=1)


def _create_resources_clip(
    duration: float,
) -> CompositeVideoClip:
    """Outro slide listing practice resources and an encouraging sign-off."""
    w, h = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    bg = ImageClip(str(config.BACKGROUND_IMAGE)).set_duration(duration)

    lines = [
        "You can also practice with AnkiWeb and Quizlet linked below!",
        "",
        "Keep learning:) You're doing a great job!",
    ]

    text = "\n".join(lines)
    txt_clip = TextClip(
        text, fontsize=54, font="Amiri-regular",
        color="black", size=(w - 160, None), method="caption",
    )
    txt_clip = txt_clip.set_position(("center", (h - txt_clip.h) // 2)).set_duration(duration)

    return (
        CompositeVideoClip([bg, txt_clip], size=(w, h))
        .set_duration(duration)
        .on_color(color=(0, 0, 0), col_opacity=1)
    )


def _create_summary_clip(vocabulary: list[dict], duration: float):
    w, h = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    pairs = [
        f"{e['source_word']}  ·  {e['target_word']}"
        for e in vocabulary
        if e.get("target_word", "").strip()
    ]
    font_size = 40
    bg = ImageClip(str(config.BACKGROUND_IMAGE)).set_duration(duration)

    txt_full = TextClip("\n".join(pairs), fontsize=font_size, font="Amiri-regular",
                        color="black", size=(w - 100, None), method="caption")

    if txt_full.h > h - 100:
        # 2-column layout — centered as a unit
        mid = len(pairs) // 2
        col_w = (w - 140) // 2  # 140 = 2×50 padding + 40 gap
        col1 = TextClip("\n".join(pairs[:mid]), fontsize=font_size, font="Amiri-regular",
                        color="black", size=(col_w, None), method="caption")
        col2 = TextClip("\n".join(pairs[mid:]), fontsize=font_size, font="Amiri-regular",
                        color="black", size=(col_w, None), method="caption")
        gap = max(30, w - col1.w - col2.w - 100)  # at least 40px, shrinks padding before gap
        total_w = col1.w + gap + col2.w
        x1 = max(50, (w - total_w) // 2)
        x2 = x1 + col1.w + gap
        col_y1 = (h - col1.h) // 2
        col_y2 = (h - col2.h) // 2
        layers = [
            bg,
            col1.set_position((x1, col_y1)).set_duration(duration),
            col2.set_position((x2, col_y2)).set_duration(duration),
        ]
    else:
        layers = [
            bg,
            txt_full.set_position(("center", (h - txt_full.h) // 2)).set_duration(duration),
        ]

    return (
        CompositeVideoClip(layers, size=(w, h))
        .set_duration(duration)
        .on_color(color=(0, 0, 0), col_opacity=1)
    )


def create_vocabulary_video(
    vocabulary: list[dict],
    collection: str,
    source_lang: str = "de",
    target_lang: str = "en",
    tts_provider: str | None = None,
    reuse_audio: bool = False,
    book: str = "",
) -> Path:
    output_dir = config.OUTPUT_DIR / collection
    audio_dir = output_dir / "audio"
    video_dir = output_dir / "video"
    image_dir = output_dir / "image"

    for d in (audio_dir, video_dir, image_dir):
        d.mkdir(parents=True, exist_ok=True)

    # --- Build one clip per vocabulary entry ---
    clips = []

    for entry in vocabulary:
        lemma = entry["file_name"]
        source_word = entry["source_word"]
        target_word = entry["target_word"]
        source_sentence = entry.get("source_sentence", "")
        target_sentence = entry.get("target_sentence", "")

        if not target_word or not target_word.strip():
            print(f"[skip] '{lemma}' has no translation, skipping")
            continue

        # generate_vocab_audio handles "die Familie, Familien" → split into segments
        src_word_audio = audio_dir / f"{lemma}_source_word.mp3"
        tgt_word_audio = audio_dir / f"{lemma}_target_word.mp3"
        if not (reuse_audio and src_word_audio.exists()):
            generate_vocab_audio(source_word, src_word_audio, lang=source_lang, silent=500, provider=tts_provider)
        if not (reuse_audio and tgt_word_audio.exists()):
            generate_audio(target_word, tgt_word_audio, lang=target_lang, silent=1000, provider=tts_provider)
        combined_word_audio = _concatenate_audios([src_word_audio, tgt_word_audio], audio_dir, lemma)
        word_duration = get_audio_duration(combined_word_audio)
        de_word_duration = get_audio_duration(src_word_audio)

        word_clip = _create_text_clip(
            source_word, target_word, word_duration,
            font_size=100, transition_start=word_duration - de_word_duration,
            img_dir=image_dir, background_image_path=None,
        ).set_audio(AudioFileClip(str(combined_word_audio)).set_duration(word_duration))

        # Generate (or reuse) sentence audio and append sentence clip if available
        if source_sentence and target_sentence:
            src_sent_audio = audio_dir / f"{lemma}_source_sentence.mp3"
            tgt_sent_audio = audio_dir / f"{lemma}_target_sentence.mp3"
            if not (reuse_audio and src_sent_audio.exists()):
                generate_audio(source_sentence, src_sent_audio, lang=source_lang, silent=500, provider=tts_provider)
            if not (reuse_audio and tgt_sent_audio.exists()):
                generate_audio(target_sentence, tgt_sent_audio, lang=target_lang, silent=1000, provider=tts_provider)
            combined_sent_audio = _concatenate_audios([src_sent_audio, tgt_sent_audio], audio_dir, f"{lemma}_sentence")
            sent_duration = get_audio_duration(combined_sent_audio)
            de_sent_duration = get_audio_duration(src_sent_audio)

            sent_clip = _create_text_clip(
                source_sentence, target_sentence, sent_duration,
                font_size=90, transition_start=sent_duration - de_sent_duration,
                img_dir=image_dir, background_image_path=None,
            ).set_audio(AudioFileClip(str(combined_sent_audio)).set_duration(sent_duration))

            clips.extend([word_clip, sent_clip])
        else:
            clips.append(word_clip)

    # --- Prepend cover intro (fade out → first vocab clip fades in) ---
    cover_prefix = collection.split("_")[0]
    cover_path = Path("input/assets/background.png")   # clean background, no baked-in text
    if cover_path.exists() and clips:
        from scripts.preview_cover import draw_cover_overlay
        with Image.open(cover_path) as _img:
            cover_resized = _img.resize((config.VIDEO_WIDTH, config.VIDEO_HEIGHT), Image.LANCZOS).convert("RGBA")
        cover_resized = draw_cover_overlay(cover_resized, collection, config.VIDEO_WIDTH, config.VIDEO_HEIGHT)
        cover_resized_path = image_dir / f"cover-{cover_prefix}-resized.png"
        cover_resized.convert("RGB").save(str(cover_resized_path))
        cover_clip = (
            ImageClip(str(cover_resized_path))
            .set_duration(3)
            .set_audio(_silent_audio(3))
            .fadeout(1.0)
        )
        clips[0] = clips[0].fadein(1.0).audio_fadein(1.0)
        clips.insert(0, cover_clip)

    # --- Append summary outro (last vocab clip fades out → summary fades in/out) ---
    if clips:
        clips[-1] = clips[-1].fadeout(1.0).audio_fadeout(1.0)
        summary = _create_summary_clip(vocabulary, duration=8).set_audio(_silent_audio(8)).fadein(1.0).audio_fadein(1.0).fadeout(1.0).audio_fadeout(1.0)
        clips.append(summary)

        resources = _create_resources_clip(duration=8).set_audio(_silent_audio(8)).fadein(1.0).audio_fadein(1.0).fadeout(1.0).audio_fadeout(1.0)
        clips.append(resources)

        # Write summary to text folder
        text_dir = output_dir / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        summary_lines = [
            f"{e['source_word']}  ·  {e['target_word']}"
            for e in vocabulary
            if e.get("target_word", "").strip()
        ]
        (text_dir / "summary.txt").write_text("\n".join(summary_lines), encoding="utf-8")
        generate_description(
            collection=collection, book=book or collection.split("_")[0],
            source_lang=source_lang, target_lang=target_lang,
        )

    final_clip = concatenate_videoclips(clips, method="compose")

    # --- Mix in background music at low volume with fade in/out ---
    bg_music_path = Path(f"input/assets/background-music-{cover_prefix}.mp3")
    if bg_music_path.exists():
        total_dur = final_clip.duration
        music = AudioFileClip(str(bg_music_path))
        if music.duration < total_dur:
            music = audio_loop(music, duration=total_dur)
        else:
            music = music.subclip(0, total_dur)
        music = music.volumex(0.08).fx(audio_fadein, 2.0).fx(audio_fadeout, 2.0)
        mixed = CompositeAudioClip([final_clip.audio, music])
        final_clip = final_clip.set_audio(mixed)

    video_path = video_dir / "vocabulary_video.mp4"
    final_clip.write_videofile(str(video_path), fps=24, codec="libx264", audio_codec="aac")
    return video_path
