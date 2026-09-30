import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from day_manager import (
    HOURS_PER_CALENDAR_DAY,
    PASS_OUT_AFTER_HOURS,
    SLEEPY_AFTER_HOURS,
    DayManager,
    calendar_date_string,
    clock_time_string,
    due_date_calendar_string,
)
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

    def test_go_home_advances_the_game_clock_overnight(self):
        # Leaving after only 6 active hours should still let the whole
        # rest of the 24-hour calendar day (the overnight sleep) pass on
        # GameClock, not leave it standing still -- otherwise nothing
        # scheduled against it (a reaction's finish time) can ever
        # complete while the player is away for the night.
        self.clock.advance(6.0)
        self.days.go_home(self.clock)
        self.assertAlmostEqual(self.clock.now(), 24.0)

    def test_pass_out_advances_the_game_clock_across_both_skipped_days(self):
        self.clock.advance(PASS_OUT_AFTER_HOURS)
        self.days.pass_out(self.clock)
        self.assertAlmostEqual(self.clock.now(), 48.0)

    def test_a_reaction_length_overnight_gap_is_enough_to_finish_it(self):
        # A reaction started 10 active hours into the day (well within the
        # 14-hour pass-out budget), needing 8 hours total, should read as
        # finished once the player has gone home for the night -- it
        # couldn't possibly finish before that if the clock never advanced
        # overnight.
        self.clock.advance(10.0)
        start_time = self.clock.now()
        reaction_duration = 8.0
        self.days.go_home(self.clock)
        self.assertGreaterEqual(self.clock.now(), start_time + reaction_duration)


class TestClockTimeString(unittest.TestCase):

    def test_zero_hours_is_8am(self):
        self.assertEqual(clock_time_string(0.0), "8:00 AM")

    def test_half_hour_in(self):
        self.assertEqual(clock_time_string(0.5), "8:30 AM")

    def test_crosses_noon(self):
        self.assertEqual(clock_time_string(4.0), "12:00 PM")

    def test_afternoon(self):
        self.assertEqual(clock_time_string(6.5), "2:30 PM")

    def test_near_pass_out_threshold(self):
        self.assertEqual(clock_time_string(PASS_OUT_AFTER_HOURS), "10:00 PM")

    def test_wraps_past_midnight(self):
        self.assertEqual(clock_time_string(16.0), "12:00 AM")


class TestCalendarDateString(unittest.TestCase):

    def test_day_one_is_start_date(self):
        self.assertEqual(calendar_date_string(1), "03/29/2001")

    def test_day_two_is_next_day(self):
        self.assertEqual(calendar_date_string(2), "03/30/2001")

    def test_crosses_month_boundary(self):
        self.assertEqual(calendar_date_string(4), "04/01/2001")


class TestDueDateCalendarString(unittest.TestCase):

    def test_rush_ignores_days_to_complete_and_due_date(self):
        self.assertEqual(due_date_calendar_string(True, 0, 12.0), "Rush")

    def test_open_ended_has_no_days_to_complete(self):
        self.assertEqual(due_date_calendar_string(False, None, None), "Open Ended")

    def test_not_yet_accepted_falls_back_to_a_relative_day_count(self):
        self.assertEqual(due_date_calendar_string(False, 5, None), "5d")

    def test_accepted_contract_shows_the_real_calendar_date(self):
        due_date = 3 * HOURS_PER_CALENDAR_DAY  # falls within day 4
        self.assertEqual(due_date_calendar_string(False, 2, due_date), "04/01/2001")


if __name__ == "__main__":
    unittest.main()
