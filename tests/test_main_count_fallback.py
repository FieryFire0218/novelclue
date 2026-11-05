import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from chapter_status import parse_chapter_status

class FallbackTests(unittest.TestCase):
    def test_unknown_extras_use_main(self):
        for raw,expected in [
            ('1613 Chapters + 3 Side Stories / 1 Afterword (Completed)',1613),
            ('1314 Chapters + 1 Epilogue (Completed)',1314),
            ('50 WN Chapters + 3 Side Stories / 2 Volumes (Complete)',50),
            ('Main Story: 100 Chapters (Completed)\nSide Stories (Completed)',100),
        ]:
            with self.subTest(raw=raw):
                r=parse_chapter_status(raw)
                self.assertEqual(r['original_chapters_total'],expected)
                self.assertEqual(r['original_chapters_main'],expected)
                self.assertEqual(r['chapter_count_method'],'main_only')
                self.assertEqual(r['publication_status'],'completed')
                self.assertEqual(r['chapter_status_raw'],raw)

    def test_known_extras_still_included(self):
        r=parse_chapter_status('100 Chapters + 5 Extra Chapters (Completed)')
        self.assertEqual(r['original_chapters_total'],105)
        self.assertEqual(r['chapter_count_method'],'calculated')

    def test_unknown_main_stays_unknown(self):
        self.assertIsNone(parse_chapter_status('100+ Chapters (Ongoing)')['original_chapters_total'])
        self.assertIsNone(parse_chapter_status('5 Volumes and Side Stories (Complete)')['original_chapters_total'])

    def test_conflicting_totals_not_hidden(self):
        r=parse_chapter_status('99 Chapters (Completed)\nMain Story: 100 Chapters\nExtra: 5 Chapters\nEpilogue')
        self.assertIsNone(r['original_chapters_total'])
        self.assertEqual(r['chapter_count_method'],'unresolved')

if __name__=='__main__':unittest.main()
