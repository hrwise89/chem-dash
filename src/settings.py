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
# floor (LabView). Most time progression is meant to come from actions
# (running a reaction, purifying, warping to collect) rather than from
# walking itself, so this is deliberately slow -- at 0.005, walking around
# for a full real minute only costs 0.3 in-game hours (18 minutes).
# Time-consuming actions advance the clock directly (see purification.py,
# reaction_engine.py) and are unaffected by this constant. Purely a pacing
# knob -- tune freely.
GAME_HOURS_PER_REAL_SECOND = 0.005

# Developer / debug logging (DEV_MODE, LOG_FILE_PATH) lives in devtools.py,
# not here -- this file imports arcade at the top (for color constants
# below), and devtools.py is imported from reaction_engine.py/inventory.py,
# which are deliberately arcade-free so their tests can run headless
# (no display needed). Importing settings.py from devtools.py would drag
# arcade into that chain and break that. See devtools.py to change them.