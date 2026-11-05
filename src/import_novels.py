import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from database import Base, SessionLocal, engine
from models import Novel, DailyAnswer


# Locate the existing JSON dataset.
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "novels.json"


def import_novels():

    Base.metadata.create_all(bind=engine)

    # load the existing novel dataset
    with open(DATA_PATH, "r", encoding="utf-8") as file:
        novels = json.load(file)

    with SessionLocal.begin() as session:
        for novel in novels:
            statement = insert(Novel).values(
                title=novel["title"],
                url=novel["url"],
                author=novel["author"],
                translator=novel["translator"],
                rating=novel["rating"],
                chapters=novel["chapters"],
                genres=novel["genres"],
            )

            # Update the existing novel when the URL already exists instead of inserting twice
            statement = statement.on_conflict_do_update(
                index_elements=[Novel.url],
                set_={
                    "title": statement.excluded.title,
                    "author": statement.excluded.author,
                    "translator": statement.excluded.translator,
                    "rating": statement.excluded.rating,
                    "chapters": statement.excluded.chapters,
                    "genres": statement.excluded.genres,
                    "updated_at": func.now(),
                },
            )

            session.execute(statement)

    with SessionLocal() as session:
        total = session.scalar(
            select(func.count()).select_from(Novel)
        )

    print(f"Processed {len(novels)} novels.")
    print(f"Total novels in PostgreSQL: {total}")


if __name__ == "__main__":
    import_novels()
