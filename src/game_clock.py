"""
In-game clock, tracked in hours.

This is deliberately separate from timer_manager.Timer, which counts down in
real (wall-clock) seconds for things like the column mini-game. GameClock
instead tracks a single monotonically-increasing in-game timestamp that
reactions (and eventually other long processes) are scheduled against. It
only moves forward when something explicitly advances it -- there's no
real-time ticking -- which is what lets the player "warp" straight to the
end of a reaction instead of waiting it out.
"""


class GameClock:
    """Tracks elapsed in-game time, in hours."""

    def __init__(self, start_time: float = 0.0):
        self.current_time = start_time

    def now(self) -> float:
        return self.current_time

    def advance(self, hours: float) -> float:
        """Push the clock forward by `hours`. Returns the new current time."""
        if hours < 0:
            raise ValueError("Cannot advance the game clock by a negative amount")
        self.current_time += hours
        return self.current_time

    def advance_to(self, target_time: float) -> float:
        """Jump the clock forward to an absolute time (e.g. a process's end_time)."""
        if target_time < self.current_time:
            raise ValueError("Cannot move the game clock backwards")
        self.current_time = target_time
        return self.current_time
