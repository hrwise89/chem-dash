import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import arcade

from notebook import GRID_COLUMNS, GRID_ROWS, PANELS, Notebook


def _index_of(section_key):
    return next(i for i, (_, section) in enumerate(PANELS) if section == section_key)


def _make_window():
    """A minimal window double with empty-but-well-shaped data for every
    section -- enough for handle_key's list-length/navigation logic
    without needing a real game to be running. Tests that care about
    actual item content replace the relevant attribute themselves."""
    window = MagicMock()
    window.chemical_inventory.species_catalog = {}
    window.chemical_inventory.contents = {}
    window.reaction_engine.active_processes = {}
    window.reaction_engine.reaction_db = {}
    window.contract_board.accepted = []
    window.contract_board.in_transit = []
    window.equipment_inventory.items = {}
    window.equipment_catalog = {}
    window.consumables.contents = {}
    window.consumable_catalog = {}
    return window


class TestNotebookToggle(unittest.TestCase):

    def test_toggle_opens_and_closes(self):
        notebook = Notebook()
        self.assertFalse(notebook.is_open)
        notebook.toggle()
        self.assertTrue(notebook.is_open)
        notebook.toggle()
        self.assertFalse(notebook.is_open)

    def test_toggle_preserves_section_and_tab_state(self):
        notebook = Notebook()
        window = _make_window()
        notebook.toggle()  # open
        notebook.cursor_index = _index_of("inventory")
        notebook.handle_key(arcade.key.ENTER, window)
        self.assertEqual(notebook.section, "inventory")
        notebook.handle_key(arcade.key.RIGHT, window)  # Reagents (default) -> "Consumables" tab
        self.assertEqual(notebook.inventory.tab, 2)

        notebook.toggle()  # close via N
        self.assertFalse(notebook.is_open)
        self.assertEqual(notebook.section, "inventory")
        self.assertEqual(notebook.inventory.tab, 2)

        notebook.toggle()  # reopen via N
        self.assertTrue(notebook.is_open)
        self.assertEqual(notebook.section, "inventory")
        self.assertEqual(notebook.inventory.tab, 2)


class TestGridNavigation(unittest.TestCase):

    def test_right_wraps_within_row(self):
        notebook = Notebook()
        window = _make_window()
        notebook.cursor_index = 1  # row 0, col 1 (last column)
        notebook.handle_key(arcade.key.RIGHT, window)
        self.assertEqual(notebook.cursor_index, 0)  # wrapped to col 0, same row

    def test_down_wraps_within_column(self):
        notebook = Notebook()
        window = _make_window()
        last_row = GRID_ROWS - 1
        notebook.cursor_index = last_row * GRID_COLUMNS  # bottom of column 0
        notebook.handle_key(arcade.key.DOWN, window)
        self.assertEqual(notebook.cursor_index, 0)  # wrapped to row 0, same column

    def test_escape_on_grid_closes_notebook(self):
        notebook = Notebook()
        window = _make_window()
        notebook.is_open = True
        notebook.handle_key(arcade.key.ESCAPE, window)
        self.assertFalse(notebook.is_open)


class TestActivate(unittest.TestCase):

    def test_placeholder_panel_is_a_no_op(self):
        notebook = Notebook()
        window = _make_window()
        notebook.cursor_index = _index_of(None)
        notebook.handle_key(arcade.key.ENTER, window)
        self.assertIsNone(notebook.section)

    def test_history_panel_is_a_no_op(self):
        notebook = Notebook()
        window = _make_window()
        labels_with_none = [i for i, (label, section) in enumerate(PANELS) if section is None]
        history_index = next(i for i in labels_with_none if PANELS[i][0] == "History")
        notebook.cursor_index = history_index
        notebook.handle_key(arcade.key.ENTER, window)
        self.assertIsNone(notebook.section)

    def test_active_reactions_panel_opens_section(self):
        notebook = Notebook()
        window = _make_window()
        notebook.cursor_index = _index_of("active_reactions")
        notebook.handle_key(arcade.key.ENTER, window)
        self.assertEqual(notebook.section, "active_reactions")

    def test_orders_panel_opens_section(self):
        notebook = Notebook()
        window = _make_window()
        notebook.cursor_index = _index_of("orders")
        notebook.handle_key(arcade.key.ENTER, window)
        self.assertEqual(notebook.section, "orders")

    def test_inventory_panel_opens_section(self):
        notebook = Notebook()
        window = _make_window()
        notebook.cursor_index = _index_of("inventory")
        notebook.handle_key(arcade.key.ENTER, window)
        self.assertEqual(notebook.section, "inventory")

    def test_known_reactions_panel_opens_section(self):
        notebook = Notebook()
        window = _make_window()
        notebook.cursor_index = _index_of("known_reactions")
        notebook.handle_key(arcade.key.ENTER, window)
        self.assertEqual(notebook.section, "known_reactions")


class TestEscapeBacksOutOfAnySection(unittest.TestCase):

    def test_escape_in_section_backs_out_to_grid(self):
        notebook = Notebook()
        window = _make_window()
        notebook.section = "orders"
        notebook.handle_key(arcade.key.ESCAPE, window)
        self.assertIsNone(notebook.section)


class TestNotebookDelegatesToSharedSections(unittest.TestCase):
    """Notebook.handle_key/draw just dispatch to the shared_sections.py
    objects it owns -- see test_shared_sections.py for the sections'
    own navigation/data behavior in isolation."""

    def test_active_reactions_scroll_uses_the_shared_section(self):
        notebook = Notebook()
        window = _make_window()
        window.reaction_engine.active_processes = {"p1": object(), "p2": object()}
        notebook.section = "active_reactions"
        notebook.handle_key(arcade.key.DOWN, window)
        self.assertEqual(notebook.active_reactions.cursor, 1)

    def test_known_reactions_has_its_own_section_and_cursor(self):
        notebook = Notebook()
        self.assertIsNot(notebook.active_reactions, notebook.known_reactions)


class TestOrdersSection(unittest.TestCase):

    def test_tab_switch_cycles_and_resets_cursor(self):
        notebook = Notebook()
        window = _make_window()
        notebook.section = "orders"
        notebook.orders_cursor = 3
        notebook.handle_key(arcade.key.RIGHT, window)
        self.assertEqual(notebook.orders_tab, 1)
        self.assertEqual(notebook.orders_cursor, 0)
        notebook.handle_key(arcade.key.RIGHT, window)
        self.assertEqual(notebook.orders_tab, 0)  # wrapped back to "Open Orders"

    def test_scroll_wraps_within_current_tab(self):
        notebook = Notebook()
        window = _make_window()
        window.contract_board.accepted = [object(), object()]
        window.contract_board.in_transit = [object()]
        notebook.section = "orders"
        notebook.orders_tab = 0  # "Open Orders" -> 2 entries
        notebook.orders_cursor = 0
        notebook.handle_key(arcade.key.UP, window)
        self.assertEqual(notebook.orders_cursor, 1)

    def test_scroll_is_a_no_op_with_no_orders(self):
        notebook = Notebook()
        window = _make_window()
        notebook.section = "orders"
        notebook.handle_key(arcade.key.DOWN, window)
        self.assertEqual(notebook.orders_cursor, 0)


if __name__ == "__main__":
    unittest.main()
