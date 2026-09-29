"""
Inventory systems for Chem Dash.

Two kinds of inventory:
  - ChemicalInventory: tracks chemical stock in real-world units -- grams
    for a solid, mL for a liquid or a solution -- rather than moles
    directly. What a name actually means physically (its state, molecular
    weight, and for a liquid/solution its molarity) lives in a separate
    "species catalog" (see ChemicalSpecies below), so the same inventory
    entry can answer "how many moles of X do I have" on demand.

    A solution (e.g. "48% hydrobromic acid") is a container for some other
    reactive species (its `solute`, e.g. "HBr"): a reaction that calls for
    HBr can be supplied by any solution whose solute is HBr, without the
    solution masquerading as pure HBr in the inventory list. Resolving
    "what supplies chemical X" is resolve_supplier(); has_moles(),
    remove_moles(), and add_moles() are the mole-based read/write API that
    reaction_engine.py (and anything else that thinks in moles) should use
    -- add()/remove()/has() stay as the low-level, unit-agnostic API for
    loaders and code (like purification.py) that only needs to move a
    physical quantity around without caring what it converts to.

    Purity is tracked as a binary crude/pure state encoded directly in the
    chemical's name (e.g. "ethyl bromide" vs "ethyl bromide (crude)"),
    consistent with how the reaction engine already labels its crude
    output; crude and pure forms share the same species definition (same
    substance, just impure), so species lookups strip the suffix.
  - EquipmentInventory: tracks discrete pieces of lab glassware/equipment
    (RB flasks, purification columns, ...). Each item can be free or
    in_use. Reservations for a reaction are all-or-nothing: either every
    required role is available and gets reserved together, or nothing is
    touched.
"""

import itertools
import json
import os
from dataclasses import dataclass

# ===============================================================
# Crude/pure naming
# ===============================================================
# A single, shared place for the "(crude)" naming convention -- both
# ChemicalInventory (species lookups) and purification.py (which chemicals
# count as purifiable) need it, so it lives here rather than being defined
# twice.

CRUDE_SUFFIX = " (crude)"


class NotCrudeError(ValueError):
    """Raised when asked to treat something as crude that isn't."""


def is_crude(name: str) -> bool:
    return name.endswith(CRUDE_SUFFIX)


def pure_name_for(crude_name: str) -> str:
    """'ethyl bromide (crude)' -> 'ethyl bromide'."""
    if not is_crude(crude_name):
        raise NotCrudeError(f"'{crude_name}' is not a crude chemical (no '{CRUDE_SUFFIX}' suffix)")
    return crude_name[: -len(CRUDE_SUFFIX)]


def crude_name_for(pure_name: str) -> str:
    """'ethyl bromide' -> 'ethyl bromide (crude)'."""
    if is_crude(pure_name):
        raise ValueError(f"'{pure_name}' is already a crude name")
    return pure_name + CRUDE_SUFFIX


def canonical_species_name(name: str) -> str:
    """The name to look up in the species catalog: crude and pure forms of
    the same substance share one definition, so a crude name resolves to
    its pure name first."""
    return pure_name_for(name) if is_crude(name) else name


# ===============================================================
# Chemical species catalog
# ===============================================================

@dataclass
class ChemicalSpecies:
    """
    What a chemical *is*, independent of how much of it you have:
      - "solid": tracked in grams; needs molecular_weight to convert to moles.
      - "liquid": tracked in mL; needs molarity (mol/L) to convert to moles
        (for a pure liquid this is its neat concentration -- moles per
        liter of the liquid itself, derivable from density/molecular_weight).
      - "solution": tracked in mL like a liquid, but stands in for some
        other reactive species (`solute`) rather than being that species
        itself -- e.g. "48% hydrobromic acid" is a solution whose solute
        is "HBr". `solvent` is informational for now (e.g. "water").
    """
    name: str
    state: str                        # "solid" | "liquid" | "solution"
    molecular_weight: float | None = None   # g/mol -- required for "solid"
    molarity: float | None = None           # mol/L -- required for "liquid"/"solution"
    solute: str | None = None               # required for "solution"
    solvent: str | None = None              # informational, "solution" only
    density: float | None = None            # g/mL -- required for "liquid". Lets
                                             # purification.py convert a liquid's
                                             # native mL amount to a mass in grams,
                                             # the unit purification always works in
                                             # (so the same mass-based slider/cost
                                             # numbers apply to solids and liquids
                                             # alike). Purely a property for now --
                                             # nothing else reads it yet.
    price_per_unit: float | None = None     # $ per native unit (g or mL), for the
                                             # computer bench's catalogue; None means
                                             # it isn't sold there (e.g. a product
                                             # the player makes rather than buys)
    short_name: str | None = None           # e.g. "EtOH" -- what a fixed-width list
                                             # row shows; None falls back to `name`
    description: str = ""                   # the catalogue's description-panel text; "" is
                                             # rendered as a generic placeholder, not blank

    @property
    def display_name(self) -> str:
        return self.short_name or self.name

    def __post_init__(self):
        if self.state == "solid" and not self.molecular_weight:
            raise ValueError(f"Solid species '{self.name}' needs a molecular_weight")
        if self.state in ("liquid", "solution") and not self.molarity:
            raise ValueError(f"{self.state.capitalize()} species '{self.name}' needs a molarity")
        if self.state == "liquid" and not self.density:
            raise ValueError(f"Liquid species '{self.name}' needs a density")
        if self.state == "solution" and not self.solute:
            raise ValueError(f"Solution species '{self.name}' needs a solute")
        if self.state not in ("solid", "liquid", "solution"):
            raise ValueError(f"Unknown species state '{self.state}' for '{self.name}'")

    def moles_per_unit(self) -> float:
        """Moles per native unit of stored amount: per gram for a solid,
        per mL for a liquid or solution (molarity is mol/L, so mol/mL is
        molarity / 1000)."""
        if self.state == "solid":
            return 1.0 / self.molecular_weight
        return self.molarity / 1000.0

    def unit_label(self) -> str:
        return "g" if self.state == "solid" else "mL"


def load_species_catalog(path: str) -> dict[str, ChemicalSpecies]:
    """Load a {name: {state, molecular_weight, molarity, solute, solvent}}
    JSON file into ChemicalSpecies objects."""
    with open(path, "r") as f:
        data = json.load(f)
    return {name: ChemicalSpecies(name=name, **spec) for name, spec in data.items()}


# ===============================================================
# Chemical inventory
# ===============================================================

class ChemicalInventory:
    """
    Tracks available chemicals by real-world quantity (grams for a solid,
    mL for a liquid/solution) rather than moles. A species_catalog (see
    ChemicalSpecies) is what makes moles-based reads/writes possible; an
    inventory can be built without one (contents-only bookkeeping still
    works via add()/remove()/has()), but has_moles()/remove_moles()/
    add_moles()/moles_of()/describe() all need it.
    """

    def __init__(self, species_catalog: dict[str, ChemicalSpecies] | None = None):
        self.contents: dict[str, float] = {}          # name -> amount in native units
        self.species_catalog = species_catalog or {}

    # ---- low-level, unit-agnostic (grams or mL, whatever the name uses) ----

    def add(self, name: str, amount: float):
        self.contents[name] = self.contents.get(name, 0.0) + amount

    def remove(self, name: str, amount: float):
        if self.has(name, amount):
            self.contents[name] -= amount
            if self.contents[name] <= 0:
                del self.contents[name]
        else:
            raise ValueError(f"Not enough {name} in inventory to remove {amount}")

    def has(self, name: str, amount: float) -> bool:
        return self.contents.get(name, 0.0) >= amount

    # ---- species lookups ----

    def species_for(self, name: str) -> ChemicalSpecies:
        """The species definition for `name`, stripping a '(crude)' suffix
        first since crude/pure share one definition. Raises KeyError if
        the catalog has no entry for it."""
        lookup_name = canonical_species_name(name)
        species = self.species_catalog.get(lookup_name)
        if species is None:
            raise KeyError(f"No species definition for '{name}' (looked up as '{lookup_name}')")
        return species

    def moles_of(self, name: str) -> float:
        """Moles of `name` currently held, computed from its stored
        quantity and species definition. 0.0 if none is held (even if the
        species is unknown -- nothing to convert)."""
        amount = self.contents.get(name, 0.0)
        if amount <= 0:
            return 0.0
        return amount * self.species_for(name).moles_per_unit()

    def describe(self, name: str) -> str:
        """A human-readable "<amount> <unit> (<moles> mol)" string for the
        UI, e.g. "700.0 mL (6.16 mol)"."""
        amount = self.contents.get(name, 0.0)
        species = self.species_for(name)
        moles = amount * species.moles_per_unit()
        return f"{amount:.1f} {species.unit_label()} ({moles:.2f} mol)"

    # ---- moles-based read/write (what reaction_engine.py uses) ----

    def resolve_supplier(self, identity: str) -> str | None:
        """
        Which inventory entry (by name) currently supplies chemical
        `identity` -- either an entry named exactly that, or (failing that)
        any solution entry whose `solute` is `identity`. Returns None if
        nothing in inventory supplies it. Does not consider quantity.
        """
        if identity in self.contents:
            return identity
        for held_name, amount in self.contents.items():
            if amount <= 0:
                continue
            try:
                species = self.species_for(held_name)
            except KeyError:
                continue
            if species.state == "solution" and species.solute == identity:
                return held_name
        return None

    def available_moles(self, identity: str) -> float:
        """Moles of `identity` available from whatever currently supplies
        it (0.0 if nothing does)."""
        supplier = self.resolve_supplier(identity)
        return self.moles_of(supplier) if supplier else 0.0

    def has_moles(self, identity: str, moles: float) -> bool:
        return self.available_moles(identity) >= moles

    def remove_moles(self, identity: str, moles: float):
        """Remove `moles` of `identity` from whatever supplies it (a direct
        entry, or a solution's stock). Raises ValueError if nothing
        supplies enough."""
        supplier = self.resolve_supplier(identity)
        if supplier is None or not self.has_moles(identity, moles):
            have = self.available_moles(identity)
            raise ValueError(
                f"Not enough {identity} in inventory to remove {moles:.2f} mol (have {have:.2f} mol)"
            )
        native_amount = moles / self.species_for(supplier).moles_per_unit()
        self.remove(supplier, native_amount)

    def add_moles(self, name: str, moles: float):
        """Add `moles` of `name` to inventory, converted to native units
        via its own species definition (crude-suffix-aware). Unlike
        remove_moles, this always adds under `name` directly -- products
        are stored by their own produced name, not resolved through a
        solute."""
        native_amount = moles / self.species_for(name).moles_per_unit()
        self.add(name, native_amount)

    def __repr__(self):
        return f"ChemicalInventory({self.contents})"


# Backwards-compatible alias: reaction_engine.py (and earlier tests) referred
# to this class as `Inventory`.
Inventory = ChemicalInventory


# ===============================================================
# Consumable supplies (not chemicals -- e.g. silica for column packing)
# ===============================================================

class ConsumableInventory:
    """
    Tracks disposable lab supplies used up by actions rather than reacted --
    e.g. silica for column chromatography. Unlike ChemicalInventory, there's
    no species catalog/moles conversion: just a name -> amount (native
    units, e.g. grams) ledger, consumed by plain quantity.
    """

    def __init__(self):
        self.contents: dict[str, float] = {}

    def add(self, name: str, amount: float):
        self.contents[name] = self.contents.get(name, 0.0) + amount

    def remove(self, name: str, amount: float):
        if not self.has(name, amount):
            raise ValueError(f"Not enough {name} in inventory to remove {amount}")
        self.contents[name] -= amount
        if self.contents[name] <= 0:
            del self.contents[name]

    def has(self, name: str, amount: float) -> bool:
        return self.contents.get(name, 0.0) >= amount

    def __repr__(self):
        return f"ConsumableInventory({self.contents})"


@dataclass
class ConsumableCatalogEntry:
    """A consumable's *catalog* metadata: which bench(es) it's used at, its
    purchase price, and its display unit. Kept separate from
    ConsumableInventory (a bare name -> amount ledger) the same way
    ChemicalSpecies is kept separate from ChemicalInventory."""
    name: str
    bench: list[str]                # e.g. ["reaction", "purify"]
    price: float | None = None      # $ per native unit, for the computer bench's catalogue
    unit: str = "unit"
    short_name: str | None = None   # what a fixed-width list row shows; None falls back to `name`
    description: str = ""           # the catalogue's description-panel text; "" is
                                     # rendered as a generic placeholder, not blank

    @property
    def display_name(self) -> str:
        return self.short_name or self.name


def load_consumable_catalog(path: str) -> dict[str, ConsumableCatalogEntry]:
    """Load a {name: {bench, price, unit}} JSON file into
    ConsumableCatalogEntry objects -- see src/data/consumables.json."""
    with open(path, "r") as f:
        data = json.load(f)
    return {name: ConsumableCatalogEntry(name=name, **spec) for name, spec in data.items()}


# ===============================================================
# Equipment / glassware inventory
# ===============================================================

class EquipmentUnavailableError(Exception):
    """Raised when a reaction can't reserve all the equipment it needs."""


@dataclass
class EquipmentItem:
    """A single physical piece of lab equipment the player owns."""
    id: str
    type: str                       # e.g. "rb_flask", "chroma_column_micro"
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
                     min_flask_capacity: float | None = None,
                     preferred_flask_id: str | None = None) -> list[str] | None:
        """
        Attempt to reserve one free item per required type, all at once.

        For the "rb_flask" role, only flasks with capacity >= min_flask_capacity
        are considered, and the smallest one that fits is chosen (best fit) --
        unless preferred_flask_id names a specific flask (e.g. one the
        player picked at the bench), in which case that exact flask is
        reserved instead, or the whole reservation fails if it's busy, too
        small, or doesn't exist.

        Returns the list of reserved item ids on success, or None if any
        required role couldn't be satisfied (in which case nothing is reserved).
        """
        chosen: list[EquipmentItem] = []
        chosen_ids = set()

        for type_ in required_types:
            min_cap = min_flask_capacity if type_ == "rb_flask" else None

            if type_ == "rb_flask" and preferred_flask_id is not None:
                item = self.items.get(preferred_flask_id)
                is_valid = (
                    item is not None and item.type == "rb_flask" and not item.in_use
                    and item.id not in chosen_ids
                    and (min_cap is None or (item.capacity is not None and item.capacity >= min_cap))
                )
                candidates = [item] if is_valid else []
            else:
                candidates = [
                    item for item in self.available_items(type_, min_capacity=min_cap)
                    if item.id not in chosen_ids
                ]
                if type_ == "rb_flask" and min_cap is not None:
                    candidates.sort(key=lambda item: item.capacity)

            if not candidates:
                return None  # all-or-nothing: bail without reserving anything

            pick = candidates[0]
            chosen.append(pick)
            chosen_ids.add(pick.id)

        for item in chosen:
            item.in_use = True

        return [item.id for item in chosen]

    def missing_types(self, required_types: list[str],
                       min_flask_capacity: float | None = None) -> list[str]:
        """
        Report which of the required equipment types currently have no
        available (free, and big-enough-if-a-flask) item -- so callers can
        tell the player exactly what they're short of, rather than a plain
        "equipment unavailable". Does not reserve anything.
        """
        missing = []
        tentatively_claimed = set()
        for type_ in required_types:
            min_cap = min_flask_capacity if type_ == "rb_flask" else None
            candidates = [
                item for item in self.available_items(type_, min_capacity=min_cap)
                if item.id not in tentatively_claimed
            ]
            if not candidates:
                missing.append(type_)
            else:
                # Claim one so two required roles of the same type don't
                # both "pass" by pointing at the one physical item.
                tentatively_claimed.add(candidates[0].id)
        return missing

    def release_set(self, item_ids: list[str]) -> None:
        """Free up a set of previously-reserved items (e.g. after a reaction completes)."""
        for item_id in item_ids:
            if item_id in self.items:
                self.items[item_id].in_use = False

    def __repr__(self):
        return f"EquipmentInventory({list(self.items.values())})"


@dataclass
class EquipmentCatalogEntry:
    """One purchasable line item in the equipment catalog: which physical
    `type` it adds to an EquipmentInventory when bought, which bench it
    belongs to, and (for a vessel) its capacity. Several catalog entries
    can share the same `type` (e.g. every RB flask size is still
    type="rb_flask" for reservation purposes) while having their own name/
    capacity/price -- see src/data/equipment.json."""
    name: str
    type: str
    bench: str                      # "reaction" | "purify"
    price: float | None = None      # $, for the computer bench's catalogue
    capacity: float | None = None
    short_name: str | None = None   # what a fixed-width list row shows; None falls back to `name`
    description: str = ""           # the catalogue's description-panel text; "" is
                                     # rendered as a generic placeholder, not blank

    @property
    def display_name(self) -> str:
        return self.short_name or self.name


def load_equipment_catalog(path: str) -> dict[str, EquipmentCatalogEntry]:
    """Load a {name: {type, bench, price, capacity}} JSON file into
    EquipmentCatalogEntry objects -- see src/data/equipment.json."""
    with open(path, "r") as f:
        data = json.load(f)
    return {name: EquipmentCatalogEntry(name=name, **spec) for name, spec in data.items()}


def bench_for_equipment_type(catalog: dict[str, EquipmentCatalogEntry], type_: str) -> str | None:
    """Which bench owns equipment `type_`, per the catalog (None if no
    catalog entry has that type). Multiple catalog entries can share a
    type (e.g. every rb_flask size); the first match wins, on the
    assumption that all of them agree on the bench."""
    for entry in catalog.values():
        if entry.type == type_:
            return entry.bench
    return None


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

def chemical_inventory_from_dict(data: dict, species_catalog: dict[str, ChemicalSpecies]) -> ChemicalInventory:
    """Build a ChemicalInventory from a {chemical_name: amount} mapping,
    where amount is in that chemical's native units (grams for a solid,
    mL for a liquid/solution) per species_catalog."""
    inventory = ChemicalInventory(species_catalog=species_catalog)
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


def consumable_inventory_from_dict(data: dict) -> ConsumableInventory:
    """Build a ConsumableInventory from a {name: amount} mapping."""
    inventory = ConsumableInventory()
    for name, amount in data.items():
        inventory.add(name, amount)
    return inventory


def load_starting_inventories(
    path: str, species_catalog_path: str | None = None,
) -> tuple[ChemicalInventory, EquipmentInventory, ConsumableInventory]:
    """
    Load the player's default starting chemicals, equipment, and
    consumable supplies from a JSON file shaped like:
        {"chemicals": {"48% hydrobromic acid": 700.0, ...},
         "equipment": [{"type": ..., "name": ...}, ...],
         "consumables": {"silica": 50.0}}
    where each chemical amount is in native units (grams/mL) per the
    species catalog, and each consumable amount is in its own native unit
    (also grams/mL, but with no species definition needed). "consumables"
    may be omitted entirely (an empty ConsumableInventory). species_catalog_path
    defaults to "chemicals.json" in the same directory as `path`, since a
    starting loadout and its species catalog are meant to travel together.
    """
    if species_catalog_path is None:
        species_catalog_path = os.path.join(os.path.dirname(path), "chemicals.json")

    with open(path, "r") as f:
        data = json.load(f)
    species_catalog = load_species_catalog(species_catalog_path)
    chemicals = chemical_inventory_from_dict(data.get("chemicals", {}), species_catalog)
    equipment = equipment_inventory_from_dict(data.get("equipment", []))
    consumables = consumable_inventory_from_dict(data.get("consumables", {}))
    return chemicals, equipment, consumables
