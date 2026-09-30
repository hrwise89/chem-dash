"""
Dev tool: open a single bench/notebook screen directly -- loaded from a
saved game state -- without walking across the lab floor or triggering
whatever in-game precondition normally gets you there. Run it, look at
the result on your own screen, edit the bench's code, then re-run the
same command; much faster than "start the game, walk over, get the right
state" for every layout/spacing tweak.

Usage:
    python3 dev/menu_lab.py <target> [--stage STAGE] [--section SECTION] [--save PATH]

<target> is one of: lab, notebook, computer, catalogue, contract_inbox,
shipping, purify, reaction

--stage sets the view's own .stage attribute right after opening it, for
a bench with its own sub-screens (e.g. `reaction --stage start_amount`,
`purify --stage sliders`) -- only meaningful for views that actually have
a .stage attribute; check the bench's own __init__ for its stage names.
A stage reachable only after picking something earlier in its own flow
(e.g. reaction bench's "start_amount" needs a recipe+vessel already
chosen) is auto-filled with a sensible default first, via the view's own
dev_prime(stage) method, if it has one -- see reaction_bench.py's.

--section, for `notebook` only, opens straight to that section instead of
the main grid -- see notebook.py's PANELS for valid keys ("active_
reactions", "orders", "inventory", "known_reactions").

--save defaults to dev/design_save.json, a fixture with populated
inventory/orders/two active reactions (see dev/build_design_save.py) so
screens don't look empty -- pass another save (e.g. the game's own
save.json, or one of your own) to look at a different state instead.

Runs a real, fully-playable arcade window -- all the normal keys work,
including N for the notebook and ESC to back out -- this only skips
however you'd normally have arrived at <target>.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

import arcade  # noqa: E402

from benches.catalogue_bench import CatalogueBenchView  # noqa: E402
from benches.computer_bench import ComputerBenchView  # noqa: E402
from benches.contract_inbox import ContractInboxView  # noqa: E402
from benches.purify_bench import PurifyBenchView  # noqa: E402
from benches.reaction_bench import ReactionBenchView  # noqa: E402
from benches.shipping_bench import ShippingBenchView  # noqa: E402
from benches.ui_theme import ensure_theme_font_loaded  # noqa: E402
from day_manager import DayManager  # noqa: E402
from economy import ContractBoard, Wallet  # noqa: E402
from game_clock import GameClock  # noqa: E402
from inventory import load_consumable_catalog, load_equipment_catalog, load_starting_inventories  # noqa: E402
from lab_view import LabView  # noqa: E402
from message_log import MessageLog  # noqa: E402
from notebook import Notebook  # noqa: E402
from reaction_engine import ReactionEngine  # noqa: E402
from save_game import load_game  # noqa: E402
from settings import SCREEN_HEIGHT, SCREEN_TITLE, SCREEN_WIDTH  # noqa: E402
from skills import PlayerSkills  # noqa: E402
from timer_manager import TimerManager  # noqa: E402

BENCH_VIEWS = {
    "computer": ComputerBenchView,
    "catalogue": CatalogueBenchView,
    "contract_inbox": ContractInboxView,
    "shipping": ShippingBenchView,
    "purify": PurifyBenchView,
    "reaction": ReactionBenchView,
}
TARGETS = ["lab", "notebook", *BENCH_VIEWS.keys()]

DEFAULT_SAVE = os.path.join(os.path.dirname(__file__), "design_save.json")


def build_window() -> arcade.Window:
    """The same window-level setup main.py does, minus load_game (the
    caller does that itself, once it knows which save path to use)."""
    window = arcade.Window(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE)
    ensure_theme_font_loaded()
    window.game_clock = GameClock()
    window.day_manager = DayManager()
    window.message_log = MessageLog()
    window.wallet = Wallet(200.0)
    window.contract_board = ContractBoard()
    window.reaction_engine = ReactionEngine("src/data/reactions.json")
    window.chemical_inventory, window.equipment_inventory, window.consumables = load_starting_inventories(
        "src/data/starting_inventory.json")
    window.equipment_catalog = load_equipment_catalog("src/data/equipment.json")
    window.consumable_catalog = load_consumable_catalog("src/data/consumables.json")
    window.player_skills = PlayerSkills()
    window.timer_manager = TimerManager()
    window.notebook = Notebook()
    return window


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", choices=TARGETS)
    parser.add_argument("--stage", help="set the view's own .stage right after opening it")
    parser.add_argument("--section", help="notebook only -- open straight to this section")
    parser.add_argument("--save", default=DEFAULT_SAVE, help=f"save file to load (default: {DEFAULT_SAVE})")
    args = parser.parse_args()

    window = build_window()
    player_start = load_game(window, path=args.save) if os.path.exists(args.save) else None
    if player_start is None and args.save != DEFAULT_SAVE:
        print(f"Warning: '{args.save}' not found -- using the default starting state instead.")

    lab_view = LabView(window, player_start=player_start)
    window.show_view(lab_view)

    if args.target == "notebook":
        window.notebook.is_open = True
        if args.section:
            window.notebook.section = args.section
    elif args.target != "lab":
        view = BENCH_VIEWS[args.target](window, lab_view)
        if args.stage is not None:
            if hasattr(view, "dev_prime"):
                view.dev_prime(args.stage)
            view.stage = args.stage
        window.show_view(view)

    arcade.run()


if __name__ == "__main__":
    main()
