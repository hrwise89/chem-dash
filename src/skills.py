"""
Player skills/specialities: named levels that nudge yield and speed on
actions, and can gate access to a scale/method/equipment outright. This is
deliberately minimal -- there's no XP system yet to raise a level, and the
actual skill names/thresholds below are placeholders (tune freely, same as
GAME_HOURS_PER_REAL_SECOND in settings.py) -- the point is to give
purify()/start_reaction() one stable extension point to plug real
progression into later, rather than threading a new parameter through them
again for every future change.

Kept arcade-free so it stays headless-testable, like reaction_engine.py/
inventory.py/purification.py.
"""

from dataclasses import dataclass, field

# Skill names purify()/reaction_engine.py currently look for. Not an
# exhaustive or final list -- just what those two hooks need today.
SYNTHESIS = "synthesis"       # reaction yield
PURIFICATION = "purification"  # purification speed


@dataclass
class PlayerSkills:
    """levels maps a skill name to an integer level (0 = untrained, and
    the implicit level for any skill name not present)."""
    levels: dict[str, int] = field(default_factory=dict)

    def level_of(self, skill_name: str) -> int:
        return self.levels.get(skill_name, 0)

    def meets(self, requirement: tuple[str, int] | None) -> bool:
        """requirement is (skill_name, min_level), or None for "nothing
        required" -- always True in that case."""
        if requirement is None:
            return True
        skill_name, min_level = requirement
        return self.level_of(skill_name) >= min_level


def synthesis_yield_bonus(level: int) -> float:
    """Additive bonus to a reaction's condition_score per synthesis level
    -- +1% per level, capped at +15% (level 15+). A skilled player can
    fully offset one "off-spec" condition penalty (each costs 20-50%) but
    not stack enough to make sloppy technique free."""
    return min(level * 0.01, 0.15)


def purification_speed_multiplier(level: int) -> float:
    """Multiplies a purification method's time_hours per purification
    level -- 2% faster per level, floored at 50% of the base time (level
    25+)."""
    return max(1.0 - level * 0.02, 0.5)
