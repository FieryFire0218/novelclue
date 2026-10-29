import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from compare import compare_guess


class FeedbackTests(unittest.TestCase):
    def compare(self, guess, answer):
        return compare_guess(dict(guess, title='Guess'), dict(answer, title='Answer'))

    def test_shared_latin_alias(self):
        g = {'author': '我吃西红柿', 'author_aliases': ['I Eat Tomatoes', '我吃西红柿']}
        a = {'author': 'i eat tomatoes', 'author_identity_unverified': True}
        self.assertEqual(self.compare(g, a)['author'], '✔️ Same author — I Eat Tomatoes')

    def test_native_match_uses_guess_latin_alias(self):
        g = {'author': '我吃西红柿', 'author_aliases': ['I Eat Tomatoes']}
        self.assertEqual(self.compare(g, {'author': '我吃西红柿'})['author'], '✔️ Same author — I Eat Tomatoes')

    def test_native_fallback(self):
        self.assertEqual(self.compare({'author': '作者'}, {'author': '作者'})['author'], '✔️ Same author — 作者')

    def test_different_author_does_not_leak_name(self):
        r = self.compare({'author': 'A', 'author_identity_unverified': True}, {'author': 'Secret Name'})
        self.assertEqual(r['author'], '❌ Different author')
        self.assertNotIn('Secret Name', str(r))

    def test_missing_author(self):
        self.assertEqual(self.compare({'author': None}, {'author': 'A'})['author'], 'Author unknown')

    def test_status_feedback_no_answer_status(self):
        r = self.compare({'publication_status': 'ongoing'}, {'publication_status': 'completed'})
        self.assertEqual(r['publication_status'], 'Your guess: Ongoing · ❌ Different status')
        self.assertNotIn('Completed', r['publication_status'])

    def test_unknown_guess(self):
        r = self.compare({}, {'publication_status': 'completed'})
        self.assertIn('guess status unknown', r['publication_status'])
        self.assertNotIn('Completed', r['publication_status'])


if __name__ == '__main__':
    unittest.main()
