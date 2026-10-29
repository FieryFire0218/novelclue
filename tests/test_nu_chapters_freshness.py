import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from chapter_status import parse_chapter_status
from page_provenance import choose_page, read_cache, write_cache, sidecar_path, content_hash
from parse_novelupdates import parse_html
from novel_metadata import game_data, snapshot_data
from compare import compare_guess
from attach_novelupdates_metadata import plan_updates


def html(status='149 Chapters + 5 Extras (Completed)'):
    return f'''<link rel="canonical" href="https://www.novelupdates.com/series/example/">
    <div class="seriestitlenu">Example</div><div id="showlang">Chinese</div>
    <div id="seriesgenre"><a class="genre">Xianxia</a></div>
    <div id="showtags"><a class="genre">Cultivation</a></div>
    <div id="showauthors"><a>Author</a></div><div id="editassociated">Alias</div>
    <div id="editdescription">An example synopsis.</div>
    <span class="uvotes">(4.3 / 5.0, 100 votes)</span><b class="rlist">2,500</b>
    <div id="editstatus">{status.replace(chr(10), '<br>')}</div>'''


class ChapterTests(unittest.TestCase):
    def check(self, raw, total, main=None, extra=None, status='completed', method=None):
        result=parse_chapter_status(raw)
        self.assertEqual(result['original_chapters_total'],total)
        self.assertEqual(result['original_chapters_main'],main)
        self.assertEqual(result['original_chapters_extra'],extra)
        self.assertEqual(result['publication_status'],status)
        if method:self.assertEqual(result['chapter_count_method'],method)
        return result

    def test_simple_statuses(self):
        for label,status in [('Completed','completed'),('Complete','completed'),('Ongoing','ongoing'),('Dropped','dropped'),('Hiatus','hiatus'),('Cancelled','cancelled')]:
            with self.subTest(label=label):self.check(f'1,648 Chapters ({label})',1648,status=status,method='reported')
        self.check('0 chapters',0,status='unknown')
        self.check('133 (Completed)',None)
        self.check('Completed',None)
        self.check('Complete\n- 143 Chapters',143)

    def test_extra_totals(self):
        self.check('149 Chapters + 5 Extras (Completed)',154,149,5,method='calculated')
        self.check('834 Chapters - Completed\n36 Extra - Completed',870,834,36,method='calculated')
        self.check('182 Chapters + 19 Extras (Completed)',201,182,19)
        self.check('98 Chapters + 2 Extras (Completed)',100,98,2)
        self.check('74 Chapters + 6 Extras (Completed)',80,74,6)
        self.check('248 Chapters + 44 Extras (Completed)',292,248,44)
        self.check('119 Chapters + 21 Extras (released with the book) + 7 Extras\n(released as of June 2023) + 2 Extras (Completed)\n149 Total Chapters',149,119,30,method='reported')

    def test_breakdown_not_added_twice(self):
        self.check('381 Chapters (Completed)\n-main story: 355 chapters (completed)\n-extra: 26 chapters (completed)',381,355,26)
        self.check('598 Chapters (Completed)\nMain Story - 573 Chapters + 25 Bonus Chapters',598,573,25)
        self.check('Main Story Chapters 212 (Complete)\nExtra Chapters 20\n(Overall Chapters 232)',232,212,20)
        self.check('16 Volumes / 400 Chapters (Completed):\n-Part 1: 287 Chapters (Completed)\n-Part 2: 113 Chapters (Completed)',400)
        self.check('1400 chapters (completed)/ 56 volumes (completed)\n- 1 season: 26 Volumes (Completed)/ 650 chapters (completed)\n- 2 season: 30 volumes (completed)/ 750 chapters (completed)',1400)

    def test_partial_and_contradictory(self):
        self.check('50 WN Chapters + 3 Side Stories / 2 Volumes (Complete)',None,50)
        self.check('118 Chapters (Completed)\n-Main Story: 118 Chapters (Completed)\n-Side Story: 62 Chapters (Completed)\n5 Volumes (Completed)\n-Main Story: 3 Volumes\n-Side Story: 1 Volume\n-Special Side Stories: 1 Volume',None,118,62)
        self.check('193 Chapters (Completed):\n⊱ Prologue\n⊱ Main Story: 170 Chapters\n⊱ Side Story: 22 Chapters\n[Split in Translation]',193,170,22)
        self.check('100 Chapters (Completed)\n-Part 1: 40 Chapters\n-Part 2: 50 Chapters',None)
        self.check('149 Chapters + 5 Extras (Completed)\n153 Total Chapters',None,149,5)
        self.check('100+ chapters (Ongoing)',None,status='ongoing')
        r=self.check('Main Story: 100 Chapters (Completed)\nSide Story: 5 Chapters (Ongoing)',105,100,5,status='unknown')
        self.assertEqual(r['main_publication_status'],'completed')

    def test_page_fields(self):
        r=parse_html(html(),'old.html')
        self.assertEqual(r['original_chapters_total'],154)
        self.assertEqual(r['novelupdates_rating_raw'],4.3)
        self.assertEqual(r['publication_status'],'completed')
        self.assertIsNone(r['fetched_at'])
        self.assertEqual(r['freshness'],'unknown')
        self.assertEqual(r['html_sha256'],content_hash(html()))


class FreshnessTests(unittest.TestCase):
    def test_fetch_then_cache_preserves_observation(self):
        from fetch_novelupdates import collect, cache_path
        driver=SimpleNamespace(title='Example',current_url='https://www.novelupdates.com/series/example/',
                               page_source=html(),set_page_load_timeout=lambda _:None,
                               get=lambda _:None,find_elements=lambda *_:[1],quit=lambda:None)
        class Wait:
            def __init__(self,*args):pass
            def until(self,fn,**kwargs):self_result=fn(driver);self.assert_dummy(self_result)
            @staticmethod
            def assert_dummy(value):
                if not value:raise RuntimeError('Page not ready')
        selenium=ModuleType('selenium')
        calls=[]
        def browser(**kwargs):calls.append(1);return driver
        selenium.webdriver=SimpleNamespace(FirefoxOptions=SimpleNamespace,ChromeOptions=SimpleNamespace,
                                          Firefox=browser,Chrome=browser)
        exceptions=ModuleType('selenium.common.exceptions')
        exceptions.TimeoutException=type('TimeoutException',(Exception,),{})
        exceptions.WebDriverException=type('WebDriverException',(Exception,),{})
        by=ModuleType('selenium.webdriver.common.by');by.By=SimpleNamespace(CSS_SELECTOR='css')
        ui=ModuleType('selenium.webdriver.support.ui');ui.WebDriverWait=Wait
        with patch.dict(sys.modules,{'selenium':selenium,'selenium.common.exceptions':exceptions,
                                     'selenium.webdriver.common.by':by,'selenium.webdriver.support.ui':ui}):
            with tempfile.TemporaryDirectory() as d:
                url=driver.current_url
                a=collect([url],Path(d),'firefox')[0]
                b=collect([url],Path(d),'firefox')[0]
                self.assertEqual(len(calls),1)
                self.assertIsNotNone(a['fetched_at'])
                self.assertEqual(a['fetched_at'],b['fetched_at'])
                self.assertEqual(a['html_sha256'],b['html_sha256'])
                self.assertTrue(sidecar_path(cache_path(Path(d),url)).exists())

    def test_cache_roundtrip_and_hash(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'page.html';p.write_text(html(),encoding='utf-8')
            self.assertIsNone(read_cache(p)[1])
            date='2026-10-28T01:00:00+00:00'
            write_cache(p,html(),'https://www.novelupdates.com/series/example/',date)
            data,observed,url=read_cache(p)
            self.assertEqual(observed,date)
            a=parse_html(data,p.name,observed)
            b=parse_html(data,p.name,observed)
            self.assertEqual(a['fetched_at'],b['fetched_at'])
            self.assertEqual(choose_page(a,b)[0],a)
            p.write_bytes(data+b'changed')
            with self.assertRaises(ValueError):read_cache(p)

    def test_unknown_age_and_older_fetch_held(self):
        old=parse_html(html(),'old.html','2026-10-27T00:00:00+00:00')
        unknown=parse_html(html('900 chapters (Ongoing)'),'unknown.html')
        unknown['parsed_at']='2099-01-01T00:00:00+00:00'
        self.assertEqual(choose_page(old,unknown)[0],old)
        older=parse_html(html('800 chapters'),'older.html','2026-10-26T00:00:00+00:00')
        self.assertEqual(choose_page(old,older)[0],old)
        newer=parse_html(html('900 chapters'),'newer.html','2026-10-28T00:00:00+00:00')
        self.assertEqual(choose_page(old,newer)[0],newer)

    def test_same_content_can_be_reparsed_without_new_age(self):
        old=parse_html(html(),'old.html','2026-10-27T00:00:00+00:00')
        old['parser_revision']=1;old.pop('original_chapters_total')
        incoming=parse_html(html(),'old.html')
        selected,reason=choose_page(old,incoming)
        self.assertEqual(selected['fetched_at'],old['fetched_at'])
        self.assertEqual(selected['original_chapters_total'],154)
        self.assertEqual(reason,'same_content_reparsed')

    def test_legacy_enrichment_does_not_replace_known_values(self):
        incoming=parse_html(html(),'old.html')
        old={k:incoming[k] for k in ['source','source_title','novelupdates_url','authors','genres','original_language','novelupdates_rating_count','novelupdates_reading_list_count']}
        selected,reason=choose_page(old,incoming)
        self.assertEqual(reason,'legacy_missing_fields_enriched')
        self.assertIsNone(selected['fetched_at'])
        conflicting=dict(incoming,novelupdates_reading_list_count=10)
        self.assertEqual(choose_page(old,conflicting)[0],old)

    def test_attachment_idempotent(self):
        source={'source':'shaido987/novel-dataset','source_novel_id':1,'source_title':'Example','associated_names':[], 'original_language':'zh','warnings':[]}
        payload={'report_type':'external_dataset_import_preview','source_provenance':{},'pool_config':{},'rules_version':'scope-v3','results':[{'source_novel_id':1,'source_title':'Example','record':source,'status':'matched','database_novel_id':5,'normal_candidate':True,'broad_candidate':True}]}
        n=SimpleNamespace(id=5,title='Example',original_language='zh',source_metadata=None,url='https://www.novelupdates.com/series/example/',novelupdates_url=None)
        page=parse_html(html(),'page.html')
        plan=plan_updates(payload,[n],{n.url:page})
        self.assertIsNone(n.source_metadata)
        n.source_metadata=plan[0][3]
        reparsed=parse_html(html(),'page.html')
        self.assertEqual(plan_updates(payload,[n],{n.url:reparsed})[0][0],'unchanged')


class GameTests(unittest.TestCase):
    def test_newer_ambiguous_count_does_not_fall_back(self):
        n=SimpleNamespace(title='Example',url='x',novelupdates_url=None,author='A',genres=['Fantasy'],source_metadata={'record':{'source':'shaido987/novel-dataset','original_chapter_status_raw':'100 chapters (Completed)'},'novelupdates_page':{'source':'novelupdates','original_chapter_status_raw':'100+ chapters (Ongoing)'}})
        g=game_data(n)
        self.assertIsNone(g['chapters'])
        self.assertEqual(g['publication_status'],'ongoing')

    def test_status_feedback_and_snapshots(self):
        base={'title':'Example','author':'A','genres':['Fantasy'],'rating':4,'chapters':100,'publication_status':'completed'}
        other=dict(base,title='Other',publication_status='ongoing')
        self.assertEqual(compare_guess(base,other)['publication_status'],'❌')
        self.assertEqual(compare_guess(base,dict(other,publication_status='completed'))['publication_status'],'✔️')
        self.assertEqual(compare_guess(base,dict(other,publication_status='unknown'))['publication_status'],'Publication status unknown')
        old=snapshot_data(dict(base,game_metadata_version='novelupdates-v1'))
        self.assertEqual(old['rating'],4)
        self.assertIsNone(old['chapters'])
        self.assertEqual(old['publication_status'],'unknown')
        self.assertIsNone(snapshot_data(dict(base,rating=80))['rating'])


if __name__=='__main__':unittest.main()
