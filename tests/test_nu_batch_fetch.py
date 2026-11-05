import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import fetch_novelupdates_batch as batch
from page_provenance import write_cache
from test_nu_id_fetch import HTML, URL


def row(sid, normal=True):
    return dict(source_novel_id=sid, normal_candidate=normal, next_action='resolve_url')

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audit = self.root/'audit.json'
        self.cache = self.root/'cache'
        self.output = self.root/'batch1.json'
        self.rows = [row(1, False), row(2), row(3), row(4)]
        self.write_audit()

    def write_audit(self):
        self.audit.write_text(json.dumps(dict(report_type='novel_readiness_audit', results=self.rows)))

    def cache_id(self, sid):
        write_cache(batch.cache_path(self.cache, batch.lookup_url(sid)),
                    HTML.replace('value="3453"', f'value="{sid}"'), URL,
                    '2026-10-01T00:00:00+00:00')

    def fake_collect(self, ids, cache, browser, **kwargs):
        records=[]
        for sid in ids:
            if batch.cached_record(cache, sid) is None: self.cache_id(sid)
            record=batch.cached_record(cache, sid)
            kwargs['on_record'](sid, record)
            records.append(record)
        return records

    def run_batch(self, **kwargs):
        return batch.run(self.audit, self.cache, self.output, self.root, **kwargs)

    def test_normal_first_skip_cache_then_next_batch(self):
        self.cache_id(2)
        with patch.object(batch, 'collect', side_effect=self.fake_collect) as collect:
            records=self.run_batch(limit=2)
            self.assertEqual(collect.call_args.args[0], [3,4])
            self.assertEqual([r['source_novel_id'] for r in records],[3,4])
            self.output=self.root/'batch2.json'
            self.run_batch(limit=2)
            self.assertEqual(collect.call_args.args[0], [1])

    def test_interruption_pins_batch_and_resumes(self):
        def interrupted(ids, cache, browser, **kwargs):
            self.cache_id(ids[0])
            kwargs['on_record'](ids[0],batch.cached_record(cache,ids[0]))
            raise KeyboardInterrupt()
        with patch.object(batch,'collect',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):self.run_batch(limit=2)
        self.assertFalse(self.output.exists())
        state_path=Path(str(self.output)+'.progress.json')
        state=json.loads(state_path.read_text())
        self.assertEqual(state['status'],'stopped')
        self.assertEqual(state['completed_ids'],[2])
        with patch.object(batch,'collect',side_effect=self.fake_collect) as collect:
            self.run_batch(limit=1)
            self.assertEqual(collect.call_args.args[0],[2,3])
        self.assertEqual(json.loads(state_path.read_text())['status'],'complete')

    def test_changed_audit_rejected_on_resume(self):
        with patch.object(batch,'collect',side_effect=ValueError('blocked')):
            with self.assertRaises(ValueError):self.run_batch()
        self.rows.append(row(5));self.write_audit()
        with patch.object(batch,'collect') as collect:
            with self.assertRaisesRegex(ValueError,'different audit'):self.run_batch()
            collect.assert_not_called()

    def test_invalid_configuration(self):
        for kw in [dict(limit=0),dict(limit=21),dict(delay=0),dict(delay=float('nan')),dict(delay=float('inf'))]:
            with self.subTest(kw=kw), self.assertRaises(ValueError):self.run_batch(**kw)

    def test_corrupt_cache_stops_before_browser(self):
        self.cache_id(2)
        batch.cache_path(self.cache,batch.lookup_url(2)).write_text('bad')
        with patch.object(batch,'collect') as collect:
            with self.assertRaises(ValueError):self.run_batch()
            collect.assert_not_called()

    def test_existing_output_preserved(self):
        self.output.write_text('keep')
        with self.assertRaises(ValueError):self.run_batch()
        self.assertEqual(self.output.read_text(),'keep')

    def test_duplicate_ids_rejected(self):
        self.rows.append(row(2));self.write_audit()
        with self.assertRaises(ValueError):self.run_batch()

    def test_all_cached_no_browser(self):
        for r in self.rows:self.cache_id(r['source_novel_id'])
        with patch.object(batch,'collect') as collect:
            self.assertEqual(self.run_batch(),[])
            collect.assert_not_called()

    def test_profile_option_and_delay(self):
        from types import SimpleNamespace
        import fetch_novelupdates as fetch
        from test_nu_id_fetch import ImmediateWait
        driver=SimpleNamespace(title='Example', current_url=URL, page_source=HTML,
            get=lambda _:None, set_page_load_timeout=lambda _:None,
            find_elements=lambda *_:[1],quit=lambda:None)
        options=SimpleNamespace()
        with patch('selenium.webdriver.FirefoxOptions',return_value=options), patch(
                'selenium.webdriver.Firefox',return_value=driver), patch(
                'selenium.webdriver.support.ui.WebDriverWait',ImmediateWait), patch(
                'fetch_novelupdates.time.sleep') as sleep:
            fetch.collect([3453,3453],self.cache,'firefox',refresh=True,
                          firefox_profile=self.root,delay=10)
        self.assertEqual(options.profile,str(self.root.resolve()))
        sleep.assert_called_once_with(10)

if __name__=='__main__':unittest.main()
