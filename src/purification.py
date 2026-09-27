"""
Purification: turning a crude chemical into its pure form.

Crude/pure is tracked as a binary state encoded in the chemical's name
(see inventory.py) -- "ethyl bromide (crude)" vs "ethyl bromide". Two ways
to purify are planned:
  - manual: play a purification mini-game (column chromatography,
    recrystallization, ...) for a better yield. Not implemented yet --
    see benches/purify_bench.py's PurifyBenchView, which currently reports
    "manual" as unavailable.
  - auto: a no-skill-required conversion at a worse (but randomized) yield,
    of however much of the crude chemical the player chooses (see `amount`
    below) -- this is what this module implements.

Either way, purification is a "time-consuming action" (see day_manager.py):
it always costs AUTO_PURIFY_TIME_COST_HOURS of in-game time, applied all at
once when it completes, rather than time passing while the player sits in
a menu.
"""

import random

from devtools import logger
from inventory import (  # noqa: F401 -- re-exported
    CRUDE_SUFFIX,
    NotCrudeError,
    is_crude,
    pure_name_for,
)

# Auto-purify's default yield range and time cost. Deliberately worse than
# a well-run manual purification will eventually be -- that gap is the
# whole point of offering both options.
AUTO_PURIFY_MIN_YIELD = 0.80
AUTO_PURIFY_MAX_YIELD = 0.95
AUTO_PURIFY_TIME_COST_HOURS = 20 / 60  # 20 minutes

# Fixed per-purification requirements, regardless of how much crude
# chemical is being purified: a column (equipment, not consumed) plus a
# fixed amount of silica (a consumable) and diethyl ether (an ordinary
# chemical, tagged is_solvent -- see chemicals.json) that ARE consumed.
GLASS_COLUMN_TYPE = "glass_column"
SILICA_NAME = "silica"
SILICA_REQUIRED_G = 10.0
DIETHYL_ETHER_NAME = "diethyl ether"
DIETHYL_ETHER_REQUIRED_ML = 50.0


def auto_purify(
    inventory,
    equipment_inventory,
    consumables,
    game_clock,
    crude_name: str,
    amount: float,
    min_yield: float = AUTO_PURIFY_MIN_YIELD,
    max_yield: float = AUTO_PURIFY_MAX_YIELD,
    time_cost_hours: float = AUTO_PURIFY_TIME_COST_HOURS,
    rng: random.Random | None = None,
) -> tuple[str, float, float]:
    """
    Auto-purify `amount` (native units, up to however much of `crude_name`
    is on hand) into its pure form at a random yield in
    [min_yield, max_yield], consuming one glass column's availability plus
    a fixed SILICA_REQUIRED_G of silica and DIETHYL_ETHER_REQUIRED_ML of
    diethyl ether (the column itself isn't used up), and advancing the game
    clock by time_cost_hours all at once.

    Returns (pure_name, amount_purified, yield_fraction).
    Raises NotCrudeError if crude_name isn't a "... (crude)" chemical, and
    ValueError (leaving everything untouched) if amount isn't available, or
    the column/silica/ether requirements aren't met.
    """
    pure_name = pure_name_for(crude_name)  # raises NotCrudeError if not crude

    have = inventory.contents.get(crude_name, 0.0)
    if amount <= 0 or amount > have + 1e-9:
        raise ValueError(f"Can't purify {amount:.2f} of {crude_name} (have {have:.2f}).")
    if not equipment_inventory.available_items(GLASS_COLUMN_TYPE):
        raise ValueError("No glass column available.")
    if not consumables.has(SILICA_NAME, SILICA_REQUIRED_G):
        have_silica = consumables.contents.get(SILICA_NAME, 0.0)
        raise ValueError(f"Not enough silica (need {SILICA_REQUIRED_G:.0f} g, have {have_silica:.0f} g).")
    if not inventory.has(DIETHYL_ETHER_NAME, DIETHYL_ETHER_REQUIRED_ML):
        have_ether = inventory.contents.get(DIETHYL_ETHER_NAME, 0.0)
        raise ValueError(
            f"Not enough diethyl ether (need {DIETHYL_ETHER_REQUIRED_ML:.0f} mL, have {have_ether:.0f} mL)."
        )

    rng = rng or random
    yield_fraction = rng.uniform(min_yield, max_yield)
    purified_amount = amount * yield_fraction

    consumables.remove(SILICA_NAME, SILICA_REQUIRED_G)
    inventory.remove(DIETHYL_ETHER_NAME, DIETHYL_ETHER_REQUIRED_ML)
    inventory.remove(crude_name, amount)
    inventory.add(pure_name, purified_amount)
    game_clock.advance(time_cost_hours)

    # Native units (g/mL) come from the species catalog when the inventory
    # has one; falls back to a generic label so this stays usable against a
    # bare ChemicalInventory() with no catalog (e.g. in unit tests).
    try:
        unit = inventory.species_for(pure_name).unit_label()
    except (KeyError, AttributeError):
        unit = "units"

    logger.info(
        "Auto-purified %.2f %s %s -> %.2f %s %s (%.1f%% yield), +%.2fh, "
        "using %.0fg silica + %.0fmL diethyl ether",
        amount, unit, crude_name, purified_amount, unit, pure_name, yield_fraction * 100, time_cost_hours,
        SILICA_REQUIRED_G, DIETHYL_ETHER_REQUIRED_ML,
    )
    return pure_name, purified_amount, yield_fraction
