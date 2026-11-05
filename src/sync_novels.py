import argparse
import json
from pathlib import Path

from sqlalchemy import select

from database import SessionLocal
from models import Novel


REQUIRED_FIELDS = {
    "title",
    "url",
    "author",
    "translator",
    "rating",
    "chapters",
    "genres",
}


def validate_novel(novel, index):
    if not isinstance(novel, dict):
        raise ValueError(f"Record {index} must be an object")

    missing = REQUIRED_FIELDS - novel.keys()

    if missing:
        raise ValueError(
            f"Record {index} missing fields: {sorted(missing)}"
        )

    for field in ["title", "url", "author", "translator"]:
        value = novel[field]

        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Record {index}: invalid {field}"
            )

    if not novel["url"].startswith(("http://", "https://")):
        raise ValueError(f"Record {index}: invalid URL")

    rating = novel["rating"]
    chapters = novel["chapters"]

    if type(rating) is not int or not 0 <= rating <= 100:
        raise ValueError(
            f"Record {index}: rating must be 0-100"
        )

    if type(chapters) is not int or chapters < 0:
        raise ValueError(
            f"Record {index}: invalid chapter count"
        )

    genres = novel["genres"]

    if not isinstance(genres, list) or not all(
        isinstance(genre, str) and genre.strip()
        for genre in genres
    ):
        raise ValueError(
            f"Record {index}: invalid genres"
        )

    return {
        field: novel[field]
        for field in REQUIRED_FIELDS
    }


def sync_novels(file_path):
    path = Path(file_path)

    with path.open("r", encoding="utf-8") as file:
        raw_novels = json.load(file)

    if not isinstance(raw_novels, list):
        raise ValueError("Expected a JSON array of novels")

    novels = [
        validate_novel(novel, index)
        for index, novel in enumerate(raw_novels, start=1)
    ]

    urls = [novel["url"] for novel in novels]
    titles = [novel["title"] for novel in novels]

    if len(urls) != len(set(urls)):
        raise ValueError("Duplicate URLs in input file")

    if len(titles) != len(set(titles)):
        raise ValueError("Duplicate titles in input file")

    inserted = 0
    updated = 0
    unchanged = 0

    with SessionLocal.begin() as session:
        existing = {
            novel.url: novel
            for novel in session.scalars(
                select(Novel).where(Novel.url.in_(urls))
            ).all()
        }

        for data in novels:
            current = existing.get(data["url"])

            if current is None:
                session.add(Novel(**data))
                inserted += 1

            elif current.to_dict() == data:
                unchanged += 1

            else:
                for field, value in data.items():
                    setattr(current, field, value)

                updated += 1

    print("Database synchronization complete!")
    print(f"Inserted: {inserted}")
    print(f"Updated: {updated}")
    print(f"Unchanged: {unchanged}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Synchronize novel JSON data with PostgreSQL"
    )

    parser.add_argument(
        "file",
        help="Path to a JSON file containing novel records",
    )

    args = parser.parse_args()

    sync_novels(args.file)
