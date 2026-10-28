import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit

from compare import _text_key


def url_key(value):
    if not isinstance(value, str):
        return None
    p = urlsplit(value)
    if p.scheme not in {"http", "https"} or p.netloc not in {"www.novelupdates.com", "novelupdates.com"}:
        return None
    if not p.path.startswith("/series/") or len(p.path.strip("/").split("/")) != 2 or p.query or p.fragment:
        return None
    return "https://www.novelupdates.com" + p.path.rstrip("/") + "/"


def timestamp(record):
    value = record.get("parsed_at")
    if not isinstance(value, str):
        raise ValueError("Page record has no parsed_at timestamp.")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Page timestamps must include a timezone.")
    return result


def load_pages(paths):
    pages = {}
    for path in paths:
        records = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(records, list):
            raise ValueError("--details expects detail-record lists, not scope reports.")
        for record in records:
            key = url_key(record.get("novelupdates_url"))
            if not key or record.get("source") != "novelupdates" or record.get("warnings"):
                raise ValueError("Invalid or warned detail record; resolve before attaching.")
            date = timestamp(record)
            if key not in pages or date > timestamp(pages[key]):
                pages[key] = record
    return pages


def plan_updates(preview, novels, pages):
    if preview.get("report_type") != "external_dataset_import_preview":
        raise ValueError("Expected the reviewed dataset import preview.")
    if not isinstance(preview.get("source_provenance"), dict):
        raise ValueError("Missing source provenance.")
    by_id = {novel.id: novel for novel in novels}
    by_source = {}
    for novel in novels:
        source_id = (novel.source_metadata or {}).get("source_novel_id")
        if source_id is not None:
            if source_id in by_source:
                raise ValueError(f"Multiple database rows claim source ID {source_id}.")
            by_source[source_id] = novel
    plan, seen, targets = [], set(), set()
    for item in preview["results"]:
        source_id = item["source_novel_id"]
        record = item["record"]
        if type(source_id) is not int or source_id <= 0 or source_id in seen or record.get("source_novel_id") != source_id:
            raise ValueError("Invalid or duplicate source ID.")
        seen.add(source_id)
        if record.get("source") != "shaido987/novel-dataset" or record.get("warnings"):
            raise ValueError("Unexpected or warned source record.")
        if item["status"] == "conflict":
            raise ValueError("Resolve input identity conflicts before applying.")
        current = by_source.get(source_id)
        if item["status"] == "matched":
            target = by_id.get(item["database_novel_id"])
            if target is None or (current is not None and current.id != target.id):
                raise ValueError(f"Stale database identity: {item['source_title']}")
            current = target
        elif item["status"] != "new_candidate":
            raise ValueError("Unexpected preview matching status.")
        if current is None:
            plan.append(("not_in_database", item["source_title"], None, None))
            continue
        if current.id in targets:
            raise ValueError("Multiple source records target one database row.")
        targets.add(current.id)
        metadata = deepcopy(current.source_metadata or {})
        if metadata.get("source_novel_id") not in {None, source_id}:
            raise ValueError(f"Existing source ID conflict: {current.title}")
        titles = [record["source_title"], *record.get("associated_names", [])]
        if metadata.get("source_novel_id") is None and _text_key(current.title) not in {_text_key(t) for t in titles}:
            raise ValueError(f"Database title changed since preview: {current.title}")
        if current.original_language and current.original_language != record["original_language"]:
            raise ValueError(f"Language conflict: {current.title}")
        # existing retained records are never replaced by this historical snapshot.
        # a newer page record is stored separately for field-level precedence.
        metadata.setdefault("record", record)
        metadata.setdefault("source_novel_id", source_id)
        metadata.setdefault("source_provenance", preview["source_provenance"])
        metadata.setdefault("pool_config", preview["pool_config"])
        metadata.setdefault("scope_rules_version", preview["rules_version"])
        metadata.setdefault("normal_candidate", item["normal_candidate"])
        metadata.setdefault("broad_candidate", item["broad_candidate"])
        metadata.setdefault("author_display_policy", "first source entry; not a canonical author identity")
        keys = {url_key(current.url), url_key(current.novelupdates_url), url_key(metadata.get("resolved_url"))} - {None}
        if len(keys) > 1:
            raise ValueError(f"Conflicting NU URLs: {current.title}")
        page = next((pages[key] for key in keys if key in pages), None)
        if page is not None:
            if page.get("original_language") != record["original_language"]:
                raise ValueError(f"Page language conflict: {current.title}")
            previous = metadata.get("novelupdates_page")
            if previous is None or timestamp(page) > timestamp(previous):
                metadata["novelupdates_page"] = page
        changed = metadata != (current.source_metadata or {})
        if changed:
            metadata["metadata_attached_at"] = datetime.now(timezone.utc).isoformat()
        plan.append(("update" if changed else "unchanged", current.title, current, metadata))
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preview", type=Path)
    parser.add_argument("--details", nargs="*", type=Path, default=[])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from sqlalchemy import select, text
    from sqlalchemy.exc import SQLAlchemyError
    from database import SessionLocal
    from models import Novel
    try:
        preview = json.loads(args.preview.read_text(encoding="utf-8-sig"))
        pages = load_pages(args.details)
        with SessionLocal.begin() as session:
            if args.apply:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(text("LOCK TABLE novels IN SHARE ROW EXCLUSIVE MODE"))
            else:
                session.execute(text("SET TRANSACTION READ ONLY"))
            novels = session.scalars(select(Novel)).all()
            plan = plan_updates(preview, novels, pages)
            for status, title, current, metadata in plan:
                if status != "not_in_database":
                    print(f"[{status.upper()}] #{current.id} {title}")
            if args.apply:
                for status, _, current, metadata in plan:
                    if status == "update":
                        current.source_metadata = metadata
                session.flush()
        counts = Counter(row[0] for row in plan)
        print("Summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        print("Source metadata committed. Eligibility and daily history unchanged." if args.apply else "Preview only. No database changes.")
    except SQLAlchemyError:
        parser.exit(1, "Database operation failed; no successful commit was confirmed. Rerun preview to inspect state.\n")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
