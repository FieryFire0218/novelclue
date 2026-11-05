import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from audit_novel_readiness import build_report


def preview():
    rows = []
    for i in (1, 2):
        record = dict(source='shaido987/novel-dataset', source_novel_id=i, source_title=f'Novel {i}',
                      original_language='zh', associated_names=[], authors=['Author'], genres=['Xianxia'],
                      warnings=[], novelupdates_reading_list_count=1000*i, novelupdates_rating_count=100)
        rows.append(dict(source_novel_id=i, source_title=record['source_title'], status='new_candidate',
                         normal_candidate=(i == 1), broad_candidate=True, record=record))
    return dict(report_type='external_dataset_import_preview', source_provenance={'source_commit':'test'},
                pool_config={}, rules_version='scope-v3', results=rows)


class ReadinessTests(unittest.TestCase):
    def test_missing_and_priority(self):
        r = build_report(preview(), [])
        self.assertEqual(r['missing_candidates'], 2)
        self.assertEqual(r['summary'], {'resolve_url': 2})
        self.assertEqual(r['results'][0]['source_novel_id'], 1)

    def test_existing_source_id_overrides_old_preview(self):
        p = preview()
        n = SimpleNamespace(id=42, title='Novel 1', url='https://www.novelupdates.com/series/example/',
             novelupdates_url=None, original_language='zh', author='Author', genres=['Xianxia'],
             source_metadata={'source_novel_id':1, 'record':p['results'][0]['record']})
        before = copy.deepcopy(vars(n))
        r = build_report(p, [n])
        self.assertEqual(r['existing_candidates'], 1)
        self.assertEqual(r['results'][0]['next_action'], 'enrich_metadata')
        self.assertIn('publication_status', r['results'][0]['missing_game_fields'])
        self.assertEqual(vars(n), before)

    def test_known_source_url(self):
        p = preview()
        p['results'][0]['record']['novelupdates_url'] = 'https://www.novelupdates.com/series/example/'
        self.assertEqual(build_report(p, [])['results'][0]['next_action'], 'stage_import')

    def test_conflict_rejected(self):
        p = preview(); p['results'][0]['status'] = 'conflict'
        with self.assertRaises(ValueError): build_report(p, [])


if __name__ == '__main__': unittest.main()
