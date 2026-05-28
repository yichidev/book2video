"""
One-time migration script to update existing MongoDB documents to the new schema.

What it does:
- Renames german_word → source_word, german_sentence → source_sentence
- Renames translated_word → target_word, translated_sentence → target_sentence
- Adds book, source_lang="de", target_lang="en", book_type="vocabulary" to all existing docs

Run once:
    python migrate_schema.py
"""

from dotenv import load_dotenv
load_dotenv()

from storage.mongodb import _vocabulary

RENAMES = {
    "german_word": "source_word",
    "german_sentence": "source_sentence",
    "translated_word": "target_word",
    "translated_sentence": "target_sentence",
}


def infer_book(collection: str) -> str:
    """Infer book code from collection name, e.g. 'A1_A_1' → 'A1'."""
    parts = collection.split("_")
    return parts[0] if parts else ""


def migrate():
    col = _vocabulary()
    docs = list(col.find({}))
    print(f"Found {len(docs)} documents to migrate.")

    updated = 0
    skipped = 0

    for doc in docs:
        doc_id = doc["_id"]
        update = {}

        # Rename fields
        unset = {}
        for old, new in RENAMES.items():
            if old in doc and new not in doc:
                update[new] = doc[old]
                unset[old] = ""

        # Add metadata if missing
        collection_name = doc.get("collection", "")
        if "book" not in doc:
            update["book"] = infer_book(collection_name)
        if "source_lang" not in doc:
            update["source_lang"] = "de"
        if "target_lang" not in doc:
            update["target_lang"] = "en"
        if "book_type" not in doc:
            update["book_type"] = "vocabulary"

        if not update and not unset:
            skipped += 1
            continue

        op = {}
        if update:
            op["$set"] = update
        if unset:
            op["$unset"] = unset

        col.update_one({"_id": doc_id}, op)
        updated += 1

    print(f"Migrated: {updated} documents")
    print(f"Skipped (already up to date): {skipped} documents")


if __name__ == "__main__":
    migrate()
