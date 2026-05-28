from datetime import datetime, timezone
import certifi
from pymongo import MongoClient, ASCENDING
from pymongo.collection import Collection
import config

_client: MongoClient | None = None


def _get_db():
    global _client
    if _client is None:
        if not config.MONGODB_URI:
            raise ValueError(
                "MONGODB_URI is not set in .env.\n"
                "1. Create a free cluster at https://cloud.mongodb.com\n"
                "2. Click 'Connect' → 'Drivers' and copy the connection string\n"
                "3. Add it to .env: MONGODB_URI=mongodb+srv://<user>:<pass>@cluster.mongodb.net/"
            )
        _client = MongoClient(config.MONGODB_URI, tlsCAFile=certifi.where())
    return _client["book2video"]


def _vocabulary(db=None) -> Collection:
    if db is None:
        db = _get_db()
    return db["vocabulary"]


def upsert_entry(collection_name: str, lemma: str, data: dict, book: str = "", source_lang: str = "de", target_lang: str = "en", book_type: str = "vocabulary") -> None:
    col = _vocabulary()
    meta = {
        "collection": collection_name,
        "lemma": lemma,
        "updated_at": datetime.now(timezone.utc),
    }
    if book:
        meta["book"] = book
    if source_lang:
        meta["source_lang"] = source_lang
    if target_lang:
        meta["target_lang"] = target_lang
    if book_type:
        meta["book_type"] = book_type
    col.update_one(
        {"collection": collection_name, "lemma": lemma},
        {"$set": {**data, **meta}},
        upsert=True,
    )


def get_collection(collection_name: str) -> list[dict]:
    col = _vocabulary()
    return list(col.find({"collection": collection_name}, {"_id": 0}).sort("lemma", ASCENDING))


def save_collection(collection_name: str, vocabulary: dict, book: str = "", source_lang: str = "de", target_lang: str = "en", book_type: str = "vocabulary") -> None:
    # Clear existing entries first so re-extractions don't stack stale data
    _vocabulary().delete_many({"collection": collection_name})
    for lemma, entry in vocabulary.items():
        upsert_entry(collection_name, lemma, entry, book=book, source_lang=source_lang, target_lang=target_lang, book_type=book_type)


def delete_collection(collection_name: str) -> int:
    result = _vocabulary().delete_many({"collection": collection_name})
    return result.deleted_count


def list_similar_collections(prefix: str) -> list[str]:
    col = _vocabulary()
    return sorted(c for c in col.distinct("collection") if c.startswith(prefix + "_"))


def get_collections_by_book(book: str) -> list[str]:
    col = _vocabulary()
    return sorted(col.distinct("collection", {"book": book}))


def mark_video_generated(collection_name: str) -> None:
    db = _get_db()
    db["pipeline_state"].update_one(
        {"collection": collection_name},
        {"$set": {"video_generated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )


# ---------------------------------------------------------------------------
# Ebook mode: sentence-level storage
# ---------------------------------------------------------------------------

def _sentences(db=None):
    if db is None:
        db = _get_db()
    return db["sentences"]


def save_ebook_sentences(book: str, sentences: list[dict], source_lang: str = "de", target_lang: str = "en") -> None:
    """Save (or replace) all sentences for an ebook book."""
    col = _sentences()
    col.delete_many({"book": book})
    now = datetime.now(timezone.utc)
    docs = [
        {
            "book": book,
            "chapter": s["chapter"],
            "chapter_index": s["chapter_index"],
            "sentence_index": s["sentence_index"],
            "source_sentence": s["source_sentence"],
            "target_sentence": s.get("target_sentence", ""),
            "source_lang": source_lang,
            "target_lang": target_lang,
            "audio_generated": False,
            "updated_at": now,
        }
        for s in sentences
    ]
    if docs:
        col.insert_many(docs)


def get_ebook_sentences(book: str) -> list[dict]:
    """Retrieve all sentences for a book, ordered by chapter then sentence index."""
    col = _sentences()
    return list(
        col.find({"book": book}, {"_id": 0})
        .sort([("chapter_index", ASCENDING), ("sentence_index", ASCENDING)])
    )


def update_ebook_translations(book: str, translations: list[dict]) -> None:
    """Bulk-update target_sentence for each sentence identified by chapter_index + sentence_index."""
    col = _sentences()
    now = datetime.now(timezone.utc)
    for t in translations:
        col.update_one(
            {"book": book, "chapter_index": t["chapter_index"], "sentence_index": t["sentence_index"]},
            {"$set": {"target_sentence": t["target_sentence"], "updated_at": now}},
        )


def mark_ebook_audio_generated(book: str, chapter_index: int) -> None:
    col = _sentences()
    col.update_many(
        {"book": book, "chapter_index": chapter_index},
        {"$set": {"audio_generated": True, "updated_at": datetime.now(timezone.utc)}},
    )
