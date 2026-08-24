import unittest
from src.reaction_engine import ReactionEngine, Inventory

class TestReactionEngine(unittest.TestCase):

    def setUp(self):
        # Pass the path to the reaction JSON file
        self.engine = ReactionEngine("src/data/reactions.json")

    # --- Helper function to create a fresh inventory ---
    def make_inventory(self, **kwargs):
        """
        Returns a new Inventory object preloaded with chemicals
        """
        inv = Inventory()
        for chem, amt in kwargs.items():
            inv.add(chem, amt)
        return inv

    # --- Original tests updated to use make_inventory and (crude) suffix ---
    def test_valid_reaction_ideal_conditions(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        products = self.engine.run_reaction(inventory, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0)
        self.assertAlmostEqual(products["ethyl bromide (crude)"], 1.0, places=2)
        self.assertAlmostEqual(products["water"], 1.0, places=2)

    def test_temperature_too_high_reduces_yield(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        products = self.engine.run_reaction(inventory, {"HBr": 1.0, "ethanol": 1.0}, "neat", 50.0, 4.0)
        self.assertLess(products["ethyl bromide (crude)"], 1.0)
        self.assertGreater(products["ethyl bromide (crude)"], 0.4)

    def test_wrong_solvent_penalty(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        products = self.engine.run_reaction(inventory, {"HBr": 1.0, "ethanol": 1.0}, "toluene", 20.0, 4.0)
        self.assertLess(products["ethyl bromide (crude)"], 1.0)

    def test_time_too_short_reduces_yield(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=1.0)
        products = self.engine.run_reaction(inventory, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 1.0)
        self.assertLess(products["ethyl bromide (crude)"], 1.0)

    def test_unmatched_reaction_returns_unknown(self):
        inventory = self.make_inventory(NaOH=1.0, ethanol=1.0)
        products = self.engine.run_reaction(inventory, {"NaOH": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0)
        self.assertIn("unknown mixture", products)

    def test_reagent_limit_check(self):
        inventory = self.make_inventory(HBr=3.0, ethanol=1.0)
        with self.assertRaises(ValueError):
            self.engine.run_reaction(inventory, {"HBr": 3.0, "ethanol": 1.0}, "neat", 20.0, 4.0)

    def test_limiting_reagent(self):
        inventory = self.make_inventory(HBr=2.0, ethanol=1.0)
        products = self.engine.run_reaction(inventory, {"HBr": 2.0, "ethanol": 1.0}, "neat", 20.0, 4.0)
        self.assertAlmostEqual(products["ethyl bromide (crude)"], 1.0, places=2)

    def test_side_products_not_added_to_inventory(self):
        inventory = self.make_inventory(HBr=2.0, ethanol=2.0)
        products = self.engine.run_reaction(inventory, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0)
        self.assertIn("ethyl bromide (crude)", products)
        self.assertIn("water", products)
        self.assertNotIn("water (crude)", products)

    def test_new_reaction_ethylnitrile(self):
        inventory = self.make_inventory(**{"sodium cyanide": 1.0, "ethyl bromide": 1.0})
        products = self.engine.run_reaction(
            inventory,
            {"sodium cyanide": 1.0, "ethyl bromide": 1.0},
            "toluene",
            40.0,
            4.0
        )
        self.assertAlmostEqual(products["ethyl cyanide (crude)"], 1.0, places=2)
        self.assertAlmostEqual(products["sodium bromide"], 1.0, places=2)

    def test_insufficient_inventory_raises(self):
        inventory = self.make_inventory(HBr=0.5, ethanol=1.0)
        with self.assertRaises(ValueError):
            self.engine.run_reaction(inventory, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20.0, 4.0)

    def test_partial_reaction_efficiency(self):
        inventory = self.make_inventory(HBr=1.0, ethanol=2.0)
        products = self.engine.run_reaction(inventory, {"HBr": 1.0, "ethanol": 2.0}, "neat", 20.0, 4.0)
        self.assertAlmostEqual(products["ethyl bromide (crude)"], 1.0, places=2)


if __name__ == "__main__":
    unittest.main()