"""
Generates dev/design_save.json: a save file with populated state (varied
inventory, one contract in each of Available/Accepted/Rejected/In-transit,
two active reactions -- one ready, one not) so every menu/bench screen has
something real to show instead of a mostly-empty fresh game. Built through
the same game systems a real playthrough would use (ContractBoard.offer/
accept/reject, ReactionEngine.start_reaction, ...), then saved with
save_game() -- not hand-written JSON -- so it can't drift from whatever
the save format actually needs.

Re-run this whenever the save format changes (save_game.py) or you want
richer/different sample data for design work:

    python3 dev/build_design_save.py

See dev/menu_lab.py for what actually loads this file.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from day_manager import DayManager
from economy import ContractBoard, Wallet
from game_clock import GameClock
from inventory import load_consumable_catalog, load_equipment_catalog, load_starting_inventories
from message_log import MessageLog
from reaction_engine import ReactionEngine
from save_game import save_game
from skills import PlayerSkills

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "design_save.json")


class _Window:
    """A bare stand-in for arcade.Window -- save_game only reads the
    plain-data attributes below, never anything arcade-specific."""


def build():
    window = _Window()
    window.game_clock = GameClock()
    window.day_manager = DayManager()
    window.message_log = MessageLog()
    window.wallet = Wallet(500.0)
    window.contract_board = ContractBoard()
    window.reaction_engine = ReactionEngine("src/data/reactions.json")
    window.chemical_inventory, window.equipment_inventory, window.consumables = load_starting_inventories(
        "src/data/starting_inventory.json")
    window.equipment_catalog = load_equipment_catalog("src/data/equipment.json")
    window.consumable_catalog = load_consumable_catalog("src/data/consumables.json")
    window.player_skills = PlayerSkills()

    inv = window.chemical_inventory
    inv.add("48% hydrobromic acid", 1500.0)
    inv.add("ethanol", 800.0)
    inv.add("methanol", 600.0)
    inv.add("sodium cyanide", 300.0)
    inv.add("ethyl bromide (crude)", 40.0)
    inv.add("ethyl bromide", 30.0)

    now = window.game_clock.now()
    day_start = window.day_manager.day_start_time
    day = window.day_manager.current_day
    board = window.contract_board

    available = board.offer(
        "Need ethyl bromide", "Polymer Lab",
        "Our group is starting a new alkylation series this week and we're short on ethyl bromide. "
        "Could you supply 0.5 mol? Crude is fine -- we're distilling it ourselves before use. "
        "Payment on delivery, as usual.",
        "ethyl bromide", "EtBr", 0.5, 40.0, now, day_start, day, days_to_complete=5,
    )

    accepted = board.offer(
        "Methyl bromide batch", "Acme Labs", "Standard order, ship whenever ready.",
        "methyl bromide", "MeBr", 0.3, 25.0, now, day_start, day, days_to_complete=2,
    )
    board.accept(accepted.contract_id, day_start)

    in_transit = board.offer(
        "Pure ethyl bromide", "Northgate Analytics",
        "We need this batch pure, not crude -- it's going straight into a sensitive assay.",
        "ethyl bromide", "EtBr", 0.2, 60.0, now, day_start, day,
        requires_purity=True, days_to_complete=2,
    )
    board.accept(in_transit.contract_id, day_start)
    board.ship(in_transit.contract_id, window.chemical_inventory)

    rejected = board.offer(
        "Rush acetonitrile", "Quickchem", "Need this today if at all possible, sorry for the short notice!",
        "acetonitrile", "MeCN", 0.4, 30.0, now, day_start, day, days_to_complete=0,
    )
    board.reject(rejected.contract_id, now, day)

    window.reaction_engine.start_reaction(
        inv, window.equipment_inventory, {"HBr": 1.0, "ethanol": 1.0}, "neat", 20, 4, window.game_clock,
    )
    window.reaction_engine.start_reaction(
        inv, window.equipment_inventory, {"HBr": 1.0, "methanol": 1.0}, "neat", 20, 3, window.game_clock,
    )
    window.game_clock.advance(3.5)  # the methyl-bromide-bound one (3h) is now ready; the other isn't yet

    save_game(window, player_row=5, player_col=5, path=OUTPUT_PATH)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    build()
