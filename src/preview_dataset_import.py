import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from preview_dataset_scope import validate
from preview_novelupdates_import import load_novels, normalize_title


def validate_config(config):
    for pool in ("normal", "broad"):
        for field in ("min_reading_lists", "min_rating_votes"):
            value = config[pool][field]
            if type(value) is not int or value < 0:
                raise ValueError(f"Invalid {pool}.{field}")

    for field in ("min_reading_lists", "min_rating_votes"):
        if config["normal"][field] < config["broad"][field]:
            raise ValueError("Normal must be at least as strict as broad.")
        
    pairs = config.get("verified_distinct_pairs", [])
    if not isinstance(pairs, list):
        raise ValueError("verified_distinct_pairs must be a list.")

    for pair in pairs:
        if not isinstance(pair, dict):
            raise ValueError("Each verified pair must be an object.")

        ids = pair.get("source_ids")
        if (
            not isinstance(ids, list)
            or len(ids) != 2
            or any(type(value) is not int or value <= 0 for value in ids)
            or ids[0] == ids[1]
        ):
            raise ValueError("Each verified pair needs two distinct positive IDs.")

        reason = pair.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Each verified pair needs a reason.")


def qualifies(record, requirements):
    fields = {
        "novelupdates_reading_list_count": "min_reading_lists",
        "novelupdates_rating_count": "min_rating_votes",
    }
    return all(
        type(record.get(field)) is int
        and record[field] >= requirements[minimum]
        for field, minimum in fields.items()
    )


def title_keys(record):
    aliases = record.get("associated_names") or []
    if not isinstance(aliases, list) or any(
        not isinstance(alias, str) for alias in aliases
    ):
        raise ValueError("associated_names must be a string list.")

    # always retain the primary title, even if it is short.
    keys = {normalize_title(record["source_title"])}

    for alias in aliases:
        alias = alias.strip()
        if not alias:
            continue

        # short uppercase Latin aliases are often ambiguous abbreviations.
        # preserve them in metadata, but don't use them as identity evidence.
        abbreviation = (
            2 <= len(alias) <= 5
            and alias.isascii()
            and alias.isalpha()
            and alias.isupper()
        )
        if abbreviation:
            continue

        keys.add(normalize_title(alias))

    return keys


def build_preview(scope, config, novels):
    verified_distinct = {
        frozenset(pair["source_ids"]): pair["reason"]
        for pair in config.get("verified_distinct_pairs", [])
    }

    database_titles = defaultdict(set)
    database_by_id = {}

    for novel in novels:
        database_titles[normalize_title(novel["title"])].add(novel["id"])
        database_by_id[novel["id"]] = novel

    selected = [
        item for item in scope["results"]
        if item["decision"] == "include"
        and qualifies(item["record"], config["broad"])
    ]

    # detect overlapping names within the eligible source batch too
    source_titles = defaultdict(set)
    for item in selected:
        record = item["record"]
        for key in title_keys(record):
            source_titles[key].add(record["source_novel_id"])

    results = []
    target_counts = Counter()

    for item in selected:
        record = item["record"]
        source_id = record["source_novel_id"]
        keys = title_keys(record)

        matches = set()
        source_collisions = set()
        for key in keys:
            matches.update(database_titles.get(key, set()))
            source_collisions.update(source_titles[key] - {source_id})

        notes = []

        for other_id in sorted(source_collisions):
            pair = frozenset((source_id, other_id))
            if pair in verified_distinct:
                notes.append(
                    f"Verified distinct from source ID {other_id}: "
                    + verified_distinct[pair]
                )

        source_collisions = {
            other_id for other_id in source_collisions
            if frozenset((source_id, other_id)) not in verified_distinct
        }

        status = "new_candidate"
        target = None

        if source_collisions:
            status = "conflict"
            notes.append(
                "Overlapping titles/aliases with source IDs: "
                + ", ".join(map(str, sorted(source_collisions)))
            )

        if len(matches) > 1:
            status = "conflict"
            notes.append("Titles/aliases match multiple database novels.")
        elif len(matches) == 1:
            target = next(iter(matches))
            target_counts[target] += 1
            existing = database_by_id[target]
            if status != "conflict":
                status = "matched"

            old_language = existing.get("original_language")
            if old_language and old_language != record["original_language"]:
                status = "conflict"
                notes.append("Original language conflicts with database.")

            notes.append(
                "Exact normalized title/alias match; "
                "no database fields will be overwritten."
            )

        blockers = []
        if not matches:
            if not record.get("novelupdates_url"):
                blockers.append("Canonical series URL unresolved.")
            if not record.get("authors"):
                blockers.append("Author unavailable.")

        results.append({
            "status": status,
            "source_novel_id": source_id,
            "source_title": record["source_title"],
            "database_novel_id": target,
            "database_title": (
                database_by_id[target]["title"] if target is not None else None
            ),
            "database_match_candidates": sorted(matches),
            "scope_rule": item["rule"],
            "scope_reasons": item["reasons"],
            "broad_candidate": True,
            "normal_candidate": qualifies(record, config["normal"]),
            "activation": "unchanged",
            "notes": notes,
            "new_record_blockers": blockers,
            "record": record,
        })

    for result in results:
        target = result["database_novel_id"]
        if target is not None and target_counts[target] > 1:
            result["status"] = "conflict"
            result["notes"].append(
                "Multiple source records target the same database novel."
            )

    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        if args.output.resolve() in {
            args.input.resolve(), args.config.resolve()
        }:
            raise ValueError("Output must differ from both input files.")
        if args.output.exists():
            raise ValueError("Output exists; choose a new output filename.")

        scope = json.loads(args.input.read_text(encoding="utf-8-sig"))
        config = json.loads(args.config.read_text(encoding="utf-8-sig"))

        if scope.get("report_type") != "external_dataset_scope_preview":
            raise ValueError("Expected the external dataset scope report.")
        if scope["rules_version"] != config["required_scope_version"]:
            raise ValueError("Scope version does not match configuration.")

        validate_config(config)
        validate([item["record"] for item in scope["results"]])

        # this helper explicitly starts a PostgreSQL READ ONLY transaction.
        novels = load_novels()
        results = build_preview(scope, config, novels)

        statuses = Counter({
            "matched": 0,
            "new_candidate": 0,
            "conflict": 0,
        })
        statuses.update(result["status"] for result in results)

        normal_count = sum(result["normal_candidate"] for result in results)

        report = {
            "report_type": "external_dataset_import_preview",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_provenance": scope.get("source_provenance"),
            "rules_version": scope["rules_version"],
            "pool_config": config,
            "summary": {
                "database_records": len(novels),
                "broad_candidates": len(results),
                "normal_candidates": normal_count,
                "matching": dict(statuses),
            },
            "results": results,
        }

        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, indent=2)
            file.write("\n")

        print(f"Database records: {len(novels)}")
        print(f"Broad candidates: {len(results)}")
        print(f"Normal candidates: {normal_count}")
        for status, count in statuses.items():
            print(f"{status}: {count}")

        print(f"Saved: {args.output}")
        print("Preview only. No database or daily eligibility changes.")

    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()