import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from inventory import (  # noqa: E402
    EquipmentInventory,
    chemical_inventory_from_dict,
    equipment_inventory_from_dict,
    load_starting_inventories,
)


class TestInventoryLoaders(unittest.TestCase):

    def test_chemical_inventory_from_dict(self):
        inv = chemical_inventory_from_dict({"HBr": 2.0, "ethanol": 1.5})
        self.assertTrue(inv.has("HBr", 2.0))
        self.assertTrue(inv.has("ethanol", 1.5))
        self.assertFalse(inv.has("HBr", 2.1))

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

    def test_load_starting_inventories_from_file(self):
        data = {
            "chemicals": {"HBr": 2.0, "ethanol": 2.0},
            "equipment": [
                {"type": "rb_flask", "name": "250 mL RB Flask", "capacity": 2.0},
                {"type": "condenser", "name": "Reflux Condenser"},
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name

        try:
            chemicals, equipment = load_starting_inventories(path)
            self.assertTrue(chemicals.has("HBr", 2.0))
            self.assertEqual(len(equipment.available_items("rb_flask")), 1)
        finally:
            os.remove(path)

    def test_starting_inventory_data_file_loads_and_has_full_rig(self):
        # Guards against src/data/starting_inventory.json drifting out of
        # sync with what reactions.json actually requires.
        path = os.path.join(os.path.dirname(__file__), "..", "src", "data", "starting_inventory.json")
        chemicals, equipment = load_starting_inventories(path)

        for chem in ("HBr", "ethanol"):
            self.assertTrue(chemicals.has(chem, 1.0), f"missing starting {chem}")

        for equip_type in ("rb_flask", "condenser", "tubing",
                            "heating_mantle", "stir_bar", "magnetic_stirrer"):
            self.assertTrue(equipment.available_items(equip_type),
                             f"missing starting {equip_type}")


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


if __name__ == "__main__":
    unittest.main()
