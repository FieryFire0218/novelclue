import argparse

from sqlalchemy import select

from database import SessionLocal
from models import Novel


LANGUAGE_LABELS = {
    "chinese": "zh",
    "korean": "ko",
}


def clean_metadata(apply=False):
    changed = 0
    missing_genres = 0

    with SessionLocal() as session:
        novels = session.scalars(
            select(Novel).order_by(Novel.id)
        ).all()

        for novel in novels:
            original_genres = novel.genres

            if not isinstance(original_genres, list) or not all(
                isinstance(value, str) for value in original_genres
            ):
                raise ValueError(
                    f"Invalid genres for novel {novel.id}: {novel.title}"
                )

            detected_languages = {
                LANGUAGE_LABELS[value.strip().casefold()]
                for value in original_genres
                if value.strip().casefold() in LANGUAGE_LABELS
            }

            if len(detected_languages) > 1:
                raise ValueError(
                    f"Conflicting language labels: {novel.title}"
                )

            detected_language = next(iter(detected_languages), None)
            current_language = novel.original_language

            if (
                detected_language
                and current_language
                and detected_language != current_language
            ):
                raise ValueError(
                    f"Language conflicts with existing value: {novel.title}"
                )

            new_language = current_language or detected_language

            # Remove language labels, whitespace, and duplicate genres.
            cleaned_genres = []
            seen = set()

            for value in original_genres:
                genre = value.strip()
                key = genre.casefold()

                if not genre or key in LANGUAGE_LABELS or key in seen:
                    continue

                cleaned_genres.append(genre)
                seen.add(key)

            if not cleaned_genres:
                missing_genres += 1

            if (
                new_language == current_language
                and cleaned_genres == original_genres
            ):
                continue

            changed += 1

            print(f"\n{novel.id}: {novel.title}")
            print(f"  Language: {current_language!r} -> {new_language!r}")
            print(f"  Genres: {original_genres!r} -> {cleaned_genres!r}")

            if apply:
                novel.original_language = new_language
                novel.genres = cleaned_genres

        if apply:
            session.commit()

        print(f"\nNovels needing changes: {changed}")
        print(f"Novels without actual genres: {missing_genres}")
        print("Changes saved." if apply else "Preview only. Nothing saved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Separate novel languages from genre labels."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Save changes. Without this flag, only preview them.",
    )
    args = parser.parse_args()

    clean_metadata(apply=args.apply)