import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from inventory import ChemicalSpecies
from units import format_mass, format_moles, format_native_amount, format_volume


class TestFormatMass(unittest.TestCase):

    def test_grams_tier_min(self):
        self.assertEqual(format_mass(1.0), "1.000 g")

    def test_grams_tier_max(self):
        self.assertEqual(format_mass(999.9), "999.9 g")

    def test_kilograms_tier_starts_at_1000g(self):
        self.assertEqual(format_mass(1000.0), "1.000 kg")

    def test_kilograms_tier_max(self):
        self.assertEqual(format_mass(999900.0), "999.9 kg")

    def test_milligrams_tier_min(self):
        self.assertEqual(format_mass(0.005), "5.000 mg")

    def test_milligrams_tier_max(self):
        self.assertEqual(format_mass(0.9999), "999.9 mg")

    def test_below_milligram_minimum_still_shows_milligrams_with_more_decimals(self):
        self.assertEqual(format_mass(0.000003), "0.003 mg")

    def test_zero_is_zero(self):
        self.assertEqual(format_mass(0.0), "0 mg")

    def test_four_significant_figures_scale_with_integer_digit_count(self):
        self.assertEqual(format_mass(12.345), "12.35 g")
        self.assertEqual(format_mass(123.45), "123.5 g")


class TestFormatVolume(unittest.TestCase):

    def test_milliliters_tier(self):
        self.assertEqual(format_volume(1.0), "1.000 mL")
        self.assertEqual(format_volume(631.0), "631.0 mL")

    def test_liters_tier_starts_at_1000ml(self):
        self.assertEqual(format_volume(1000.0), "1.000 L")

    def test_below_one_milliliter_still_shows_milliliters(self):
        self.assertEqual(format_volume(0.4), "0.400 mL")


class TestFormatMoles(unittest.TestCase):

    def test_moles_tier(self):
        self.assertEqual(format_moles(1.0), "1.000 mol")
        self.assertEqual(format_moles(18.14), "18.14 mol")

    def test_millimoles_tier_below_one_mole(self):
        self.assertEqual(format_moles(0.345), "345.0 mmol")

    def test_below_one_millimole_still_shows_millimoles(self):
        self.assertEqual(format_moles(0.0003), "0.300 mmol")


class TestFormatNativeAmount(unittest.TestCase):

    def test_solid_uses_mass(self):
        species = ChemicalSpecies(name="sodium cyanide", state="solid", molecular_weight=49.01)
        self.assertEqual(format_native_amount(species, 12.0), "12.00 g")

    def test_liquid_uses_volume(self):
        species = ChemicalSpecies(name="ethanol", state="liquid", molarity=17.13, density=0.79)
        self.assertEqual(format_native_amount(species, 500.0), "500.0 mL")


if __name__ == "__main__":
    unittest.main()
