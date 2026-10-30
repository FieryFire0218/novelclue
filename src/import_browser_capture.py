import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
from fetch_novelupdates import validate_id_page, atomic_write, normalize_url
from page_provenance import read_cache, write_cache, fetch_time


def prepare(payload):
    if (not isinstance(payload, dict) or payload.get('report_type') != 'novelclue_browser_capture'
            or payload.get('version') != 1):
        raise ValueError('Expected a version 1 NovelClue browser capture.')
    rows=payload.get('records')
    if not isinstance(rows,list) or not 1 <= len(rows) <= 10000:
        raise ValueError('Expected a nonempty records array (maximum 10,000).')
    seen=set(); urls=set(); prepared=[]
    for row in rows:
        sid=row.get('source_novel_id')
        if type(sid) is not int or sid <= 0 or sid in seen:
            raise ValueError('Invalid or duplicate source ID.')
        seen.add(sid)
        if row.get('capture_format') != 'novelclue_metadata_fragment_v1':
            raise ValueError('Unsupported capture format.')
        html=row.get('html')
        if not isinstance(html,str) or not html or len(html)>1000000:
            raise ValueError('Missing or oversized metadata fragment.')
        date=fetch_time(row.get('captured_at'))
        if date is None or date > datetime.now(timezone.utc)+timedelta(minutes=5):
            raise ValueError('Missing or future capture timestamp.')
        # content-addressed filenames preserve prior observations and allow retries.
        digest=hashlib.sha256((str(sid)+'\n'+date.isoformat()+'\n'+html).encode()).hexdigest()
        name=f'extension-{digest}.html'
        record=validate_id_page(html,sid,name,fetched_at=date.isoformat())
        canonical=normalize_url(row.get('novelupdates_url'))
        if canonical != record['novelupdates_url'] or canonical in urls:
            raise ValueError('Canonical URL mismatch or one URL assigned to multiple IDs.')
        urls.add(canonical)
        record['capture_format']=row['capture_format']
        prepared.append((name,html,record))
    return prepared


def convert(source, cache, output):
    if source.resolve()==output.resolve() or output.exists():
        raise ValueError('Choose a new output file distinct from the capture input.')
    payload=json.loads(source.read_text(encoding='utf-8-sig'))
    prepared=prepare(payload)  # validate every record before writing any caches.
    for name,html,record in prepared:
        path=cache/name
        if path.exists():
            old,date,url=read_cache(path)
            if (old != html.encode('utf-8') or date != record['fetched_at']
                    or url != record['novelupdates_url']):
                raise ValueError(f'Existing cache differs: {path}')
    for name,html,record in prepared:
        path=cache/name
        if not path.exists():write_cache(path,html,record['novelupdates_url'],record['fetched_at'])
    records=[r for _,_,r in prepared]
    atomic_write(output,json.dumps(records,ensure_ascii=False,indent=2)+'\n')
    for r in records:
        print(f"VALIDATED: #{r['source_novel_id']} {r['source_title']} | chapters={r.get('original_chapters_total')} | status={r.get('publication_status')}")
    print(f'Saved {len(records)} parsed records to {output}')
    print('No network requests or database changes. Capture time is observation time, not publication time.')
    return records


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path)
    p.add_argument('--cache',type=Path,default=Path('data/nu_browser_cache'))
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    try:convert(args.input,args.cache,args.output)
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as e:p.exit(1,f'Error: {e}\n')

if __name__=='__main__':main()
