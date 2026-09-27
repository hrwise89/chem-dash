import itertools
import json
from dataclasses import dataclass, field

from devtools import logger
from game_clock import GameClock
from inventory import ChemicalInventory, EquipmentInventory, EquipmentUnavailableError

# Re-exported for convenience / backwards compatibility with code that used
# to import Inventory directly from reaction_engine.
Inventory = ChemicalInventory

# A vessel is never filled past this fraction of its capacity (a hard cap --
# it just won't physically fit past this), and filling it below this
# fraction is allowed but triggers UNDERFILL_YIELD_PENALTY (a suggestion,
# not a block -- see start_reaction).
MAX_FILL_FRACTION = 0.8
RECOMMENDED_MIN_FILL_FRACTION = 0.2
UNDERFILL_YIELD_PENALTY = 0.5

# Default granularity (mol of the reference reagent) for the amount-picker
# slider. A recipe can override this via ReactionDefinition.scale_step --
# e.g. a future micro-scale recipe where 0.1 mol would already be a huge
# batch could set scale_step to something like 0.001 (1 mmol).
DEFAULT_SCALE_STEP = 0.1


# ===============================================================
# Errors
# ===============================================================

class ReactionNotReadyError(Exception):
    """Raised when trying to collect a reaction before its end_time."""


# ===============================================================
# Reaction data structures
# ===============================================================

@dataclass
class ReactionDefinition:
    """Defines a valid reaction with required reagents, conditions, and equipment."""
    reactants: dict[str, float]                # name -> stoichiometric moles (base ratio)
    products: dict[str, float]                  # name -> moles produced per reaction
    side_products: dict[str, float] = field(default_factory=dict)
    solvent: str | None = None                # e.g., 'neat' or 'water'
    temperature: float = 25.0                    # ideal temp in degC
    time_hours: float = 1.0                       # ideal reaction time
    efficiency: float = 1.0                        # yield factor (0-1)
    equipment: list[str] = field(default_factory=list)  # required equipment roles,
                                                          # e.g. ["rb_flask", "condenser"]
    reference_reagent: str | None = None       # which reactant "1 mole of reference
                                                # reagent" scales against, for the
                                                # amount-picker; defaults to the first
                                                # key in `reactants` if unset
    scale_step: float = DEFAULT_SCALE_STEP     # mol granularity for the amount slider


@dataclass
class ReactionLogEntry:
    """A permanent record of a completed reaction, kept after its
    ReactionProcess is discarded, so the player can look back at what
    conditions produced what yield (the notebook's reaction history)."""
    reaction_name: str
    start_time: float
    end_time: float
    solvent: str | None
    temperature: float
    scheduled_hours: float
    yield_fraction: float          # definition.efficiency * condition_score
    products: dict[str, float]
    side_products: dict[str, float]


@dataclass
class ReactionProcess:
    """An in-progress reaction: reagents consumed and equipment reserved,
    waiting for the game clock to reach end_time before it can be collected."""
    process_id: str
    reaction_name: str
    definition: ReactionDefinition
    reagents: dict[str, float]
    solvent: str | None
    temperature: float
    scheduled_hours: float
    start_time: float
    end_time: float
    equipment_ids: list[str]
    limiting_ratio: float
    condition_score: float

    def is_ready(self, game_clock: GameClock) -> bool:
        return game_clock.now() >= self.end_time

    def time_remaining(self, game_clock: GameClock) -> float:
        return max(0.0, self.end_time - game_clock.now())


def reference_reagent_for(definition: ReactionDefinition) -> str:
    """Which reactant "1 mole of reference reagent" is scaled against --
    definition.reference_reagent if set, else whichever reactant is listed
    first (fine for the 1:1 recipes so far; worth setting explicitly once a
    recipe's ratios aren't all equal)."""
    return definition.reference_reagent or next(iter(definition.reactants))


def reagents_for_scale(definition: ReactionDefinition, reference_moles: float) -> dict[str, float]:
    """
    Scale a reaction's base reactant ratios so the reference reagent (see
    reference_reagent_for) totals `reference_moles`, preserving the
    recipe's ratios for everything else. This is the single knob the
    amount picker turns -- "moles of limiting reagent" -- expanded into the
    full reagents dict start_reaction() needs.
    """
    ref = reference_reagent_for(definition)
    ref_coeff = definition.reactants[ref]
    if ref_coeff <= 0:
        raise ValueError(f"Reference reagent '{ref}' has a non-positive stoichiometric coefficient")
    scale = reference_moles / ref_coeff
    return {name: coeff * scale for name, coeff in definition.reactants.items()}


def reaction_volume_ml(reagents: dict[str, float], inventory: ChemicalInventory) -> float | None:
    """
    Total real-world volume (mL) the given reagent amounts would occupy in
    a vessel, based on whatever currently supplies each one (a direct
    stock, or a solution -- see ChemicalInventory.resolve_supplier). Solid
    reagents (tracked by mass, not volume -- e.g. sodium cyanide) don't
    contribute; that's a real simplification, but treating them as
    occupying ~0 mL is a reasonable one for a solid dissolved into a
    liquid-dominated reaction volume.

    Returns None if any reagent currently has no supplier at all, since
    there's nothing to size against -- callers that already validated
    inventory.has_moles() for each reagent won't normally see this.
    """
    total_ml = 0.0
    for name, moles in reagents.items():
        supplier = inventory.resolve_supplier(name)
        if supplier is None:
            return None
        species = inventory.species_for(supplier)
        if species.state == "solid":
            continue
        total_ml += moles / species.moles_per_unit()
    return total_ml


def reaction_scale_bounds(
    definition: ReactionDefinition,
    inventory: ChemicalInventory,
    flask_capacity_ml: float,
) -> tuple[float, float] | None:
    """
    (recommended_min_moles, max_moles) of the reference reagent for running
    this reaction in a vessel of flask_capacity_ml:
      - max_moles fills MAX_FILL_FRACTION of the vessel -- a hard cap, since
        past this the reaction mixture just doesn't fit.
      - recommended_min_moles fills RECOMMENDED_MIN_FILL_FRACTION -- a
        suggestion, not enforced (a smaller amount is allowed; see
        start_reaction's underfill yield penalty).

    Both scale with how concentrated whatever's currently supplying each
    reagent is -- a stronger acid solution needs less volume per mole, so
    it raises how much you can make in the same flask. Returns None if the
    per-mole volume can't be determined (see reaction_volume_ml).
    """
    unit_reagents = reagents_for_scale(definition, 1.0)
    ml_per_reference_mole = reaction_volume_ml(unit_reagents, inventory)
    if not ml_per_reference_mole:
        return None
    return (
        flask_capacity_ml * RECOMMENDED_MIN_FILL_FRACTION / ml_per_reference_mole,
        flask_capacity_ml * MAX_FILL_FRACTION / ml_per_reference_mole,
    )


# ===============================================================
# Reaction Engine
# ===============================================================

class ReactionEngine:
    """
    Evaluates and executes chemical reactions based on a simple reaction database.

    Running a reaction is two phases:
      1. start_reaction(...) - validates reagents & equipment, reserves the
         equipment, consumes the reagents, and schedules a ReactionProcess to
         finish at some point on the GameClock.
      2. collect_reaction(...) - once the game clock has reached the
         process's end_time, this finalizes the crude products into the
         inventory and frees up the equipment again.
    """

    def __init__(self, reaction_file: str):
        self.reaction_db = self._load_reactions(reaction_file)
        self.active_processes: dict[str, ReactionProcess] = {}
        self.history: list[ReactionLogEntry] = []
        self._process_id_counter = itertools.count(1)

    def _load_reactions(self, path: str) -> dict[str, ReactionDefinition]:
        """Load JSON reaction data into ReactionDefinition objects."""
        with open(path, "r") as f:
            data = json.load(f)
        db = {}
        for name, r in data.items():
            db[name] = ReactionDefinition(**r)
        return db

    def find_match(self, reagents: dict[str, float]) -> tuple[str, ReactionDefinition] | None:
        """
        Check whether the provided reagents match any known reaction.
        Returns (reaction_name, definition) or None if no match.
        """
        reagent_keys = set(reagents.keys())

        for name, definition in self.reaction_db.items():
            required_keys = set(definition.reactants.keys())
            if reagent_keys == required_keys:
                return name, definition

        return None

    def start_reaction(
        self,
        inventory: ChemicalInventory,
        equipment_inventory: EquipmentInventory,
        reagents: dict[str, float],
        solvent: str | None,
        temperature: float,
        time_hours: float,
        game_clock: GameClock,
        preferred_flask_id: str | None = None,
    ) -> ReactionProcess | dict[str, float]:
        """
        Attempt to start a reaction.

        If the reagents don't match any known reaction, nothing is consumed
        or reserved, and {"unknown mixture": 1.0} is returned directly
        instead of a process.

        Otherwise, equipment is reserved (all-or-nothing -- raises
        EquipmentUnavailableError if anything required is missing or busy),
        reagents are consumed from inventory, and a ReactionProcess is
        returned that will be ready to collect once the game clock reaches
        its end_time.

        preferred_flask_id reserves that specific rb_flask (e.g. one the
        player picked at the bench) instead of auto-picking the smallest
        sufficient one; the reaction is rejected if it doesn't fit or isn't
        free. Left as None, the old best-fit behavior applies.
        """
        # Check inventory has enough of each reagent (resolved through
        # whatever actually supplies it -- a direct stock, or a solution
        # whose solute matches, e.g. "48% hydrobromic acid" supplying HBr)
        for r, amt in reagents.items():
            if not inventory.has_moles(r, amt):
                logger.warning("start_reaction rejected: not enough %s (need %.2f mol, have %.2f mol)",
                                r, amt, inventory.available_moles(r))
                raise ValueError(f"Not enough {r} in inventory to run reaction.")

        match = self.find_match(reagents)
        if not match:
            logger.debug("start_reaction: reagents %s matched no known reaction", reagents)
            return {"unknown mixture": 1.0}

        reaction_name, definition = match
        logger.debug("start_reaction: matched '%s' for reagents %s", reaction_name, reagents)

        # --- Reaction volume must fit in the reserved flask ---
        required_ml = reaction_volume_ml(reagents, inventory) or 0.0

        # --- Reserve equipment (all-or-nothing) ---
        equipment_ids = equipment_inventory.reserve_set(
            definition.equipment, min_flask_capacity=required_ml, preferred_flask_id=preferred_flask_id,
        )
        if equipment_ids is None:
            missing = equipment_inventory.missing_types(
                definition.equipment, min_flask_capacity=required_ml
            )
            missing_desc = ", ".join(missing) if missing else "equipment"
            logger.warning("start_reaction rejected: missing/busy equipment %s for '%s' (needs %.1f mL)",
                            missing, reaction_name, required_ml)
            raise EquipmentUnavailableError(
                f"Missing or busy: {missing_desc} "
                f"(need a flask holding at least {required_ml:.1f} mL for '{reaction_name}')"
            )
        logger.debug("start_reaction: reserved equipment %s for '%s'", equipment_ids, reaction_name)

        # --- Condition matching (computed now, applied at collection) ---
        condition_score = 1.0
        if definition.solvent and solvent != definition.solvent:
            condition_score *= 0.5
        temp_diff = abs(temperature - definition.temperature)
        if temp_diff > 10:
            condition_score *= 0.5
        elif temp_diff > 5:
            condition_score *= 0.8
        time_ratio = time_hours / definition.time_hours
        if time_ratio < 0.5 or time_ratio > 1.5:
            condition_score *= 0.5
        elif time_ratio < 0.8 or time_ratio > 1.2:
            condition_score *= 0.8

        # Filling the flask below RECOMMENDED_MIN_FILL_FRACTION is allowed
        # (no hard minimum -- see reaction_scale_bounds) but isn't how
        # you'd really run it, so it costs yield same as any other
        # off-spec condition above.
        flask_item = next(
            (equipment_inventory.items[i] for i in equipment_ids
             if equipment_inventory.items[i].type == "rb_flask"),
            None,
        )
        if flask_item is not None and flask_item.capacity:
            if required_ml < flask_item.capacity * RECOMMENDED_MIN_FILL_FRACTION:
                condition_score *= UNDERFILL_YIELD_PENALTY
                logger.debug("start_reaction: '%s' underfilled (%.1f mL in a %.1f mL flask) -- yield penalty applied",
                             reaction_name, required_ml, flask_item.capacity)

        limiting_ratio = min(
            reagents[r] / req for r, req in definition.reactants.items()
        )

        # --- Consume reagents from inventory ---
        for r, amt in reagents.items():
            inventory.remove_moles(r, amt)

        process_id = f"proc_{next(self._process_id_counter)}"
        start_time = game_clock.now()
        process = ReactionProcess(
            process_id=process_id,
            reaction_name=reaction_name,
            definition=definition,
            reagents=dict(reagents),
            solvent=solvent,
            temperature=temperature,
            scheduled_hours=time_hours,
            start_time=start_time,
            end_time=start_time + time_hours,
            equipment_ids=equipment_ids,
            limiting_ratio=limiting_ratio,
            condition_score=condition_score,
        )
        self.active_processes[process_id] = process
        logger.info("Started '%s' (%s): condition_score=%.2f, ready at t=%.2fh",
                    reaction_name, process_id, condition_score, process.end_time)
        return process

    def collect_reaction(
        self,
        process_id: str,
        inventory: ChemicalInventory,
        equipment_inventory: EquipmentInventory,
        game_clock: GameClock,
    ) -> dict[str, float]:
        """
        Finalize a reaction that has finished (game_clock.now() >= end_time):
        adds crude products to inventory, releases the reserved equipment,
        and returns the product amounts (side products included for
        logging, but not added to inventory).
        """
        process = self.active_processes.get(process_id)
        if process is None:
            logger.error("collect_reaction called with unknown process_id '%s'", process_id)
            raise KeyError(f"No active reaction process with id '{process_id}'")

        if not process.is_ready(game_clock):
            logger.warning("collect_reaction rejected: '%s' has %.2fh remaining",
                            process.reaction_name, process.time_remaining(game_clock))
            raise ReactionNotReadyError(
                f"'{process.reaction_name}' isn't done yet: "
                f"{process.time_remaining(game_clock):.2f}h remaining"
            )

        definition = process.definition
        efficiency = definition.efficiency * process.condition_score

        products: dict[str, float] = {}

        # Main (crude) products -> added to inventory
        for product, stoich in definition.products.items():
            amt = stoich * process.limiting_ratio * efficiency
            products[f"{product} (crude)"] = amt
            inventory.add_moles(f"{product} (crude)", amt)

        # Side products -> tracked in the result for logging, not stored
        for side, stoich in definition.side_products.items():
            amt = stoich * process.limiting_ratio * efficiency
            products[side] = amt

        equipment_inventory.release_set(process.equipment_ids)
        del self.active_processes[process_id]

        self.history.append(ReactionLogEntry(
            reaction_name=process.reaction_name,
            start_time=process.start_time,
            end_time=process.end_time,
            solvent=process.solvent,
            temperature=process.temperature,
            scheduled_hours=process.scheduled_hours,
            yield_fraction=efficiency,
            products=dict(products),
            side_products={s: products[s] for s in definition.side_products if s in products},
        ))

        logger.info("Collected '%s' (%s): %s; released equipment %s",
                    process.reaction_name, process_id, products, process.equipment_ids)
        return products


if __name__ == "__main__":
    from inventory import load_species_catalog

    species = load_species_catalog("src/data/chemicals.json")
    inv = ChemicalInventory(species_catalog=species)
    inv.add("48% hydrobromic acid", 250.0)   # supplies HBr, moles derived from molarity
    inv.add("ethanol", 150.0)
    inv.add("sodium cyanide", 50.0)
    inv.add("ethyl bromide", 100.0)

    equipment = EquipmentInventory()
    equipment.add_item("rb_flask", "250 mL RB Flask", capacity=2.0)
    equipment.add_item("condenser", "Reflux Condenser")
    equipment.add_item("tubing", "Rubber Tubing")
    equipment.add_item("heating_mantle", "Heating Mantle")
    equipment.add_item("stir_bar", "Stir Bar")
    equipment.add_item("magnetic_stirrer", "Magnetic Stirrer")

    clock = GameClock()
    engine = ReactionEngine("src/data/reactions.json")

    print("Initial inventory:", inv)

    process = engine.start_reaction(
        inv, equipment, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20, 4, clock
    )
    print(f"\nStarted '{process.reaction_name}', ready at t={process.end_time}h")
    print("Equipment reserved:", process.equipment_ids)

    clock.advance_to(process.end_time)  # warp to completion
    result = engine.collect_reaction(process.process_id, inv, equipment, clock)
    print("\nReaction result:", result)
    print("Updated inventory:", inv)
    print("Equipment freed:", [i.in_use for i in equipment.items.values()])
