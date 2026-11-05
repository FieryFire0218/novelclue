import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import unicodedata
from urllib.parse import urlsplit


COUNTS = ("novelupdates_rating_count", "novelupdates_reading_list_count")
FIELDS = ("novelupdates_url", "original_language", "genres", "synopsis", *COUNTS)


def normalize_title(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def normalize_url(value):
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or parts.netloc not in {"www.novelupdates.com", "novelupdates.com"}
        or parts.query or parts.fragment
        or len(parts.path.strip("/").split("/")) != 2
        or not parts.path.startswith("/series/")
    ):
        raise ValueError(f"Invalid NovelUpdates series URL: {value!r}")
    return "https://www.novelupdates.com" + parts.path.rstrip("/") + "/"


def validate_records(records):
    if not isinstance(records, list) or not records:
        raise ValueError("Input must be a nonempty JSON array.")
    seen = set()
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict):
            raise ValueError(f"Record {index} must be an object.")
        for key in ("source_title", "novelupdates_url"):
            if not isinstance(record.get(key), str) or not record[key].strip():
                raise ValueError(f"Record {index}: missing {key}.")
        url = normalize_url(record["novelupdates_url"])
        if url in seen:
            raise ValueError(f"Duplicate source URL: {url}")
        seen.add(url)
        for key in ("associated_names", "genres", "warnings"):
            if not isinstance(record.get(key, []), list) or not all(
                isinstance(v, str) and v.strip() for v in record.get(key, [])
            ):
                raise ValueError(f"Record {index}: invalid {key}.")
        if record.get("original_language") not in {None, "zh", "ko", "ja"}:
            raise ValueError(f"Record {index}: unsupported language code.")
        if record.get("synopsis") is not None and not isinstance(record["synopsis"], str):
            raise ValueError(f"Record {index}: invalid synopsis.")
        for key in COUNTS:
            value = record.get(key)
            if value is not None and (type(value) is not int or not 0 <= value <= 2147483647):
                raise ValueError(f"Record {index}: invalid {key}.")


def make_preview(records, novels):
    validate_records(records)
    by_url, by_title = defaultdict(list), defaultdict(list)
    for novel in novels:
        by_title[normalize_title(novel["title"])].append(novel)
        if novel.get("novelupdates_url"):
            by_url[normalize_url(novel["novelupdates_url"])].append(novel)

    results = []
    for record in records:
        url = normalize_url(record["novelupdates_url"])
        candidates = by_url.get(url, [])
        method = "stored NovelUpdates URL"
        if not candidates:
            method = "exact title or associated name (case/spacing normalized)"
            names = [record["source_title"], *record.get("associated_names", [])]
            found = {
                n["id"]: n for name in names
                for n in by_title.get(normalize_title(name), [])
            }
            candidates = list(found.values())

        item = {
            "source_title": record["source_title"],
            "novelupdates_url": url,
            "status": "unmatched",
            "match_method": method,
            "candidates": [{"id": n["id"], "title": n["title"]} for n in candidates],
            "changes": {},
            "notes": list(record.get("warnings", [])),
        }
        results.append(item)
        if not candidates:
            item["notes"].append("No exact match. No new novel will be inserted.")
            continue
        if len(candidates) != 1:
            item["status"] = "review"
            item["notes"].append("Multiple candidates; no match selected.")
            continue

        novel = candidates[0]
        item["novel_id"] = novel["id"]
        item["database_title"] = novel["title"]
        conflicts = []
        if novel.get("novelupdates_url") and normalize_url(novel["novelupdates_url"]) != url:
            conflicts.append("Novel is already linked to a different NovelUpdates URL.")
        language = record.get("original_language")
        if language and novel.get("original_language") and language != novel["original_language"]:
            conflicts.append("Original languages conflict.")
        if conflicts:
            item["status"] = "review"
            item["notes"].extend(conflicts)
            continue

        proposed = {"novelupdates_url": url}
        if language:
            proposed["original_language"] = language
        # first enrichment pass fills gaps, preserving existing curated text.
        for key in ("genres", "synopsis"):
            value = record.get(key)
            if isinstance(value, str):
                value = value.strip()
            existing = novel.get(key)
            if isinstance(existing, str):
                existing = existing.strip()
            if value and not existing:
                proposed[key] = value
            elif value and existing and value != novel.get(key):
                item["notes"].append(f"Kept existing {key}; source value differs.")
        for key in COUNTS:
            if record.get(key) is not None:
                proposed[key] = record[key]

        item["changes"] = {
            key: {"old": novel.get(key), "new": value}
            for key, value in proposed.items() if novel.get(key) != value
        }
        item["status"] = "matched" if item["changes"] else "unchanged"
        if record.get("warnings"):
            item["status"] = "review"

    # prevent two different source records from claiming one database novel.
    targets = Counter(item.get("novel_id") for item in results if "novel_id" in item)
    for item in results:
        if targets.get(item.get("novel_id"), 0) > 1:
            item["status"] = "review"
            item["notes"].append("Multiple input records target this novel; resolve before importing.")
    return results


def load_novels():
    from sqlalchemy import select, text
    from database import SessionLocal
    from models import Novel

    columns = [Novel.id, Novel.title, *(getattr(Novel, name) for name in FIELDS)]
    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        return [dict(row) for row in session.execute(select(*columns)).mappings()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        records = json.loads(args.input.read_text(encoding="utf-8-sig"))
        validate_records(records)
        results = make_preview(records, load_novels())
    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")

    for item in results:
        print(f"\n[{item['status'].upper()}] {item['source_title']}")
        if "novel_id" in item:
            print(f"  Database: #{item['novel_id']} {item['database_title']}")
            print(f"  Match: {item['match_method']}")
        elif item["candidates"]:
            print(f"  Candidates: {item['candidates']}")
        for field, change in item["changes"].items():
            print(f"  {field}:")
            print("    old: " + json.dumps(change["old"], ensure_ascii=False))
            print("    new: " + json.dumps(change["new"], ensure_ascii=False))
        for note in item["notes"]:
            print(f"  NOTE: {note}")
    counts = Counter(item["status"] for item in results)
    print("\nSummary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print("Preview only. No database changes were saved.")


if __name__ == "__main__":
    main()
