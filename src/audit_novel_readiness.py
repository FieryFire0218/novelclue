import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from attach_novelupdates_metadata import plan_updates, url_key
from novel_metadata import game_data


def build_report(preview, novels):
    plan = plan_updates(preview, novels, {})
    rows = []
    for item, (_, _, novel, _) in zip(preview['results'], plan):
        record = item['record']
        metadata = (novel.source_metadata or {}) if novel is not None else {}
        url = None
        if novel is not None:
            url = url_key(novel.novelupdates_url) or url_key(metadata.get('resolved_url')) or url_key(novel.url)
        # a source record may already contain a canonical URL; never invent a slug.
        url = url or url_key(record.get('novelupdates_url'))
        data = game_data(novel) if novel is not None else {}
        missing = []
        if novel is not None:
            if not data.get('author'): missing.append('author')
            if not data.get('genres'): missing.append('genres')
            if data.get('rating') is None: missing.append('rating')
            if data.get('chapters') is None: missing.append('chapter_total')
            if data.get('publication_status') == 'unknown': missing.append('publication_status')
        action = ('resolve_url' if not url else 'stage_import') if novel is None else (
            'resolve_url' if not url else 'enrich_metadata' if missing else 'no_metadata_gap')
        rows.append({
            'source_novel_id': item['source_novel_id'],
            'source_title': record['source_title'],
            'original_language': record['original_language'],
            'normal_candidate': bool(item.get('normal_candidate')),
            'database_novel_id': novel.id if novel is not None else None,
            'novelupdates_url': url,
            'next_action': action,
            'missing_game_fields': missing,
            'reading_lists': record.get('novelupdates_reading_list_count'),
            'rating_votes': record.get('novelupdates_rating_count'),
            'page_fetched_at': (metadata.get('novelupdates_page') or {}).get('fetched_at'),
        })
    # stable source-snapshot popularity ordering, not an assertion of current popularity.
    def count(value):
        return value if type(value) is int and value >= 0 else -1
    rows.sort(key=lambda r: (not r['normal_candidate'], -count(r['reading_lists']), -count(r['rating_votes']), r['source_novel_id']))
    summary = dict(Counter(r['next_action'] for r in rows))
    return {'report_type': 'novel_readiness_audit', 'generated_at': datetime.now(timezone.utc).isoformat(),
            'source_provenance': preview['source_provenance'], 'pool_config': preview['pool_config'],
            'summary': summary, 'existing_candidates': sum(r['database_novel_id'] is not None for r in rows),
            'missing_candidates': sum(r['database_novel_id'] is None for r in rows),
            'results': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('preview', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    if args.output.resolve() == args.preview.resolve():
        parser.error('Output must not overwrite input.')
    if args.output.exists() and not args.overwrite:
        parser.error('Output exists; choose a new filename or use --overwrite.')
    from sqlalchemy import select, text
    from database import SessionLocal
    from models import Novel
    preview = json.loads(args.preview.read_text(encoding='utf-8-sig'))
    with SessionLocal.begin() as session:
        session.execute(text('SET TRANSACTION READ ONLY'))
        report = build_report(preview, session.scalars(select(Novel)).all())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w' if args.overwrite else 'x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f"Candidates in database: {report['existing_candidates']}")
    print(f"Candidates outside database: {report['missing_candidates']}")
    for key, value in sorted(report['summary'].items()): print(f'{key}: {value}')
    print(f'Saved: {args.output}')
    print('Read-only audit. No network requests or database changes.')


if __name__ == '__main__':
    main()
