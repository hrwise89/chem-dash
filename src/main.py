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
from timer_manager import TimerManager, Timer  # noqa: E402
from inventory import load_starting_inventories  # noqa: E402
from reaction_engine import ReactionEngine  # noqa: E402
from game_clock import GameClock  # noqa: E402


def main():
	window = arcade.Window(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE)

	# Game clock
	window.game_clock = GameClock()

	# Reaction engine
	window.reaction_engine = ReactionEngine("src/data/reactions.json")

	# Chemical + equipment inventory, loaded from the default starting loadout
	window.chemical_inventory, window.equipment_inventory = load_starting_inventories(
		"src/data/starting_inventory.json"
	)

	window.timer_manager = TimerManager()  # attach it to the window
	window.timer_manager.add_timer("col1", Timer(30))
	window.timer_manager.add_timer("col2", Timer(30))
	window.timer_manager.add_timer("col3", Timer(30))

	# Create labview
	lab_view = LabView(window)

	window.show_view(lab_view)
	arcade.run()

if __name__ == "__main__":
	main()