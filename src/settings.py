import arcade

# Window Settings
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
SCREEN_TITLE = "Chem Dash (Working Title), Starter"
SPRITE_SCALING = 4

# Tile / Grid Settings
TILE_SIZE = 32

# The lab room (LabView's walkable interior) is deliberately smaller than
# the window and recentered in it, with a status bar reserved above it and
# a scrolling message box reserved below it -- see ROOM_ORIGIN_X/Y.
ROOM_COLS = 20
ROOM_ROWS = 10
ROOM_WIDTH = ROOM_COLS * TILE_SIZE
ROOM_HEIGHT = ROOM_ROWS * TILE_SIZE

# GRID_WIDTH/GRID_HEIGHT are what LabView bounds player movement against --
# kept as separate names (rather than using ROOM_COLS/ROOM_ROWS directly)
# in case some future room isn't the same size as the "current" one.
GRID_WIDTH = ROOM_COLS
GRID_HEIGHT = ROOM_ROWS

# Status bar (time/date/money, top of window) and message box (scrolling
# status/prompt text, bottom of window) reserve fixed-height strips; the
# room is centered in whatever vertical space is left between them, and
# centered horizontally in the full window width.
STATUS_BAR_HEIGHT = 40
MESSAGE_BOX_HEIGHT = 110

ROOM_ORIGIN_X = (SCREEN_WIDTH - ROOM_WIDTH) // 2
ROOM_ORIGIN_Y = MESSAGE_BOX_HEIGHT + (SCREEN_HEIGHT - STATUS_BAR_HEIGHT - MESSAGE_BOX_HEIGHT - ROOM_HEIGHT) // 2

# Player Settings
PLAYER_COLOR = arcade.color.BLUE

# Level Settings
MAP_BACKGROUND_COLOR = arcade.color.LIGHT_BLUE
OUTSIDE_ROOM_COLOR = arcade.color.BLACK

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