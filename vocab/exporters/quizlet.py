from pathlib import Path

import config


def create_quizlet_export(vocabulary: list[dict], collection: str) -> Path:
    quizlet_dir = config.OUTPUT_DIR / collection / "quizlet"
    quizlet_dir.mkdir(parents=True, exist_ok=True)
    out_path = quizlet_dir / f"{collection}.txt"

    lines = []
    for entry in vocabulary:
        source_word = entry["source_word"]
        target_word = entry.get("target_word", "")
        if not target_word.strip():
            print(f"[skip] '{entry.get('file_name', '?')}' has no translation, skipping")
            continue
        lines.append(f"{source_word}\t{target_word}")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[quizlet] Saved {len(lines)} terms → {out_path}")
    return out_path
