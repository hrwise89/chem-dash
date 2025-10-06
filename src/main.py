import arcade
from settings import (SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE, SPRITE_SCALING, TILE_SIZE, 
	GRID_WIDTH, GRID_HEIGHT, PLAYER_COLOR, MAP_BACKGROUND_COLOR)
from lab_view import LabView
from timer_manager import TimerManager, Timer


def main():
	window = arcade.Window(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE)

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