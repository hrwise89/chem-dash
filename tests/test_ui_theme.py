import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from benches.ui_theme import scroll_offset_for_cursor, visible_item_count


class TestVisibleItemCount(unittest.TestCase):

    def test_all_single_row_items_fit_up_to_max_rows(self):
        row_counts = [1] * 20
        self.assertEqual(visible_item_count(row_counts, 0, 5), 5)

    def test_a_wrapped_item_counts_for_its_full_row_span(self):
        # 5 one-row items, then a 3-row item, then more one-row items --
        # with max_rows=8 that's items 0-6 (5 + 3 = 8 rows across 6 items).
        row_counts = [1, 1, 1, 1, 1, 3, 1, 1, 1, 1]
        self.assertEqual(visible_item_count(row_counts, 0, 8), 6)

    def test_starting_mid_list_only_counts_from_start_index(self):
        row_counts = [1, 1, 1, 1, 1, 3, 1, 1, 1, 1, 1, 1]
        # From index 5: 3+1+1+1+1+1 = 8 rows across 6 items (indices 5-10).
        self.assertEqual(visible_item_count(row_counts, 5, 8), 6)

    def test_a_single_item_taller_than_max_rows_still_counts_as_one(self):
        row_counts = [10, 1, 1]
        self.assertEqual(visible_item_count(row_counts, 0, 3), 1)

    def test_empty_from_start_index_at_end_of_list(self):
        row_counts = [1, 1, 1]
        self.assertEqual(visible_item_count(row_counts, 3, 5), 0)


class TestScrollOffsetForCursor(unittest.TestCase):

    def test_cursor_above_current_scroll_jumps_up_to_it(self):
        row_counts = [1] * 20
        self.assertEqual(scroll_offset_for_cursor(row_counts, 2, 10, 5), 2)

    def test_cursor_within_view_does_not_scroll(self):
        row_counts = [1] * 20
        self.assertEqual(scroll_offset_for_cursor(row_counts, 3, 0, 5), 0)

    def test_cursor_past_view_scrolls_forward_one_item_at_a_time(self):
        row_counts = [1] * 20
        # From offset 0, 5 rows show items 0-4; cursor at 5 must push the
        # window forward until it's visible.
        self.assertEqual(scroll_offset_for_cursor(row_counts, 5, 0, 5), 1)

    def test_wrapped_item_pulls_the_scroll_point_earlier(self):
        # Regression test for the reported bug: a wrapped item earlier in
        # the list consumes extra rows, so the cursor should need to
        # scroll sooner than a flat item-count would suggest -- not later.
        row_counts = [1, 1, 1, 1, 1, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
        max_rows = 17
        flat_visible = max_rows  # what the old (buggy) assumption used
        wrapped_visible = visible_item_count(row_counts, 0, max_rows)
        self.assertLess(wrapped_visible, flat_visible)

        cursor_index = wrapped_visible  # first item that should force a scroll
        self.assertEqual(scroll_offset_for_cursor(row_counts, cursor_index, 0, max_rows), 1)

    def test_scrolling_forward_keeps_cursor_visible_across_the_whole_list(self):
        row_counts = [1, 1, 1, 1, 1, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
        max_rows = 17
        scroll_offset = 0
        for cursor in range(len(row_counts)):
            scroll_offset = scroll_offset_for_cursor(row_counts, cursor, scroll_offset, max_rows)
            visible = visible_item_count(row_counts, scroll_offset, max_rows)
            self.assertGreaterEqual(cursor, scroll_offset)
            self.assertLess(cursor, scroll_offset + visible)


if __name__ == "__main__":
    unittest.main()
