import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import arcade

from notebook import GRID_COLUMNS, GRID_ROWS, PANELS, Notebook


def _window_with_inventory(names=()):
    window = MagicMock()
    window.chemical_inventory.contents = {name: 10.0 for name in names}
    window.chemical_inventory.describe.side_effect = lambda name: f"10.0 g ({name})"
    return window


class TestNotebookToggle(unittest.TestCase):

    def test_toggle_opens_and_closes(self):
        notebook = Notebook()
        self.assertFalse(notebook.is_open)
        notebook.toggle()
        self.assertTrue(notebook.is_open)
        notebook.toggle()
        self.assertFalse(notebook.is_open)

    def test_toggle_preserves_section_and_cursor(self):
        notebook = Notebook()
        window = _window_with_inventory(["sodium cyanide"])
        notebook.toggle()  # open
        notebook.cursor_index = 1  # Chemical Inventory panel
        notebook.handle_key(arcade.key.ENTER, window)
        self.assertEqual(notebook.section, "chemical_inventory")
        notebook.section_cursor = 0

        notebook.toggle()  # close via N
        self.assertFalse(notebook.is_open)
        self.assertEqual(notebook.section, "chemical_inventory")

        notebook.toggle()  # reopen via N
        self.assertTrue(notebook.is_open)
        self.assertEqual(notebook.section, "chemical_inventory")


class TestGridNavigation(unittest.TestCase):

    def test_right_wraps_within_row(self):
        notebook = Notebook()
        window = _window_with_inventory()
        notebook.cursor_index = 1  # row 0, col 1 (last column)
        notebook.handle_key(arcade.key.RIGHT, window)
        self.assertEqual(notebook.cursor_index, 0)  # wrapped to col 0, same row

    def test_down_wraps_within_column(self):
        notebook = Notebook()
        window = _window_with_inventory()
        last_row = GRID_ROWS - 1
        notebook.cursor_index = last_row * GRID_COLUMNS  # bottom of column 0
        notebook.handle_key(arcade.key.DOWN, window)
        self.assertEqual(notebook.cursor_index, 0)  # wrapped to row 0, same column

    def test_escape_on_grid_closes_notebook(self):
        notebook = Notebook()
        window = _window_with_inventory()
        notebook.is_open = True
        notebook.handle_key(arcade.key.ESCAPE, window)
        self.assertFalse(notebook.is_open)


class TestActivate(unittest.TestCase):

    def test_placeholder_panel_is_a_no_op(self):
        notebook = Notebook()
        window = _window_with_inventory()
        notebook.cursor_index = 0  # "Active Reactions" -> None
        notebook.handle_key(arcade.key.ENTER, window)
        self.assertIsNone(notebook.section)

    def test_chemical_inventory_panel_opens_section(self):
        notebook = Notebook()
        window = _window_with_inventory()
        chem_inv_index = next(i for i, (_, section) in enumerate(PANELS) if section == "chemical_inventory")
        notebook.cursor_index = chem_inv_index
        notebook.handle_key(arcade.key.ENTER, window)
        self.assertEqual(notebook.section, "chemical_inventory")
        self.assertEqual(notebook.section_cursor, 0)


class TestSectionNavigation(unittest.TestCase):

    def test_escape_in_section_backs_out_to_grid(self):
        notebook = Notebook()
        window = _window_with_inventory(["sodium cyanide"])
        notebook.section = "chemical_inventory"
        notebook.handle_key(arcade.key.ESCAPE, window)
        self.assertIsNone(notebook.section)

    def test_up_down_scroll_wraps_over_items(self):
        notebook = Notebook()
        window = _window_with_inventory(["a", "b", "c"])
        notebook.section = "chemical_inventory"
        notebook.section_cursor = 0
        notebook.handle_key(arcade.key.UP, window)
        self.assertEqual(notebook.section_cursor, 2)  # wrapped to last item
        notebook.handle_key(arcade.key.DOWN, window)
        self.assertEqual(notebook.section_cursor, 0)

    def test_scroll_is_a_no_op_with_no_items(self):
        notebook = Notebook()
        window = _window_with_inventory()
        notebook.section = "chemical_inventory"
        notebook.handle_key(arcade.key.DOWN, window)
        self.assertEqual(notebook.section_cursor, 0)


if __name__ == "__main__":
    unittest.main()
