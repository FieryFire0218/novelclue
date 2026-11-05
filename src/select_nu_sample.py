import json
from pathlib import Path


INPUT = Path("data/nu_candidates_browser.json")
OUTPUT = Path("data/nu_sample_candidates.json")
PER_LANGUAGE = 3


def main():
    candidates = json.loads(INPUT.read_text(encoding="utf-8"))
    selected = []

    for language in ("zh", "ko"):
        pool = [
            novel
            for novel in candidates
            if novel["original_language"] == language
        ]

        pool.sort(
            key=lambda novel: (
                -novel["listing_readers"],
                novel["novelupdates_url"],
            )
        )

        if len(pool) < PER_LANGUAGE:
            raise ValueError(f"Not enough candidates for {language}")

        selected.extend(pool[:PER_LANGUAGE])

    with OUTPUT.open("x", encoding="utf-8") as file:
        json.dump(selected, file, ensure_ascii=False, indent=2)
        file.write("\n")

    for novel in selected:
        print(
            f"{novel['original_language']} | "
            f"{novel['source_title']} | "
            f"{novel['listing_readers']:,} readers"
        )

    print(f"\nSaved {len(selected)} candidates to {OUTPUT}")


if __name__ == "__main__":
    main()