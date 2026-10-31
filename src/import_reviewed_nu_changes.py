
import argparse
from hashlib import sha256
import json
from pathlib import Path

from preview_nu_field_changes import build, load_inputs

REVIEWED_HASH = "e6d210135a97ce5355f9a94f1cc454e650a7d717555ecfee7abdc95e30f1197d"


def load_review(folder):
    report = json.loads((folder / "nu_field_changes_preview.json").read_text(encoding="utf-8-sig"))
    data = json.dumps(report, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    if sha256(data).hexdigest() != REVIEWED_HASH:
        raise ValueError("The field preview differs from the reviewed file.")
    return report


def check_live(report, fresh_rows, initial_count):
    if report["database_records"] != initial_count or report["results"] != fresh_rows:
        raise ValueError("The live database no longer reproduces the reviewed preview. Generate a fresh preview.")


def verify_saved(actions, saved, initial_count):
    if len(saved) != initial_count + sum(row["action"] == "insert" for row in actions):
        raise ValueError("Unexpected final novel count.")
    by_source = {}
    for novel in saved:
        source = (novel["source_metadata"] or {}).get("source_novel_id")
        if source is not None:
            by_source.setdefault(source, []).append(novel)
    for row in actions:
        source = row["source_novel_id"]
        matches = by_source.get(source, [])
        if len(matches) != 1:
            raise ValueError(f"Expected one saved novel for source {source}.")
        novel = matches[0]
        if row["action"] == "insert":
            expected = row["values"]
        else:
            if novel["id"] != row["target_id"]:
                raise ValueError(f"Unexpected target for source {source}.")
            expected = {key: change["after"] for key, change in row["changes"].items()}
        if any(novel[key] != value for key, value in expected.items()):
            raise ValueError(f"Saved values differ for source {source}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--apply", action="store_true", help="Commit the verified import.")
    args = parser.parse_args()
    report = load_review(args.data_dir)
    inputs = load_inputs(args.data_dir)
    from sqlalchemy import insert, select, text, update
    from database import SessionLocal
    from models import Novel
    table = Novel.__table__
    with SessionLocal.begin() as session:
        if args.apply:
            session.execute(text("SET LOCAL lock_timeout = '5s'"))
            session.execute(text("LOCK TABLE novels IN SHARE ROW EXCLUSIVE MODE"))
        else:
            session.execute(text("SET TRANSACTION READ ONLY"))
        initial = list(session.execute(select(table)).mappings())
        rows = build(*inputs, initial)
        check_live(report, rows, len(initial))
        if not args.apply:
            print("Verified 1,381 inserts and 114 updates against the live database (read-only).")
            return
        for row in rows:
            if row["action"] == "update":
                values = {k: delta["after"] for k, delta in row["changes"].items()}
                result = session.execute(update(table).where(table.c.id == row["target_id"]).values(**values))
                if result.rowcount != 1:
                    raise ValueError(f"Unexpected update count for source {row['source_novel_id']}.")
        inserts = [r["values"] for r in rows if r["action"] == "insert"]
        session.execute(insert(table), inserts)
        saved = list(session.execute(select(table)).mappings())
        verify_saved(rows, saved, len(initial))
    print(f"Committed {len(inserts):,} inserts and {len(rows)-len(inserts)} updates. Verified {len(saved):,} novels.")


if __name__ == "__main__":
    main()
