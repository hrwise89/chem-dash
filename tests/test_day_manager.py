import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from day_manager import PASS_OUT_AFTER_HOURS, SLEEPY_AFTER_HOURS, DayManager
from game_clock import GameClock


class TestDayManager(unittest.TestCase):

    def setUp(self):
        self.clock = GameClock()
        self.days = DayManager()

    def test_starts_on_day_one_with_no_hours_elapsed(self):
        self.assertEqual(self.days.current_day, 1)
        self.assertEqual(self.days.hours_into_day(self.clock), 0.0)

    def test_hours_into_day_tracks_the_clock(self):
        self.clock.advance(5.0)
        self.assertAlmostEqual(self.days.hours_into_day(self.clock), 5.0)

    def test_not_sleepy_or_passed_out_early_in_the_day(self):
        self.clock.advance(SLEEPY_AFTER_HOURS - 0.1)
        self.assertFalse(self.days.is_sleepy(self.clock))
        self.assertFalse(self.days.has_passed_out(self.clock))

    def test_sleepy_between_thresholds(self):
        self.clock.advance(SLEEPY_AFTER_HOURS + 0.5)
        self.assertTrue(self.days.is_sleepy(self.clock))
        self.assertFalse(self.days.has_passed_out(self.clock))

    def test_passed_out_at_or_past_threshold(self):
        self.clock.advance(PASS_OUT_AFTER_HOURS)
        self.assertFalse(self.days.is_sleepy(self.clock))  # no longer just "sleepy"
        self.assertTrue(self.days.has_passed_out(self.clock))

    def test_go_home_advances_one_day_and_resets_hours(self):
        self.clock.advance(6.0)
        new_day = self.days.go_home(self.clock)
        self.assertEqual(new_day, 2)
        self.assertEqual(self.days.current_day, 2)
        self.assertAlmostEqual(self.days.hours_into_day(self.clock), 0.0)

    def test_pass_out_skips_a_day(self):
        self.clock.advance(PASS_OUT_AFTER_HOURS)
        new_day = self.days.pass_out(self.clock)
        # Leaving too late on day 1 skips day 2 entirely.
        self.assertEqual(new_day, 3)
        self.assertAlmostEqual(self.days.hours_into_day(self.clock), 0.0)

    def test_pass_out_on_day_two_lands_on_day_four(self):
        self.days.go_home(self.clock)  # day 1 -> 2
        self.clock.advance(PASS_OUT_AFTER_HOURS)
        new_day = self.days.pass_out(self.clock)
        self.assertEqual(new_day, 4)

    def test_hours_into_day_measured_from_last_day_boundary(self):
        self.clock.advance(20.0)
        self.days.go_home(self.clock)
        self.clock.advance(3.0)
        self.assertAlmostEqual(self.days.hours_into_day(self.clock), 3.0)


if __name__ == "__main__":
    unittest.main()
