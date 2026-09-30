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
from inventory import NotCrudeError, is_crude, pure_name_for  # noqa: F401 -- NotCrudeError/is_crude re-exported for tests
from skills import PURIFICATION, purification_speed_multiplier

SILICA_NAME = "Silica Gel"

# A crude remainder under this (mass, in grams) can't be purified on its
# own -- it won't reach even a scale's smallest slider notch -- so it
# would otherwise sit in inventory forever as unusable dust. purify()
# absorbs it into whatever's being purified instead (see the comment at
# its dust-bump check).
DUST_THRESHOLD_G = 0.005
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
    # (skill_name, min_level) required to use this method, or None for no
    # requirement -- see skills.py. Nothing sets this yet.
    required_skill: tuple[str, int] | None = None

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
    # (skill_name, min_level) required to use this scale at all, or None
    # for no requirement -- see skills.py. Nothing sets this yet; Pilot/
    # Production are still gated purely through DISABLED_SCALES.
    required_skill: tuple[str, int] | None = None

    def format_amount(self, mass_g: float) -> str:
        displayed = mass_g * self.display_divisor
        return f"{displayed:g} {self.display_unit}"

    def range_label(self) -> str:
        """E.g. "Micro-Scale (5 mg - 500 mg)" -- just the label, with no
        range shown, for a scale with no slider notches yet (Pilot/
        Production)."""
        if not self.slider_values_g:
            return self.label
        lo = self.format_amount(self.slider_values_g[0])
        hi = self.format_amount(self.slider_values_g[-1])
        return f"{self.label} ({lo} - {hi})"


MICRO_SCALE = PurifyScaleSpec(
    label="Micro-Scale",
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
    label="Bench-Scale",
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

PILOT_SCALE = PurifyScaleSpec(label="Pilot-Scale", equipment_types=())
PRODUCTION_SCALE = PurifyScaleSpec(label="Production-Scale", equipment_types=())

PURIFY_SCALES: dict[str, PurifyScaleSpec] = {
    "micro": MICRO_SCALE,
    "bench": BENCH_SCALE,
    "pilot": PILOT_SCALE,
    "production": PRODUCTION_SCALE,
}
PURIFY_SCALE_ORDER = ["micro", "bench", "pilot", "production"]
PURIFY_METHOD_ORDER = [COLUMN_CHROMATOGRAPHY, DISTILLATION]

# How many columns/distillations of the same method a player can run
# concurrently in one batch (see purify_batch()) -- an arbitrary game-feel
# cap, not derived from anything physical.
MAX_CONCURRENT_RUNS = 3


def scale_is_available(scale_key: str, equipment_inventory, skills=None) -> bool:
    if scale_key in DISABLED_SCALES:
        return False
    spec = PURIFY_SCALES[scale_key]
    if skills is not None and not skills.meets(spec.required_skill):
        return False
    return any(equipment_inventory.available_items(t) for t in spec.equipment_types)


def method_is_available(scale_key: str, method_key: str, equipment_inventory, skills=None) -> bool:
    if not scale_is_available(scale_key, equipment_inventory, skills):
        return False
    method = PURIFY_SCALES[scale_key].methods.get(method_key)
    if method is None:
        return False
    if skills is not None and not skills.meets(method.required_skill):
        return False
    return bool(equipment_inventory.available_items(method.equipment_type))


def max_concurrent_runs(scale_key: str, method_key: str, equipment_inventory, skills=None) -> int:
    """How many columns/distillations of `method_key` the player can run
    at once right now -- min(MAX_CONCURRENT_RUNS, how many matching
    columns they own and aren't already using). 0 if the method isn't
    available at all (see method_is_available)."""
    if not method_is_available(scale_key, method_key, equipment_inventory, skills):
        return 0
    method = PURIFY_SCALES[scale_key].methods[method_key]
    owned = len(equipment_inventory.available_items(method.equipment_type))
    return min(MAX_CONCURRENT_RUNS, owned)


def effective_time_hours(method: PurifyMethodSpec, skills=None) -> float:
    """method.time_hours, sped up by skills.purification_speed_multiplier()
    when skills is given -- the single place both purify() and the bench
    UI's time preview compute this, so they can never drift apart."""
    if skills is None:
        return method.time_hours
    return method.time_hours * purification_speed_multiplier(skills.level_of(PURIFICATION))


def available_slider_values(scale_key: str, available_mass_g: float) -> list[float]:
    """Ascending notches (in grams) at or under available_mass_g -- the
    ones the player can actually pick given how much crude chemical is on
    hand. The top of the list is always exactly min(available_mass_g, the
    scale's max notch) -- even when that doesn't land on one of the
    scale's fixed notches -- so the player can always select everything
    they have on hand (up to what the scale supports) rather than being
    rounded down to the nearest notch below it."""
    all_values = PURIFY_SCALES[scale_key].slider_values_g
    if not all_values:
        return []
    cap = min(available_mass_g, all_values[-1])
    if cap < all_values[0] - 1e-9:
        return []  # not even enough for the smallest notch
    # Deliberately NOT rounded: available_mass_g came from a
    # mass_grams()/native_amount_for_mass() round-trip through a
    # (possibly non-integer) density, so rounding it here would silently
    # introduce enough drift that converting it back in purify() reads as
    # "more than we actually have" and rejects the player's own on-hand
    # amount (see purify()'s have_native comparison tolerance).
    values = [v for v in all_values if v <= cap - 1e-9]
    values.append(cap)
    return values


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
    skills=None,
) -> tuple[str, float, float]:
    """
    Purify `mass_g` grams (mass, not native units -- see mass_grams()/
    native_amount_for_mass()) of `crude_name` using `method_key` at
    `scale_key`, at a random yield within the method's range. Consumes the
    crude chemical, silica (if the method uses any), and solvent, then
    advances the game clock by the method's fixed time -- all at once.

    `skills` (a skills.PlayerSkills, optional) gates scale/method access
    per their required_skill, and speeds up the method's base time_hours
    per skills.purification_speed_multiplier() -- see skills.py. Left as
    None, this behaves exactly as if the player had no skills at all (no
    gating beyond equipment, no speed bonus).

    Returns (pure_name, purified_mass_g, yield_fraction). Raises
    NotCrudeError if crude_name isn't crude, and ValueError (leaving
    everything untouched) if the scale/method isn't available, mass_g
    isn't positive, or there isn't enough crude chemical/silica/solvent.
    """
    pure_name = pure_name_for(crude_name)  # raises NotCrudeError if not crude

    scale = PURIFY_SCALES[scale_key]
    if not scale_is_available(scale_key, equipment_inventory, skills):
        raise ValueError(f"{scale.label} scale isn't available.")
    if not method_is_available(scale_key, method_key, equipment_inventory, skills):
        method_label = scale.methods[method_key].label if method_key in scale.methods else method_key
        raise ValueError(f"{method_label} isn't available at {scale.label} scale.")

    method = scale.methods[method_key]

    if mass_g <= 0:
        raise ValueError("Nothing to purify.")

    native_amount = native_amount_for_mass(inventory, crude_name, mass_g)
    have_native = inventory.contents.get(crude_name, 0.0)
    # A relative (not just fixed 1e-9) tolerance: mass_g is typically the
    # slider's max value, which is have_native run through a
    # mass_grams()/native_amount_for_mass() round-trip via density -- with
    # a non-round density that reintroduces enough floating-point drift to
    # read as "more than we have" at a fixed epsilon, wrongly rejecting
    # the player's own full on-hand amount. When it's this close, treat it
    # as exactly what's on hand rather than leave a dust-sized negative
    # remainder in inventory.
    tolerance = max(1e-9, have_native * 1e-6)
    if native_amount > have_native + tolerance:
        have_mass_g = mass_grams(inventory, crude_name, have_native)
        raise ValueError(f"Can't purify {mass_g:.3f} g of {crude_name} (have {have_mass_g:.3f} g).")
    native_amount = min(native_amount, have_native)

    # Dust bump: if what's requested would leave under DUST_THRESHOLD_G of
    # crude behind, take all of it instead -- consumable cost below is
    # still based on the originally requested mass_g (the sub-5mg
    # difference is negligible), only the crude consumed/product yielded
    # grows to match what's actually taken.
    leftover_mass_g = mass_grams(inventory, crude_name, have_native - native_amount)
    if 0 < leftover_mass_g < DUST_THRESHOLD_G:
        native_amount = have_native

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
    # Based on native_amount (the actual amount consumed, which the dust
    # bump above may have grown past the requested mass_g), not mass_g
    # itself -- a dust-absorbing run yields proportionally more product.
    consumed_mass_g = mass_grams(inventory, crude_name, native_amount)
    purified_mass_g = consumed_mass_g * yield_fraction

    time_hours = effective_time_hours(method, skills)

    if silica_g > 0:
        consumables.remove(SILICA_NAME, silica_g)
    if solvent_ml > 0:
        consumables.remove(method.solvent_name, solvent_ml)
    inventory.remove(crude_name, native_amount)
    purified_native = native_amount_for_mass(inventory, pure_name, purified_mass_g)
    inventory.add(pure_name, purified_native)
    game_clock.advance(time_hours)

    logger.info(
        "Purified %.3fg %s -> %.3fg %s via %s (%s scale, %.1f%% yield), +%.2fh, "
        "using %.1fg silica + %.1fmL %s",
        consumed_mass_g, crude_name, purified_mass_g, pure_name, method.label, scale.label,
        yield_fraction * 100, time_hours, silica_g, solvent_ml, method.solvent_name,
    )
    return pure_name, purified_mass_g, yield_fraction


def purify_batch(
    scale_key: str,
    method_key: str,
    inventory,
    equipment_inventory,
    consumables,
    game_clock,
    crude_name: str,
    mass_values_g: list[float],
    rng: random.Random | None = None,
    skills=None,
) -> list[tuple[str, float, float]]:
    """
    Like purify(), but runs len(mass_values_g) columns/distillations of
    the same method concurrently (see max_concurrent_runs) -- one entry
    per run, each purifying that much crude independently (its own
    randomly-rolled yield). Total crude/silica/solvent consumed is the
    sum across every run, but the game clock only advances once by the
    method's fixed time_hours: that's the entire point of running several
    at once instead of one after another -- more product per batch in the
    same wall-clock time, not less time per run.

    Raises ValueError for the same reasons as purify() (scale/method
    unavailable, nothing to purify, not enough crude/silica/solvent), plus
    if more runs are requested than max_concurrent_runs() allows. Returns
    a list of (pure_name, purified_mass_g, yield_fraction), one per run,
    in the same order as mass_values_g.
    """
    pure_name = pure_name_for(crude_name)  # raises NotCrudeError if not crude

    scale = PURIFY_SCALES[scale_key]
    if not scale_is_available(scale_key, equipment_inventory, skills):
        raise ValueError(f"{scale.label} scale isn't available.")
    if not method_is_available(scale_key, method_key, equipment_inventory, skills):
        method_label = scale.methods[method_key].label if method_key in scale.methods else method_key
        raise ValueError(f"{method_label} isn't available at {scale.label} scale.")

    method = scale.methods[method_key]

    if not mass_values_g:
        raise ValueError("Nothing to purify.")
    if any(m <= 0 for m in mass_values_g):
        raise ValueError("Nothing to purify.")
    max_runs = max_concurrent_runs(scale_key, method_key, equipment_inventory, skills)
    if len(mass_values_g) > max_runs:
        raise ValueError(f"Only {max_runs} {method.label} column(s) available at {scale.label} scale.")

    total_mass_g = sum(mass_values_g)
    native_amount = native_amount_for_mass(inventory, crude_name, total_mass_g)
    have_native = inventory.contents.get(crude_name, 0.0)
    # Same rounding-tolerance reasoning as purify() -- see its own comment.
    tolerance = max(1e-9, have_native * 1e-6)
    if native_amount > have_native + tolerance:
        have_mass_g = mass_grams(inventory, crude_name, have_native)
        raise ValueError(f"Can't purify {total_mass_g:.3f} g of {crude_name} (have {have_mass_g:.3f} g).")
    native_amount = min(native_amount, have_native)

    # Dust bump (see purify()) -- shared across the whole batch's draw
    # from the same crude stock, attributed to the last run for output
    # purposes (arbitrary; the split doesn't matter, only the total does).
    dust_bonus_g = 0.0
    leftover_mass_g = mass_grams(inventory, crude_name, have_native - native_amount)
    if 0 < leftover_mass_g < DUST_THRESHOLD_G:
        dust_bonus_g = leftover_mass_g
        native_amount = have_native

    total_silica_g = 0.0
    total_solvent_ml = 0.0
    for m in mass_values_g:
        silica_g, solvent_ml = method.cost(m)
        total_silica_g += silica_g
        total_solvent_ml += solvent_ml
    if total_silica_g > 0 and not consumables.has(SILICA_NAME, total_silica_g):
        have_silica = consumables.contents.get(SILICA_NAME, 0.0)
        raise ValueError(f"Not enough {SILICA_NAME} (need {total_silica_g:.1f} g, have {have_silica:.1f} g).")
    if total_solvent_ml > 0 and not consumables.has(method.solvent_name, total_solvent_ml):
        have_solvent = consumables.contents.get(method.solvent_name, 0.0)
        raise ValueError(
            f"Not enough {method.solvent_name} (need {total_solvent_ml:.1f} mL, have {have_solvent:.1f} mL)."
        )

    rng = rng or random
    run_masses_g = list(mass_values_g)
    run_masses_g[-1] += dust_bonus_g
    results = [(pure_name, m * (yf := rng.uniform(method.min_yield, method.max_yield)), yf) for m in run_masses_g]

    time_hours = effective_time_hours(method, skills)

    if total_silica_g > 0:
        consumables.remove(SILICA_NAME, total_silica_g)
    if total_solvent_ml > 0:
        consumables.remove(method.solvent_name, total_solvent_ml)
    inventory.remove(crude_name, native_amount)
    for _, purified_mass_g, _ in results:
        purified_native = native_amount_for_mass(inventory, pure_name, purified_mass_g)
        inventory.add(pure_name, purified_native)
    game_clock.advance(time_hours)

    logger.info(
        "Purified %d concurrent %s run(s) totalling %.3fg %s -> %s (%s scale), +%.2fh, "
        "using %.1fg silica + %.1fmL %s",
        len(results), method.label, sum(run_masses_g), crude_name,
        ["%.3fg (%.1f%%)" % (m, y * 100) for _, m, y in results], scale.label,
        time_hours, total_silica_g, total_solvent_ml, method.solvent_name,
    )
    return results
