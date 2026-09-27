import os
import sys
import unittest

# Tests run from repo root, but game modules use flat imports (matching how
# main.py runs with src/ on sys.path) -- so make sure src/ is importable here too.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from game_clock import GameClock
from inventory import (
    ChemicalInventory,
    ChemicalSpecies,
    EquipmentInventory,
    EquipmentUnavailableError,
)
from reaction_engine import (
    RECOMMENDED_MIN_FILL_FRACTION,
    UNDERFILL_YIELD_PENALTY,
    ReactionEngine,
    ReactionNotReadyError,
    reaction_scale_bounds,
    reaction_volume_ml,
    reagents_for_scale,
    reference_reagent_for,
)

FULL_RIG = ["rb_flask", "condenser", "tubing", "heating_mantle", "stir_bar", "magnetic_stirrer"]

# These tests are about reaction logic (stoichiometry, equipment,
# timing, logging) -- not the mass/volume/solution conversions, which get
# their own dedicated coverage in test_inventory.py. So every chemical here
# is defined as an idealized "liquid" with molarity 1000 mol/L (1 mol per
# mL), making native inventory amounts numerically equal to moles, and
# every make_inventory(chem=amt) call below reads exactly like it did
# before ChemicalInventory switched to mass/volume-based storage.
IDENTITY_MOLARITY = 1000.0


def _identity_species(*names) -> dict[str, ChemicalSpecies]:
    return {name: ChemicalSpecies(name=name, state="liquid", molarity=IDENTITY_MOLARITY) for name in names}


TEST_SPECIES_CATALOG = _identity_species(
    "HBr", "ethanol", "sodium cyanide", "ethyl bromide", "ethyl cyanide",
    "NaOH", "water", "sodium bromide",
)


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
        inv = ChemicalInventory(species_catalog=TEST_SPECIES_CATALOG)
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

    def test_preferred_flask_id_overrides_best_fit(self):
        # The player picked the big flask at the bench, even though the
        # small one would also fit -- start_reaction should honor that.
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        big = equipment.add_item("rb_flask", "1 L RB Flask", capacity=5.0)
        equipment.add_item("rb_flask", "100 mL RB Flask", capacity=2.0)
        equipment.add_item("condenser", "Reflux Condenser")
        equipment.add_item("tubing", "Rubber Tubing")
        equipment.add_item("heating_mantle", "Heating Mantle")
        equipment.add_item("stir_bar", "Stir Bar")
        equipment.add_item("magnetic_stirrer", "Magnetic Stirrer")

        process = self.engine.start_reaction(
            inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock,
            preferred_flask_id=big.id,
        )
        self.assertIn(big.id, process.equipment_ids)

    def test_preferred_flask_id_too_small_is_rejected(self):
        inventory = self.make_inventory(HBr=2.0, ethanol=2.0)
        equipment = EquipmentInventory()
        too_small = equipment.add_item("rb_flask", "100 mL RB Flask", capacity=1.0)
        equipment.add_item("condenser", "Reflux Condenser")
        equipment.add_item("tubing", "Rubber Tubing")
        equipment.add_item("heating_mantle", "Heating Mantle")
        equipment.add_item("stir_bar", "Stir Bar")
        equipment.add_item("magnetic_stirrer", "Magnetic Stirrer")

        with self.assertRaises(EquipmentUnavailableError):
            self.engine.start_reaction(
                inventory, equipment, {"HBr": 2.0, "ethanol": 2.0}, "neat", 20.0, 4.0, self.clock,
                preferred_flask_id=too_small.id,
            )

    # --- Underfill yield penalty ---
    def test_underfilled_flask_reduces_yield(self):
        # 2 mL of reaction mixture (identity molarity, 1:1 ratio) in a 100 mL
        # flask is well under RECOMMENDED_MIN_FILL_FRACTION (20 mL) -- should
        # apply UNDERFILL_YIELD_PENALTY on top of the normal efficiency.
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment, flask_capacity=100.0)

        products = self.run_to_completion(inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0)
        self.assertAlmostEqual(products["ethyl bromide (crude)"], 1.0 * UNDERFILL_YIELD_PENALTY, places=2)

    def test_adequately_filled_flask_has_no_underfill_penalty(self):
        # Same reaction, but sized to actually use the flask -- no penalty.
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment, flask_capacity=2.0 / RECOMMENDED_MIN_FILL_FRACTION)  # exactly at the recommended min

        products = self.run_to_completion(inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0)
        self.assertAlmostEqual(products["ethyl bromide (crude)"], 1.0, places=2)

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

    # --- Missing-equipment error reporting ---
    def test_equipment_error_names_missing_types(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        # Everything except a condenser and a heating mantle
        equipment.add_item("rb_flask", "250 mL RB Flask", capacity=2.0)
        equipment.add_item("tubing", "Rubber Tubing")
        equipment.add_item("stir_bar", "Stir Bar")
        equipment.add_item("magnetic_stirrer", "Magnetic Stirrer")

        with self.assertRaises(EquipmentUnavailableError) as ctx:
            self.engine.start_reaction(
                inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
            )
        message = str(ctx.exception)
        self.assertIn("condenser", message)
        self.assertIn("heating_mantle", message)
        self.assertNotIn("tubing", message)  # tubing IS available, shouldn't be listed as missing

    # --- Reference-reagent scaling & vessel-based sizing ---
    def test_reference_reagent_defaults_to_first_reactant(self):
        definition = self.engine.reaction_db["HBr + ethanol → ethyl bromide"]
        # Explicitly set in reactions.json, but this also covers the
        # fallback for a definition that doesn't set it:
        self.assertEqual(reference_reagent_for(definition), "HBr")

        from reaction_engine import ReactionDefinition
        unset = ReactionDefinition(reactants={"foo": 2.0, "bar": 1.0}, products={"baz": 1.0})
        self.assertEqual(reference_reagent_for(unset), "foo")

    def test_reagents_for_scale_preserves_ratio(self):
        definition = self.engine.reaction_db["HBr + ethanol → ethyl bromide"]
        reagents = reagents_for_scale(definition, reference_moles=4.0)
        self.assertAlmostEqual(reagents["HBr"], 4.0, places=6)
        self.assertAlmostEqual(reagents["ethanol"], 4.0, places=6)  # 1:1 ratio

    def test_reagents_for_scale_with_uneven_ratio(self):
        from reaction_engine import ReactionDefinition
        definition = ReactionDefinition(
            reactants={"foo": 2.0, "bar": 1.0}, products={"baz": 1.0}, reference_reagent="bar",
        )
        reagents = reagents_for_scale(definition, reference_moles=3.0)
        self.assertAlmostEqual(reagents["bar"], 3.0, places=6)
        self.assertAlmostEqual(reagents["foo"], 6.0, places=6)  # 2:1 ratio to bar

    def test_reaction_volume_ml_sums_supplier_volumes(self):
        inventory = self.make_inventory(HBr=5.0, ethanol=5.0)
        # Identity-molarity catalog (1 mol/mL), so 1 mol HBr + 1 mol ethanol == 2 mL
        volume = reaction_volume_ml({"HBr": 1.0, "ethanol": 1.0}, inventory)
        self.assertAlmostEqual(volume, 2.0, places=6)

    def test_reaction_volume_ml_none_without_a_supplier(self):
        inventory = self.make_inventory(HBr=5.0)  # no ethanol at all
        volume = reaction_volume_ml({"HBr": 1.0, "ethanol": 1.0}, inventory)
        self.assertIsNone(volume)

    def test_reaction_scale_bounds_scale_with_flask_capacity(self):
        definition = self.engine.reaction_db["HBr + ethanol → ethyl bromide"]
        inventory = self.make_inventory(HBr=100.0, ethanol=100.0)
        bounds = reaction_scale_bounds(definition, inventory, flask_capacity_ml=10.0)
        self.assertIsNotNone(bounds)
        recommended_min, max_moles = bounds
        # 1 mol HBr + 1 mol ethanol (1:1 ratio, identity molarity) == 2 mL
        # per mole of reference reagent (HBr), so for a 10 mL flask:
        self.assertAlmostEqual(max_moles, 10.0 * 0.8 / 2.0, places=6)
        self.assertAlmostEqual(recommended_min, 10.0 * 0.2 / 2.0, places=6)

    def test_reaction_scale_bounds_none_without_a_supplier(self):
        definition = self.engine.reaction_db["HBr + ethanol → ethyl bromide"]
        inventory = self.make_inventory()  # empty
        self.assertIsNone(reaction_scale_bounds(definition, inventory, flask_capacity_ml=250.0))

    # --- Multiple equipment of the same type ---
    def test_two_reactions_run_concurrently_with_duplicate_equipment(self):
        # This is the whole point of owning more than one of each item --
        # two full rigs free at once should let two batches run side by
        # side, each getting its own equipment set.
        # Enough chemicals for 3 batches, so the 3rd start_reaction below
        # fails on equipment specifically, not on running out of reagent.
        inventory = self.make_inventory(HBr=3.0, ethanol=3.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)  # rig #1
        make_full_rig(equipment)  # rig #2

        process_a = self.engine.start_reaction(
            inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
        )
        process_b = self.engine.start_reaction(
            inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
        )
        self.assertNotEqual(process_a.process_id, process_b.process_id)
        self.assertTrue(set(process_a.equipment_ids).isdisjoint(process_b.equipment_ids),
                         "the two reactions should not share any physical equipment item")

        # A third attempt with no equipment left should still fail cleanly
        with self.assertRaises(EquipmentUnavailableError):
            self.engine.start_reaction(
                inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
            )

    # --- Dev-mode logging: confirm key events actually emit, at the levels
    # the on-screen messages are supposed to mirror ---
    def test_successful_start_logs_info(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        with self.assertLogs("chem_dash", level="INFO") as log:
            self.engine.start_reaction(
                inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
            )
        self.assertTrue(any("Started" in message for message in log.output))

    def test_insufficient_chemicals_logs_warning(self):
        inventory = self.make_inventory(HBr=0.5, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        with self.assertLogs("chem_dash", level="WARNING") as log:
            with self.assertRaises(ValueError):
                self.engine.start_reaction(
                    inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
                )
        self.assertTrue(any("not enough" in message.lower() for message in log.output))

    def test_missing_equipment_logs_warning(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()  # nothing added

        with self.assertLogs("chem_dash", level="WARNING") as log:
            with self.assertRaises(EquipmentUnavailableError):
                self.engine.start_reaction(
                    inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
                )
        self.assertTrue(any("missing/busy equipment" in message.lower() for message in log.output))

    def test_successful_collect_logs_info(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        process = self.engine.start_reaction(
            inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
        )
        self.clock.advance_to(process.end_time)

        with self.assertLogs("chem_dash", level="INFO") as log:
            self.engine.collect_reaction(process.process_id, inventory, equipment, self.clock)
        self.assertTrue(any("Collected" in message for message in log.output))

    def test_collect_too_early_logs_warning(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        equipment = EquipmentInventory()
        make_full_rig(equipment)

        process = self.engine.start_reaction(
            inventory, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0, self.clock
        )

        with self.assertLogs("chem_dash", level="WARNING") as log:
            with self.assertRaises(ReactionNotReadyError):
                self.engine.collect_reaction(process.process_id, inventory, equipment, self.clock)
        self.assertTrue(any("remaining" in message.lower() for message in log.output))


if __name__ == "__main__":
    unittest.main()
