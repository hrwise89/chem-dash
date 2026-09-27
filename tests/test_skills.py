import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from skills import (
    PURIFICATION,
    SYNTHESIS,
    PlayerSkills,
    purification_speed_multiplier,
    synthesis_yield_bonus,
)


class TestPlayerSkills(unittest.TestCase):

    def test_untrained_skill_reads_as_level_zero(self):
        skills = PlayerSkills()
        self.assertEqual(skills.level_of(SYNTHESIS), 0)

    def test_level_of_reads_a_set_level(self):
        skills = PlayerSkills(levels={SYNTHESIS: 5})
        self.assertEqual(skills.level_of(SYNTHESIS), 5)
        self.assertEqual(skills.level_of(PURIFICATION), 0)  # unset stays 0

    def test_meets_with_no_requirement_is_always_true(self):
        skills = PlayerSkills()
        self.assertTrue(skills.meets(None))

    def test_meets_checks_the_named_skills_level(self):
        skills = PlayerSkills(levels={PURIFICATION: 3})
        self.assertTrue(skills.meets((PURIFICATION, 3)))
        self.assertTrue(skills.meets((PURIFICATION, 2)))
        self.assertFalse(skills.meets((PURIFICATION, 4)))

    def test_meets_treats_an_unset_skill_as_level_zero(self):
        skills = PlayerSkills()
        self.assertFalse(skills.meets((SYNTHESIS, 1)))
        self.assertTrue(skills.meets((SYNTHESIS, 0)))


class TestSynthesisYieldBonus(unittest.TestCase):

    def test_zero_level_gives_no_bonus(self):
        self.assertEqual(synthesis_yield_bonus(0), 0.0)

    def test_bonus_scales_with_level(self):
        self.assertAlmostEqual(synthesis_yield_bonus(5), 0.05)

    def test_bonus_caps_at_fifteen_percent(self):
        self.assertAlmostEqual(synthesis_yield_bonus(15), 0.15)
        self.assertAlmostEqual(synthesis_yield_bonus(100), 0.15)


class TestPurificationSpeedMultiplier(unittest.TestCase):

    def test_zero_level_gives_no_speedup(self):
        self.assertEqual(purification_speed_multiplier(0), 1.0)

    def test_multiplier_shrinks_with_level(self):
        self.assertAlmostEqual(purification_speed_multiplier(10), 0.8)

    def test_multiplier_floors_at_half_time(self):
        self.assertAlmostEqual(purification_speed_multiplier(25), 0.5)
        self.assertAlmostEqual(purification_speed_multiplier(100), 0.5)


if __name__ == "__main__":
    unittest.main()
