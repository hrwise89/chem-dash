import arcade

# Window Settings
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
SCREEN_TITLE = "Chem Dash (Working Title), Starter"
SPRITE_SCALING = 4

# Tile / Grid Settings
TILE_SIZE = 32
GRID_WIDTH = SCREEN_WIDTH // TILE_SIZE
GRID_HEIGHT = SCREEN_HEIGHT // TILE_SIZE

# Player Settings
PLAYER_COLOR = arcade.color.BLUE

# Level Settings
MAP_BACKGROUND_COLOR = arcade.color.LIGHT_BLUE

# Time Settings
# How many in-game hours pass per real second while walking around the lab
# floor (LabView). At 0.05, a 4-hour reaction finishes after ~80 real
# seconds of walking. Purely a pacing knob -- tune freely.
GAME_HOURS_PER_REAL_SECOND = 0.05