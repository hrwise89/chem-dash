import itertools
import json
from dataclasses import dataclass, field

from game_clock import GameClock
from inventory import ChemicalInventory, EquipmentInventory, EquipmentUnavailableError

# Re-exported for convenience / backwards compatibility with code that used
# to import Inventory directly from reaction_engine.
Inventory = ChemicalInventory


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
        """
        # Check inventory has enough of each reagent
        for r, amt in reagents.items():
            if not inventory.has(r, amt):
                raise ValueError(f"Not enough {r} in inventory to run reaction.")

        match = self.find_match(reagents)
        if not match:
            return {"unknown mixture": 1.0}

        reaction_name, definition = match

        # --- Reaction scale must fit in the reserved flask ---
        scale = sum(reagents.values())

        # --- Reserve equipment (all-or-nothing) ---
        equipment_ids = equipment_inventory.reserve_set(
            definition.equipment, min_flask_capacity=scale
        )
        if equipment_ids is None:
            raise EquipmentUnavailableError(
                f"Missing or busy equipment for '{reaction_name}' "
                f"(need: {definition.equipment}, scale: {scale} mol)"
            )

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

        limiting_ratio = min(
            reagents[r] / req for r, req in definition.reactants.items()
        )

        # --- Consume reagents from inventory ---
        for r, amt in reagents.items():
            inventory.remove(r, amt)

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
            raise KeyError(f"No active reaction process with id '{process_id}'")

        if not process.is_ready(game_clock):
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
            inventory.add(f"{product} (crude)", amt)

        # Side products -> tracked in the result for logging, not stored
        for side, stoich in definition.side_products.items():
            amt = stoich * process.limiting_ratio * efficiency
            products[side] = amt

        equipment_inventory.release_set(process.equipment_ids)
        del self.active_processes[process_id]

        return products


if __name__ == "__main__":
    inv = ChemicalInventory()
    inv.add("HBr", 2.0)
    inv.add("ethanol", 2.0)
    inv.add("sodium cyanide", 1.0)
    inv.add("ethyl bromide", 1.0)

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
