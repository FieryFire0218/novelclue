from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import fetch_novelupdates as fetch
from page_provenance import read_cache, write_cache

URL = 'https://www.novelupdates.com/series/example/'
HTML = '''<link rel="canonical" href="https://www.novelupdates.com/series/example/">
<input id="mypostid" value="3453">
<div class="seriestitlenu">Example</div><div id="showlang">Chinese</div>
<div id="seriesgenre"><a class="genre">Xianxia</a></div>
<div id="showtags"><a class="genre">Cultivation</a></div>
<div id="showauthors"><a>Author</a></div><div id="editassociated">Alias</div>
<div id="editdescription">An example synopsis.</div>
<span class="uvotes">(4.3 / 5.0, 100 votes)</span><b class="rlist">2,500</b>
<div id="editstatus">100 Chapters (Completed)</div>'''

class ImmediateWait:
    def __init__(self, driver, timeout): self.driver = driver
    def until(self, fn, **kwargs):
        from selenium.common.exceptions import TimeoutException
        if not fn(self.driver): raise TimeoutException('Test challenge')

class IDFetchTests(unittest.TestCase):
    def test_valid_id_and_metadata(self):
        r = fetch.validate_id_page(HTML, 3453, 'test.html')
        self.assertEqual(r['source_novel_id'], 3453)
        self.assertEqual(r['novelupdates_url'], URL)
        self.assertEqual(r['synopsis'], 'An example synopsis.')
        self.assertEqual(r['publication_status'], 'completed')

    def test_identity_rejections(self):
        for h in (HTML.replace('value="3453"', 'value="1"'),
                  HTML.replace('<input id="mypostid" value="3453">', ''),
                  HTML + '<input id="mypostid" value="3453">',
                  HTML.replace(URL, 'https://example.com/series/example/'),
                  '<title>Just a moment...</title>'):
            with self.subTest(html=h), self.assertRaises(ValueError):
                fetch.validate_id_page(h, 3453, 'test.html')

    def test_url_mode_still_validates_canonical(self):
        self.assertEqual(fetch.validate_page(HTML, URL, 'test.html')['novelupdates_url'], URL)
        with self.assertRaises(ValueError):
            fetch.validate_page(HTML, URL.replace('example', 'other'), 'test.html')

    def test_cache_reuse_preserves_timestamp_without_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            path = fetch.cache_path(cache, fetch.lookup_url(3453))
            write_cache(path, HTML, URL, '2026-10-01T00:00:00+00:00')
            with patch('selenium.webdriver.Firefox') as browser:
                records = fetch.collect([3453], cache, 'firefox')
            browser.assert_not_called()
            self.assertEqual(records[0]['fetched_at'], '2026-10-01T00:00:00+00:00')

    def test_cache_metadata_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            write_cache(fetch.cache_path(cache, fetch.lookup_url(3453)), HTML,
                        URL.replace('example', 'other'), '2026-10-01T00:00:00+00:00')
            with self.assertRaises(ValueError): fetch.collect([3453], cache, 'firefox')

    def driver(self, get):
        return SimpleNamespace(title='Example', current_url=URL, page_source=HTML,
            get=get, set_page_load_timeout=lambda _: None,
            find_elements=lambda *_: [1], quit=lambda: None)

    def test_live_lookup_saves_canonical_and_id(self):
        visited = []
        driver = self.driver(visited.append)
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            with patch('selenium.webdriver.Firefox', return_value=driver), patch(
                'selenium.webdriver.support.ui.WebDriverWait', ImmediateWait):
                records = fetch.collect([3453], cache, 'firefox')
            self.assertEqual(visited, ['https://www.novelupdates.com/?p=3453'])
            self.assertEqual(records[0]['source_novel_id'], 3453)
            _, date, canonical = read_cache(fetch.cache_path(cache, visited[0]))
            self.assertIsNotNone(date)
            self.assertEqual(canonical, URL)

    def test_challenge_stops_and_retains_first_page(self):
        visited = []
        def get(url):
            visited.append(url)
            if len(visited) == 2: driver.title = 'Just a moment...'
        driver = self.driver(get)
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            with patch('selenium.webdriver.Firefox', return_value=driver), patch(
                'selenium.webdriver.support.ui.WebDriverWait', ImmediateWait), patch('fetch_novelupdates.time.sleep'):
                with self.assertRaisesRegex(ValueError, 'Collection stopped'):
                    fetch.collect([3453, 1846, 999], cache, 'firefox')
            self.assertEqual(len(visited), 2)
            self.assertTrue(fetch.cache_path(cache, fetch.lookup_url(3453)).exists())
            self.assertFalse(fetch.cache_path(cache, fetch.lookup_url(1846)).exists())

    def test_invalid_cli_inputs_never_collect(self):
        for args in (['--ids', '0'], ['--ids', '1', '1'],
                     ['--ids', '1', '2', '3', '4', '5', '6'],
                     ['input.json', '--ids', '1'], []):
            with self.subTest(args=args), patch.object(sys, 'argv',
                ['fetch_novelupdates.py', *args, '--output', 'test-output.json']), patch.object(fetch, 'collect') as collect:
                with self.assertRaises(SystemExit): fetch.main()
                collect.assert_not_called()

if __name__ == '__main__': unittest.main()
