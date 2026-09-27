"""
Tracks in-game "days" on top of GameClock's single ever-increasing
timestamp (see game_clock.py) -- the "go home before you crash" mechanic
from the design doc. Kept separate from GameClock itself (which only
knows about one monotonic timeline, used for scheduling reactions) and
free of any arcade import so it stays headless-testable like
reaction_engine.py/inventory.py.

A "day" here isn't a real 24-hour cycle -- it's a budget of active hours
(time spent walking the lab floor, or warped through while collecting a
reaction) before the player must go home. Going home through the door
ends the day normally; staying out past PASS_OUT_AFTER_HOURS forces it to
end anyway and costs an extra day, simulating recovering from exhaustion.
"""

from game_clock import GameClock

SLEEPY_AFTER_HOURS = 12.0
PASS_OUT_AFTER_HOURS = 14.0


class DayManager:
    """current_day starts at 1; day_start_time is the GameClock reading
    when the current day began."""

    def __init__(self, start_day: int = 1):
        self.current_day = start_day
        self.day_start_time = 0.0

    def hours_into_day(self, game_clock: GameClock) -> float:
        return game_clock.now() - self.day_start_time

    def is_sleepy(self, game_clock: GameClock) -> bool:
        """True once the player has been out long enough to be warned,
        but before they've actually passed out."""
        hours = self.hours_into_day(game_clock)
        return SLEEPY_AFTER_HOURS <= hours < PASS_OUT_AFTER_HOURS

    def has_passed_out(self, game_clock: GameClock) -> bool:
        return self.hours_into_day(game_clock) >= PASS_OUT_AFTER_HOURS

    def go_home(self, game_clock: GameClock) -> int:
        """End the day normally (the player used the door). Returns the
        new current_day."""
        self.current_day += 1
        self.day_start_time = game_clock.now()
        return self.current_day

    def pass_out(self, game_clock: GameClock) -> int:
        """Force-end the day because the player stayed out too long --
        skips the following day entirely as the cost of passing out.
        Returns the new current_day."""
        self.current_day += 2
        self.day_start_time = game_clock.now()
        return self.current_day
