import argparse
from collections import Counter
import json
from pathlib import Path

from preview_novelupdates_import import (
    FIELDS, load_novels, make_preview, validate_records,
)


def show_results(results):
    for item in results:
        print(f"\n[{item['status'].upper()}] {item['source_title']}")
        if "novel_id" in item:
            print(f"  Database: #{item['novel_id']} {item['database_title']}")
            print(f"  Match: {item['match_method']}")
        else:
            print(f"  Candidates: {item['candidates']}")
        for field, change in item["changes"].items():
            print(f"  {field}:")
            print("    old: " + json.dumps(change["old"], ensure_ascii=False))
            print("    new: " + json.dumps(change["new"], ensure_ascii=False))
        for note in item["notes"]:
            print(f"  NOTE: {note}")
    counts = Counter(item["status"] for item in results)
    print("\nSummary: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))


def stage_changes(results, by_id):
    """Validate the complete plan before assigning any ORM attributes."""
    blocked = [item for item in results if item["status"] not in {"matched", "unchanged"}]
    if blocked:
        titles = ", ".join(item["source_title"] for item in blocked)
        raise ValueError(f"Import stopped: resolve unmatched/review records first: {titles}")

    seen = set()
    for item in results:
        novel_id = item["novel_id"]
        if novel_id in seen or novel_id not in by_id:
            raise ValueError("Duplicate or missing target novel; nothing saved.")
        seen.add(novel_id)
        for field, change in item["changes"].items():
            if field not in FIELDS:
                raise ValueError(f"Unexpected update field: {field}")
            if getattr(by_id[novel_id], field) != change["old"]:
                raise ValueError("Database changed since planning; nothing saved.")

    updated = 0
    for item in results:
        if item["changes"]:
            novel = by_id[item["novel_id"]]
            for field, change in item["changes"].items():
                setattr(novel, field, change["new"])
            updated += 1
    return updated


def apply_records(records):
    from sqlalchemy import select, text
    from database import SessionLocal
    from models import Novel

    validate_records(records)
    # transaction context commits only after every update succeeds.
    # a failure (including a constraint violation) rolls back the entire batch.
    with SessionLocal.begin() as session:
        # A short batch lock prevents concurrent writes/inserts from changing the title/URL matching set. Ordinary reads remain available.
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        session.execute(text("LOCK TABLE novels IN SHARE ROW EXCLUSIVE MODE"))
        novels = session.scalars(select(Novel).order_by(Novel.id)).all()
        by_id = {novel.id: novel for novel in novels}
        snapshots = [
            {"id": novel.id, "title": novel.title,
             **{field: getattr(novel, field) for field in FIELDS}}
            for novel in novels
        ]
        results = make_preview(records, snapshots)
        show_results(results)
        updated = stage_changes(results, by_id)
        session.flush()

    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--apply", action="store_true", help="Save changes in one transaction")
    args = parser.parse_args()

    from sqlalchemy.exc import SQLAlchemyError

    try:
        records = json.loads(args.input.read_text(encoding="utf-8-sig"))
        validate_records(records)
        if args.apply:
            updated = apply_records(records)
            print(f"\nImport committed. Updated: {updated}; unchanged: {len(records) - updated}.")
        else:
            show_results(make_preview(records, load_novels()))
            print("\nPreview only. No database changes were saved.")
    except SQLAlchemyError:
        parser.exit(1, "Database operation failed. No successful commit was confirmed. "
                    "Check PostgreSQL connectivity, migrations, and competing imports; "
                    "rerun the preview to inspect the current state.\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
