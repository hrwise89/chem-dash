import warnings

# Harmless on macOS: pyglet checks the installed FFmpeg's version against a
# list of ones it's been tested with, and warns when it doesn't recognize
# a newer release. It doesn't affect playback/behavior, so it's silenced
# here rather than left to print on every launch. Must be registered before
# arcade/pyglet import the media-codecs module below.
warnings.filterwarnings("ignore", category=UserWarning, module=r"pyglet\.media\.codecs.*")

import arcade  # noqa: E402
from settings import (SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE, SPRITE_SCALING, TILE_SIZE,  # noqa: E402
	GRID_WIDTH, GRID_HEIGHT, PLAYER_COLOR, MAP_BACKGROUND_COLOR)
from lab_view import LabView  # noqa: E402
from timer_manager import TimerManager  # noqa: E402
from inventory import load_consumable_catalog, load_equipment_catalog, load_starting_inventories  # noqa: E402
from reaction_engine import ReactionEngine  # noqa: E402
from game_clock import GameClock  # noqa: E402
from day_manager import DayManager  # noqa: E402
from economy import ContractBoard, Wallet, load_contract_offers  # noqa: E402
from devtools import install_crash_logging  # noqa: E402
from message_log import MessageLog  # noqa: E402

STARTING_BALANCE = 200.0


def main():
	install_crash_logging()  # so a crash always leaves a traceback in chem_dash.log, not just the console
	window = arcade.Window(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE)

	# Game clock
	window.game_clock = GameClock()
	window.day_manager = DayManager()
	window.message_log = MessageLog()

	# Money + contracts ("orders")
	window.wallet = Wallet(STARTING_BALANCE)
	window.contract_board = ContractBoard()
	load_contract_offers(window.contract_board, "src/data/contracts.json")

	# Reaction engine
	window.reaction_engine = ReactionEngine("src/data/reactions.json")

	# Chemical + equipment + consumable-supply inventory, loaded from the
	# default starting loadout
	window.chemical_inventory, window.equipment_inventory, window.consumables = load_starting_inventories(
		"src/data/starting_inventory.json"
	)

	# Catalogs: what's purchasable (equipment/consumables) and which bench
	# each belongs to -- used by the computer bench's catalogue and by
	# benches that auto-list their own equipment/supplies.
	window.equipment_catalog = load_equipment_catalog("src/data/equipment.json")
	window.consumable_catalog = load_consumable_catalog("src/data/consumables.json")

	window.timer_manager = TimerManager()  # attach it to the window

	# Create labview
	lab_view = LabView(window)

	window.show_view(lab_view)
	arcade.run()

if __name__ == "__main__":
	main()