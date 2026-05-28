import ast
import pdfplumber
from openai import OpenAI
import config

_client: OpenAI | None = None


def _openai() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client



def _extract_filtered_text(pdf_path: str, alphabet: str) -> str:
    """Extract full PDF text locally, return only lines containing words starting with alphabet."""
    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    letter = alphabet.lower()
    relevant_lines = [
        line for line in full_text.splitlines()
        if any(word.lstrip("(").lower().startswith(letter) for word in line.split())
    ]
    return "\n".join(relevant_lines)


def file_search_local(pdf_path: str, alphabet: str) -> list:
    """Method A: pdfplumber local extraction + GPT-4.1 Chat API structuring."""
    filtered_text = _extract_filtered_text(pdf_path, alphabet)
    response = _openai().chat.completions.create(
        model="gpt-4.1", temperature=0, max_tokens=16384,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a German vocabulary extractor. "
                    "Extract ALL parts of speech — nouns, verbs, adjectives, adverbs, prepositions, "
                    "conjunctions, and other function words. Do not skip non-nouns. "
                    "CRITICAL: (1) Every noun MUST be prefixed with its correct German article "
                    "(der/die/das). Never output a noun without its article. "
                    "(2) Verbs MUST be lowercase infinitive form. Never capitalise a verb. "
                    "Output only a Python list, no markdown, no explanation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Extract every German word starting with the letter '{alphabet}' from the text below.\n\n"
                    "Output format — a Python list of 3-item lists:\n"
                    "  [lemma, plural_or_empty_string, example_sentence_or_empty_string]\n\n"
                    "Rules per part of speech:\n"
                    "  - Nouns: ALWAYS write 'der/die/das Lemma' — article is REQUIRED.\n"
                    "    Example: 'die Familie', 'der Fehler', 'das Foto'\n"
                    "  - Verbs: ALWAYS lowercase infinitive. Example: 'fahren', 'füllen', 'finden'\n"
                    "  - Reflexive verbs: prefix '(sich) '. Example: '(sich) freuen'\n"
                    "  - Adjectives / adverbs / prepositions / conjunctions: lowercase base form\n"
                    "  - Field 2: plural without article for nouns; '' for everything else\n"
                    "  - Field 3: example sentence from the text if present; '' otherwise\n"
                    "  - Do NOT invent words not in the text\n\n"
                    "Example output:\n"
                    "[['der Fehler', 'Fehler', 'Diesen Fehler mache ich immer.'],\n"
                    " ['die Familie', 'Familien', 'Meine Familie lebt in Spanien.'],\n"
                    " ['falsch', '', 'Das ist falsch.'],\n"
                    " ['fahren', '', 'Fahren Sie bitte nicht so schnell.'],\n"
                    " ['für', '', 'Das ist für Sie.']]\n\n"
                    f"Text:\n{filtered_text}"
                ),
            },
        ],
    )
    return ast.literal_eval(response.choices[0].message.content)


def file_search_merged(pdf_path: str, alphabet: str) -> list:
    """Extract vocabulary using Method A (pdfplumber + GPT-4.1) with sanity checks.
    Method B (Assistants RAG) was evaluated but dropped — it introduced conjugated forms,
    proper nouns, and garbled entries that prompts could not reliably suppress.
    """
    def _norm(lemma: str) -> str:
        for art in ("der/die ", "der ", "die ", "das "):
            if lemma.lower().startswith(art):
                lemma = lemma[len(art):]
        return lemma.lstrip("(").strip().lower()

    entries = file_search_local(pdf_path, alphabet)

    # Deduplicate by normalised key, preferring entries with an article
    def _has_article(lemma: str) -> bool:
        return any(lemma.lower().startswith(art) for art in ("der ", "die ", "das ", "der/die "))

    merged: dict[str, list] = {}
    for entry in entries:
        if len(entry) != 3:
            continue
        key = _norm(entry[0])
        if key not in merged:
            merged[key] = entry
        else:
            existing = merged[key]
            if _has_article(entry[0]) and not _has_article(existing[0]):
                merged[key] = entry  # upgrade to version with article
            elif not _has_article(entry[0]) and _has_article(existing[0]):
                pass
            elif sum(bool(f) for f in entry) > sum(bool(f) for f in existing):
                merged[key] = entry

    # Letter filter: remove false positives whose lemma doesn't start with the target letter
    letter = alphabet.lower()
    merged = {k: v for k, v in merged.items() if k.startswith(letter)}

    # Plural dedup: remove standalone plural entries already captured by their base noun
    known_plurals = {_norm(v[1]) for v in merged.values() if v[1]}
    merged = {k: v for k, v in merged.items() if k not in known_plurals}

    return _cleanup_entries(list(merged.values()))


def _cleanup_entries(entries: list) -> list:
    """Second LLM pass: fix missing articles, lowercase verbs, strip non-sentence examples."""
    payload = repr(entries)
    response = _openai().responses.create(
        model="gpt-5-mini",
        instructions=(
            "You are a German vocabulary quality checker. "
            "You will receive a Python list of 3-item lists: [lemma, plural, example_sentence]. "
            "Fix the following issues and return the corrected list — same format, no markdown, no explanation.\n\n"
            "Rules:\n"
            "1. NOUNS must have a German article: 'der', 'die', or 'das'. "
            "   If a lemma is a capitalised German noun without an article, add the correct article. "
            "   Example: 'Feierabend' → 'der Feierabend', 'Feiertag' → 'der Feiertag', 'Freundin' → 'die Freundin'.\n"
            "2. VERBS must be lowercase infinitive. "
            "   If a lemma looks like a verb (all-caps first letter, no article, no plural) → lowercase it. "
            "   Example: 'Füllen' → 'füllen', 'Fahren' → 'fahren'.\n"
            "3. EXAMPLE SENTENCES must be complete, natural German sentences with a subject and verb. "
            "   Replace field 3 with '' if it is: a dictionary notation, word list, fragment, phrase without a verb, "
            "   numeric/math notation, or a letter/formula expression. "
            "   Example: 'Feier- z. B. Feierabend, Feiertag' → '', '5 = fünf 30 = dreißig' → '', 'Mit freundlichen Grüßen' → ''.\n"
            "4. NOUNS with a missing plural (field 2 is empty string '') should have the correct German plural filled in. "
            "   Only fill plurals for countable nouns — leave field 2 as '' for uncountable nouns (e.g. 'das Fleisch', 'das Fieber'), "
            "   mass nouns, proper nouns (e.g. 'Finnland'), and non-nouns. "
            "   Example: ['der Flughafen', '', '...'] → ['der Flughafen', 'Flughäfen', '...']\n"
            "5. Do NOT add or remove entries. Do not change anything not covered by rules 1–4."
        ),
        input=f"Fix this list:\n{payload}",
    )
    try:
        return ast.literal_eval(response.output_text)
    except Exception:
        # If parse fails, return original rather than crashing
        return entries


def parse_to_vocabulary(entries: list) -> dict:
    output = {}
    for entry in entries:
        if len(entry) != 3:
            continue
        lemma, lemma_plural, example = entry
        # Strip trailing dashes from lemmas like "all-", "ander-"
        lemma = lemma.rstrip("-").strip()
        parts = lemma.split(" ")
        if parts[0] in ("der", "die", "das", "der/die"):
            # Noun with article: key = bare noun, source_word = "die Familie, Familien"
            key = parts[1] if len(parts) >= 2 else parts[0]
            german_word = f"{lemma}, {lemma_plural}" if lemma_plural else lemma
        elif len(parts) == 1 and lemma and lemma[0].isupper() and lemma_plural:
            # Noun missing article (LLM forgot it): key = bare noun, still include plural
            key = lemma
            german_word = f"{lemma}, {lemma_plural}"
        else:
            # Verb / adjective / other
            key = lemma
            german_word = lemma
        output[key] = {"source_word": german_word, "source_sentence": example}
    return output
