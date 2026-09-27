import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from game_clock import GameClock  # noqa: E402
from inventory import (  # noqa: E402
    ChemicalInventory,
    ChemicalSpecies,
    ConsumableInventory,
    EquipmentInventory,
)
from purification import (  # noqa: E402
    BENCH_SCALE,
    COLUMN_CHROMATOGRAPHY,
    DISTILLATION,
    MICRO_SCALE,
    REAGENT_SOLVENT_NAME,
    SILICA_NAME,
    TECHNICAL_SOLVENT_NAME,
    NotCrudeError,
    available_slider_values,
    is_crude,
    mass_grams,
    method_is_available,
    native_amount_for_mass,
    pure_name_for,
    purify,
    scale_is_available,
)

SPECIES_CATALOG = {
    "ethyl bromide": ChemicalSpecies(name="ethyl bromide", state="liquid", molarity=1000.0, density=2.0),
    "sodium bromide": ChemicalSpecies(name="sodium bromide", state="solid", molecular_weight=102.89),
}


class TestPurificationHelpers(unittest.TestCase):

    def test_is_crude(self):
        self.assertTrue(is_crude("ethyl bromide (crude)"))
        self.assertFalse(is_crude("ethyl bromide"))

    def test_pure_name_for(self):
        self.assertEqual(pure_name_for("ethyl bromide (crude)"), "ethyl bromide")

    def test_pure_name_for_rejects_non_crude(self):
        with self.assertRaises(NotCrudeError):
            pure_name_for("ethyl bromide")


class TestMassConversion(unittest.TestCase):

    def setUp(self):
        self.inventory = ChemicalInventory(species_catalog=SPECIES_CATALOG)

    def test_solid_mass_is_native_amount(self):
        self.assertAlmostEqual(mass_grams(self.inventory, "sodium bromide", 5.0), 5.0)
        self.assertAlmostEqual(native_amount_for_mass(self.inventory, "sodium bromide", 5.0), 5.0)

    def test_liquid_mass_uses_density(self):
        # density=2.0 g/mL -> 3 mL weighs 6 g
        self.assertAlmostEqual(mass_grams(self.inventory, "ethyl bromide", 3.0), 6.0)
        self.assertAlmostEqual(native_amount_for_mass(self.inventory, "ethyl bromide", 6.0), 3.0)

    def test_crude_name_shares_species_with_pure(self):
        self.assertAlmostEqual(mass_grams(self.inventory, "ethyl bromide (crude)", 3.0), 6.0)


class TestSliderValues(unittest.TestCase):

    def test_micro_slider_matches_spec(self):
        mg_values = [round(v * 1000, 3) for v in MICRO_SCALE.slider_values_g]
        self.assertEqual(mg_values[:11], [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55])
        self.assertIn(250.0, mg_values)
        self.assertEqual(mg_values[-1], 500.0)
        self.assertEqual(len(mg_values), len(set(mg_values)))  # no duplicated notches

    def test_bench_slider_matches_spec(self):
        self.assertEqual(BENCH_SCALE.slider_values_g[0], 0.5)
        self.assertEqual(BENCH_SCALE.slider_values_g[-1], 100.0)
        self.assertIn(20.0, BENCH_SCALE.slider_values_g)
        self.assertIn(10.0, BENCH_SCALE.slider_values_g)

    def test_available_slider_values_caps_at_stock(self):
        values = available_slider_values("bench", 12.5)
        self.assertEqual(values[-1], 12.0)
        self.assertNotIn(14.0, values)

    def test_available_slider_values_empty_below_smallest_notch(self):
        self.assertEqual(available_slider_values("bench", 0.1), [])
        self.assertEqual(available_slider_values("micro", 0.001), [])


class TestScaleAndMethodAvailability(unittest.TestCase):

    def setUp(self):
        self.equipment = EquipmentInventory()

    def test_micro_unavailable_without_equipment(self):
        self.assertFalse(scale_is_available("micro", self.equipment))

    def test_micro_available_with_chroma_column(self):
        self.equipment.add_item("chroma_column_micro", "Chromatography Column (Micro)")
        self.assertTrue(scale_is_available("micro", self.equipment))

    def test_micro_available_with_distill_column(self):
        self.equipment.add_item("distill_column_micro", "Distillation Column (Micro)")
        self.assertTrue(scale_is_available("micro", self.equipment))

    def test_pilot_and_production_always_disabled(self):
        self.equipment.add_item("chroma_column_micro", "x")
        self.equipment.add_item("chroma_column_bench", "x")
        self.assertFalse(scale_is_available("pilot", self.equipment))
        self.assertFalse(scale_is_available("production", self.equipment))

    def test_method_unavailable_without_its_own_column(self):
        self.equipment.add_item("chroma_column_micro", "Chromatography Column (Micro)")
        self.assertTrue(method_is_available("micro", COLUMN_CHROMATOGRAPHY, self.equipment))
        self.assertFalse(method_is_available("micro", DISTILLATION, self.equipment))

    def test_method_unavailable_if_scale_unavailable_even_with_column(self):
        # No equipment at all -> scale itself is unavailable, so neither
        # method should read as available regardless of column checks.
        self.assertFalse(method_is_available("micro", COLUMN_CHROMATOGRAPHY, self.equipment))

    def test_in_use_column_does_not_count_as_available(self):
        item = self.equipment.add_item("chroma_column_bench", "Chromatography Column (Bench)")
        item.in_use = True
        self.assertFalse(scale_is_available("bench", self.equipment))


class TestPurify(unittest.TestCase):

    def setUp(self):
        self.inventory = ChemicalInventory(species_catalog=SPECIES_CATALOG)
        self.inventory.add("ethyl bromide (crude)", 100.0)  # 100 mL * density 2.0 = 200 g
        self.equipment = EquipmentInventory()
        self.equipment.add_item("chroma_column_micro", "Chromatography Column (Micro)")
        self.equipment.add_item("distill_column_micro", "Distillation Column (Micro)")
        self.equipment.add_item("chroma_column_bench", "Chromatography Column (Bench)")
        self.equipment.add_item("distill_column_bench", "Distillation Column (Bench)")
        self.consumables = ConsumableInventory()
        self.consumables.add(SILICA_NAME, 1000.0)
        self.consumables.add(TECHNICAL_SOLVENT_NAME, 5000.0)
        self.consumables.add(REAGENT_SOLVENT_NAME, 5000.0)
        self.clock = GameClock()
        self.rng = random.Random(1234)

    def run_purify(self, scale, method, mass_g, **kwargs):
        return purify(
            scale, method, self.inventory, self.equipment, self.consumables, self.clock,
            "ethyl bromide (crude)", mass_g, rng=self.rng, **kwargs,
        )

    # --- Micro column chromatography ---

    def test_micro_column_chromatography_yield_range(self):
        pure_name, purified_mass_g, yield_fraction = self.run_purify("micro", COLUMN_CHROMATOGRAPHY, 0.05)
        self.assertEqual(pure_name, "ethyl bromide")
        self.assertGreaterEqual(yield_fraction, 0.85)
        self.assertLessEqual(yield_fraction, 1.00)
        self.assertAlmostEqual(purified_mass_g, 0.05 * yield_fraction, places=6)

    def test_micro_column_chromatography_base_cost(self):
        self.run_purify("micro", COLUMN_CHROMATOGRAPHY, 0.05)  # 50 mg = 1 "unit"
        self.assertAlmostEqual(self.consumables.contents[SILICA_NAME], 1000.0 - 11.0, places=6)
        self.assertAlmostEqual(self.consumables.contents[TECHNICAL_SOLVENT_NAME], 5000.0 - 27.0, places=6)

    def test_micro_column_chromatography_scales_with_amount(self):
        self.run_purify("micro", COLUMN_CHROMATOGRAPHY, 0.15)  # 150 mg = 3 units
        self.assertAlmostEqual(self.consumables.contents[SILICA_NAME], 1000.0 - 13.0, places=6)
        self.assertAlmostEqual(self.consumables.contents[TECHNICAL_SOLVENT_NAME], 5000.0 - 31.0, places=6)

    def test_micro_column_chromatography_time_cost(self):
        self.run_purify("micro", COLUMN_CHROMATOGRAPHY, 0.05)
        self.assertAlmostEqual(self.clock.now(), 20 / 60, places=6)

    def test_micro_distillation_yield_and_time(self):
        _, _, yield_fraction = self.run_purify("micro", DISTILLATION, 0.05)
        self.assertGreaterEqual(yield_fraction, 0.90)
        self.assertLessEqual(yield_fraction, 1.00)
        self.assertAlmostEqual(self.clock.now(), 15 / 60, places=6)

    def test_micro_distillation_uses_no_silica(self):
        self.run_purify("micro", DISTILLATION, 0.05)
        self.assertAlmostEqual(self.consumables.contents[SILICA_NAME], 1000.0, places=6)

    # --- Bench column chromatography ---

    def test_bench_column_chromatography_base_cost(self):
        self.run_purify("bench", COLUMN_CHROMATOGRAPHY, 1.0)  # 1 g = 1 unit
        self.assertAlmostEqual(self.consumables.contents[SILICA_NAME], 1000.0 - 26.0, places=6)
        self.assertAlmostEqual(self.consumables.contents[TECHNICAL_SOLVENT_NAME], 5000.0 - 103.0, places=6)

    def test_bench_column_chromatography_time_and_yield(self):
        _, _, yield_fraction = self.run_purify("bench", COLUMN_CHROMATOGRAPHY, 1.0)
        self.assertGreaterEqual(yield_fraction, 0.80)
        self.assertLessEqual(yield_fraction, 1.00)
        self.assertAlmostEqual(self.clock.now(), 1.0, places=6)

    def test_bench_distillation_time_and_yield(self):
        _, _, yield_fraction = self.run_purify("bench", DISTILLATION, 1.0)
        self.assertGreaterEqual(yield_fraction, 0.88)
        self.assertLessEqual(yield_fraction, 1.00)
        self.assertAlmostEqual(self.clock.now(), 0.75, places=6)

    def test_bench_distillation_uses_no_silica(self):
        self.run_purify("bench", DISTILLATION, 1.0)
        self.assertAlmostEqual(self.consumables.contents[SILICA_NAME], 1000.0, places=6)

    # --- Mass <-> native conversion round-trips through the crude stock ---

    def test_consumes_correct_native_amount_of_crude(self):
        # 50 g purified, density 2.0 -> 25 mL of the 100 mL on hand
        self.run_purify("bench", COLUMN_CHROMATOGRAPHY, 50.0)
        self.assertAlmostEqual(self.inventory.contents["ethyl bromide (crude)"], 75.0, places=6)

    def test_adds_purified_mass_converted_to_native_units(self):
        _, purified_mass_g, _ = self.run_purify("bench", COLUMN_CHROMATOGRAPHY, 50.0)
        expected_native = purified_mass_g / 2.0  # density 2.0
        self.assertAlmostEqual(self.inventory.contents["ethyl bromide"], expected_native, places=6)

    # --- Failure paths leave everything untouched ---

    def test_rejects_non_crude_chemical(self):
        self.inventory.add("ethyl bromide", 10.0)
        with self.assertRaises(NotCrudeError):
            purify("micro", COLUMN_CHROMATOGRAPHY, self.inventory, self.equipment, self.consumables,
                   self.clock, "ethyl bromide", 0.05, rng=self.rng)

    def test_rejects_disabled_scale(self):
        with self.assertRaises(ValueError):
            self.run_purify("pilot", COLUMN_CHROMATOGRAPHY, 0.05)

    def test_rejects_unavailable_method(self):
        equipment = EquipmentInventory()
        equipment.add_item("chroma_column_micro", "Chromatography Column (Micro)")
        with self.assertRaises(ValueError):
            purify("micro", DISTILLATION, self.inventory, equipment, self.consumables,
                   self.clock, "ethyl bromide (crude)", 0.05, rng=self.rng)

    def test_rejects_amount_exceeding_stock(self):
        with self.assertRaises(ValueError):
            self.run_purify("bench", COLUMN_CHROMATOGRAPHY, 10000.0)

    def test_rejects_non_positive_amount(self):
        with self.assertRaises(ValueError):
            self.run_purify("bench", COLUMN_CHROMATOGRAPHY, 0.0)

    def test_rejects_without_enough_silica(self):
        self.consumables = ConsumableInventory()
        self.consumables.add(SILICA_NAME, 1.0)
        self.consumables.add(TECHNICAL_SOLVENT_NAME, 5000.0)
        with self.assertRaises(ValueError):
            self.run_purify("bench", COLUMN_CHROMATOGRAPHY, 1.0)
        self.assertEqual(self.consumables.contents[SILICA_NAME], 1.0)

    def test_rejects_without_enough_solvent(self):
        self.consumables = ConsumableInventory()
        self.consumables.add(SILICA_NAME, 1000.0)
        self.consumables.add(TECHNICAL_SOLVENT_NAME, 1.0)
        with self.assertRaises(ValueError):
            self.run_purify("bench", COLUMN_CHROMATOGRAPHY, 1.0)

    def test_failed_attempt_does_not_consume_crude_or_advance_clock(self):
        with self.assertRaises(ValueError):
            self.run_purify("pilot", COLUMN_CHROMATOGRAPHY, 0.05)
        self.assertAlmostEqual(self.inventory.contents["ethyl bromide (crude)"], 100.0, places=6)
        self.assertEqual(self.clock.now(), 0.0)

    def test_yield_is_randomized_across_calls(self):
        yields = []
        for _ in range(5):
            self.inventory.add("ethyl bromide (crude)", 100.0)
            _, _, y = self.run_purify("bench", COLUMN_CHROMATOGRAPHY, 1.0)
            yields.append(y)
        self.assertGreater(len(set(yields)), 1)


if __name__ == "__main__":
    unittest.main()
