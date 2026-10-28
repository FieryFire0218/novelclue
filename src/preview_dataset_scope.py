import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from preview_novel_scope import RULES_VERSION, classify


def validate(records):
    if not isinstance(records, list):
        raise ValueError("records must be a list.")

    seen = set()

    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Each record must be an object.")

        source_id = record.get("source_novel_id")
        if (
            isinstance(source_id, bool)
            or not isinstance(source_id, int)
            or source_id <= 0
        ):
            raise ValueError("Each record needs a positive source_novel_id.")

        if source_id in seen:
            raise ValueError(f"Duplicate source ID: {source_id}")
        seen.add(source_id)

        title = record.get("source_title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"{source_id}: missing title.")

        if record.get("original_language") not in {"zh", "ko"}:
            raise ValueError(f"{source_id}: unexpected language.")

        for field in ("genres", "tags", "warnings"):
            value = record.get(field)
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                raise ValueError(f"{source_id}: invalid {field}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        if args.input.resolve() == args.output.resolve():
            raise ValueError("Input and output must be different files.")

        prepared = json.loads(
            args.input.read_text(encoding="utf-8-sig")
        )
        if (
            not isinstance(prepared, dict)
            or prepared.get("report_type") != "external_novel_metadata"
        ):
            raise ValueError("Expected the prepared external dataset report.")

        records = prepared.get("records")
        validate(records)

        totals = Counter({"include": 0, "defer": 0, "exclude": 0})
        by_language = {
            language: Counter({"include": 0, "defer": 0, "exclude": 0})
            for language in ("zh", "ko")
        }
        by_rule = Counter()
        results = []

        for record in records:
            decision, rule, reasons = classify(record)
            totals[decision] += 1
            by_language[record["original_language"]][decision] += 1
            by_rule[rule] += 1

            results.append({
                "decision": decision,
                "rule": rule,
                "reasons": reasons,
                "record": record,
            })

        report = {
            "report_type": "external_dataset_scope_preview",
            "rules_version": RULES_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_provenance": {
                key: prepared.get(key)
                for key in (
                    "source_repository",
                    "source_commit",
                    "dataset_version",
                    "dataset_reported_update_date",
                    "input_sha256",
                    "adapter_version",
                )
            },
            "popularity_filter_applied": False,
            "summary": dict(totals),
            "by_language": {
                key: dict(value) for key, value in by_language.items()
            },
            "by_rule": dict(by_rule),
            "results": results,
        }

        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, indent=2)
            file.write("\n")

        print(f"Rules: {RULES_VERSION}")
        print(f"Evaluated: {len(records)}")
        for language, counts in by_language.items():
            print(f"{language}: " + ", ".join(
                f"{key}={value}" for key, value in counts.items()
            ))

        print("\nBy rule:")
        for rule, count in sorted(by_rule.items()):
            print(f"  {rule}: {count}")

        print("\nNo popularity cutoff applied.")
        print(f"Saved: {args.output}")
        print("No database changes were made.")

    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()