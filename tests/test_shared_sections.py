import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import arcade

from benches.shared_sections import INVENTORY_TABS, InventorySection, ReactionsSection


def _make_window():
    window = MagicMock()
    window.chemical_inventory.species_catalog = {}
    window.chemical_inventory.contents = {}
    window.reaction_engine.active_processes = {}
    window.reaction_engine.reaction_db = {}
    window.equipment_inventory.items = {}
    window.equipment_catalog = {}
    window.consumables.contents = {}
    window.consumable_catalog = {}
    return window


def _fake_process(process_id="p1", ready=True, end_time=4.0):
    process = MagicMock()
    process.process_id = process_id
    process.is_ready.return_value = ready
    process.end_time = end_time
    process.time_remaining.return_value = 0.0 if ready else 1.5
    return process


class TestReactionsSectionNavigation(unittest.TestCase):

    def test_scroll_wraps_over_active_processes(self):
        section = ReactionsSection(running=True)
        window = _make_window()
        window.reaction_engine.active_processes = {"p1": object(), "p2": object(), "p3": object()}
        section.handle_key(arcade.key.UP, window)
        self.assertEqual(section.cursor, 2)  # wrapped to last item
        section.handle_key(arcade.key.DOWN, window)
        self.assertEqual(section.cursor, 0)

    def test_known_reactions_sorted_by_product_display_name(self):
        section = ReactionsSection(running=False)
        window = _make_window()
        window.reaction_engine.reaction_db = {
            "r1": SimpleNamespace(products={"zzz product": 1.0}),
            "r2": SimpleNamespace(products={"aaa product": 1.0}),
        }
        items = section.items(window)
        # "aaa product" has no species entry, so display_name falls back to
        # the raw name -- alphabetically first, so it sorts first.
        self.assertEqual(next(iter(items[0].products)), "aaa product")

    def test_scroll_is_a_no_op_with_no_items(self):
        section = ReactionsSection(running=True)
        window = _make_window()
        section.handle_key(arcade.key.DOWN, window)
        self.assertEqual(section.cursor, 0)

    def test_two_instances_have_independent_cursors(self):
        active = ReactionsSection(running=True)
        known = ReactionsSection(running=False)
        active.cursor = 3
        self.assertEqual(known.cursor, 0)


class TestReactionsSectionCollectible(unittest.TestCase):

    def test_enter_is_a_no_op_when_not_collectible(self):
        section = ReactionsSection(running=True, collectible=False)
        window = _make_window()
        process = _fake_process(ready=True)
        window.reaction_engine.active_processes = {"p1": process}
        section.handle_key(arcade.key.ENTER, window)
        window.reaction_engine.collect_reaction.assert_not_called()

    def test_enter_collects_a_ready_process(self):
        section = ReactionsSection(running=True, collectible=True)
        window = _make_window()
        process = _fake_process(ready=True)
        window.reaction_engine.active_processes = {"p1": process}
        window.reaction_engine.collect_reaction.return_value = {"ethyl bromide (crude)": 1.0}
        messages = []
        section.handle_key(arcade.key.ENTER, window, show_message=lambda text, color=None: messages.append(text))
        window.reaction_engine.collect_reaction.assert_called_once()
        self.assertTrue(any("Collected" in m for m in messages))

    def test_enter_on_a_not_ready_process_does_not_collect(self):
        section = ReactionsSection(running=True, collectible=True)
        window = _make_window()
        process = _fake_process(ready=False)
        window.reaction_engine.active_processes = {"p1": process}
        messages = []
        section.handle_key(arcade.key.ENTER, window, show_message=lambda text, color=None: messages.append(text))
        window.reaction_engine.collect_reaction.assert_not_called()
        self.assertTrue(any("Not ready" in m for m in messages))

    def test_f_warps_game_clock_to_process_end_time(self):
        section = ReactionsSection(running=True, collectible=True)
        window = _make_window()
        process = _fake_process(end_time=7.5)
        window.reaction_engine.active_processes = {"p1": process}
        section.handle_key(arcade.key.F, window)
        window.game_clock.advance_to.assert_called_once_with(7.5)

    def test_f_is_a_no_op_when_not_collectible(self):
        section = ReactionsSection(running=True, collectible=False)
        window = _make_window()
        process = _fake_process()
        window.reaction_engine.active_processes = {"p1": process}
        section.handle_key(arcade.key.F, window)
        window.game_clock.advance_to.assert_not_called()

    def test_collect_and_warp_are_only_active_for_running_sections(self):
        section = ReactionsSection(running=False, collectible=True)  # nonsensical combo, but shouldn't crash
        window = _make_window()
        window.reaction_engine.reaction_db = {"r1": SimpleNamespace(products={"ethyl bromide": 1.0})}
        section.handle_key(arcade.key.ENTER, window)
        window.reaction_engine.collect_reaction.assert_not_called()


class TestReactionsSectionSelectable(unittest.TestCase):

    def test_enter_calls_on_select_with_the_chosen_definition(self):
        chosen = []
        section = ReactionsSection(running=False, selectable=True, on_select=chosen.append)
        window = _make_window()
        definition = SimpleNamespace(products={"ethyl bromide": 1.0})
        window.reaction_engine.reaction_db = {"r1": definition}
        section.handle_key(arcade.key.ENTER, window)
        self.assertEqual(chosen, [definition])

    def test_enter_is_a_no_op_when_not_selectable(self):
        chosen = []
        section = ReactionsSection(running=False, selectable=False, on_select=chosen.append)
        window = _make_window()
        window.reaction_engine.reaction_db = {"r1": SimpleNamespace(products={"ethyl bromide": 1.0})}
        section.handle_key(arcade.key.ENTER, window)
        self.assertEqual(chosen, [])


class TestInventorySection(unittest.TestCase):

    def test_reagents_is_the_default_tab(self):
        section = InventorySection()
        self.assertEqual(INVENTORY_TABS[section.tab], "Reagents")

    def test_tab_switch_cycles_through_all_three_and_resets_cursor(self):
        section = InventorySection()
        window = _make_window()
        section.tab = 0
        section.cursor = 2
        self.assertEqual(len(INVENTORY_TABS), 3)
        section.handle_key(arcade.key.LEFT, window)  # wraps backward to the last tab
        self.assertEqual(section.tab, 2)
        self.assertEqual(section.cursor, 0)

    def test_scroll_wraps_within_equipment_tab(self):
        section = InventorySection()
        window = _make_window()
        window.equipment_inventory.items = {
            "a": SimpleNamespace(type="rb_flask", name="125 mL RB Flask", capacity=125.0, in_use=False),
            "b": SimpleNamespace(type="rb_flask", name="250 mL RB Flask", capacity=250.0, in_use=False),
        }
        section.tab = 0  # "Equipment"
        section.handle_key(arcade.key.UP, window)
        self.assertEqual(section.cursor, 1)  # wrapped to last item

    def test_scroll_is_a_no_op_with_no_items_on_tab(self):
        section = InventorySection()
        window = _make_window()
        section.tab = 1  # "Reagents", empty in this window double
        section.handle_key(arcade.key.DOWN, window)
        self.assertEqual(section.cursor, 0)


if __name__ == "__main__":
    unittest.main()
