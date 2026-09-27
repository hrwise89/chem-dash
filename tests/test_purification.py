import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from game_clock import GameClock  # noqa: E402
from inventory import (  # noqa: E402
    ChemicalInventory,
    ConsumableInventory,
    EquipmentInventory,
)
from purification import (  # noqa: E402
    AUTO_PURIFY_MAX_YIELD,
    AUTO_PURIFY_MIN_YIELD,
    AUTO_PURIFY_TIME_COST_HOURS,
    DIETHYL_ETHER_NAME,
    DIETHYL_ETHER_REQUIRED_ML,
    SILICA_NAME,
    SILICA_REQUIRED_G,
    NotCrudeError,
    auto_purify,
    is_crude,
    pure_name_for,
)


class TestPurificationHelpers(unittest.TestCase):

    def test_is_crude(self):
        self.assertTrue(is_crude("ethyl bromide (crude)"))
        self.assertFalse(is_crude("ethyl bromide"))

    def test_pure_name_for(self):
        self.assertEqual(pure_name_for("ethyl bromide (crude)"), "ethyl bromide")

    def test_pure_name_for_rejects_non_crude(self):
        with self.assertRaises(NotCrudeError):
            pure_name_for("ethyl bromide")


class TestAutoPurify(unittest.TestCase):

    def setUp(self):
        self.inventory = ChemicalInventory()
        self.inventory.add("ethyl bromide (crude)", 1.0)
        self.inventory.add(DIETHYL_ETHER_NAME, DIETHYL_ETHER_REQUIRED_ML * 2)
        self.equipment = EquipmentInventory()
        self.equipment.add_item("glass_column", "Glass Column")
        self.consumables = ConsumableInventory()
        self.consumables.add(SILICA_NAME, SILICA_REQUIRED_G * 2)
        self.clock = GameClock()
        self.rng = random.Random(1234)  # deterministic for these tests

    def purify(self, amount=1.0, **kwargs):
        return auto_purify(
            self.inventory, self.equipment, self.consumables, self.clock,
            "ethyl bromide (crude)", amount, rng=self.rng, **kwargs,
        )

    def test_converts_crude_to_pure_within_yield_range(self):
        pure_name, amount, yield_fraction = self.purify()
        self.assertEqual(pure_name, "ethyl bromide")
        self.assertGreaterEqual(yield_fraction, AUTO_PURIFY_MIN_YIELD)
        self.assertLessEqual(yield_fraction, AUTO_PURIFY_MAX_YIELD)
        self.assertAlmostEqual(amount, 1.0 * yield_fraction, places=6)

    def test_consumes_only_the_requested_amount_of_crude_stock(self):
        self.inventory.add("ethyl bromide (crude)", 1.0)  # now have 2.0 total
        self.purify(amount=1.0)
        self.assertTrue(self.inventory.has("ethyl bromide (crude)", 1.0 - 1e-6))
        self.assertFalse(self.inventory.has("ethyl bromide (crude)", 1.1))

    def test_adds_purified_amount_to_pure_stock(self):
        _, amount, _ = self.purify()
        self.assertTrue(self.inventory.has("ethyl bromide", amount - 1e-9))

    def test_advances_game_clock_by_time_cost(self):
        start = self.clock.now()
        self.purify()
        self.assertAlmostEqual(self.clock.now(), start + AUTO_PURIFY_TIME_COST_HOURS, places=6)

    def test_consumes_fixed_silica_and_ether_regardless_of_amount(self):
        self.purify(amount=1.0)
        self.assertAlmostEqual(self.consumables.contents[SILICA_NAME], SILICA_REQUIRED_G, places=6)
        self.assertAlmostEqual(
            self.inventory.contents[DIETHYL_ETHER_NAME], DIETHYL_ETHER_REQUIRED_ML, places=6
        )

    def test_column_is_not_consumed(self):
        self.purify()
        self.assertEqual(len(self.equipment.available_items("glass_column")), 1)

    def test_custom_time_cost_and_yield_range(self):
        _, amount, yield_fraction = self.purify(min_yield=0.5, max_yield=0.5, time_cost_hours=1.0)
        self.assertAlmostEqual(yield_fraction, 0.5, places=6)
        self.assertAlmostEqual(amount, 0.5, places=6)
        self.assertAlmostEqual(self.clock.now(), 1.0, places=6)

    def test_rejects_non_crude_chemical(self):
        self.inventory.add("HBr", 1.0)
        with self.assertRaises(NotCrudeError):
            auto_purify(self.inventory, self.equipment, self.consumables, self.clock, "HBr", 1.0, rng=self.rng)

    def test_raises_if_nothing_to_purify(self):
        empty_inventory = ChemicalInventory()
        empty_inventory.add(DIETHYL_ETHER_NAME, DIETHYL_ETHER_REQUIRED_ML)
        with self.assertRaises(ValueError):
            auto_purify(
                empty_inventory, self.equipment, self.consumables, self.clock,
                "ethyl bromide (crude)", 1.0, rng=self.rng,
            )

    def test_raises_if_amount_exceeds_stock(self):
        with self.assertRaises(ValueError):
            self.purify(amount=2.0)  # only 1.0 mol on hand

    def test_raises_without_a_glass_column(self):
        self.equipment = EquipmentInventory()  # no column added
        with self.assertRaises(ValueError):
            self.purify()

    def test_raises_without_enough_silica(self):
        self.consumables = ConsumableInventory()
        self.consumables.add(SILICA_NAME, SILICA_REQUIRED_G - 1)
        with self.assertRaises(ValueError):
            self.purify()
        # Nothing should have been consumed on a rejected attempt.
        self.assertAlmostEqual(self.consumables.contents[SILICA_NAME], SILICA_REQUIRED_G - 1, places=6)

    def test_raises_without_enough_diethyl_ether(self):
        self.inventory = ChemicalInventory()
        self.inventory.add("ethyl bromide (crude)", 1.0)
        self.inventory.add(DIETHYL_ETHER_NAME, DIETHYL_ETHER_REQUIRED_ML - 1)
        with self.assertRaises(ValueError):
            self.purify()

    def test_failed_attempt_does_not_consume_crude(self):
        self.equipment = EquipmentInventory()  # missing column -> rejected
        with self.assertRaises(ValueError):
            self.purify()
        self.assertTrue(self.inventory.has("ethyl bromide (crude)", 1.0 - 1e-9))

    def test_yield_is_randomized_across_calls(self):
        # Not a strict guarantee (could theoretically collide), but with a
        # real RNG and a continuous range this is effectively certain not
        # to produce the exact same yield twice.
        yields = []
        for _ in range(5):
            self.inventory.add("ethyl bromide (crude)", 1.0)
            self.consumables.add(SILICA_NAME, SILICA_REQUIRED_G)
            self.inventory.add(DIETHYL_ETHER_NAME, DIETHYL_ETHER_REQUIRED_ML)
            _, _, y = self.purify(amount=1.0)
            yields.append(y)
        self.assertGreater(len(set(yields)), 1)


if __name__ == "__main__":
    unittest.main()
