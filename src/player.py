"""The player's sprite: tile-by-tile grid movement with an eased visual
slide between tiles, and collision-checked against whatever sprite lists
(walls, benches) LabView passes to move()."""

import arcade

from room_geometry import room_x, room_y
from settings import GRID_HEIGHT, GRID_WIDTH, PLAYER_COLOR, TILE_SIZE


class Player(arcade.Sprite):
    def __init__(self, row: int, col: int, color: tuple[int, int, int] = PLAYER_COLOR):
        super().__init__()
        self.texture = arcade.make_soft_square_texture(TILE_SIZE - 2, color, outer_alpha=255)
        self.row = row
        self.col = col
        self.target_x = room_x(self.col)
        self.target_y = room_y(self.row)
        self.center_x = self.target_x
        self.center_y = self.target_y
        self.moving = False
        self.near_bench = False

    def move(self, d_row: int, d_col: int, collidables: list) -> None:
        new_row = max(0, min(self.row + d_row, GRID_HEIGHT - 1))
        new_col = max(0, min(self.col + d_col, GRID_WIDTH - 1))

        # Compute target position
        target_x = room_x(new_col)
        target_y = room_y(new_row)

        # Test new position
        old_x, old_y = self.center_x, self.center_y
        self.center_x, self.center_y = target_x, target_y
        # Test for collisions from list of collidables
        for colideable in collidables:
            if arcade.check_for_collision_with_list(self, colideable):
                # reset position and return before moving
                self.center_x, self.center_y = old_x, old_y
                return

        # Otherwise, move
        if new_row != self.row or new_col != self.col:
            self.row = new_row
            self.col = new_col
            # Start sliding toward new target
            self.start_x = self.center_x
            self.start_y = self.center_y
            self.target_x = room_x(self.col)
            self.target_y = room_y(self.row)
            self.moving = True
            self.move_progress = 0.0

    def update_position(self, delta_time: float, slide_speed: float) -> None:
        if self.moving:
            self.move_progress += delta_time / slide_speed

            if self.move_progress >= 1.0:
                # Snap to target
                self.center_x = self.target_x
                self.center_y = self.target_y
                self.moving = False
                self.move_progress = 0.0
            else:
                t = self.move_progress
                eased_t = t * t * (3 - 2 * t)

                self.center_x = self.start_x + (self.target_x - self.start_x) * eased_t
                self.center_y = self.start_y + (self.target_y - self.start_y) * eased_t
