import argparse
import json
from pathlib import Path


def select_sample(records, per_language):
    unique = {}

    for record in records:
        url = record.get("novelupdates_url")
        if not isinstance(url, str) or not url:
            raise ValueError("Each candidate needs a novelupdates_url.")

        language = record.get("original_language")
        if language not in {"zh", "ko"}:
            continue

        readers = record.get("listing_readers")
        if (
            isinstance(readers, bool)
            or not isinstance(readers, int)
            or readers < 0
        ):
            raise ValueError(f"Missing or invalid listing_readers: {url}")

        if url in unique and unique[url] != record:
            raise ValueError(f"Conflicting duplicate candidate: {url}")

        unique[url] = record

    selected = []

    for language in ("zh", "ko"):
        candidates = sorted(
            (
                record for record in unique.values()
                if record["original_language"] == language
            ),
            key=lambda record: (
                -record["listing_readers"],
                record["novelupdates_url"],
            ),
        )

        count = min(per_language, len(candidates))

        if count <= 1:
            picks = candidates[:count]
        else:
            indexes = [
                i * (len(candidates) - 1) // (count - 1)
                for i in range(count)
            ]
            picks = [candidates[index] for index in indexes]

        selected.extend(picks)

    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--per-language", type=int, default=10)
    args = parser.parse_args()

    try:
        if args.per_language < 1:
            raise ValueError("--per-language must be positive.")
        if args.input.resolve() == args.output.resolve():
            raise ValueError("Input and output must be different files.")

        records = json.loads(args.input.read_text(encoding="utf-8-sig"))
        if not isinstance(records, list) or any(
            not isinstance(record, dict) for record in records
        ):
            raise ValueError("Input must be a JSON list of candidate objects.")

        selected = select_sample(records, args.per_language)
        if not selected:
            raise ValueError("No Chinese or Korean candidates found.")

        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(selected, file, ensure_ascii=False, indent=2)
            file.write("\n")

        for record in selected:
            print(
                f"{record['original_language']} | "
                f"{record['listing_readers']} readers | "
                f"{record.get('source_title', record['novelupdates_url'])}"
            )

        print(f"\nSaved {len(selected)} candidates to {args.output}")

    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()