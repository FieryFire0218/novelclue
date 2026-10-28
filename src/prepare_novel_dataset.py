import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


SOURCE = "https://github.com/shaido987/novel-dataset"
COMMIT = "dbaed96ef98788c86bd9d3909f8092269505249d"
LANGUAGES = {"chinese": "zh", "korean": "ko"}


def string_list(record, field):
    value = record.get(field)
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in value
    ):
        raise ValueError(f"{record.get('id')}: invalid {field}")
    return list(dict.fromkeys(
        item.strip() for item in value if item.strip()
    ))


def count_value(record, field, warnings):
    value = record.get(field)
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        warnings.append(
            f"Invalid source {field}: {value!r}; normalized to null."
        )
        return None
    return value


def prepare(records):
    prepared = []
    seen = set()

    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Every input record must be an object.")

        language = record.get("original_language")
        if not isinstance(language, str):
            continue
        language = LANGUAGES.get(language.strip().casefold())
        if language is None:
            continue

        source_id = record.get("id")
        if (
            isinstance(source_id, bool)
            or not isinstance(source_id, int)
            or source_id <= 0
        ):
            raise ValueError("Missing or invalid source novel ID.")
        if source_id in seen:
            raise ValueError(f"Duplicate source ID: {source_id}")
        seen.add(source_id)

        title = record.get("name")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"{source_id}: missing title")

        warnings = []

        prepared.append({
            "source": "shaido987/novel-dataset",
            "source_novel_id": source_id,
            "source_title": title.strip(),
            "associated_names": string_list(record, "assoc_names"),
            "authors": string_list(record, "authors"),
            "original_language": language,
            "genres": string_list(record, "genres"),
            "tags": string_list(record, "tags"),

            # these fields are not supplied by this dataset.
            "novelupdates_url": None,
            "synopsis": None,
            "novelupdates_reader_count": None,

            # preserve the source metric's meaning.
            "novelupdates_reading_list_count": count_value(
                record, "on_reading_lists", warnings
            ),
            "novelupdates_rating_count": count_value(
                record, "rating_votes", warnings
            ),
            "source_popularity_raw": {
                "on_reading_lists": record.get("on_reading_lists"),
                "rating_votes": record.get("rating_votes"),
            },

            # keep source-specific values separate from game fields.
            "novelupdates_rating_raw": record.get("rating"),
            "original_chapter_status_raw": record.get(
                "chapters_original_current"
            ),
            "warnings": warnings,
        })

    return prepared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError("Input and output must be different files.")

        raw = args.input.read_bytes()
        records = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(records, list):
            raise ValueError("Expected a JSON list.")

        prepared = prepare(records)
        languages = Counter(
            record["original_language"] for record in prepared
        )

        report = {
            "report_type": "external_novel_metadata",
            "adapter_version": "1",
            "source_repository": SOURCE,
            "source_commit": COMMIT,
            "dataset_version": "0.1.5",
            "dataset_reported_update_date": "2025-08-21",
            "input_sha256": hashlib.sha256(raw).hexdigest(),
            "prepared_at": datetime.now(timezone.utc).isoformat(),
            "popularity_filter_applied": False,
            "scope_filter_applied": False,
            "summary": {
                "input_records": len(records),
                "prepared_records": len(prepared),
                "by_language": dict(languages),
            },
            "records": prepared,
        }

        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, indent=2)
            file.write("\n")

        print(f"Input records: {len(records)}")
        print(f"Chinese: {languages['zh']}")
        print(f"Korean: {languages['ko']}")
        print(f"Prepared records: {len(prepared)}")
        print("No popularity or scope cutoff applied.")
        print(f"Saved: {args.output}")
        print("No database changes were made.")

    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()