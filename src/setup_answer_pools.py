import argparse
from sqlalchemy import text, update
from answer_pools import pool_ids
from models import LanguageDailyAnswer, Novel
from database import SessionLocal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal.begin() as session:
        if args.apply:
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            session.execute(text("LOCK TABLE novels IN SHARE ROW EXCLUSIVE MODE"))
        else:
            session.execute(text("SET TRANSACTION READ ONLY"))
        activate = []
        for lang in ("zh", "ko"):
            normal = list(session.scalars(pool_ids(lang, "normal", require_activation=False)))
            hard = list(session.scalars(pool_ids(lang, "hard")))
            active = set(session.scalars(pool_ids(lang, "normal")))
            activate.extend(set(normal) - active)
            print(f"{lang}: normal {len(normal)}, hard {len(hard)}, already active {len(active)}")
        if args.apply:
            LanguageDailyAnswer.__table__.create(session.connection(), checkfirst=True)
            if activate:
                session.execute(update(Novel).where(Novel.id.in_(activate)).values(daily_eligible=True))
    print(f"{'Activated' if args.apply else 'Would activate'} {len(activate)} additional daily answers.")


if __name__ == "__main__":
    main()
