import unittest, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from chapter_status import parse_chapter_status

class ChapterTests(unittest.TestCase):

    def check(self, raw, total, main=None, extra=None, status='completed', method=None):
        result = parse_chapter_status(raw)
        self.assertEqual(result['original_chapters_total'], total)
        self.assertEqual(result['original_chapters_main'], main)
        self.assertEqual(result['original_chapters_extra'], extra)
        self.assertEqual(result['publication_status'], status)
        if method:
            self.assertEqual(result['chapter_count_method'], method)
        return result

    def test_simple_statuses(self):
        for label, status in [('Completed', 'completed'), ('Complete', 'completed'), ('Ongoing', 'ongoing'), ('Dropped', 'dropped'), ('Hiatus', 'hiatus'), ('Cancelled', 'cancelled')]:
            with self.subTest(label=label):
                self.check(f'1,648 Chapters ({label})', 1648, status=status, method='reported')
        self.check('0 chapters', 0, status='unknown')
        self.check('133 (Completed)', None)
        self.check('Completed', None)
        self.check('Complete\n- 143 Chapters', 143)

    def test_extra_totals(self):
        self.check('149 Chapters + 5 Extras (Completed)', 154, 149, 5, method='calculated')
        self.check('834 Chapters - Completed\n36 Extra - Completed', 870, 834, 36, method='calculated')
        self.check('182 Chapters + 19 Extras (Completed)', 201, 182, 19)
        self.check('98 Chapters + 2 Extras (Completed)', 100, 98, 2)
        self.check('74 Chapters + 6 Extras (Completed)', 80, 74, 6)
        self.check('248 Chapters + 44 Extras (Completed)', 292, 248, 44)
        self.check('119 Chapters + 21 Extras (released with the book) + 7 Extras\n(released as of June 2023) + 2 Extras (Completed)\n149 Total Chapters', 149, 119, 30, method='reported')

    def test_breakdown_not_added_twice(self):
        self.check('381 Chapters (Completed)\n-main story: 355 chapters (completed)\n-extra: 26 chapters (completed)', 381, 355, 26)
        self.check('598 Chapters (Completed)\nMain Story - 573 Chapters + 25 Bonus Chapters', 598, 573, 25)
        self.check('Main Story Chapters 212 (Complete)\nExtra Chapters 20\n(Overall Chapters 232)', 232, 212, 20)
        self.check('16 Volumes / 400 Chapters (Completed):\n-Part 1: 287 Chapters (Completed)\n-Part 2: 113 Chapters (Completed)', 400)
        self.check('1400 chapters (completed)/ 56 volumes (completed)\n- 1 season: 26 Volumes (Completed)/ 650 chapters (completed)\n- 2 season: 30 volumes (completed)/ 750 chapters (completed)', 1400)

    def test_partial_and_contradictory(self):
        self.check('50 WN Chapters + 3 Side Stories / 2 Volumes (Complete)', None, 50)
        self.check('118 Chapters (Completed)\n-Main Story: 118 Chapters (Completed)\n-Side Story: 62 Chapters (Completed)\n5 Volumes (Completed)\n-Main Story: 3 Volumes\n-Side Story: 1 Volume\n-Special Side Stories: 1 Volume', None, 118, 62)
        self.check('193 Chapters (Completed):\n⊱ Prologue\n⊱ Main Story: 170 Chapters\n⊱ Side Story: 22 Chapters\n[Split in Translation]', 193, 170, 22)
        self.check('100 Chapters (Completed)\n-Part 1: 40 Chapters\n-Part 2: 50 Chapters', None)
        self.check('149 Chapters + 5 Extras (Completed)\n153 Total Chapters', None, 149, 5)
        self.check('100+ chapters (Ongoing)', None, status='ongoing')
        r = self.check('Main Story: 100 Chapters (Completed)\nSide Story: 5 Chapters (Ongoing)', 105, 100, 5, status='unknown')
        self.assertEqual(r['main_publication_status'], 'completed')

class CaptureTests(unittest.TestCase):
    def test_captured_breakdowns(self):
        self.assertEqual(parse_chapter_status('1200 Chapters (Completed)')["original_chapters_total"], 1200)
        self.assertEqual(parse_chapter_status('1450 Chapters (Complete)\n58 Volumes (Complete)')["original_chapters_total"], 1450)
        self.assertEqual(parse_chapter_status('22 Volumes / 2200 Chapters (Ongoing)')["original_chapters_total"], 2200)
        self.assertEqual(parse_chapter_status('1442 Chapters (Ongoing):\n-Part 1 "The Birth of a Hero": 776 Chapters + 23 Extra Chapters (Completed)\n-Part 2 "The Laws of the Hunt": 643 Chapters (Ongoing)')["original_chapters_total"], 1442)
        self.assertEqual(parse_chapter_status('378 Chapters (Completed):\n— 348 Main Story Chapters (Completed)\n— 4 Extra Chapters (Completed)\n— 1 Afterword (Completed)\n— 25 Side Story Chapters (Completed)')["original_chapters_total"], 378)
        self.assertEqual(parse_chapter_status('1442 Chapters (Ongoing):\n-Part 1 "The Birth of a Hero": 776 Chapters + 23 Extra Chapters (Completed)\n-Part 2 "The Laws of the Hunt": 643 Chapters (Ongoing)')["publication_status"], "ongoing")
    def test_conflict_and_ambiguous_units(self):
        self.assertIsNone(parse_chapter_status('1443 Chapters (Ongoing):\n-Part 1 "The Birth of a Hero": 776 Chapters + 23 Extra Chapters (Completed)\n-Part 2 "The Laws of the Hunt": 643 Chapters (Ongoing)')["original_chapters_total"])
        self.assertIsNone(parse_chapter_status('1442 Chapters (Ongoing):\n-Part 1 "The Birth of a Hero": 776 Chapters + 23 Side Stories (Completed)\n-Part 2 "The Laws of the Hunt": 643 Chapters (Ongoing)')["original_chapters_total"])
        self.assertIsNone(parse_chapter_status('378 Chapters (Completed):\n— 348 Main Story Chapters (Completed)\n— 4 Extra Chapters (Completed)\n— 1 Afterword (Completed)\n— 25 Side Stories (Completed)')["original_chapters_total"])
        self.assertIsNone(parse_chapter_status('378 Chapters (Completed):\n— 348 Main Story Chapters (Completed)\n— 4 Extra Chapters (Completed)\n— 1 Afterword (Completed)\n— 25 Side Story Chapters (Completed)\n— 25 Side Story Chapters (Completed)')["original_chapters_total"])

if __name__ == "__main__": unittest.main()
