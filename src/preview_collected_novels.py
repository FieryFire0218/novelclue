import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from import_dataset_candidates import canonical_url, existing_urls, normalized
from preview_dataset_import import build_preview, title_keys, validate_config
from preview_dataset_scope import validate
from preview_novel_scope import RULES_VERSION, classify, validate_records


def load_database():
    from sqlalchemy import select, text
    from database import SessionLocal
    from models import Novel

    with SessionLocal.begin() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        fields = (Novel.id, Novel.title, Novel.url, Novel.novelupdates_url,
                  Novel.original_language, Novel.source_metadata)
        return [dict(row) for row in session.execute(select(*fields)).mappings()]


def preview(scope, config, novels):
    if (scope.get("report_type") != "novel_scope_preview"
            or scope["rules_version"] != RULES_VERSION
            or config["required_scope_version"] != RULES_VERSION):
        raise ValueError("Scope report and project classifier must use the configured version.")
    records = [item["record"] for item in scope["results"]]
    validate(records)
    validate_records(records)
    validate_config(config)
    for item in scope["results"]:
        if classify(item["record"])[:2] != (item["decision"], item["rule"]):
            raise ValueError("Scope classification changed. Regenerate the scope report.")
    candidates = build_preview(scope, config, [])  # Source alias collisions only.
    by_id = {novel["id"]: novel for novel in novels}
    urls, sources, titles = defaultdict(set), defaultdict(set), defaultdict(set)
    for novel in novels:
        nid = novel["id"]
        titles[normalized(novel["title"])].add(nid)
        for url in existing_urls(novel):
            urls[url].add(nid)
        source = (novel.get("source_metadata") or {}).get("source_novel_id")
        if source is not None:
            sources[source].add(nid)

    rows = []
    targets = Counter()
    for item in candidates:
        r = item["record"]
        sid = r["source_novel_id"]
        url = canonical_url(r["novelupdates_url"])
        strong = urls[url] | sources[sid]
        named = set().union(*(titles[key] for key in title_keys(r)))
        hits = sorted(strong | named)
        targets.update(hits)
        notes = list(item["notes"])
        issues = []
        if item["status"] == "conflict":
            issues.append("Overlapping source titles or aliases.")
        if len(hits) > 1:
            issues.append("Evidence points to multiple database novels.")
        for nid in hits:
            novel = by_id[nid]
            old_id = (novel.get("source_metadata") or {}).get("source_novel_id")
            old_urls = existing_urls(novel)
            if old_id not in (None, sid):
                issues.append("Stored source ID differs.")
            if (old_urls - {url}) or (novel["novelupdates_url"] and url not in old_urls):
                issues.append("Stored series URL needs review.")
            if novel["original_language"] not in (None, r["original_language"]):
                issues.append("Original languages differ.")
        status = ("conflict" if issues else "matched" if strong else
                  "review_title_match" if named else "new_candidate")
        rows.append(dict(source_novel_id=sid, source_title=r["source_title"],
                         novelupdates_url=url, scope_rule=item["scope_rule"],
                         normal_candidate=item["normal_candidate"], status=status,
                         database_candidates=[{"id":n, "title":by_id[n]["title"]} for n in hits],
                         source_id_matches=sorted(sources[sid]), url_matches=sorted(urls[url]),
                         title_matches=sorted(named), notes=notes+issues,
                         missing_chapters=r["original_chapters_total"] is None,
                         unknown_status=r["publication_status"]=="unknown",
                         observation_time=r.get("fetched_at")))
    for row in rows:
        if any(targets[n["id"]] > 1 for n in row["database_candidates"]):
            row["status"] = "conflict"
            row["notes"].append("Multiple candidate novels point to this database row.")
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scope", type=Path, default=Path("data/nu_scope_refreshed.json"))
    p.add_argument("--config", type=Path, default=Path("data/nu_preview_pool_config.json"))
    p.add_argument("--output", type=Path, default=Path("data/nu_current_db_preview.json"))
    args = p.parse_args()
    if args.output.exists():
        p.error("Output already exists. Choose a new filename with --output.")
    scope, config = (json.loads(path.read_text(encoding="utf-8-sig")) for path in (args.scope,args.config))
    novels = load_database()
    rows = preview(scope, config, novels)
    counts = dict(Counter(r["status"] for r in rows))
    report = dict(report_type="collected_novel_identity_preview", rules_version=RULES_VERSION,
                  generated_at=datetime.now(timezone.utc).isoformat(), database_records=len(novels),
                  scope_summary=scope["summary"], pool_config=config, summary=counts, results=rows)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Checked {len(rows)} candidates against {len(novels)} database novels.")
    print(counts)
    print(f"Saved {args.output}. Database transaction was read-only.")


if __name__ == "__main__":
    main()
