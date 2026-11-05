import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def sample_key(result):
    source_id = result["record"]["source_novel_id"]
    return hashlib.sha256(
        f"novelclue-scope-audit-v1:{source_id}".encode()
    ).hexdigest()


def valid_count(value):
    return type(value) is int and value >= 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--per-group", type=int, default=3)
    args = parser.parse_args()

    try:
        if args.per_group < 1:
            raise ValueError("--per-group must be positive.")
        if args.input.resolve() == args.output.resolve():
            raise ValueError("Input and output must be different files.")

        report = json.loads(
            args.input.read_text(encoding="utf-8-sig")
        )
        if report.get("report_type") != "external_dataset_scope_preview":
            raise ValueError("Expected an external dataset scope report.")

        included = [
            result for result in report["results"]
            if result["decision"] == "include"
        ]

        groups = defaultdict(list)
        for result in included:
            language = result["record"]["original_language"]
            groups[(language, result["rule"])].append(result)

        samples = []
        group_sizes = {}

        for (language, rule), results in sorted(groups.items()):
            group_sizes[f"{language}:{rule}"] = len(results)
            samples.extend(
                sorted(results, key=sample_key)[:args.per_group]
            )

        statistics = {}
        for language in ("zh", "ko"):
            records = [
                result["record"] for result in included
                if result["record"]["original_language"] == language
            ]
            metrics = {}

            for field, thresholds in (
                (
                    "novelupdates_reading_list_count",
                    (1000, 2500, 5000, 10000),
                ),
                (
                    "novelupdates_rating_count",
                    (50, 100, 250, 500),
                ),
            ):
                values = [
                    record.get(field) for record in records
                    if valid_count(record.get(field))
                ]
                metrics[field] = {
                    "known": len(values),
                    "unknown": len(records) - len(values),
                    "at_least": {
                        str(threshold): sum(
                            value >= threshold for value in values
                        )
                        for threshold in thresholds
                    },
                }

            statistics[language] = {
                "included": len(records),
                "metrics": metrics,
            }

        output = {
            "report_type": "dataset_scope_audit",
            "rules_version": report["rules_version"],
            "source_provenance": report.get("source_provenance"),
            "sampling_method": (
                "Deterministic SHA-256 ordering by source ID, "
                "sampled separately for each language and inclusion rule."
            ),
            "popularity_filter_applied": False,
            "group_sizes": group_sizes,
            "statistics": statistics,
            "samples": samples,
        }

        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(output, file, ensure_ascii=False, indent=2)
            file.write("\n")

        print(f"Included novels: {len(included)}")
        print(f"Sampled novels: {len(samples)}")

        for language, stats in statistics.items():
            print(f"\n{language}: {stats['included']} included")
            for field, metric in stats["metrics"].items():
                print(f"  {field}")
                print(
                    f"    known={metric['known']}, "
                    f"unknown={metric['unknown']}"
                )
                for threshold, count in metric["at_least"].items():
                    print(f"    >= {threshold}: {count}")

        print(f"\nSaved audit: {args.output}")
        print("Diagnostic only. No eligibility or database changes.")

    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()