import arcade
from settings import (SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE, SPRITE_SCALING, TILE_SIZE,
	GRID_WIDTH, GRID_HEIGHT, PLAYER_COLOR, MAP_BACKGROUND_COLOR)
from lab_view import LabView
from timer_manager import TimerManager, Timer
from inventory import load_starting_inventories
from reaction_engine import ReactionEngine
from game_clock import GameClock


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