import argparse
import json
import unicodedata
from pathlib import Path


def normalize(value):
    value = unicodedata.normalize("NFKC", value)
    return " ".join(value.casefold().split())


def terms(*values):
    return {normalize(value) for value in values}


CULTIVATION_GENRES = terms("Wuxia", "Xianxia", "Xuanhuan")

CULTIVATION_TAGS = terms(
    "Cultivation",
    "Fast Cultivation",
    "Demonic Cultivation Technique",
    "Heavenly Tribulation",
)

# require both a relevant setting and progression/combat evidence.
SETTING_TAGS = terms(
    "Battle Academy",
    "Dungeons",
    "Hunters",
    "Tower Climbing",
    "Sword And Magic",
    "Fantasy World",
)

MECHANIC_TAGS = terms(
    "Level System",
    "Skill Assimilation",
    "Skill Books",
    "Game Ranking System",
    "Weak to Strong",
    "Strategic Battles",
)

FANTASY_GENRES = terms("Fantasy", "Supernatural")


def matching(values, expected):
    return sorted(
        {value for value in values if normalize(value) in expected},
        key=str.casefold,
    )


def classify(record):
    language = record.get("original_language")

    if language not in {"zh", "ko"}:
        if language is None:
            return "review", ["Original language unavailable."]
        return "exclude", ["Original language is outside Chinese/Korean scope."]

    genres = record.get("genres") or []
    tags = record.get("tags") or []

    cultivation = (
        matching(genres, CULTIVATION_GENRES)
        + matching(tags, CULTIVATION_TAGS)
    )
    if cultivation:
        return "include", [
            "Cultivation or martial-world evidence: "
            + ", ".join(cultivation)
        ]

    settings = matching(tags, SETTING_TAGS)
    mechanics = matching(tags, MECHANIC_TAGS)
    fantasy = matching(genres, FANTASY_GENRES)

    if fantasy and settings and mechanics:
        return "include", [
            "Fantasy setting: " + ", ".join(settings),
            "Progression or combat evidence: " + ", ".join(mechanics),
        ]

    reasons = [
        "Needs synopsis review: metadata does not establish a strong scope match."
    ]
    if not tags:
        reasons.append("Tags are missing or empty.")
    if settings:
        reasons.append("Possible setting evidence: " + ", ".join(settings))
    if mechanics:
        reasons.append("Possible progression evidence: " + ", ".join(mechanics))

    return "review", reasons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()

    try:
        records = json.loads(args.input.read_text(encoding="utf-8-sig"))
        if not isinstance(records, list):
            raise ValueError("Input must be a JSON list of novel detail records.")

        # Validate the entire input before printing decisions.
        for record in records:
            if not isinstance(record, dict) or not record.get("source_title"):
                raise ValueError("Each record must contain a source_title.")
            if "genres" not in record or "tags" not in record:
                raise ValueError(
                    "Use the detail preview with tags, not the candidate list."
                )
            for field in ("genres", "tags"):
                value = record[field]
                if value is not None and (
                    not isinstance(value, list)
                    or any(not isinstance(item, str) for item in value)
                ):
                    raise ValueError(f"{field} must be a list of strings or null.")

        counts = {"include": 0, "review": 0, "exclude": 0}

        for record in records:
            status, reasons = classify(record)
            counts[status] += 1
            print(f"\n[{status.upper()}] {record['source_title']}")
            for reason in reasons:
                print(f"  {reason}")

        print("\nSummary: " + ", ".join(
            f"{status}={count}" for status, count in counts.items()
        ))
        print("Scope preview only. No database changes were made.")

    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()