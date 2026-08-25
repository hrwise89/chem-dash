import os
import sys
import unittest

# Tests run from repo root, but game modules use flat imports (matching how
# main.py runs with src/ on sys.path) -- so make sure src/ is importable here too.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from game_clock import GameClock
from inventory import (
    ChemicalInventory,
    EquipmentInventory,
    EquipmentUnavailableError,
)
from reaction_engine import ReactionEngine, ReactionNotReadyError

FULL_RIG = ["rb_flask", "condenser", "tubing", "heating_mantle", "stir_bar", "magnetic_stirrer"]


def make_full_rig(equipment_inventory: EquipmentInventory, flask_capacity: float = 2.0):
    """Add one of every piece of equipment a basic reaction needs."""
    equipment_inventory.add_item("rb_flask", "250 mL RB Flask", capacity=flask_capacity)
    equipment_inventory.add_item("condenser", "Reflux Condenser")
    equipment_inventory.add_item("tubing", "Rubber Tubing")
    equipment_inventory.add_item("heating_mantle", "Heating Mantle")
    equipment_inventory.add_item("stir_bar", "Stir Bar")
    equipment_inventory.add_item("magnetic_stirrer", "Magnetic Stirrer")


class TestReactionEngine(unittest.TestCase):

    def setUp(self):
        self.engine = ReactionEngine("src/data/reactions.json")
        self.clock = GameClock()

    def make_inventory(self, **kwargs):
        inv = ChemicalInventory()
        for chem, amt in kwargs.items():
            inv.add(chem, amt)
        return inv

    def run_to_completion(self, inventory, equipment, reagents, solvent, temperature, time_hours):
        """Helper: start a reaction, advance the clock to its end, and collect it."""
        process = self.engine.start_reaction(
            inventory, equipment, reagents, solvent, temperature, time_hours, self.clock
        )
        self.clock.advance_to(process.end_time)
        return self.engine.collect_reaction(process.process_id, inventory, equipment, self.clock)

    # --- Core happy path ---
    def test_valid_reaction_ideal_conditions(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        products = self.run_to_completion(inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0)
        self.assertAlmostEqual(products["ethyl bromide (crude)"], 1.0, places=2)
        self.assertAlmostEqual(products["water"], 1.0, places=2)
        self.assertTrue(inventory.has("ethyl bromide (crude)", 1.0))

    def test_equipment_freed_after_collection(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        self.run_to_completion(inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0)
        for item in equipment.items.values():
            self.assertFalse(item.in_use)

    # --- Condition penalties (same yield logic as before, now applied at collection) ---
    def test_temperature_too_high_reduces_yield(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        products = self.run_to_completion(inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 50.0, 4.0)
        self.assertLess(products["ethyl bromide (crude)"], 1.0)
        self.assertGreater(products["ethyl bromide (crude)"], 0.4)

    def test_wrong_solvent_penalty(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        products = self.run_to_completion(inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "toluene", 20.0, 4.0)
        self.assertLess(products["ethyl bromide (crude)"], 1.0)

    def test_time_too_short_reduces_yield(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        products = self.run_to_completion(inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 1.0)
        self.assertLess(products["ethyl bromide (crude)"], 1.0)

    def test_unmatched_reaction_returns_unknown(self):
        inventory = self.make_inventory(NaOH=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        result = self.engine.start_reaction(
            inventory, equipment, {"NaOH": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
        )
        self.assertIn("unknown mixture", result)
        # Nothing should have been consumed or reserved for an unmatched mixture
        self.assertTrue(inventory.has("NaOH", 1.0))
        self.assertTrue(inventory.has("ethanol", 1.0))
        for item in equipment.items.values():
            self.assertFalse(item.in_use)

    def test_limiting_reagent(self):
        inventory = self.make_inventory(HBr=2.0, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment, flask_capacity=3.0)

        products = self.run_to_completion(inventory, equipment, {"HBr": 2.0, "ethanol": 1.0}, "neat", 20.0, 4.0)
        self.assertAlmostEqual(products["ethyl bromide (crude)"], 1.0, places=2)

    def test_side_products_not_added_to_inventory(self):
        inventory = self.make_inventory(HBr=2.0, ethanol=2.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        products = self.run_to_completion(inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0)
        self.assertIn("ethyl bromide (crude)", products)
        self.assertIn("water", products)
        self.assertNotIn("water (crude)", products)
        self.assertFalse(inventory.has("water", 0.01))

    def test_new_reaction_ethylnitrile(self):
        inventory = self.make_inventory(**{"sodium cyanide": 1.0, "ethyl bromide": 1.0})
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        products = self.run_to_completion(
            inventory, equipment, {"sodium cyanide": 1.0, "ethyl bromide": 1.0}, "toluene", 40.0, 4.0
        )
        self.assertAlmostEqual(products["ethyl cyanide (crude)"], 1.0, places=2)
        self.assertAlmostEqual(products["sodium bromide"], 1.0, places=2)

    def test_insufficient_inventory_raises(self):
        inventory = self.make_inventory(HBr=0.5, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        with self.assertRaises(ValueError):
            self.engine.start_reaction(
                inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
            )

    def test_partial_reaction_efficiency(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=2.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment, flask_capacity=3.0)

        products = self.run_to_completion(inventory, equipment, {"HBr": 1.0, "ethanol": 2.0}, "neat", 20.0, 4.0)
        self.assertAlmostEqual(products["ethyl bromide (crude)"], 1.0, places=2)

    # --- Equipment reservation ---
    def test_missing_equipment_raises(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        # No equipment added at all

        with self.assertRaises(EquipmentUnavailableError):
            self.engine.start_reaction(
                inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
            )
        # Reagents should not have been consumed since the reaction never started
        self.assertTrue(inventory.has("HBr", 1.0))

    def test_all_or_nothing_equipment_reservation(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        # Everything except a condenser
        equipment.add_item("rb_flask", "250 mL RB Flask", capacity=2.0)
        equipment.add_item("tubing", "Rubber Tubing")
        equipment.add_item("heating_mantle", "Heating Mantle")
        equipment.add_item("stir_bar", "Stir Bar")
        equipment.add_item("magnetic_stirrer", "Magnetic Stirrer")

        with self.assertRaises(EquipmentUnavailableError):
            self.engine.start_reaction(
                inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
            )
        # Nothing should have been reserved, since the reservation was all-or-nothing
        for item in equipment.items.values():
            self.assertFalse(item.in_use)

    def test_flask_too_small_blocks_reaction(self):
        inventory = self.make_inventory(HBr=2.0, ethanol=2.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment, flask_capacity=1.0)  # too small for a 2+2 mol scale reaction

        with self.assertRaises(EquipmentUnavailableError):
            self.engine.start_reaction(
                inventory, equipment, {"HBr": 2.0, "ethanol": 2.0}, "neat", 20.0, 4.0, self.clock
            )

    def test_best_fit_flask_chosen(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        equipment.add_item("rb_flask", "1 L RB Flask", capacity=5.0)
        small = equipment.add_item("rb_flask", "100 mL RB Flask", capacity=2.0)
        equipment.add_item("condenser", "Reflux Condenser")
        equipment.add_item("tubing", "Rubber Tubing")
        equipment.add_item("heating_mantle", "Heating Mantle")
        equipment.add_item("stir_bar", "Stir Bar")
        equipment.add_item("magnetic_stirrer", "Magnetic Stirrer")

        process = self.engine.start_reaction(
            inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
        )
        self.assertIn(small.id, process.equipment_ids)

    def test_second_reaction_blocked_while_equipment_in_use(self):
        inventory = self.make_inventory(HBr=2.0, ethanol=2.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)  # only one of each item

        self.engine.start_reaction(
            inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
        )
        with self.assertRaises(EquipmentUnavailableError):
            self.engine.start_reaction(
                inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
            )

    # --- Time / game clock ---
    def test_cannot_collect_before_ready(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        process = self.engine.start_reaction(
            inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
        )
        self.clock.advance(1.0)  # only 1 of 4 hours have passed
        with self.assertRaises(ReactionNotReadyError):
            self.engine.collect_reaction(process.process_id, inventory, equipment, self.clock)

    def test_warp_to_end_collects_successfully(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        process = self.engine.start_reaction(
            inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
        )
        # "Warp to end" = advance the clock straight to the process's end_time
        self.clock.advance_to(process.end_time)
        products = self.engine.collect_reaction(process.process_id, inventory, equipment, self.clock)
        self.assertAlmostEqual(products["ethyl bromide (crude)"], 1.0, places=2)


if __name__ == "__main__":
    unittest.main()
