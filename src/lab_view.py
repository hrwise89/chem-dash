import arcade
import math
from settings import (SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE, SPRITE_SCALING, TILE_SIZE, 
	GRID_WIDTH, GRID_HEIGHT, PLAYER_COLOR, MAP_BACKGROUND_COLOR)
from mini_games.column import ColumnMiniGameView
from timer_manager import TimerManager, Timer

class Player(arcade.Sprite):
	def __init__(self, row: int, col: int, color: tuple[int,int,int] = PLAYER_COLOR):
		super().__init__()
		self.texture = arcade.make_soft_square_texture(TILE_SIZE - 2, color, 
			outer_alpha=255)
		self.row = row
		self.col = col
		self.target_x = self.col * TILE_SIZE + TILE_SIZE // 2
		self.target_y = self.row * TILE_SIZE + TILE_SIZE // 2
		self.center_x = self.target_x
		self.center_y = self.target_y
		self.moving = False

	def move(self, d_row: int, d_col: int, collidables: list) -> None:
		new_row = max(0, min(self.row + d_row, GRID_HEIGHT - 1))
		new_col = max(0, min(self.col + d_col, GRID_WIDTH - 1))

		# Compute target position
		target_x = new_col * TILE_SIZE + TILE_SIZE // 2
		target_y = new_row * TILE_SIZE + TILE_SIZE // 2

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
			self.target_x = self.col * TILE_SIZE + TILE_SIZE // 2
			self.target_y = self.row * TILE_SIZE + TILE_SIZE // 2
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
				# eased_t = (1 - math.cos(t * math.pi)) / 2
				eased_t = t * t * (3 - 2 * t) 

				self.center_x = self.start_x + (self.target_x - self.start_x) * eased_t
				self.center_y = self.start_y + (self.target_y - self.start_y) * eased_t


class LabView(arcade.View):
	def __init__(self, window):
		# View level attributes
		super().__init__()
		self.window = window
		self.timer_manager = window.timer_manager
		arcade.set_background_color(MAP_BACKGROUND_COLOR)
		# Movement
		self.keys_held = set()
		self.move_speed = 0.3
		self.slide_speed = self.move_speed * 0.9
		self.time_since_move = 0.0

		# Player
		self.player = Player(GRID_HEIGHT // 2, GRID_WIDTH // 2)
		self.all_sprites = arcade.SpriteList()
		self.all_sprites.append(self.player)
		
		# Text
		self.instruction_text = arcade.Text("Use arrow keys to move player tile by tile", 
			10, SCREEN_HEIGHT - 20, arcade.color.BLACK, font_size=14)

		# Walls
		self.walls = arcade.SpriteList()
		walls_packed = [
			[TILE_SIZE * 22, TILE_SIZE // 2, TILE_SIZE * 12.5,
				TILE_SIZE * 17 + TILE_SIZE // 4, arcade.color.BLACK],
			[TILE_SIZE * 22, TILE_SIZE // 2, TILE_SIZE * 12.5,
				TILE_SIZE * 0.75, arcade.color.BLACK],
			[TILE_SIZE // 2, TILE_SIZE * 16.5, TILE_SIZE * 1.75,
				TILE_SIZE * 9.25, arcade.color.BLACK],
			[TILE_SIZE // 2, TILE_SIZE * 16.5, TILE_SIZE * 24 - 3 * TILE_SIZE // 4,
				TILE_SIZE * 9.25, arcade.color.BLACK]]
		for wall_pack in walls_packed:
			wall = arcade.SpriteSolidColor(*wall_pack)
			self.walls.append(wall)

		# Benches
		bench_specs = [
			{"name": "bench_col_1", "x": TILE_SIZE * 12.5, "y": TILE_SIZE * 16.5,
				"width": TILE_SIZE * 3, "height": TILE_SIZE, 
				"color": arcade.color.BROWN, "mini_game": "view your columns"},
			{"name": "bench_hood_1", "x": TILE_SIZE * 6.5, "y": TILE_SIZE * 16.5,
				"width": TILE_SIZE * 3, "height": TILE_SIZE, 
				"color": arcade.color.DARK_GRAY, "mini_game": "view your hood"}	
			# Additional benches here
		]

		self.bench_specs = bench_specs
		self.benches = {} # name -> sprite
		self.bench_list = arcade.SpriteList()

		for spec in self.bench_specs:
			bench = arcade.SpriteSolidColor(spec["width"], spec["height"],
				spec["x"], spec["y"], spec["color"])
			self.benches[spec["name"]] = bench
			self.bench_list.append(bench)


	def on_draw(self):
		self.clear()
		# Draw grid
		for row in range(GRID_HEIGHT):
			for col in range(GRID_WIDTH):
				arcade.draw_lrbt_rectangle_outline(col * TILE_SIZE, 
					(col + 1) * TILE_SIZE, row * TILE_SIZE, 
					(row + 1) * TILE_SIZE, arcade.color.DARK_GRAY, 
					border_width=1)
		# Draw all sprites via sprite list, text, walls
		self.all_sprites.draw()
		self.instruction_text.draw()
		self.walls.draw()
		# Draw all benches
		self.bench_list.draw()


		# Draw bench text
		if self.near_bench:
			bench = self.benches[self.near_bench["name"]]
			self.prompt_text = arcade.Text(f"Press SPACE to {self.near_bench["mini_game"]}",
				bench.center_x, bench.center_y + 40, arcade.color.BLACK,
				font_size=14, anchor_x="center")
			self.prompt_text.draw()
		else:
			self.prompt_text = None


	def on_update(self, delta_time):
		self.time_since_move += delta_time

		# Handle keyboard input
		d_row, d_col = 0, 0
		if arcade.key.UP in self.keys_held or arcade.key.W in self.keys_held:
			d_row += 1
		if arcade.key.DOWN in self.keys_held or arcade.key.S in self.keys_held:
			d_row -= 1
		if arcade.key.RIGHT in self.keys_held or arcade.key.D in self.keys_held:
			d_col += 1
		if arcade.key.LEFT in self.keys_held or arcade.key.A in self.keys_held:
			d_col -= 1

		if d_row != 0 or d_col != 0:
			if self.time_since_move >= self.move_speed and not self.player.moving:
				self.player.move(d_row, d_col, [self.walls, self.bench_list])
				self.time_since_move = 0.0

		# Always update player position smoothly
		self.player.update_position(delta_time, self.slide_speed)

		# Bench proximity
		self.near_bench = None
		for spec in self.bench_specs:
			bench = self.benches[spec["name"]]
			bench_row = int(bench.center_y // TILE_SIZE)
			bench_col = int(bench.center_x // TILE_SIZE)

			if abs(self.player.row - bench_row) + abs(self.player.col - bench_col) == 1:
				self.near_bench = spec
				break

	def on_key_press(self, key, modifiers):
		self.keys_held.add(key)
		
		if key == arcade.key.ESCAPE:
			arcade.close_window()

		# Interaction with benches
		if key == arcade.key.SPACE and self.near_bench:
			self.window.show_view(ColumnMiniGameView(self.window, self))

	def on_key_release(self, key, modifiers):
		self.keys_held.discard(key)
