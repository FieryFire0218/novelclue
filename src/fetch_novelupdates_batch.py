import argparse
import hashlib
import json
import math
from pathlib import Path
from datetime import datetime, timezone

from fetch_novelupdates import (atomic_write, cache_path, collect, lookup_url,
                               normalize_url, read_cache, validate_id_page)


def save(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def candidates(audit):
    if not isinstance(audit, dict) or audit.get('report_type') != 'novel_readiness_audit':
        raise ValueError('Expected a novel_readiness_audit report.')
    rows = audit.get('results')
    if not isinstance(rows, list):
        raise ValueError('Audit results must be a list.')
    seen = set()
    eligible = []
    for row in rows:
        sid = row.get('source_novel_id')
        if type(sid) is not int or sid <= 0 or sid in seen:
            raise ValueError('Audit has an invalid or duplicate source ID.')
        seen.add(sid)
        if type(row.get('normal_candidate')) is not bool:
            raise ValueError('Audit has an invalid normal_candidate flag.')
        if row.get('next_action') in {'resolve_url', 'stage_import', 'enrich_metadata'}:
            eligible.append(row)
    # preserve audit order within each pool. The audit already ranks candidates.
    return sorted(eligible, key=lambda row: not row['normal_candidate'])


def cached_record(cache, sid):
    path = cache_path(cache, lookup_url(sid))
    if not path.exists():
        return None
    html, date, url = read_cache(path)
    record = validate_id_page(html, sid, path.name, date)
    if url and normalize_url(url) != record['novelupdates_url']:
        raise ValueError(f'Cache URL metadata mismatch for ID {sid}.')
    return record


def run(audit_path, cache, output, profile, limit=20, delay=10):
    if not 1 <= limit <= 20:
        raise ValueError('Batch size must be between 1 and 20.')
    if not math.isfinite(delay) or delay < 5:
        raise ValueError('Delay must be finite and at least 5 seconds.')
    if not profile.is_dir():
        raise ValueError('Firefox profile directory does not exist.')
    state_path = Path(str(output) + '.progress.json')
    if output.suffix.lower() != '.json':
        raise ValueError('Output must be a JSON file.')
    if audit_path.resolve() in {output.resolve(), state_path.resolve()}:
        raise ValueError('Output and progress paths must differ from the audit.')
    if output.exists():
        raise ValueError('Output already exists. Use a new output filename for the next batch.')
    raw = audit_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    rows = candidates(json.loads(raw.decode('utf-8-sig')))
    context = {'audit_sha256': digest, 'cache': str(cache.resolve())}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state.get('report_type') != 'novelupdates_batch_progress' or state.get('context') != context:
            raise ValueError('Progress belongs to a different audit or cache; use a new output filename.')
        ids = state.get('selected_ids')
        allowed = {row['source_novel_id'] for row in rows}
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 20
                or any(type(i) is not int or i not in allowed for i in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError('Invalid saved batch IDs.')
        print(f'Resuming saved batch of {len(ids)} novels; saved selection takes precedence over --limit.')
    else:
        ids = []
        skipped = 0
        for row in rows:
            sid = row['source_novel_id']
            if cached_record(cache, sid) is not None:
                skipped += 1
                continue
            ids.append(sid)
            if len(ids) == limit:
                break
        print(f'Already cached before selection: {skipped}; selected: {len(ids)}')
        if not ids:
            print('No uncached candidates remain for the checked audit actions.')
            return []
        state = {'report_type': 'novelupdates_batch_progress', 'context': context,
                 'selected_ids': ids}
    # the cache, not progress flags, is the authority when resuming.
    state.update(status='running', completed_ids=[])
    save(state_path, state)
    def checkpoint(sid, record):
        state['completed_ids'].append(sid)
        state['updated_at'] = datetime.now(timezone.utc).isoformat()
        save(state_path, state)
    try:
        records = collect(ids, cache, 'firefox', firefox_profile=profile,
                          delay=delay, on_record=checkpoint)
        save(output, records)
    except BaseException:
        state['status'] = 'stopped'
        save(state_path, state)
        raise
    state['status'] = 'complete'
    save(state_path, state)
    print(f'Saved {len(records)} records to {output}')
    print('No database changes. Use a NEW output filename for the next batch.')
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audit', type=Path)
    parser.add_argument('--cache', type=Path, default=Path('data/nu_id_test_cache'))
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--firefox-profile', required=True, type=Path)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--delay', type=float, default=10)
    args = parser.parse_args()
    try:
        run(args.audit, args.cache, args.output, args.firefox_profile, args.limit, args.delay)
    except KeyboardInterrupt:
        parser.exit(130, 'Stopped. Rerun the same command to resume the saved batch.\n')
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'Error: {error}\nRerun the same command after resolving the problem.\n')


if __name__ == '__main__':
    main()
