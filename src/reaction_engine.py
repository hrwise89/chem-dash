from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
import json
import os


# ===============================================================
# Reaction data structures
# ===============================================================

@dataclass
class ReactionDefinition:
    """Defines a valid reaction with required reagents and conditions."""
    reactants: Dict[str, float]                # name -> stoichiometric moles (base ratio)
    products: Dict[str, float]                 # name -> moles produced per reaction
    side_products: Dict[str, float] = field(default_factory=dict)
    solvent: Optional[str] = None              # e.g., 'neat' or 'water'
    temperature: float = 25.0                  # ideal temp in °C
    time_hours: float = 1.0                    # ideal reaction time
    efficiency: float = 1.0                    # yield factor (0–1)


# ===============================================================
# Reaction Engine
# ===============================================================

class ReactionEngine:
    """
    Evaluates and executes chemical reactions based on a simple reaction database.
    """

    def __init__(self, reaction_file: str):
        self.reaction_db = self._load_reactions(reaction_file)

    def _load_reactions(self, path: str) -> Dict[str, ReactionDefinition]:
        """Load JSON reaction data into ReactionDefinition objects."""
        with open(path, "r") as f:
            data = json.load(f)
        db = {}
        for name, r in data.items():
            db[name] = ReactionDefinition(**r)
        return db

    def find_match(self, reagents: Dict[str, float]) -> Optional[Tuple[str, ReactionDefinition]]:
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

    def run_reaction(
        self,
        inventory,
        reagents: Dict[str, float],
        solvent: Optional[str],
        temperature: float,
        time_hours: float,
    ) -> Dict[str, float]:
        """Simulate a reaction, consume inventory reagents, return crude product amounts."""

        # Check inventory
        for r, amt in reagents.items():
            if not inventory.has(r, amt):
                raise ValueError(f"Not enough {r} in inventory to run reaction.")
            if amt > 2.0:
                raise ValueError(f"Reagent amount too large: {r} ({amt} mol, limit 2.0)")

        match = self.find_match(reagents)
        if not match:
            return {"unknown mixture": 1.0}

        reaction_name, definition = match

        # --- Condition matching ---
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
        efficiency = definition.efficiency * condition_score

        # --- Consume reagents from inventory ---
        for r, amt in reagents.items():
            inventory.remove(r, amt)

        # --- Add crude products to inventory ---
        products = {}

        # Main (crude) products — add to inventory
        for product, stoich in definition.products.items():
            amt = stoich * limiting_ratio * efficiency
            products[f"{product} (crude)"] = amt
            inventory.add(f"{product} (crude)", amt)

        # Side products — include in result for logging, but don't add to inventory
        for side, stoich in definition.side_products.items():
            amt = stoich * limiting_ratio * efficiency
            products[side] = amt  # tracked in result only, not stored in inventory

        return products

# ===============================================================
# Simple Inventory System
# ===============================================================

class Inventory:
    """Tracks available chemicals and quantities in moles."""

    def __init__(self):
        self.contents: Dict[str, float] = {}

    def add(self, name: str, amount: float):
        self.contents[name] = self.contents.get(name, 0.0) + amount

    def remove(self, name: str, amount: float):
        if self.has(name, amount):
            self.contents[name] -= amount
            if self.contents[name] <= 0:
                del self.contents[name]
        else:
            raise ValueError(f"Not enough {name} in inventory to remove {amount} mol")

    def has(self, name: str, amount: float) -> bool:
        return self.contents.get(name, 0.0) >= amount

    def __repr__(self):
        return f"Inventory({self.contents})"


if __name__ == "__main__":
    inv = Inventory()
    inv.add("HBr", 2.0)
    inv.add("ethanol", 2.0)
    inv.add("sodium cyanide", 1.0)
    inv.add("ethyl bromide", 1.0)

    engine = ReactionEngine("src/data/reactions.json")

    print("Initial inventory:", inv)

    result = engine.run_reaction(inv, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20, 4)
    print("\nReaction result:", result)
    print("Updated inventory:", inv)

    result2 = engine.run_reaction(inv, {"sodium cyanide": 1.0, "ethyl bromide": 1.0}, "toluene", 40, 4)
    print("\nReaction result:", result2)
    print("Updated inventory:", inv)