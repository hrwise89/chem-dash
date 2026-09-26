import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from game_clock import GameClock  # noqa: E402
from inventory import ChemicalInventory  # noqa: E402
from purification import (  # noqa: E402
    AUTO_PURIFY_MAX_YIELD,
    AUTO_PURIFY_MIN_YIELD,
    AUTO_PURIFY_TIME_COST_HOURS,
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
        self.clock = GameClock()
        self.rng = random.Random(1234)  # deterministic for these tests

    def test_converts_crude_to_pure_within_yield_range(self):
        pure_name, amount, yield_fraction = auto_purify(
            self.inventory, self.clock, "ethyl bromide (crude)", rng=self.rng
        )
        self.assertEqual(pure_name, "ethyl bromide")
        self.assertGreaterEqual(yield_fraction, AUTO_PURIFY_MIN_YIELD)
        self.assertLessEqual(yield_fraction, AUTO_PURIFY_MAX_YIELD)
        self.assertAlmostEqual(amount, 1.0 * yield_fraction, places=6)

    def test_consumes_all_crude_stock(self):
        auto_purify(self.inventory, self.clock, "ethyl bromide (crude)", rng=self.rng)
        self.assertFalse(self.inventory.has("ethyl bromide (crude)", 0.001))

    def test_adds_purified_amount_to_pure_stock(self):
        _, amount, _ = auto_purify(self.inventory, self.clock, "ethyl bromide (crude)", rng=self.rng)
        self.assertTrue(self.inventory.has("ethyl bromide", amount - 1e-9))

    def test_advances_game_clock_by_time_cost(self):
        start = self.clock.now()
        auto_purify(self.inventory, self.clock, "ethyl bromide (crude)", rng=self.rng)
        self.assertAlmostEqual(self.clock.now(), start + AUTO_PURIFY_TIME_COST_HOURS, places=6)

    def test_custom_time_cost_and_yield_range(self):
        _, amount, yield_fraction = auto_purify(
            self.inventory, self.clock, "ethyl bromide (crude)",
            min_yield=0.5, max_yield=0.5, time_cost_hours=1.0, rng=self.rng,
        )
        self.assertAlmostEqual(yield_fraction, 0.5, places=6)
        self.assertAlmostEqual(amount, 0.5, places=6)
        self.assertAlmostEqual(self.clock.now(), 1.0, places=6)

    def test_rejects_non_crude_chemical(self):
        self.inventory.add("HBr", 1.0)
        with self.assertRaises(NotCrudeError):
            auto_purify(self.inventory, self.clock, "HBr", rng=self.rng)

    def test_raises_if_nothing_to_purify(self):
        empty_inventory = ChemicalInventory()
        with self.assertRaises(ValueError):
            auto_purify(empty_inventory, self.clock, "ethyl bromide (crude)", rng=self.rng)

    def test_yield_is_randomized_across_calls(self):
        # Not a strict guarantee (could theoretically collide), but with a
        # real RNG and a continuous range this is effectively certain not
        # to produce the exact same yield twice.
        inv = ChemicalInventory()
        yields = []
        for _ in range(5):
            inv.add("ethyl bromide (crude)", 1.0)
            _, _, y = auto_purify(inv, self.clock, "ethyl bromide (crude)")
            yields.append(y)
        self.assertGreater(len(set(yields)), 1)


if __name__ == "__main__":
    unittest.main()
