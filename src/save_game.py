"""
Saving/loading a game in progress: wallet, day/clock, chemical/equipment/
consumable inventories, the contract board, in-progress+completed
reactions, player skills, and the player's position on the lab floor.

Kept arcade-free (like reaction_engine.py/inventory.py/day_manager.py) so
it stays headless-testable -- it never touches Player or arcade.Window
directly, only the plain data objects window already carries as
attributes, plus a bare (row, col) for player position that LabView
applies to its own Player sprite (the same way _start_new_day() already
repositions it).

This intentionally overwrites state on the objects window already has
(window.chemical_inventory.contents = ..., not a freshly-built
ChemicalInventory) rather than reconstructing them from scratch, so
species_catalog/equipment_catalog references set up once at startup stay
intact -- a save file only ever needs to carry what changes over play, not
the static catalogs.
"""

import itertools
import json
import os
from dataclasses import asdict

from devtools import logger
from economy import Contract, ContractBoard
from inventory import EquipmentInventory, EquipmentItem
from reaction_engine import ReactionEngine, ReactionLogEntry, ReactionProcess

SAVE_FORMAT_VERSION = 1
DEFAULT_SAVE_PATH = "save.json"


def _max_numeric_suffix(ids) -> int:
    """Highest trailing "_N" suffix across `ids` (0 if there are none) --
    used to resume an id counter past whatever a save file's ids already
    used, so a freshly bought/started item can never collide with one
    that was restored."""
    highest = 0
    for item_id in ids:
        _, _, suffix = item_id.rpartition("_")
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return highest


def _equipment_inventory_to_dict(equipment: EquipmentInventory) -> dict:
    return {"items": [asdict(item) for item in equipment.items.values()]}


def _restore_equipment_inventory(equipment: EquipmentInventory, data: dict) -> None:
    equipment.items = {}
    for item_data in data["items"]:
        item = EquipmentItem(**item_data)
        equipment.items[item.id] = item
    equipment._id_counter = itertools.count(_max_numeric_suffix(equipment.items.keys()) + 1)


def _contract_board_to_dict(board: ContractBoard) -> dict:
    return {
        "available": [asdict(c) for c in board.available],
        "accepted": [asdict(c) for c in board.accepted],
        "in_transit": [asdict(c) for c in board.in_transit],
        "history": [asdict(c) for c in board.history],
    }


def _restore_contract_board(board: ContractBoard, data: dict) -> None:
    board.available = [Contract(**c) for c in data["available"]]
    board.accepted = [Contract(**c) for c in data["accepted"]]
    board.in_transit = [Contract(**c) for c in data["in_transit"]]
    board.history = [Contract(**c) for c in data["history"]]
    all_ids = (c.contract_id for pool in
               (board.available, board.accepted, board.in_transit, board.history) for c in pool)
    board._id_counter = itertools.count(_max_numeric_suffix(all_ids) + 1)


def _reaction_engine_to_dict(engine: ReactionEngine) -> dict:
    return {
        "active_processes": [
            {**asdict(p), "definition": None} for p in engine.active_processes.values()
        ],
        "history": [asdict(entry) for entry in engine.history],
    }


def _restore_reaction_engine(engine: ReactionEngine, data: dict) -> None:
    """Rebuilds active_processes/history from a save. A process's
    `definition` isn't stored (a ReactionDefinition isn't plain data) --
    it's looked back up from engine.reaction_db by reaction_name, which is
    already loaded from the same static reactions.json both at save time
    and here."""
    engine.active_processes = {}
    for process_data in data["active_processes"]:
        process_data = dict(process_data)
        reaction_name = process_data["reaction_name"]
        process_data["definition"] = engine.reaction_db[reaction_name]
        engine.active_processes[process_data["process_id"]] = ReactionProcess(**process_data)
    engine.history = [ReactionLogEntry(**entry) for entry in data["history"]]
    engine._process_id_counter = itertools.count(
        _max_numeric_suffix(engine.active_processes.keys()) + 1
    )


def build_save_data(window, player_row: int, player_col: int) -> dict:
    """A plain-dict snapshot of everything a save needs to restore, from
    window's existing sub-objects plus the player's current tile."""
    return {
        "version": SAVE_FORMAT_VERSION,
        "wallet": {"balance": window.wallet.balance},
        "day_manager": {
            "current_day": window.day_manager.current_day,
            "day_start_time": window.day_manager.day_start_time,
        },
        "game_clock": {"current_time": window.game_clock.current_time},
        "player_skills": {"levels": dict(window.player_skills.levels)},
        "player": {"row": player_row, "col": player_col},
        "chemical_inventory": {"contents": dict(window.chemical_inventory.contents)},
        "consumables": {"contents": dict(window.consumables.contents)},
        "equipment_inventory": _equipment_inventory_to_dict(window.equipment_inventory),
        "contract_board": _contract_board_to_dict(window.contract_board),
        "reaction_engine": _reaction_engine_to_dict(window.reaction_engine),
    }


def apply_save_data(window, data: dict) -> tuple[int, int]:
    """Restores everything in `data` onto window's existing sub-objects
    (in place). Returns (row, col) for the caller to reposition its own
    Player sprite with -- see the module docstring for why that's not
    done here."""
    window.wallet.balance = data["wallet"]["balance"]
    window.day_manager.current_day = data["day_manager"]["current_day"]
    window.day_manager.day_start_time = data["day_manager"]["day_start_time"]
    window.game_clock.current_time = data["game_clock"]["current_time"]
    window.player_skills.levels = dict(data["player_skills"]["levels"])
    window.chemical_inventory.contents = dict(data["chemical_inventory"]["contents"])
    window.consumables.contents = dict(data["consumables"]["contents"])
    _restore_equipment_inventory(window.equipment_inventory, data["equipment_inventory"])
    _restore_contract_board(window.contract_board, data["contract_board"])
    _restore_reaction_engine(window.reaction_engine, data["reaction_engine"])
    return data["player"]["row"], data["player"]["col"]


def save_game(window, player_row: int, player_col: int, path: str = DEFAULT_SAVE_PATH) -> None:
    data = build_save_data(window, player_row, player_col)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("Saved game to '%s' (day %d)", path, window.day_manager.current_day)


def load_game(window, path: str = DEFAULT_SAVE_PATH) -> tuple[int, int] | None:
    """Restores a save from `path` onto window's existing sub-objects, if
    it exists. Returns the (row, col) to reposition the player at, or None
    if there's no save file to load (a fresh game should just keep its
    starting state)."""
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        data = json.load(f)
    position = apply_save_data(window, data)
    logger.info("Loaded game from '%s' (day %d)", path, window.day_manager.current_day)
    return position
