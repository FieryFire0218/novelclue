import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from chapter_status import parse_chapter_status
class BatchTwoTests(unittest.TestCase):
    def test_all_twenty(self):
        self.assertEqual(parse_chapter_status('481 Chapters (Completed)\n— Prologue: 1 Chapter (Complete)\n— Main Story: 379 Chapters (Complete)\n— Side Stories: 101 Chapters (Complete)')["original_chapters_total"], 481)
        self.assertEqual(parse_chapter_status('93 Chapters + 3 Extras (Complete)')["original_chapters_total"], 96)
        self.assertEqual(parse_chapter_status('507 Chapters (Ongoing)')["original_chapters_total"], 507)
        self.assertEqual(parse_chapter_status('713 Chapters + 18 Extras (Completed)')["original_chapters_total"], 731)
        self.assertEqual(parse_chapter_status('1613 Chapters + 3 Side Stories / 1 Afterword (Completed)')["original_chapters_total"], None)
        self.assertEqual(parse_chapter_status('Main Story:\n243 Chapters (complete)\nSide Story:\n27 Chapters (complete)')["original_chapters_total"], 270)
        self.assertEqual(parse_chapter_status('96 Volumes (Completed) / 2059 Chapters (Completed)')["original_chapters_total"], 2059)
        self.assertEqual(parse_chapter_status('45 Volumes / 1450 Chapters (Completed)')["original_chapters_total"], 1450)
        self.assertEqual(parse_chapter_status('433 Chapters (Complete)\nMain Story: 380 Chapters\nSide story: 53 Side Story Chapters')["original_chapters_total"], 433)
        self.assertEqual(parse_chapter_status('80 Chapters + 8 Extras (Completed)')["original_chapters_total"], 88)
        self.assertEqual(parse_chapter_status('7196 Chapters (Completed)\n+7 extra chapters (Completed)')["original_chapters_total"], 7203)
        self.assertEqual(parse_chapter_status('2255 Chapters (Completed)')["original_chapters_total"], 2255)
        self.assertEqual(parse_chapter_status('1432 Chapters (Total Completed)\n8 Volumes / 1394 Chapters (Main)\n36 Chapters (Side Story)\n2 Chapters (Bonus Story)')["original_chapters_total"], 1432)
        self.assertEqual(parse_chapter_status('92 Chapters + 14 Extras (Completed)')["original_chapters_total"], 106)
        self.assertEqual(parse_chapter_status('1165 Chapters (Completed):\n-Main Story: 35 Volumes / 856 Chapters (Completed)\n-Epilogue: 14 chapters (Completed)\n-Side Story: 167 Chapters (Completed)\n-Afterwords: 128 Chapters (Completed)')["original_chapters_total"], 1165)
        self.assertEqual(parse_chapter_status('208 Chapters (Complete)')["original_chapters_total"], 208)
        self.assertEqual(parse_chapter_status('348 Chapters (Completed)\nComplete Translation on Yonder')["original_chapters_total"], 348)
        self.assertEqual(parse_chapter_status('1314 Chapters + 1 Epilogue (Completed)')["original_chapters_total"], None)
        self.assertEqual(parse_chapter_status('128 chapters + 13 extras + 5 new extras + 8 little weibo extras (154 Complete)')["original_chapters_total"], 154)
        self.assertEqual(parse_chapter_status('425 Chapters (Complete)\n—Main Story: 400 Chapters\n—Side Story: 25 Chapters')["original_chapters_total"], 425)
    def test_bad_breakdowns(self):
        self.assertIsNone(parse_chapter_status('480 Chapters (Completed)\n— Prologue: 1 Chapter (Complete)\n— Main Story: 379 Chapters (Complete)\n— Side Stories: 101 Chapters (Complete)')["original_chapters_total"])
        self.assertIsNone(parse_chapter_status('1433 Chapters (Total Completed)\n8 Volumes / 1394 Chapters (Main)\n36 Chapters (Side Story)\n2 Chapters (Bonus Story)')["original_chapters_total"])
        self.assertIsNone(parse_chapter_status('128 chapters + 13 extras + 5 new extras + 8 little weibo extras (155 Complete)')["original_chapters_total"])
        self.assertIsNone(parse_chapter_status('481 Chapters (Completed)\n— Prologue: 1 Chapter (Complete)\n— Main Story: 379 Chapters (Complete)\n— Side Stories: 101 Chapters (Complete)\n— Side Stories: 101 Chapters (Complete)')["original_chapters_total"])
    def test_retains_known_main_counts(self):
        self.assertEqual(parse_chapter_status('1613 Chapters + 3 Side Stories / 1 Afterword (Completed)')["original_chapters_main"], 1613)
        self.assertEqual(parse_chapter_status('1314 Chapters + 1 Epilogue (Completed)')["original_chapters_main"], 1314)
