"""
Purification: turning a crude chemical into its pure form, via one of two
methods (Column Chromatography, Distillation) at one of several scales
(Micro, Bench for now -- Pilot and Production are defined but disabled
until a later pass). Design intent: column chromatography is fast,
flexible, and consumable-heavy; distillation is slower but cheaper and
suits larger amounts. Future additions: recrystallization, flash
chromatography, prep HPLC, and the Pilot/Production scales.

Amounts are always specified and tracked in MASS (grams), regardless of
whether the crude chemical is a solid (native units already grams) or a
liquid (native units mL, converted via density -- see
inventory.ChemicalSpecies.density). That's what lets one set of mass-based
slider notches/costs apply to any producible chemical, solid or liquid
alike, rather than modeling each one's purification separately.

Solvents are generic "grades" (Technical/Reagent) tracked as consumables
(inventory.ConsumableInventory), not individual chemical identities --
see the design note in the data files.

Purification is a "time-consuming action" (see day_manager.py/
benches.ui_common.check_pass_out): consuming materials, advancing the game
clock by the method's fixed time, and completing all happen at once, with
the player unable to do anything else while it's "happening".
"""

import random
from dataclasses import dataclass, field

from devtools import logger
from inventory import (  # noqa: F401 -- re-exported
    CRUDE_SUFFIX,
    NotCrudeError,
    is_crude,
    pure_name_for,
)

SILICA_NAME = "Silica Gel"
TECHNICAL_SOLVENT_NAME = "Bulk Solvent (Technical Grade, 95%)"
REAGENT_SOLVENT_NAME = "Bulk Solvent (Reagent Grade, 99%)"

COLUMN_CHROMATOGRAPHY = "column_chromatography"
DISTILLATION = "distillation"

# Scales not yet implemented -- always unavailable regardless of equipment,
# and the bench UI greys them out entirely.
DISABLED_SCALES = frozenset({"pilot", "production"})


def mass_grams(inventory, name: str, native_amount: float) -> float:
    """Native-unit amount (grams for a solid, mL for a liquid) -> mass in
    grams, via the species' density (a solid's native unit already IS
    grams, so it passes through unchanged)."""
    species = inventory.species_for(name)
    if species.state == "solid":
        return native_amount
    return native_amount * species.density


def native_amount_for_mass(inventory, name: str, mass_g: float) -> float:
    """Inverse of mass_grams()."""
    species = inventory.species_for(name)
    if species.state == "solid":
        return mass_g
    return mass_g / species.density


@dataclass
class PurifyMethodSpec:
    """One purification technique at a given scale."""
    label: str
    equipment_type: str
    time_hours: float
    min_yield: float
    max_yield: float
    unit_mass_g: float = 1.0        # the "per X purified" granularity the cost scales with
    silica_base_g: float = 0.0
    silica_per_unit_g: float = 0.0
    solvent_name: str | None = None
    solvent_base_ml: float = 0.0
    solvent_per_unit_ml: float = 0.0

    def cost(self, mass_g: float) -> tuple[float, float]:
        """(silica_g, solvent_ml) needed to purify mass_g grams."""
        units = mass_g / self.unit_mass_g if self.unit_mass_g else 0.0
        silica_g = self.silica_base_g + self.silica_per_unit_g * units
        solvent_ml = self.solvent_base_ml + self.solvent_per_unit_ml * units
        return silica_g, solvent_ml


def _tiered_slider_values(tiers: list[tuple[float, float, float]]) -> list[float]:
    """
    Build an ascending list of slider notches from descending
    (start, stop, step) tiers, each inclusive of both ends; consecutive
    tiers are expected to share their boundary value, which is
    de-duplicated. E.g. [(500, 250, 25), (250, 100, 10)] walks 500 down to
    250 in steps of 25, then continues 250 down to 100 in steps of 10,
    without repeating 250.
    """
    values: list[float] = []
    for start, stop, step in tiers:
        count = round((start - stop) / step)
        for i in range(count + 1):
            v = round(start - i * step, 6)
            if not values or abs(values[-1] - v) > 1e-9:
                values.append(v)
    values.reverse()
    return values


@dataclass
class PurifyScaleSpec:
    """One purification scale: which equipment makes it available, the
    amount notches its slider offers (always in grams internally), and its
    methods."""
    label: str
    equipment_types: tuple[str, ...]              # scale is available if any of these has a free item
    slider_values_g: list[float] = field(default_factory=list)   # ascending, in grams
    display_divisor: float = 1.0                  # multiply grams by this for the UI's number (1000 -> mg)
    display_unit: str = "g"
    methods: dict[str, PurifyMethodSpec] = field(default_factory=dict)


MICRO_SCALE = PurifyScaleSpec(
    label="Micro",
    equipment_types=("chroma_column_micro", "distill_column_micro"),
    slider_values_g=[v / 1000.0 for v in _tiered_slider_values([(500, 250, 25), (250, 100, 10), (100, 5, 5)])],
    display_divisor=1000.0,
    display_unit="mg",
    methods={
        COLUMN_CHROMATOGRAPHY: PurifyMethodSpec(
            label="Column Chromatography", equipment_type="chroma_column_micro",
            time_hours=20 / 60, min_yield=0.85, max_yield=1.00, unit_mass_g=0.05,
            silica_base_g=10.0, silica_per_unit_g=1.0,
            solvent_name=TECHNICAL_SOLVENT_NAME, solvent_base_ml=25.0, solvent_per_unit_ml=2.0,
        ),
        DISTILLATION: PurifyMethodSpec(
            label="Distillation", equipment_type="distill_column_micro",
            time_hours=15 / 60, min_yield=0.90, max_yield=1.00,
            # Not given an exact figure -- kept minimal and flat (no
            # silica, small fixed solvent draw), matching Bench
            # Distillation's "no silica, minimal solvent" note, pending
            # real balancing.
            solvent_name=TECHNICAL_SOLVENT_NAME, solvent_base_ml=5.0,
        ),
    },
)

BENCH_SCALE = PurifyScaleSpec(
    label="Bench",
    equipment_types=("chroma_column_bench", "distill_column_bench"),
    slider_values_g=_tiered_slider_values([(100, 20, 5), (20, 10, 2), (10, 1, 1), (1, 0.5, 0.5)]),
    display_divisor=1.0,
    display_unit="g",
    methods={
        COLUMN_CHROMATOGRAPHY: PurifyMethodSpec(
            label="Column Chromatography", equipment_type="chroma_column_bench",
            time_hours=60 / 60, min_yield=0.80, max_yield=1.00, unit_mass_g=1.0,
            silica_base_g=25.0, silica_per_unit_g=1.0,
            solvent_name=TECHNICAL_SOLVENT_NAME, solvent_base_ml=100.0, solvent_per_unit_ml=3.0,
        ),
        DISTILLATION: PurifyMethodSpec(
            label="Distillation", equipment_type="distill_column_bench",
            time_hours=45 / 60, min_yield=0.88, max_yield=1.00,
            # "No silica, minimal solvent consumption" -- exact figure not
            # given, kept flat and small pending real balancing.
            solvent_name=TECHNICAL_SOLVENT_NAME, solvent_base_ml=10.0,
        ),
    },
)

PILOT_SCALE = PurifyScaleSpec(label="Pilot", equipment_types=())
PRODUCTION_SCALE = PurifyScaleSpec(label="Production", equipment_types=())

PURIFY_SCALES: dict[str, PurifyScaleSpec] = {
    "micro": MICRO_SCALE,
    "bench": BENCH_SCALE,
    "pilot": PILOT_SCALE,
    "production": PRODUCTION_SCALE,
}
PURIFY_SCALE_ORDER = ["micro", "bench", "pilot", "production"]
PURIFY_METHOD_ORDER = [COLUMN_CHROMATOGRAPHY, DISTILLATION]


def scale_is_available(scale_key: str, equipment_inventory) -> bool:
    if scale_key in DISABLED_SCALES:
        return False
    spec = PURIFY_SCALES[scale_key]
    return any(equipment_inventory.available_items(t) for t in spec.equipment_types)


def method_is_available(scale_key: str, method_key: str, equipment_inventory) -> bool:
    if not scale_is_available(scale_key, equipment_inventory):
        return False
    method = PURIFY_SCALES[scale_key].methods.get(method_key)
    if method is None:
        return False
    return bool(equipment_inventory.available_items(method.equipment_type))


def available_slider_values(scale_key: str, available_mass_g: float) -> list[float]:
    """Ascending notches (in grams) at or under available_mass_g -- the
    ones the player can actually pick given how much crude chemical is on
    hand."""
    return [v for v in PURIFY_SCALES[scale_key].slider_values_g if v <= available_mass_g + 1e-9]


def purify(
    scale_key: str,
    method_key: str,
    inventory,
    equipment_inventory,
    consumables,
    game_clock,
    crude_name: str,
    mass_g: float,
    rng: random.Random | None = None,
) -> tuple[str, float, float]:
    """
    Purify `mass_g` grams (mass, not native units -- see mass_grams()/
    native_amount_for_mass()) of `crude_name` using `method_key` at
    `scale_key`, at a random yield within the method's range. Consumes the
    crude chemical, silica (if the method uses any), and solvent, then
    advances the game clock by the method's fixed time -- all at once.

    Returns (pure_name, purified_mass_g, yield_fraction). Raises
    NotCrudeError if crude_name isn't crude, and ValueError (leaving
    everything untouched) if the scale/method isn't available, mass_g
    isn't positive, or there isn't enough crude chemical/silica/solvent.
    """
    pure_name = pure_name_for(crude_name)  # raises NotCrudeError if not crude

    scale = PURIFY_SCALES[scale_key]
    if not scale_is_available(scale_key, equipment_inventory):
        raise ValueError(f"{scale.label} scale isn't available.")
    if not method_is_available(scale_key, method_key, equipment_inventory):
        method_label = scale.methods[method_key].label if method_key in scale.methods else method_key
        raise ValueError(f"{method_label} isn't available at {scale.label} scale.")

    method = scale.methods[method_key]

    if mass_g <= 0:
        raise ValueError("Nothing to purify.")

    native_amount = native_amount_for_mass(inventory, crude_name, mass_g)
    have_native = inventory.contents.get(crude_name, 0.0)
    if native_amount > have_native + 1e-9:
        have_mass_g = mass_grams(inventory, crude_name, have_native)
        raise ValueError(f"Can't purify {mass_g:.3f} g of {crude_name} (have {have_mass_g:.3f} g).")

    silica_g, solvent_ml = method.cost(mass_g)
    if silica_g > 0 and not consumables.has(SILICA_NAME, silica_g):
        have_silica = consumables.contents.get(SILICA_NAME, 0.0)
        raise ValueError(f"Not enough {SILICA_NAME} (need {silica_g:.1f} g, have {have_silica:.1f} g).")
    if solvent_ml > 0 and not consumables.has(method.solvent_name, solvent_ml):
        have_solvent = consumables.contents.get(method.solvent_name, 0.0)
        raise ValueError(
            f"Not enough {method.solvent_name} (need {solvent_ml:.1f} mL, have {have_solvent:.1f} mL)."
        )

    rng = rng or random
    yield_fraction = rng.uniform(method.min_yield, method.max_yield)
    purified_mass_g = mass_g * yield_fraction

    if silica_g > 0:
        consumables.remove(SILICA_NAME, silica_g)
    if solvent_ml > 0:
        consumables.remove(method.solvent_name, solvent_ml)
    inventory.remove(crude_name, native_amount)
    purified_native = native_amount_for_mass(inventory, pure_name, purified_mass_g)
    inventory.add(pure_name, purified_native)
    game_clock.advance(method.time_hours)

    logger.info(
        "Purified %.3fg %s -> %.3fg %s via %s (%s scale, %.1f%% yield), +%.2fh, "
        "using %.1fg silica + %.1fmL %s",
        mass_g, crude_name, purified_mass_g, pure_name, method.label, scale.label,
        yield_fraction * 100, method.time_hours, silica_g, solvent_ml, method.solvent_name,
    )
    return pure_name, purified_mass_g, yield_fraction
