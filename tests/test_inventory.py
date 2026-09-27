import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from inventory import (  # noqa: E402
    ChemicalInventory,
    ChemicalSpecies,
    ConsumableInventory,
    EquipmentInventory,
    NotCrudeError,
    chemical_inventory_from_dict,
    consumable_inventory_from_dict,
    equipment_inventory_from_dict,
    is_crude,
    load_species_catalog,
    load_starting_inventories,
    pure_name_for,
)

REAL_CHEMICALS_PATH = os.path.join(os.path.dirname(__file__), "..", "src", "data", "chemicals.json")
REAL_STARTING_INVENTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "src", "data", "starting_inventory.json")

# A small hand-built catalog for tests that don't want to depend on the
# real game data: a solid, a plain liquid, and a solution.
SAMPLE_CATALOG = {
    "sodium cyanide": ChemicalSpecies(name="sodium cyanide", state="solid", molecular_weight=49.01),
    "ethanol": ChemicalSpecies(name="ethanol", state="liquid", molarity=17.13),
    "ethyl bromide": ChemicalSpecies(name="ethyl bromide", state="liquid", molarity=13.4),
    "48% hydrobromic acid": ChemicalSpecies(
        name="48% hydrobromic acid", state="solution", solute="HBr", solvent="water", molarity=8.8,
    ),
}


class TestChemicalSpecies(unittest.TestCase):

    def test_solid_moles_per_unit_uses_molecular_weight(self):
        species = ChemicalSpecies(name="sodium cyanide", state="solid", molecular_weight=49.01)
        self.assertAlmostEqual(species.moles_per_unit(), 1 / 49.01, places=6)
        self.assertEqual(species.unit_label(), "g")

    def test_liquid_moles_per_unit_uses_molarity(self):
        species = ChemicalSpecies(name="ethanol", state="liquid", molarity=17.13)
        self.assertAlmostEqual(species.moles_per_unit(), 17.13 / 1000, places=6)
        self.assertEqual(species.unit_label(), "mL")

    def test_solution_moles_per_unit_uses_molarity_too(self):
        species = ChemicalSpecies(
            name="48% hydrobromic acid", state="solution", solute="HBr", solvent="water", molarity=8.8,
        )
        self.assertAlmostEqual(species.moles_per_unit(), 8.8 / 1000, places=6)
        self.assertEqual(species.unit_label(), "mL")

    def test_solid_without_molecular_weight_rejected(self):
        with self.assertRaises(ValueError):
            ChemicalSpecies(name="mystery solid", state="solid")

    def test_liquid_without_molarity_rejected(self):
        with self.assertRaises(ValueError):
            ChemicalSpecies(name="mystery liquid", state="liquid")

    def test_solution_without_solute_rejected(self):
        with self.assertRaises(ValueError):
            ChemicalSpecies(name="mystery solution", state="solution", molarity=1.0)

    def test_unknown_state_rejected(self):
        with self.assertRaises(ValueError):
            ChemicalSpecies(name="mystery", state="plasma", molarity=1.0)

    def test_load_species_catalog_from_file(self):
        catalog = load_species_catalog(REAL_CHEMICALS_PATH)
        self.assertIn("ethyl bromide", catalog)
        self.assertEqual(catalog["ethyl bromide"].state, "liquid")
        self.assertEqual(catalog["48% hydrobromic acid"].solute, "HBr")


class TestCrudeNaming(unittest.TestCase):

    def test_is_crude(self):
        self.assertTrue(is_crude("ethyl bromide (crude)"))
        self.assertFalse(is_crude("ethyl bromide"))

    def test_pure_name_for(self):
        self.assertEqual(pure_name_for("ethyl bromide (crude)"), "ethyl bromide")

    def test_pure_name_for_rejects_non_crude(self):
        with self.assertRaises(NotCrudeError):
            pure_name_for("ethyl bromide")


class TestChemicalInventoryRawUnits(unittest.TestCase):
    """The low-level add()/remove()/has() API: unit-agnostic, no species
    catalog required -- what purification.py relies on."""

    def test_add_and_has_without_species_catalog(self):
        inv = ChemicalInventory()
        inv.add("ethanol", 100.0)
        self.assertTrue(inv.has("ethanol", 100.0))
        self.assertFalse(inv.has("ethanol", 100.1))

    def test_remove_below_zero_raises(self):
        inv = ChemicalInventory()
        inv.add("ethanol", 50.0)
        with self.assertRaises(ValueError):
            inv.remove("ethanol", 100.0)

    def test_remove_draining_to_zero_deletes_key(self):
        inv = ChemicalInventory()
        inv.add("ethanol", 50.0)
        inv.remove("ethanol", 50.0)
        self.assertNotIn("ethanol", inv.contents)


class TestChemicalInventoryMoles(unittest.TestCase):
    """The moles-based API, which needs a species catalog."""

    def setUp(self):
        self.inv = ChemicalInventory(species_catalog=SAMPLE_CATALOG)

    def test_moles_of_solid(self):
        self.inv.add("sodium cyanide", 100.0)  # grams
        self.assertAlmostEqual(self.inv.moles_of("sodium cyanide"), 100.0 / 49.01, places=4)

    def test_moles_of_liquid(self):
        self.inv.add("ethanol", 350.0)  # mL
        self.assertAlmostEqual(self.inv.moles_of("ethanol"), 350.0 * 17.13 / 1000, places=4)

    def test_moles_of_missing_chemical_is_zero(self):
        self.assertEqual(self.inv.moles_of("ethanol"), 0.0)

    def test_moles_of_strips_crude_suffix(self):
        self.inv.add("ethyl bromide (crude)", 100.0)
        self.assertAlmostEqual(self.inv.moles_of("ethyl bromide (crude)"), 100.0 * 13.4 / 1000, places=4)

    def test_describe_formats_amount_and_moles(self):
        self.inv.add("sodium cyanide", 100.0)
        text = self.inv.describe("sodium cyanide")
        self.assertIn("100.0 g", text)
        self.assertIn("mol", text)

    def test_resolve_supplier_direct_name_match(self):
        self.inv.add("ethanol", 100.0)
        self.assertEqual(self.inv.resolve_supplier("ethanol"), "ethanol")

    def test_resolve_supplier_through_solution_solute(self):
        self.inv.add("48% hydrobromic acid", 700.0)
        self.assertEqual(self.inv.resolve_supplier("HBr"), "48% hydrobromic acid")

    def test_resolve_supplier_returns_none_when_absent(self):
        self.assertIsNone(self.inv.resolve_supplier("HBr"))

    def test_available_moles_through_solution(self):
        self.inv.add("48% hydrobromic acid", 700.0)
        self.assertAlmostEqual(self.inv.available_moles("HBr"), 700.0 * 8.8 / 1000, places=4)

    def test_has_moles_through_solution(self):
        self.inv.add("48% hydrobromic acid", 700.0)  # ~6.16 mol HBr
        self.assertTrue(self.inv.has_moles("HBr", 6.0))
        self.assertFalse(self.inv.has_moles("HBr", 7.0))

    def test_remove_moles_draws_down_the_solution_not_a_phantom_hbr_entry(self):
        self.inv.add("48% hydrobromic acid", 700.0)
        self.inv.remove_moles("HBr", 1.0)  # ~113.6 mL worth
        self.assertNotIn("HBr", self.inv.contents)
        remaining_moles = self.inv.moles_of("48% hydrobromic acid")
        self.assertAlmostEqual(remaining_moles, 700.0 * 8.8 / 1000 - 1.0, places=4)

    def test_remove_moles_raises_when_insufficient(self):
        self.inv.add("48% hydrobromic acid", 700.0)
        with self.assertRaises(ValueError):
            self.inv.remove_moles("HBr", 100.0)

    def test_remove_moles_raises_when_nothing_supplies_it(self):
        with self.assertRaises(ValueError):
            self.inv.remove_moles("HBr", 1.0)

    def test_add_moles_converts_to_native_units(self):
        self.inv.add_moles("ethanol", 1.0)
        self.assertAlmostEqual(self.inv.contents["ethanol"], 1000 / 17.13, places=4)

    def test_add_moles_of_crude_product_uses_pure_species(self):
        self.inv.add_moles("ethyl bromide (crude)", 1.0)
        self.assertAlmostEqual(self.inv.contents["ethyl bromide (crude)"], 1000 / 13.4, places=4)


class TestInventoryLoaders(unittest.TestCase):

    def test_chemical_inventory_from_dict(self):
        inv = chemical_inventory_from_dict({"ethanol": 350.0, "sodium cyanide": 100.0}, SAMPLE_CATALOG)
        self.assertTrue(inv.has("ethanol", 350.0))
        self.assertTrue(inv.has_moles("ethanol", 5.0))
        self.assertTrue(inv.has_moles("sodium cyanide", 2.0))

    def test_equipment_inventory_from_dict_assigns_ids_and_defaults(self):
        equip = equipment_inventory_from_dict([
            {"type": "rb_flask", "name": "250 mL RB Flask", "capacity": 2.0},
            {"type": "condenser", "name": "Reflux Condenser"},
        ])
        flasks = equip.available_items("rb_flask")
        self.assertEqual(len(flasks), 1)
        self.assertEqual(flasks[0].capacity, 2.0)
        self.assertFalse(flasks[0].in_use)

        condensers = equip.available_items("condenser")
        self.assertEqual(len(condensers), 1)
        self.assertIsNone(condensers[0].capacity)

    def test_equipment_inventory_from_dict_respects_explicit_id_and_in_use(self):
        # This is the shape a future save file would use: explicit id/in_use
        # so identity and reservation state survive a load.
        equip = equipment_inventory_from_dict([
            {"type": "rb_flask", "name": "250 mL RB Flask", "capacity": 2.0,
             "id": "rb_flask_saved", "in_use": True},
        ])
        item = equip.items["rb_flask_saved"]
        self.assertTrue(item.in_use)
        # An in-use item should not show up as available
        self.assertEqual(equip.available_items("rb_flask"), [])

    def test_load_starting_inventories_from_file_with_explicit_catalog(self):
        data = {
            "chemicals": {"ethanol": 350.0, "sodium cyanide": 100.0},
            "equipment": [
                {"type": "rb_flask", "name": "250 mL RB Flask", "capacity": 2.0},
                {"type": "condenser", "name": "Reflux Condenser"},
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, dir=tempfile.gettempdir()) as f:
            json.dump(data, f)
            path = f.name

        try:
            chemicals, equipment, consumables = load_starting_inventories(path, species_catalog_path=REAL_CHEMICALS_PATH)
            self.assertTrue(chemicals.has("ethanol", 350.0))
            self.assertTrue(chemicals.has_moles("sodium cyanide", 2.0))
            self.assertEqual(len(equipment.available_items("rb_flask")), 1)
            self.assertEqual(consumables.contents, {})  # no "consumables" key in this test's data
        finally:
            os.remove(path)

    def test_load_starting_inventories_default_species_catalog_path(self):
        # species_catalog_path defaults to "chemicals.json" alongside the
        # starting-inventory file -- exercised here with the real data files,
        # which live side by side in src/data/.
        chemicals, _, _ = load_starting_inventories(REAL_STARTING_INVENTORY_PATH)
        self.assertTrue(chemicals.has_moles("HBr", 1.0))  # via the HBr solution
        self.assertTrue(chemicals.has_moles("ethanol", 1.0))

    def test_starting_inventory_data_file_loads_and_has_full_rig(self):
        # Guards against src/data/starting_inventory.json drifting out of
        # sync with what reactions.json actually requires.
        chemicals, equipment, consumables = load_starting_inventories(REAL_STARTING_INVENTORY_PATH)

        for chem in ("HBr", "ethanol"):
            self.assertTrue(chemicals.has_moles(chem, 1.0), f"missing starting {chem}")

        for equip_type in ("rb_flask", "condenser", "tubing",
                            "heating_mantle", "stir_bar", "magnetic_stirrer", "glass_column"):
            self.assertTrue(equipment.available_items(equip_type),
                             f"missing starting {equip_type}")

        self.assertTrue(chemicals.has("diethyl ether", 1.0), "missing starting diethyl ether")
        self.assertTrue(consumables.has("silica", 1.0), "missing starting silica")

    def test_starting_inventory_has_multiple_of_each_equipment(self):
        # The starting loadout is meant to support running more than one
        # reaction at once -- guards against dropping back to a single
        # rig per type.
        _, equipment, _ = load_starting_inventories(REAL_STARTING_INVENTORY_PATH)

        for equip_type in ("rb_flask", "condenser", "tubing",
                            "heating_mantle", "stir_bar", "magnetic_stirrer"):
            count = len(equipment.available_items(equip_type))
            self.assertGreaterEqual(count, 2, f"expected at least 2 starting {equip_type}, got {count}")


class TestEquipmentMissingTypes(unittest.TestCase):

    def test_reports_only_actually_missing_types(self):
        equip = EquipmentInventory()
        equip.add_item("rb_flask", "250 mL RB Flask", capacity=2.0)
        equip.add_item("tubing", "Rubber Tubing")

        missing = equip.missing_types(
            ["rb_flask", "condenser", "tubing", "heating_mantle"], min_flask_capacity=2.0
        )
        self.assertEqual(set(missing), {"condenser", "heating_mantle"})

    def test_flask_present_but_too_small_counts_as_missing(self):
        equip = EquipmentInventory()
        equip.add_item("rb_flask", "100 mL RB Flask", capacity=1.0)

        missing = equip.missing_types(["rb_flask"], min_flask_capacity=2.0)
        self.assertEqual(missing, ["rb_flask"])

    def test_in_use_item_counts_as_missing(self):
        equip = EquipmentInventory()
        item = equip.add_item("condenser", "Reflux Condenser")
        item.in_use = True

        missing = equip.missing_types(["condenser"])
        self.assertEqual(missing, ["condenser"])

    def test_does_not_reserve_anything(self):
        equip = EquipmentInventory()
        equip.add_item("condenser", "Reflux Condenser")

        equip.missing_types(["condenser"])
        self.assertEqual(equip.available_items("condenser").__len__(), 1)


class TestConsumableInventory(unittest.TestCase):

    def test_add_and_has(self):
        inv = ConsumableInventory()
        inv.add("silica", 50.0)
        self.assertTrue(inv.has("silica", 50.0))
        self.assertFalse(inv.has("silica", 50.1))

    def test_remove_deducts_and_drops_empty_entries(self):
        inv = ConsumableInventory()
        inv.add("silica", 10.0)
        inv.remove("silica", 10.0)
        self.assertNotIn("silica", inv.contents)
        self.assertFalse(inv.has("silica", 0.01))

    def test_remove_more_than_available_raises_and_changes_nothing(self):
        inv = ConsumableInventory()
        inv.add("silica", 5.0)
        with self.assertRaises(ValueError):
            inv.remove("silica", 6.0)
        self.assertEqual(inv.contents["silica"], 5.0)

    def test_consumable_inventory_from_dict(self):
        inv = consumable_inventory_from_dict({"silica": 50.0})
        self.assertTrue(inv.has("silica", 50.0))


class TestSolventTag(unittest.TestCase):

    def test_is_solvent_defaults_to_false(self):
        species = ChemicalSpecies(name="ethanol", state="liquid", molarity=17.13)
        self.assertFalse(species.is_solvent)

    def test_is_solvent_can_be_set_and_species_stays_a_normal_reagent(self):
        species = ChemicalSpecies(name="diethyl ether", state="liquid", molarity=9.63, is_solvent=True)
        self.assertTrue(species.is_solvent)
        # Being tagged a solvent doesn't change how it converts to moles --
        # it's still an ordinary liquid species, usable as any reagent is.
        self.assertAlmostEqual(species.moles_per_unit(), 9.63 / 1000.0, places=6)


if __name__ == "__main__":
    unittest.main()
