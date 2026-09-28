import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from benches.ui_theme import page_count, page_start_for_cursor


class TestPageStartForCursor(unittest.TestCase):

    def test_first_page_starts_at_zero(self):
        self.assertEqual(page_start_for_cursor(0, 5), 0)
        self.assertEqual(page_start_for_cursor(4, 5), 0)

    def test_cursor_on_second_page(self):
        self.assertEqual(page_start_for_cursor(5, 5), 5)
        self.assertEqual(page_start_for_cursor(9, 5), 5)

    def test_cursor_on_third_page(self):
        self.assertEqual(page_start_for_cursor(10, 5), 10)
        self.assertEqual(page_start_for_cursor(12, 5), 10)


class TestPageCount(unittest.TestCase):

    def test_empty_list_is_still_one_page(self):
        self.assertEqual(page_count(0, 5), 1)

    def test_exact_multiple_of_rows_per_page(self):
        self.assertEqual(page_count(10, 5), 2)

    def test_rounds_up_a_partial_last_page(self):
        self.assertEqual(page_count(11, 5), 3)
        self.assertEqual(page_count(1, 5), 1)


if __name__ == "__main__":
    unittest.main()
