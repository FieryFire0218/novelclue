import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def canonical_url(value):
    if not isinstance(value, str):
        raise ValueError("A resolved canonical URL is required.")
    p = urlsplit(value)
    if (p.scheme not in {"http", "https"}
            or p.netloc not in {"novelupdates.com", "www.novelupdates.com"}
            or not re.fullmatch(r"/series/[^/]+/?", p.path)
            or p.query or p.fragment):
        raise ValueError(f"Invalid canonical series URL: {value!r}")
    result = "https://www.novelupdates.com" + p.path.rstrip("/") + "/"
    if len(result) > 500:
        raise ValueError("Series URL exceeds the database field length.")
    return result


def string_list(record, field, required=False):
    values = record.get(field)
    if not isinstance(values, list) or any(
        not isinstance(v, str) or not v.strip() for v in values
    ):
        raise ValueError(f"Invalid {field} for {record.get('source_title')!r}")
    values = list(dict.fromkeys(v.strip() for v in values))
    if required and not values:
        raise ValueError(f"Missing {field} for {record.get('source_title')!r}")
    return values


def names(record):
    keys = {normalized(record["source_title"])}
    for alias in record["associated_names"]:
        alias = alias.strip()
        abbreviation = (2 <= len(alias) <= 5 and alias.isascii()
                        and alias.isalpha() and alias.isupper())
        if not abbreviation and alias:
            keys.add(normalized(alias))
    return keys


def qualifies(record, policy):
    return (record["novelupdates_reading_list_count"] >= policy["min_reading_lists"]
            and record["novelupdates_rating_count"] >= policy["min_rating_votes"])


def prepare(payload, classify, rules_version):
    if not isinstance(payload, dict) or payload.get("report_type") != "resolved_new_novel_candidates":
        raise ValueError("Expected a resolved_new_novel_candidates staging report.")
    config = payload["pool_config"]
    if payload["rules_version"] != rules_version or config["required_scope_version"] != rules_version:
        raise ValueError("Scope version mismatch; regenerate previews first.")
    provenance = payload["source_provenance"]
    if not isinstance(provenance, dict) or not provenance.get("source_commit") or not provenance.get("input_sha256"):
        raise ValueError("Missing source commit or dataset hash.")
    for pool in ("normal", "broad"):
        for field in ("min_reading_lists", "min_rating_votes"):
            v = config[pool][field]
            if type(v) is not int or v < 0:
                raise ValueError("Invalid pool threshold.")
    for field in ("min_reading_lists", "min_rating_votes"):
        if config["normal"][field] < config["broad"][field]:
            raise ValueError("Normal requirements must be at least as strict as broad.")
    verified = set()
    for pair in config.get("verified_distinct_pairs", []):
        ids = pair["source_ids"]
        if len(ids) != 2 or any(type(v) is not int or v <= 0 for v in ids) or ids[0] == ids[1] or not pair.get("reason"):
            raise ValueError("Invalid verified-distinct exception.")
        verified.add(frozenset(ids))
    candidates = payload["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("No candidates provided.")
    prepared, ids, urls = [], set(), set()
    timestamp = datetime.now(timezone.utc).isoformat()
    for candidate in candidates:
        record = candidate["record"]
        source_id = candidate["source_novel_id"]
        if type(source_id) is not int or source_id <= 0 or source_id != record["source_novel_id"]:
            raise ValueError("Invalid or inconsistent source ID.")
        url = canonical_url(candidate["novelupdates_url"])
        if source_id in ids or url in urls:
            raise ValueError("Duplicate source ID or URL in batch.")
        ids.add(source_id)
        urls.add(url)
        title = record["source_title"]
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 255:
            raise ValueError("Invalid or oversized title.")
        authors = string_list(record, "authors", required=True)
        aliases = string_list(record, "associated_names")
        genres = string_list(record, "genres", required=True)
        string_list(record, "tags")
        if len(authors[0]) > 255:
            raise ValueError(f"Author display label too long: {title}")
        if record["original_language"] not in {"zh", "ko"} or record.get("warnings"):
            raise ValueError(f"Unsupported language or source warnings: {title}")
        for field in ("novelupdates_reading_list_count", "novelupdates_rating_count"):
            v = record[field]
            if type(v) is not int or not 0 <= v <= 2147483647:
                raise ValueError(f"Invalid {field}: {title}")
        decision, rule, reasons = classify(record)
        if decision != "include" or not qualifies(record, config["broad"]):
            raise ValueError(f"Candidate no longer qualifies: {title}")
        normal = qualifies(record, config["normal"])
        if candidate.get("broad_candidate") is not True or candidate.get("normal_candidate") is not normal:
            raise ValueError(f"Stale eligibility flags: {title}")
        keys = names({**record, "associated_names": aliases})
        metadata = {
            "importer_version": "dataset-insert-v1", "source_novel_id": source_id,
            "source_provenance": provenance, "pool_config": config,
            "scope_rules_version": rules_version, "scope_rule": rule,
            "scope_reasons": reasons, "broad_candidate": True,
            "normal_candidate": normal, "imported_at": timestamp,
            "author_display_policy": "first source entry; not a canonical author identity",
            "record": record, "resolved_url": url,
        }
        values = {
            "title": title.strip(), "url": url, "novelupdates_url": url,
            "author": authors[0], "translator": None, "rating": None,
            "chapters": None, "genres": genres,
            "original_language": record["original_language"],
            "synopsis": None, "daily_eligible": False,
            "novelupdates_reading_list_count": record["novelupdates_reading_list_count"],
            "novelupdates_rating_count": record["novelupdates_rating_count"],
            "source_metadata": metadata,
        }
        prepared.append({"source_id": source_id, "keys": keys, "values": values})
    for i, left in enumerate(prepared):
        for right in prepared[i + 1:]:
            same_title = normalized(left["values"]["title"]) == normalized(right["values"]["title"])
            distinct = frozenset((left["source_id"], right["source_id"])) in verified
            if same_title or (left["keys"] & right["keys"] and not distinct):
                raise ValueError("Unresolved title/alias overlap within batch.")
    return prepared


def existing_urls(novel):
    result = set()
    for field in ("url", "novelupdates_url"):
        try:
            result.add(canonical_url(novel.get(field)))
        except ValueError:
            pass
    return result


def make_plan(prepared, novels):
    plan = []
    for item in prepared:
        values = item["values"]
        url = values["novelupdates_url"]
        hits = []
        for novel in novels:
            metadata = novel.get("source_metadata") or {}
            source_match = metadata.get("source_novel_id") == item["source_id"]
            url_match = url in existing_urls(novel)
            title_match = normalized(novel["title"]) in item["keys"]
            if source_match or url_match or title_match:
                hits.append((novel, source_match, url_match))
        status, reason = "insert", "New title and URL; daily_eligible=False."
        if len(hits) > 1:
            status, reason = "conflict", "Identity evidence points to multiple database records."
        elif hits:
            novel, source_match, url_match = hits[0]
            metadata = novel.get("source_metadata") or {}
            old_id = metadata.get("source_novel_id")
            if old_id is not None and old_id != item["source_id"]:
                status, reason = "conflict", "Existing source ID differs."
            elif novel.get("original_language") not in {None, values["original_language"]}:
                status, reason = "conflict", "Existing original language differs."
            elif url_match:
                status, reason = "exists", "Canonical URL already present; leave existing record unchanged."
            else:
                status, reason = "conflict", "Title/alias or source ID matches, but canonical URL is unconfirmed."
        plan.append({**item, "status": status, "reason": reason,
                     "database_ids": [hit[0]["id"] for hit in hits]})
    return plan


def show(plan):
    for item in plan:
        v = item["values"]
        print(f"[{item['status'].upper()}] {v['title']}")
        print(f"  Author display: {v['author']}; URL: {v['url']}")
        print(f"  {item['reason']} Database IDs: {item['database_ids']}")
    counts = Counter(item["status"] for item in plan)
    print("Summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


def execute(prepared, apply=False):
    from sqlalchemy import select, text
    from database import SessionLocal
    from models import Novel

    fields = ("id", "title", "url", "novelupdates_url", "original_language", "source_metadata")
    with SessionLocal.begin() as session:
        if apply:
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            session.execute(text("LOCK TABLE novels IN SHARE ROW EXCLUSIVE MODE"))
        else:
            session.execute(text("SET TRANSACTION READ ONLY"))
        columns = [getattr(Novel, field) for field in fields]
        novels = [dict(row) for row in session.execute(select(*columns)).mappings()]
        plan = make_plan(prepared, novels)
        show(plan)
        if any(item["status"] == "conflict" for item in plan):
            raise ValueError("Resolve conflicts first. No records saved.")
        inserts = [item for item in plan if item["status"] == "insert"]
        if apply:
            for item in inserts:
                session.add(Novel(**item["values"]))
            session.flush()
    return len(inserts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from sqlalchemy.exc import SQLAlchemyError
    from preview_novel_scope import RULES_VERSION, classify
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
        prepared = prepare(payload, classify, RULES_VERSION)
        inserted = execute(prepared, args.apply)
        if args.apply:
            print(f"Committed {inserted} new novels. Existing records unchanged; new daily eligibility is false.")
        else:
            print("Preview only. No database changes were made.")
    except SQLAlchemyError:
        parser.exit(1, "Database operation failed; no successful commit was confirmed. "
                    "Check migrations/connectivity and rerun the preview to inspect state.\n")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
