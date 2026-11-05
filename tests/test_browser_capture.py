from pathlib import Path
import sys,json,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from import_browser_capture import prepare,convert
HTML='''<link rel="canonical" href="https://www.novelupdates.com/series/example/">
<input id="mypostid" value="4052"><div class="seriestitlenu">Example</div>
<div id="showlang">Chinese</div><div id="seriesgenre"><a class="genre">Xianxia</a></div>
<div id="showtags"><a class="genre">Cultivation</a></div><div id="showauthors"><a>Author</a></div>
<div id="editdescription"><p>First paragraph.</p><p>Second paragraph.</p></div>
<span class="uvotes">(4.3 / 5.0, 100 votes)</span><b class="rlist">2,500</b>
<div id="editstatus">149 Chapters + 5 Extras (Completed)</div>'''
def payload():return dict(report_type='novelclue_browser_capture',version=1,records=[dict(
    source_novel_id=4052,novelupdates_url='https://www.novelupdates.com/series/example/',
    capture_format='novelclue_metadata_fragment_v1',captured_at='2026-10-01T00:00:00+00:00',html=HTML)])
class CaptureTests(unittest.TestCase):
    def test_parse_fragment(self):
        r=prepare(payload())[0][2]
        self.assertEqual(r['original_chapters_total'],154)
        self.assertEqual(r['authors'],['Author'])
        self.assertEqual(r['synopsis'],'First paragraph.\n\nSecond paragraph.')
    def test_invalid_id(self):
        p=payload();p['records'][0]['source_novel_id']=42
        with self.assertRaises(ValueError):prepare(p)
    def test_bad_canonical(self):
        p=payload();p['records'][0]['novelupdates_url']='https://example.com/series/example/'
        with self.assertRaises(ValueError):prepare(p)
    def test_duplicates(self):
        p=payload();p['records']*=2
        with self.assertRaises(ValueError):prepare(p)
    def test_timestamps(self):
        for value in [None,'2026-10-01','2999-01-01T00:00:00Z']:
            p=payload();p['records'][0]['captured_at']=value
            with self.subTest(value=value),self.assertRaises(ValueError):prepare(p)
    def test_challenge(self):
        p=payload();p['records'][0]['html']='<title>Just a moment...</title>'
        with self.assertRaises(ValueError):prepare(p)
    def test_roundtrip_and_repeat_preserves_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'capture.json';source.write_text(json.dumps(payload()))
            r=convert(source,root/'cache',root/'out.json')
            files=list((root/'cache').glob('*'));times={f:f.stat().st_mtime_ns for f in files}
            again=convert(source,root/'cache',root/'out2.json')
            self.assertEqual(r[0]['fetched_at'],again[0]['fetched_at'])
            self.assertEqual(r[0]['html_sha256'],again[0]['html_sha256'])
            self.assertEqual(times,{f:f.stat().st_mtime_ns for f in files})
            with self.assertRaises(ValueError):convert(source,root/'cache',root/'out.json')
    def test_invalid_batch_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=payload();p['records'].append(dict(p['records'][0],source_novel_id=1))
            source=root/'capture.json';source.write_text(json.dumps(p))
            with self.assertRaises(ValueError):convert(source,root/'cache',root/'out.json')
            self.assertFalse((root/'cache').exists())
if __name__=='__main__':unittest.main()
