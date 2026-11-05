import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path

from import_dataset_candidates import canonical_url
from page_provenance import choose_page
from preview_collected_novels import preview
from preview_dataset_import import qualifies
from preview_novel_scope import classify

EXPECTED = {
    "nu_reviewed_identity_plan": "7b2c252af481b5e8efdcf43d5cf180b16c2d84a8eebeb7efe3944be3f4ff92f5",
    "nu_scope_refreshed": "bcf3c62f568eec7c6c5f6287857e94aae4962f20772a80e18717a217520e873d",
    "nu_preview_pool_config": "7a1a5ea1dab97670b7362cd723d78f2c2f8d2c59fda17d1ea9d26dfa73e24dc0",
}
COUNTS = ("novelupdates_reading_list_count", "novelupdates_rating_count")


def load_inputs(folder):
    inputs = []
    for name, expected_hash in EXPECTED.items():
        value = json.loads((folder / (name + ".json")).read_text(encoding="utf-8-sig"))
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        if sha256(encoded).hexdigest() != expected_hash:
            raise ValueError(f"{name}.json differs from the reviewed version.")
        inputs.append(value)
    raw = (folder / "nu_current_db_preview.json").read_bytes()
    if sha256(raw).hexdigest() != inputs[0]["database_preview_sha256"]:
        raise ValueError("The original database identity preview differs from the reviewed file.")
    return (*inputs, json.loads(raw))


def retained_claims(novels):
    owners = defaultdict(set)
    for novel in novels:
        meta = novel["source_metadata"] or {}
        claims = [meta, meta.get("record") or {}, meta.get("novelupdates_page") or {}]
        for claim in claims:
            if claim.get("source_novel_id") is not None:
                owners[("id", str(claim["source_novel_id"]))].add(novel["id"])
        for url in [meta.get("resolved_url"), *(r.get("novelupdates_url") for r in claims)]:
            if url:
                owners[("url", canonical_url(url))].add(novel["id"])
    return owners


def proposed_fields(record, current, config, rules_version):
    meta = dict(current.get("source_metadata") or {})
    previous = meta.get("novelupdates_page")
    selected, reason = choose_page(previous, record)
    decision, rule, reasons = classify(selected)
    if decision != "include" or not qualifies(selected, config["broad"]):
        raise ValueError("Retained page requires a fresh scope or popularity review.")
    url = record["novelupdates_url"]
    meta.update(source_novel_id=record["source_novel_id"], resolved_url=url,
                novelupdates_page=selected, pool_config=config, scope_rules_version=rules_version,
                scope_rule=rule, scope_reasons=reasons, normal_candidate=qualifies(selected, config["normal"]),
                broad_candidate=True)
    fields = dict(source_metadata=meta, novelupdates_url=url)
    if not current:
        fields.update(title=record["source_title"], url=url, author=record["authors"][0],
                      translator=None, rating=None, chapters=None, daily_eligible=False)
    for key in ("genres", "original_language", "synopsis"):
        if not current.get(key) and selected.get(key):
            fields[key] = selected[key]
    for key in COUNTS:
        if selected.get(key) is not None and (selected.get("fetched_at") or current.get(key) is None):
            fields[key] = selected[key]
    if not current and (len(fields["title"]) > 255 or len(fields["author"]) > 255):
        raise ValueError("Display title or author exceeds the database field length.")
    return fields, reason


def build(plan, scope, config, original, novels):
    fresh = {r["source_novel_id"]: r for r in preview(scope, config, novels)}
    old = {r["source_novel_id"]: r for r in original["results"]}
    records = {i["record"]["source_novel_id"]: i["record"] for i in scope["results"]}
    if fresh.keys() != old.keys() or set(fresh) != {r["source_novel_id"] for r in plan["results"]}:
        raise ValueError("Candidate set changed. Regenerate the identity review.")
    targets = {n["id"]: n for n in novels}
    exceptions = {i["source_novel_id"]: i["evidence"] for i in plan["reviewed_exceptions"]}
    owners = retained_claims(novels)
    results = []
    for item in plan["results"]:
        sid = item["source_novel_id"]
        target = item["target_id"]
        record = records[sid]
        row = dict(source_novel_id=sid, title=record["source_title"], target_id=target)
        results.append(row)
        try:
            if fresh[sid] != old[sid]:
                raise ValueError("Live identity evidence changed since review.")
            current = targets[target] if target is not None else {}
            url = record["novelupdates_url"]
            if (owners["id", str(sid)] | owners["url", url]) - {target}:
                raise ValueError("Another row claims this identity in retained metadata.")
            meta = current.get("source_metadata") or {}
            for claim in (meta, meta.get("record") or {}, meta.get("novelupdates_page") or {}):
                if claim.get("source_novel_id") not in (None, sid):
                    raise ValueError("Retained source ID differs.")
                for key in ("resolved_url", "novelupdates_url"):
                    if claim.get(key) and canonical_url(claim[key]) != url:
                        raise ValueError("Retained source URL differs.")
            if current.get("novelupdates_url") and canonical_url(current["novelupdates_url"]) != url:
                raise ValueError("Current series URL differs.")
            if sid in exceptions:
                evidence = exceptions[sid]
                catalog = targets[evidence["database_id"]]
                if sid in (3604, 4214) and (catalog.get("source_metadata") or {}).get("source_novel_id") != 3604:
                    raise ValueError("Dragon War God no longer has the reviewed source ID.")
                if (catalog["author"] != evidence["archive_author"] or
                        catalog["url"] != evidence["archive_url"]):
                    raise ValueError("Author or catalog URL differs from the reviewed evidence.")
            fields, reason = proposed_fields(record, current, config, scope["rules_version"])
            row["page_selection"] = reason
            if current:
                changes = {k: {"before": current[k], "after": v}
                           for k, v in fields.items() if current[k] != v}
                row.update(action="update" if changes else "unchanged", changes=changes)
            else:
                row.update(action="insert", values=fields)
        except (KeyError, ValueError, TypeError) as error:
            row.update(action="hold", reason=str(error))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("data/nu_field_changes_preview.json"))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a fresh --output filename.")
    inputs = load_inputs(args.data_dir)
    from sqlalchemy import select, text
    from database import SessionLocal
    from models import Novel
    with SessionLocal.begin() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        novels = [dict(r) for r in session.execute(select(Novel.__table__)).mappings()]
    rows = build(*inputs, novels)
    counts = dict(Counter(row["action"] for row in rows))
    report = dict(report_type="novelclue_read_only_field_preview", database_records=len(novels),
                  summary=counts, identity_plan_hash=EXPECTED["nu_reviewed_identity_plan"], results=rows)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(f"{counts}\nSaved {args.output}")


if __name__ == "__main__":
    main()
