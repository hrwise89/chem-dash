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
from benches.ui_theme import ensure_theme_font_loaded  # noqa: E402
from lab_view import LabView  # noqa: E402
from timer_manager import TimerManager  # noqa: E402
from inventory import load_consumable_catalog, load_equipment_catalog, load_starting_inventories  # noqa: E402
from reaction_engine import ReactionEngine  # noqa: E402
from game_clock import GameClock  # noqa: E402
from day_manager import DayManager  # noqa: E402
from economy import ContractBoard, Wallet, load_contract_offers  # noqa: E402
from devtools import install_crash_logging  # noqa: E402
from message_log import MessageLog  # noqa: E402
from notebook import Notebook  # noqa: E402
from save_game import load_game  # noqa: E402
from skills import PlayerSkills  # noqa: E402

STARTING_BALANCE = 200.0


def main():
	install_crash_logging()  # so a crash always leaves a traceback in chem_dash.log, not just the console
	window = arcade.Window(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE)
	ensure_theme_font_loaded()  # see benches/ui_theme.py -- a no-op until the real .ttf is added

	# Game clock
	window.game_clock = GameClock()
	window.day_manager = DayManager()
	window.message_log = MessageLog()

	# Money + contracts ("orders")
	window.wallet = Wallet(STARTING_BALANCE)
	window.contract_board = ContractBoard()
	load_contract_offers(window.contract_board, "src/data/contracts.json", window.game_clock.now(),
		window.day_manager.day_start_time, window.day_manager.current_day)

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

	# Player skills/specialities (see skills.py) -- no way to raise a level
	# yet, so this starts everyone at level 0 in everything (a no-op).
	window.player_skills = PlayerSkills()

	window.timer_manager = TimerManager()  # attach it to the window

	# The notebook overlay (N key) -- see notebook.py.
	window.notebook = Notebook()

	# Resume a save from the last day boundary, if one exists (see
	# lab_view.py's autosave in _start_new_day) -- overwrites the fresh
	# state above in place and hands back where the player was standing.
	player_start = load_game(window)

	# Create labview
	lab_view = LabView(window, player_start=player_start)

	window.show_view(lab_view)
	arcade.run()

if __name__ == "__main__":
	main()