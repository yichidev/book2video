import os
import httpx
from pathlib import Path
from gtts import gTTS
from pydub import AudioSegment
import config

_OPENAI_VOICE = {"de": "onyx", "en": "nova"}
_OPENAI_INSTRUCTIONS = {
    "de": "Speak in clear, standard German (Hochdeutsch) with natural German pronunciation and rhythm. Avoid any English-influenced accent.",
    "en": "Speak in clear, natural American English.",
}


def generate_audio(text: str, filename, lang: str = "de", silent: int = 0, provider: str | None = None) -> None:
    """Generate audio for a single text string. Use for sentences and target words."""
    if not text or not text.strip():
        raise ValueError(f"Cannot generate audio: text is empty (filename={filename})")
    _generate(segments=[text], filename=filename, lang=lang, silent=silent, provider=provider)


def generate_vocab_audio(text: str, filename, lang: str = "de", silent: int = 0, provider: str | None = None) -> None:
    """Generate audio for vocabulary source words, splitting on ', ' for compound forms.

    Splits "die Familie, Familien" into ["die Familie", "Familien"] so each segment
    gets natural pronunciation before being concatenated into one file.
    """
    if not text or not text.strip():
        raise ValueError(f"Cannot generate audio: text is empty (filename={filename})")
    segments = text.split(", ") if ", " in text else [text]
    _generate(segments=segments, filename=filename, lang=lang, silent=silent, provider=provider)


def _generate(segments: list, filename, lang: str, silent: int, provider: str | None) -> None:
    if provider is None:
        provider = config.DEFAULT_TTS_PROVIDER

    if provider == "openai":
        _generate_openai(segments, filename, lang, silent)
    else:
        _generate_gtts(segments, filename, lang, silent)


def _generate_openai(segments: list, filename, lang: str, silent: int) -> None:
    voice = _OPENAI_VOICE.get(lang, "alloy")
    temp_files = []

    for i, segment in enumerate(segments):
        temp_path = f"temp_tts_{i}_{Path(str(filename)).stem}.mp3"
        response = httpx.post(
            "https://api.openai.com/v1/audio/speech",
            headers={
                "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini-tts",
                "voice": voice,
                "input": segment,
                "instructions": _OPENAI_INSTRUCTIONS.get(lang, ""),
                "response_format": "mp3",
            },
            timeout=60,
        )
        response.raise_for_status()
        with open(temp_path, "wb") as f:
            f.write(response.content)
        temp_files.append(temp_path)

    _combine_and_export(temp_files, filename, silent, normalize=True)


def _generate_gtts(segments: list, filename, lang: str, silent: int) -> None:
    temp_files = []
    for i, segment in enumerate(segments):
        temp_path = f"temp_tts_{i}_{Path(str(filename)).stem}.mp3"
        gTTS(segment, lang=lang).save(temp_path)
        temp_files.append(temp_path)

    _combine_and_export(temp_files, filename, silent, normalize=False)


def _combine_and_export(temp_files: list, filename, silent: int, normalize: bool) -> None:
    combined = AudioSegment.silent(0)
    for i, path in enumerate(temp_files):
        audio = AudioSegment.from_file(path)
        if normalize and len(audio) > 200:
            audio = audio.normalize().fade_in(25).fade_out(25)
        combined += audio
        if i < len(temp_files) - 1:
            combined += AudioSegment.silent(100)

    if silent:
        combined += AudioSegment.silent(silent)

    combined.export(str(filename), format="mp3")

    for path in temp_files:
        os.remove(path)


def get_audio_duration(filename) -> float:
    return len(AudioSegment.from_file(str(filename))) / 1000.0
