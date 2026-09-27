"""
Coordinate conversion and layout constants for the lab room -- kept
separate from LabView so Player/DoorMenu (and anything else that needs to
place something in the room) don't have to import the view itself.
"""

import arcade

from settings import ROOM_COLS, ROOM_ORIGIN_X, ROOM_ORIGIN_Y, ROOM_ROWS, TILE_SIZE

# Player spawn point (row/col in the room's local grid, 0 at bottom-left),
# picked to sit clear of every bench and the door.
DEFAULT_X, DEFAULT_Y = 2, 10

# The door lives IN the left wall (a "chunk of the wall", not a freestanding
# tile) at the row 2 tiles down from the top of the room -- i.e. the 2nd
# tile from the top, 0-indexed from the top being row ROOM_ROWS - 1.
DOOR_ROW = ROOM_ROWS - 2
DOOR_COL = -1  # just outside the interior's leftmost column, inside the wall

# Top-row benches (reaction, purify) sit flush against the top wall, on the
# topmost interior row -- an integer row, so a 1-tile-deep bench lines up
# with the tile grid exactly instead of straddling two rows. The paired
# bench below each (shipping under reaction, computer under purify) sits
# exactly 2 tiles south, leaving one full clear tile between the rows for
# the player to walk through.
BENCH_TOP_ROW = ROOM_ROWS - 1
BENCH_BOTTOM_ROW = BENCH_TOP_ROW - 2
# Bench columns are half-tile-centered on purpose: a 3-tile-wide bench
# centered on an N.5 column lines its edges up exactly with tile
# boundaries (tiles N-1, N, N+1), the same way BENCH_TOP_ROW does for a
# 1-tile-deep bench on a whole row.
REACTION_COL = 5
PURIFY_COL = 13

# The door's own activation tile is the same color as the wall (it IS a
# chunk of the wall), so it'd otherwise be invisible -- this thin strip
# just outside it marks where it actually is.
DOOR_MARKER_WIDTH = TILE_SIZE / 4
DOOR_MARKER_COLOR = arcade.color.SADDLE_BROWN


def room_x(local_col: float) -> float:
    """Local room column (0 at the interior's left edge) -> screen x."""
    return ROOM_ORIGIN_X + local_col * TILE_SIZE + TILE_SIZE / 2


def room_y(local_row: float) -> float:
    """Local room row (0 at the interior's bottom edge) -> screen y."""
    return ROOM_ORIGIN_Y + local_row * TILE_SIZE + TILE_SIZE / 2


def wall_tile(local_row: int, local_col: int) -> arcade.SpriteSolidColor:
    return arcade.SpriteSolidColor(TILE_SIZE, TILE_SIZE, room_x(local_col), room_y(local_row),
        arcade.color.BLACK)


def wall_sprites() -> arcade.SpriteList:
    """A 1-tile-thick perimeter around the room's interior, with a gap at
    the door's row in the left wall (the door itself fills it)."""
    walls = arcade.SpriteList()
    for local_col in range(-1, ROOM_COLS + 1):
        walls.append(wall_tile(ROOM_ROWS, local_col))       # top
        walls.append(wall_tile(-1, local_col))              # bottom
    for local_row in range(ROOM_ROWS):
        if local_row != DOOR_ROW:
            walls.append(wall_tile(local_row, -1))          # left (minus door gap)
        walls.append(wall_tile(local_row, ROOM_COLS))       # right
    return walls


def draw_door_marker():
    door_left = room_x(DOOR_COL) - TILE_SIZE / 2
    door_bottom = room_y(DOOR_ROW) - TILE_SIZE / 2
    door_top = door_bottom + TILE_SIZE
    arcade.draw_lrbt_rectangle_filled(door_left - DOOR_MARKER_WIDTH, door_left, door_bottom, door_top,
        DOOR_MARKER_COLOR)
