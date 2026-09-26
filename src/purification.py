"""
Purification: turning a crude chemical into its pure form.

Crude/pure is tracked as a binary state encoded in the chemical's name
(see inventory.py) -- "ethyl bromide (crude)" vs "ethyl bromide". Two ways
to purify are planned:
  - manual: play a purification mini-game (column chromatography,
    recrystallization, ...) for a better yield. Not implemented yet --
    see benches/purify_bench.py's PurifyBenchView, which currently reports
    "manual" as unavailable.
  - auto: an instant, no-skill-required conversion at a worse (but
    randomized) yield. That's what this module implements.
"""

import random

from devtools import logger

CRUDE_SUFFIX = " (crude)"

# Auto-purify's default yield range and time cost. Deliberately worse than
# a well-run manual purification will eventually be -- that gap is the
# whole point of offering both options.
AUTO_PURIFY_MIN_YIELD = 0.80
AUTO_PURIFY_MAX_YIELD = 0.95
AUTO_PURIFY_TIME_COST_HOURS = 0.25  # 15 minutes


class NotCrudeError(ValueError):
    """Raised when asked to purify something that isn't a crude chemical."""


def is_crude(name: str) -> bool:
    return name.endswith(CRUDE_SUFFIX)


def pure_name_for(crude_name: str) -> str:
    """'ethyl bromide (crude)' -> 'ethyl bromide'."""
    if not is_crude(crude_name):
        raise NotCrudeError(f"'{crude_name}' is not a crude chemical (no '{CRUDE_SUFFIX}' suffix)")
    return crude_name[: -len(CRUDE_SUFFIX)]


def auto_purify(
    inventory,
    game_clock,
    crude_name: str,
    min_yield: float = AUTO_PURIFY_MIN_YIELD,
    max_yield: float = AUTO_PURIFY_MAX_YIELD,
    time_cost_hours: float = AUTO_PURIFY_TIME_COST_HOURS,
    rng: random.Random | None = None,
) -> tuple[str, float, float]:
    """
    Auto-purify ALL of the player's current stock of `crude_name` at once,
    converting it to its pure form at a random yield in [min_yield, max_yield],
    and advancing the game clock by time_cost_hours.

    Returns (pure_name, amount_purified, yield_fraction).
    Raises NotCrudeError if crude_name isn't a "... (crude)" chemical, or
    ValueError if there's none of it in inventory.
    """
    pure_name = pure_name_for(crude_name)  # raises NotCrudeError if not crude

    amount = inventory.contents.get(crude_name, 0.0)
    if amount <= 0:
        raise ValueError(f"No {crude_name} available to purify.")

    rng = rng or random
    yield_fraction = rng.uniform(min_yield, max_yield)
    purified_amount = amount * yield_fraction

    inventory.remove(crude_name, amount)
    inventory.add(pure_name, purified_amount)
    game_clock.advance(time_cost_hours)

    logger.info(
        "Auto-purified %.2f mol %s -> %.2f mol %s (%.1f%% yield), +%.2fh",
        amount, crude_name, purified_amount, pure_name, yield_fraction * 100, time_cost_hours,
    )
    return pure_name, purified_amount, yield_fraction
