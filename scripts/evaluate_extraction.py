"""
Evaluate and compare two PDF extraction methods side by side.
Writes a markdown report suitable for sharing.

Usage:
  python evaluate_extraction.py --pdf A1.pdf --alphabet F
"""
import argparse
from datetime import datetime
from pathlib import Path

from vocab.extractor import file_search, file_search_local


def _normalise(lemma: str) -> str:
    for article in ("der/die ", "der ", "die ", "das "):
        if lemma.lower().startswith(article):
            lemma = lemma[len(article):]
    return lemma.lstrip("(").strip().lower()


def _format_entry(entry: list) -> str:
    lemma, plural, sentence = entry
    parts = [lemma]
    if plural:
        parts.append(plural)
    result = ", ".join(parts)
    if sentence:
        result += f" — _{sentence}_"
    return result


parser = argparse.ArgumentParser()
parser.add_argument("--pdf", required=True, help="Path to PDF file")
parser.add_argument("--alphabet", required=True, help="Single letter to evaluate")
args = parser.parse_args()

letter = args.alphabet.upper()
print(f"\n[eval] Running Method A (pdfplumber + GPT-4o Chat) for letter '{letter}'...")
results_a = file_search_local(args.pdf, letter)

print(f"[eval] Running Method B (Assistants API + RAG) for letter '{letter}'...")
results_b = file_search(args.pdf, letter)

keys_a = {_normalise(e[0]): e for e in results_a if len(e) == 3}
keys_b = {_normalise(e[0]): e for e in results_b if len(e) == 3}

shared    = sorted(set(keys_a) & set(keys_b))
only_in_a = sorted(set(keys_a) - set(keys_b))
only_in_b = sorted(set(keys_b) - set(keys_a))

# Terminal summary
print(f"\n{'='*50}")
print(f"  Alphabet: {letter}")
print(f"{'='*50}")
print(f"  Method A (pdfplumber + Chat):  {len(keys_a):>3} words")
print(f"  Method B (Assistants + RAG):   {len(keys_b):>3} words")
print(f"  Shared (both agree):           {len(shared):>3} words")
print(f"  Only in Method A:              {len(only_in_a):>3} words")
print(f"  Only in Method B:              {len(only_in_b):>3} words")
print(f"{'='*50}\n")

if only_in_a:
    print(f"Words only in Method A ({len(only_in_a)}):")
    for k in only_in_a:
        print(f"  - {_format_entry(keys_a[k])}")

if only_in_b:
    print(f"\nWords only in Method B ({len(only_in_b)}):")
    for k in only_in_b:
        print(f"  - {_format_entry(keys_b[k])}")

# Write markdown report
report_path = Path(f"evaluation_{letter}.md")
lines = [
    f"# Extraction Method Comparison — Alphabet {letter}",
    f"\n_Generated on {datetime.now().strftime('%Y-%m-%d')}_",
    "\n## Background",
    "\nThis report compares two approaches to extracting German vocabulary from a PDF textbook:",
    "\n- **Method A — pdfplumber + GPT-4.1 Chat**: Extracts the full PDF text locally using `pdfplumber` (deterministic, free), filters lines containing words starting with the target letter, then sends the filtered text to GPT-4.1 via the Chat API for structuring. The prompt explicitly covers all parts of speech — nouns, verbs, adjectives, adverbs, prepositions, and conjunctions.",
    "- **Method B — OpenAI Assistants API + RAG**: Uploads the PDF to an OpenAI vector store and uses the file_search tool with an Assistant to retrieve and structure vocabulary. Relies on semantic retrieval, which may not guarantee full coverage.",
    "\n## Summary",
    "\n| Metric | Count |",
    "|--------|-------|",
    f"| Method A (pdfplumber + GPT-4o Chat) | {len(keys_a)} |",
    f"| Method B (Assistants API + RAG) | {len(keys_b)} |",
    f"| Shared (found by both) | {len(shared)} |",
    f"| Only in Method A | {len(only_in_a)} |",
    f"| Only in Method B | {len(only_in_b)} |",
    "\n## Words Found by Both Methods",
    "\n_These entries were consistently identified by both approaches._\n",
]
for k in shared:
    lines.append(f"- {_format_entry(keys_a[k])}")

lines += [
    f"\n## Words Only in Method A — pdfplumber ({len(only_in_a)})",
    "\n_Found by local text extraction but missed by RAG retrieval._\n",
]
if only_in_a:
    for k in only_in_a:
        lines.append(f"- {_format_entry(keys_a[k])}")
else:
    lines.append("_None_")

lines += [
    f"\n## Words Only in Method B — Assistants API ({len(only_in_b)})",
    "\n_Found by RAG retrieval but missed by local text extraction._\n",
]
if only_in_b:
    for k in only_in_b:
        lines.append(f"- {_format_entry(keys_b[k])}")
else:
    lines.append("_None_")

lines += [
    "\n## Observations",
    "\n_Fill in after reviewing the lists above._",
    "\n- Which method had better coverage overall?",
    "- Were the discrepancies genuine words or hallucinations?",
    "- Did one method produce better lemma forms / plurals / example sentences?",
    "- Recommendation for production use:",
]

report_path.write_text("\n".join(lines), encoding="utf-8")
print(f"\n[eval] Report written to {report_path}")
