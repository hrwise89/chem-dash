"""
Cross-file sanity checks on the static game data (src/data/*.json) that
nothing else enforces at load time -- reactions.json/contracts.json don't
validate their own chemical-name references against chemicals.json, so a
typo or a new entry that forgets to add a species definition would only
surface as a KeyError deep inside some menu at play time (economy.
order_row_lines and friends have no fallback for an unknown contract
product, unlike reaction_engine's own display code, which tolerates an
unresolvable identity by falling back to showing it verbatim -- see
shared_sections.display_name). Catching that here, once, as a fast
headless test, matters more as these files grow past their current
handful of entries.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import json

from inventory import load_consumable_catalog, load_equipment_catalog, load_species_catalog, load_starting_inventories
from reaction_engine import ReactionEngine

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "data")


class TestReactionDataAgainstSpeciesCatalog(unittest.TestCase):

    def setUp(self):
        self.species = load_species_catalog(os.path.join(DATA_DIR, "chemicals.json"))
        self.engine = ReactionEngine(os.path.join(DATA_DIR, "reactions.json"))
        # Every identity a species' `solute` field names is also a valid
        # thing for a reactant to resolve to (see ChemicalInventory.
        # resolve_supplier) even though it has no species entry of its own
        # (e.g. "HBr", supplied by "48% hydrobromic acid").
        self.solutes = {s.solute for s in self.species.values() if s.solute}

    def test_every_product_has_a_species_entry(self):
        """A reaction's product is added to inventory by name (add_moles)
        and looked up by name everywhere it's displayed -- unlike a
        reactant, it has no solute-based fallback, so a missing entry here
        is a real bug, not just a display quirk."""
        for reaction_name, definition in self.engine.reaction_db.items():
            for product in definition.products:
                self.assertIn(product, self.species,
                               f"'{reaction_name}' produces '{product}', which chemicals.json has no entry for")

    def test_every_side_product_has_a_species_entry(self):
        for reaction_name, definition in self.engine.reaction_db.items():
            for side in definition.side_products:
                self.assertIn(side, self.species,
                               f"'{reaction_name}' has side product '{side}', which chemicals.json has no entry for")

    def test_every_reactant_is_resolvable(self):
        """A reactant either has its own species entry, or is some other
        species' `solute` (resolved through a solution that supplies it,
        e.g. "HBr" via "48% hydrobromic acid") -- either way, something in
        chemicals.json has to actually be able to supply it."""
        for reaction_name, definition in self.engine.reaction_db.items():
            for reactant in definition.reactants:
                resolvable = reactant in self.species or reactant in self.solutes
                self.assertTrue(resolvable,
                                 f"'{reaction_name}' needs '{reactant}', which nothing in chemicals.json supplies")


class TestContractDataAgainstSpeciesCatalog(unittest.TestCase):

    def setUp(self):
        self.species = load_species_catalog(os.path.join(DATA_DIR, "chemicals.json"))
        with open(os.path.join(DATA_DIR, "contracts.json")) as f:
            self.contracts = json.load(f)

    def test_every_contract_product_has_a_species_entry(self):
        """order_row_lines/order_product_desc call inventory.species_for()
        on a contract's product with no fallback -- a product name that
        doesn't match chemicals.json would crash the Orders screen (the
        notebook, the shipping bench, the contract inbox) the moment that
        contract is shown, not just fail to display nicely."""
        for order_id, data in self.contracts.items():
            product = data.get("product")
            self.assertIn(product, self.species,
                           f"contract '{order_id}' orders '{product}', which chemicals.json has no entry for")


class TestStartingInventoryAgainstCatalogs(unittest.TestCase):
    """The default starting loadout (src/data/starting_inventory.json)
    references chemicals/equipment/consumables by name -- each has to
    actually match a catalog entry, or the notebook's/reaction bench's
    Inventory screens (which look descriptions up by that same name) would
    show "(no description yet)" at best, or crash at worst."""

    def setUp(self):
        self.chemicals, self.equipment, self.consumables = load_starting_inventories(
            "src/data/starting_inventory.json")
        self.equipment_catalog = load_equipment_catalog("src/data/equipment.json")
        self.consumable_catalog = load_consumable_catalog("src/data/consumables.json")

    def test_every_starting_chemical_has_a_species_entry(self):
        for name in self.chemicals.contents:
            self.assertIn(name, self.chemicals.species_catalog,
                           f"starting inventory has '{name}', which chemicals.json has no entry for")

    def test_every_starting_equipment_type_is_in_the_catalog(self):
        catalog_types = {entry.type for entry in self.equipment_catalog.values()}
        for item in self.equipment.items.values():
            self.assertIn(item.type, catalog_types,
                           f"starting equipment '{item.name}' has type '{item.type}', "
                           f"which equipment.json has no entry for")

    def test_every_starting_consumable_is_in_the_catalog(self):
        for name in self.consumables.contents:
            self.assertIn(name, self.consumable_catalog,
                           f"starting inventory has '{name}', which consumables.json has no entry for")


if __name__ == "__main__":
    unittest.main()
