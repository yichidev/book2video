from tqdm import tqdm
import deepl
import config


def _clean(text: str) -> str:
    """Remove unmatched leading parenthesis, e.g. '(undress' → 'undress'."""
    t = text.strip()
    if t.startswith("(") and not t.endswith(")"):
        t = t[1:].strip()
    return t


def add_translation(vocabulary: dict, source_lang: str = "DE", target_lang: str = "EN-US") -> dict:
    translator = deepl.Translator(config.DEEPL_API_KEY)
    translated = {}

    for lemma, entry in tqdm(vocabulary.items(), desc="Translating"):
        try:
            target_word = _clean(translator.translate_text(
                lemma, source_lang=source_lang, target_lang=target_lang
            ).text)

            target_sentence = ""
            if entry.get("source_sentence"):
                target_sentence = translator.translate_text(
                    entry["source_sentence"],
                    source_lang=source_lang,
                    target_lang=target_lang,
                ).text

            translated[lemma] = {
                "source_word": entry["source_word"],
                "source_sentence": entry.get("source_sentence", ""),
                "target_word": target_word,
                "target_sentence": target_sentence,
            }
        except Exception as e:
            print(f"Translation failed for '{lemma}': {e}")
            translated[lemma] = {
                "source_word": entry["source_word"],
                "source_sentence": entry.get("source_sentence", ""),
                "target_word": "",
                "target_sentence": "",
            }

    return translated
