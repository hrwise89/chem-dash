"""
Inventory systems for Chem Dash.

Two kinds of inventory:
  - ChemicalInventory: tracks chemical stock in moles. Purity is tracked as a
    binary crude/pure state encoded directly in the chemical's name (e.g.
    "ethyl bromide" vs "ethyl bromide (crude)"), consistent with how the
    reaction engine already labels its crude output. Purification mini-games
    (column, recrystallization) are what will move stock from the "(crude)"
    key to the plain (pure) key.
  - EquipmentInventory: tracks discrete pieces of lab glassware/equipment
    (RB flasks, condensers, tubing, heating mantles, stir bars, magnetic
    stirrers, ...). Each item can be free or in_use. Reservations for a
    reaction are all-or-nothing: either every required role is available
    and gets reserved together, or nothing is touched.
"""

import itertools
import json
from dataclasses import dataclass

# ===============================================================
# Chemical inventory
# ===============================================================

class ChemicalInventory:
    """Tracks available chemicals and quantities in moles."""

    def __init__(self):
        self.contents: dict[str, float] = {}

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
        return f"ChemicalInventory({self.contents})"


# Backwards-compatible alias: reaction_engine.py (and earlier tests) referred
# to this class as `Inventory`.
Inventory = ChemicalInventory


# ===============================================================
# Equipment / glassware inventory
# ===============================================================

class EquipmentUnavailableError(Exception):
    """Raised when a reaction can't reserve all the equipment it needs."""


@dataclass
class EquipmentItem:
    """A single physical piece of lab equipment the player owns."""
    id: str
    type: str                       # e.g. "rb_flask", "condenser", "tubing",
                                     # "heating_mantle", "stir_bar", "magnetic_stirrer"
    name: str
    capacity: float | None = None  # only meaningful for vessels like rb_flask,
                                       # in the same abstract "scale" units as
                                       # reagent moles
    in_use: bool = False


class EquipmentInventory:
    """Owns the player's pool of EquipmentItems and handles reservations."""

    def __init__(self):
        self.items: dict[str, EquipmentItem] = {}
        self._id_counter = itertools.count(1)

    def add_item(self, type_: str, name: str, capacity: float | None = None,
                 item_id: str | None = None) -> EquipmentItem:
        """Add a new piece of equipment to the player's inventory."""
        if item_id is None:
            item_id = f"{type_}_{next(self._id_counter)}"
        item = EquipmentItem(id=item_id, type=type_, name=name, capacity=capacity)
        self.items[item.id] = item
        return item

    def available_items(self, type_: str, min_capacity: float | None = None) -> list[EquipmentItem]:
        """List free items of a given type, optionally requiring a minimum capacity."""
        results = []
        for item in self.items.values():
            if item.type != type_ or item.in_use:
                continue
            if min_capacity is not None and (item.capacity is None or item.capacity < min_capacity):
                continue
            results.append(item)
        return results

    def reserve_set(self, required_types: list[str],
                     min_flask_capacity: float | None = None) -> list[str] | None:
        """
        Attempt to reserve one free item per required type, all at once.

        For the "rb_flask" role, only flasks with capacity >= min_flask_capacity
        are considered, and the smallest one that fits is chosen (best fit).

        Returns the list of reserved item ids on success, or None if any
        required role couldn't be satisfied (in which case nothing is reserved).
        """
        chosen: list[EquipmentItem] = []
        chosen_ids = set()

        for type_ in required_types:
            min_cap = min_flask_capacity if type_ == "rb_flask" else None
            candidates = [
                item for item in self.available_items(type_, min_capacity=min_cap)
                if item.id not in chosen_ids
            ]
            if not candidates:
                return None  # all-or-nothing: bail without reserving anything

            if type_ == "rb_flask" and min_cap is not None:
                candidates.sort(key=lambda item: item.capacity)

            pick = candidates[0]
            chosen.append(pick)
            chosen_ids.add(pick.id)

        for item in chosen:
            item.in_use = True

        return [item.id for item in chosen]

    def release_set(self, item_ids: list[str]) -> None:
        """Free up a set of previously-reserved items (e.g. after a reaction completes)."""
        for item_id in item_ids:
            if item_id in self.items:
                self.items[item_id].in_use = False

    def __repr__(self):
        return f"EquipmentInventory({list(self.items.values())})"


# ===============================================================
# Loading inventories from data (starting loadouts, and later saves)
# ===============================================================
#
# Both loaders below take an already-parsed dict/list, not a file path.
# That's the piece meant to carry forward into a future save system: a
# starting-loadout file and a save file will assemble this dict differently
# (a save adds each equipment item's "id" and "in_use" to preserve identity
# and reservation state across a load), but both can hand off to the same
# "build an inventory from this shape" logic here.

def chemical_inventory_from_dict(data: dict) -> ChemicalInventory:
    """Build a ChemicalInventory from a {chemical_name: moles} mapping."""
    inventory = ChemicalInventory()
    for name, amount in data.items():
        inventory.add(name, amount)
    return inventory


def equipment_inventory_from_dict(data: list) -> EquipmentInventory:
    """
    Build an EquipmentInventory from a list of item dicts, each with at
    least "type" and "name". "capacity" is optional (only vessels like
    rb_flask need it). "id" and "in_use" are also optional -- a starting
    loadout can omit them (fresh equipment, nothing reserved yet, ids
    auto-assigned), while a save file would include both to restore exact
    identity and in-progress reservations.
    """
    inventory = EquipmentInventory()
    for entry in data:
        item = inventory.add_item(
            type_=entry["type"],
            name=entry["name"],
            capacity=entry.get("capacity"),
            item_id=entry.get("id"),
        )
        item.in_use = entry.get("in_use", False)
    return inventory


def load_starting_inventories(path: str) -> tuple[ChemicalInventory, EquipmentInventory]:
    """
    Load the player's default starting chemicals + equipment from a JSON
    file shaped like:
        {"chemicals": {"HBr": 2.0, ...}, "equipment": [{"type": ..., "name": ...}, ...]}
    """
    with open(path, "r") as f:
        data = json.load(f)
    chemicals = chemical_inventory_from_dict(data.get("chemicals", {}))
    equipment = equipment_inventory_from_dict(data.get("equipment", []))
    return chemicals, equipment
