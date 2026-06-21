import ast
import json
import pdfplumber
from openai import OpenAI
import config

_client: OpenAI | None = None


def _openai() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def file_search_local(pdf_path: str, alphabet: str, model: str = "gpt-5.2") -> list:
    """pdfplumber text extraction + LLM vocabulary extraction."""
    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    letters = [l.strip().lower() for l in alphabet.split(",")]
    relevant_lines = [
        line for line in full_text.splitlines()
        if any(
            word.lstrip("(").lower().startswith(l)
            for word in line.split()
            for l in letters
        )
    ]
    filtered_text = "\n".join(relevant_lines)

    system_prompt = (
        "<extraction_spec>\n"
        "You will extract German vocabulary entries from a language textbook page into JSON.\n\n"
        "Always follow this schema exactly (no extra fields):\n"
        "{\n"
        '  "entries": [\n'
        "    {\n"
        '      "lemma":   string,           // required — canonical form: noun with article, verb as infinitive\n'
        '      "plural":  string | null,    // plural without article for countable nouns; null otherwise\n'
        '      "example": string | null     // complete example sentence from the source text; null if not found\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Extract ALL parts of speech: nouns, verbs, adjectives, adverbs, prepositions, conjunctions\n"
        "- Nouns: ALWAYS prefix lemma with the correct German article (der/die/das)\n"
        "- Verbs: ALWAYS lowercase infinitive form. If both a verb and its related noun appear, include BOTH as separate entries\n"
        "- Reflexive verbs: prefix lemma with (sich)\n"
        "- Skip proper nouns (names, cities, countries), section headings, and single-letter fragments\n"
        "- If a field is not present in the source, set it to null — do not guess or invent\n"
        "- Before returning, quickly re-scan the source text for any missed vocabulary words and correct omissions\n"
        "</extraction_spec>"
    )
    letter_display = ", ".join(l.upper() for l in letters)
    user_prompt = (
        f"Extract every German vocabulary word starting with any of the letters '{letter_display}' from the text below.\n\n"
        f"Text:\n{filtered_text}"
    )

    response = _openai().chat.completions.create(
        model=model,
        max_completion_tokens=16384,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "vocabulary_extraction",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "entries": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "lemma":   {"type": "string"},
                                    "plural":  {"type": ["string", "null"]},
                                    "example": {"type": ["string", "null"]},
                                },
                                "required": ["lemma", "plural", "example"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["entries"],
                    "additionalProperties": False,
                },
            },
        },
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    )
    data = json.loads(response.choices[0].message.content)

    return [[e["lemma"], e["plural"] or "", e["example"] or ""] for e in data["entries"]]


def file_search_merged(pdf_path: str, alphabet: str) -> list:
    """Extract vocabulary using gpt-5.2 + o3 and merge results for comprehensive coverage."""
    def _norm(lemma: str) -> str:
        for art in ("der/die ", "der ", "die ", "das "):
            if lemma.lower().startswith(art):
                lemma = lemma[len(art):]
        return lemma.lstrip("(").strip().lower()

    entries_a = file_search_local(pdf_path, alphabet, model="gpt-5.2")
    print(f"\n[gpt-5.2] {len(entries_a)} entries:")
    for e in sorted(entries_a, key=lambda x: x[0].lower()):
        print(f"  {e[0]}" + (f", {e[1]}" if e[1] else "") + (f" — {e[2]}" if e[2] else ""))

    entries_b = file_search_local(pdf_path, alphabet, model="o3")
    print(f"\n[o3] {len(entries_b)} entries:")
    for e in sorted(entries_b, key=lambda x: x[0].lower()):
        print(f"  {e[0]}" + (f", {e[1]}" if e[1] else "") + (f" — {e[2]}" if e[2] else ""))

    only_a = {e[0] for e in entries_a} - {e[0] for e in entries_b}
    only_b = {e[0] for e in entries_b} - {e[0] for e in entries_a}
    if only_a:
        print(f"\n[only in gpt-5.2]: {', '.join(sorted(only_a))}")
    if only_b:
        print(f"[only in o3]:       {', '.join(sorted(only_b))}")

    entries = entries_a + entries_b

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
                merged[key] = entry
            elif not _has_article(entry[0]) and _has_article(existing[0]):
                pass
            elif sum(bool(f) for f in entry) > sum(bool(f) for f in existing):
                merged[key] = entry

    # Letter filter: remove false positives whose lemma doesn't start with any target letter
    letters = [l.strip().lower() for l in alphabet.split(",")]
    merged = {k: v for k, v in merged.items() if any(k.startswith(l) for l in letters)}

    # Plural dedup: remove standalone plural entries already captured by their base noun
    known_plurals = {_norm(v[1]) for v in merged.values() if v[1]}
    merged = {k: v for k, v in merged.items() if k not in known_plurals}

    print(f"\n[merged] {len(merged)} entries after dedup:")
    for k in sorted(merged):
        e = merged[k]
        print(f"  {e[0]}" + (f", {e[1]}" if e[1] else "") + (f" — {e[2]}" if e[2] else ""))

    return _cleanup_entries(list(merged.values()))


def _cleanup_entries(entries: list) -> list:
    """Second LLM pass: fix missing articles, lowercase verbs, strip non-sentence examples."""
    payload = repr(entries)
    response = _openai().responses.create(
        model="gpt-4.1",
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
            key = parts[1] if len(parts) >= 2 else parts[0]
            german_word = f"{lemma}, {lemma_plural}" if lemma_plural else lemma
        elif len(parts) == 1 and lemma and lemma[0].isupper() and lemma_plural:
            key = lemma
            german_word = f"{lemma}, {lemma_plural}"
        else:
            key = lemma
            german_word = lemma
        output[key] = {"source_word": german_word, "source_sentence": example}
    return output
