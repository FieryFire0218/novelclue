import argparse
import json
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


RULES_VERSION = "scope-v2"


def normalize(value):
    return " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )


def terms(*values):
    return {normalize(value) for value in values}


CULTIVATION_GENRES = terms("Wuxia", "Xianxia", "Xuanhuan")

CULTIVATION_TAGS = terms(
    "Cultivation",
    "Fast Cultivation",
    "Demonic Cultivation Technique",
    "Heavenly Tribulation",
)

SYSTEM_SETTINGS = terms(
    "Dungeons", "Hunters", "Tower Climbing", "Battle Academy",
)

PROGRESSION = terms(
    "Level System",
    "Skill Assimilation",
    "Skill Books",
    "Game Ranking System",
    "Weak to Strong",
)

ACADEMIES = terms("Academy", "Battle Academy")

FANTASY_WORLD = terms(
    "Fantasy World",
    "Sword And Magic",
    "Magic",
    "Elemental Magic",
    "Magic Beasts",
    "Magic Formations",
    "Dragons",
    "Mythical Beasts",
    "Necromancer",
    "Spirit Users",
)

FANTASY_GENRES = terms("Fantasy", "Supernatural")
ADVENTURE_GENRES = terms("Action", "Adventure")

CULTIVATION_SUPPORT = terms(
    "Dao Comprehension",
    "Pill Based Cultivation",
    "Multiple Realms",
    "Immortals",
    "Magic Formations",
    "Spirit Stones",
    "Sect Development",
)

VIRTUAL_WORLD = terms("MMORPG", "Virtual Reality")


def matching(values, expected):
    return sorted(
        {value for value in values if normalize(value) in expected},
        key=str.casefold,
    )


def classify(record):
    language = record.get("original_language")

    if language is None:
        return "defer", "missing_language", [
            "Original language is unavailable."
        ]

    if language not in {"zh", "ko"}:
        return "exclude", "language", [
            "Original language is outside Chinese/Korean scope."
        ]

    if record.get("warnings"):
        return "defer", "source_warnings", [
            "Resolve source parsing warnings before automatic inclusion.",
            *record["warnings"],
        ]

    genres = record.get("genres") or []
    tags = record.get("tags") or []

    cultivation_genres = matching(genres, CULTIVATION_GENRES)
    cultivation_tags = matching(tags, CULTIVATION_TAGS)
    cultivation_support = matching(tags, CULTIVATION_SUPPORT)

    if cultivation_genres:
        return "include", "cultivation_genre", [
            "Cultivation or martial-world genres: "
            + ", ".join(cultivation_genres)
        ]

    if cultivation_tags and (
        cultivation_support or len(cultivation_tags) >= 2
    ):
        return "include", "cultivation_world", [
            "Cultivation evidence: " + ", ".join(cultivation_tags),
            "Supporting evidence: "
            + ", ".join(cultivation_support or cultivation_tags),
        ]

    fantasy = matching(genres, FANTASY_GENRES)
    adventure = matching(genres, ADVENTURE_GENRES)
    settings = matching(tags, SYSTEM_SETTINGS)
    progression = matching(tags, PROGRESSION)
    academies = matching(tags, ACADEMIES)
    world = matching(tags, FANTASY_WORLD)
    virtual_world = matching(tags, VIRTUAL_WORLD)

    if fantasy and adventure and virtual_world and progression:
        return "include", "virtual_world_progression", [
            "Fantasy/adventure genres: " + ", ".join(fantasy + adventure),
            "Virtual-world evidence: " + ", ".join(virtual_world),
            "Progression evidence: " + ", ".join(progression),
        ]

    if fantasy and settings and progression:
        return "include", "fantasy_system", [
            "Fantasy genres: " + ", ".join(fantasy),
            "Setting evidence: " + ", ".join(settings),
            "Progression evidence: " + ", ".join(progression),
        ]

    if fantasy and academies and len(world) >= 2:
        return "include", "fantasy_academy", [
            "Academy evidence: " + ", ".join(academies),
            "Fantasy-world evidence: " + ", ".join(world),
        ]

    if fantasy and adventure and len(world) >= 2:
        return "include", "fantasy_adventure", [
            "Adventure genres: " + ", ".join(adventure),
            "Fantasy-world evidence: " + ", ".join(world),
        ]

    reasons = [
        "Insufficient evidence for automatic thematic inclusion.",
        "Deferred novels remain outside playable pools; no review is required.",
    ]
    if not tags:
        reasons.append("Tags are missing or empty.")
    if settings:
        reasons.append("Possible setting evidence: " + ", ".join(settings))
    if progression:
        reasons.append(
            "Possible progression evidence: " + ", ".join(progression)
        )
    if world:
        reasons.append("Possible fantasy evidence: " + ", ".join(world))

    return "defer", "insufficient_evidence", reasons


def validate_records(records):
    if not isinstance(records, list):
        raise ValueError("Input must be a JSON list of detail records.")

    seen_urls = set()

    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Every record must be an object.")

        for field in ("source_title", "novelupdates_url"):
            value = record.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Each record needs a nonempty {field}.")

        url = record["novelupdates_url"]
        if url in seen_urls:
            raise ValueError(f"Duplicate novelupdates_url: {url}")
        seen_urls.add(url)

        language = record.get("original_language")
        if language is not None and not isinstance(language, str):
            raise ValueError("original_language must be a string or null.")

        for field in ("genres", "tags"):
            if field not in record:
                raise ValueError(
                    "Use the detail preview with tags, not a candidate list."
                )
            value = record[field]
            if value is not None and (
                not isinstance(value, list)
                or any(not isinstance(item, str) for item in value)
            ):
                raise ValueError(f"{field} must be a string list or null.")

        warnings = record.get("warnings", [])
        if not isinstance(warnings, list) or any(
            not isinstance(item, str) for item in warnings
        ):
            raise ValueError("warnings must be a list of strings.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError("Input and output must be different files.")
        if args.output.exists() and not args.overwrite:
            raise ValueError("Output exists; use --overwrite to replace it.")

        records = json.loads(args.input.read_text(encoding="utf-8-sig"))
        validate_records(records)

        results = []
        counts = Counter({"include": 0, "defer": 0, "exclude": 0})

        for record in records:
            decision, rule, reasons = classify(record)
            counts[decision] += 1
            results.append({
                "decision": decision,
                "rule": rule,
                "reasons": reasons,
                "record": record,
            })

        report = {
            "report_type": "novel_scope_preview",
            "rules_version": RULES_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": dict(counts),
            "results": results,
        }

        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open(
            "w" if args.overwrite else "x", encoding="utf-8"
        ) as file:
            json.dump(report, file, ensure_ascii=False, indent=2)
            file.write("\n")

        for result in results:
            title = result["record"]["source_title"]
            print(f"\n[{result['decision'].upper()}] {title}")
            for reason in result["reasons"]:
                print(f"  {reason}")

        print("\nSummary: " + ", ".join(
            f"{status}={count}" for status, count in counts.items()
        ))
        print(f"Saved scope report to {args.output}")
        print("No database changes were made.")

    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()