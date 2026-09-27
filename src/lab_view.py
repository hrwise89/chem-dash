import arcade
import math
from settings import (SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE, SPRITE_SCALING, TILE_SIZE,
	GRID_WIDTH, GRID_HEIGHT, PLAYER_COLOR, MAP_BACKGROUND_COLOR, GAME_HOURS_PER_REAL_SECOND)
from benches.computer_bench import ComputerBenchView
from benches.purify_bench import PurifyBenchView
from benches.reaction_bench import ReactionBenchView
from benches.shipping_bench import ShippingBenchView
from timer_manager import TimerManager, Timer
from devtools import logger

DEFAULT_X, DEFAULT_Y = GRID_HEIGHT * 3.5 // 4, GRID_WIDTH * 1 // 4

# Where the door (go home for the day) sits: a few tiles below the
# purify bench, close to the rest of the top-row benches rather than
# clear across the room.
DOOR_ROW, DOOR_COL = 13, 12

STATUS_MESSAGE_DURATION = 4.0

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
		self.near_bench = False

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
		self.day_manager = window.day_manager
		arcade.set_background_color(MAP_BACKGROUND_COLOR)
		# Movement
		self.keys_held = set()
		self.move_speed = 0.3 / 1.15  # ~15% faster tile-to-tile movement than before
		self.slide_speed = self.move_speed * 0.9
		self.time_since_move = 0.0

		# Player
		self.player = Player(DEFAULT_X, DEFAULT_Y)
		self.all_sprites = arcade.SpriteList()
		self.all_sprites.append(self.player)
		
		# Text
		self.instruction_text = arcade.Text("Use arrow keys to move player tile by tile",
			10, SCREEN_HEIGHT - 20, arcade.color.BLACK, font_size=14)
		# Reused across frames (rather than rebuilt each on_draw) for the
		# "Press SPACE to ..." bench prompt -- see on_draw/on_update.
		self.prompt_text = arcade.Text("", 0, 0, arcade.color.BLACK,
			font_size=14, anchor_x="center")
		# Day/time-of-day readout, top-right.
		self.day_text = arcade.Text("", SCREEN_WIDTH - 10, SCREEN_HEIGHT - 20,
			arcade.color.BLACK, font_size=14, anchor_x="right")
		# Transient status line (sleepy warning, "you passed out", etc), same
		# pattern as BenchView.show_message/draw_message.
		self.status_text = arcade.Text("", SCREEN_WIDTH // 2, SCREEN_HEIGHT - 20,
			arcade.color.DARK_RED, font_size=14, anchor_x="center")
		self.status_message = ""
		self.status_message_timer = 0.0

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
				"color": arcade.color.BROWN, "action": "purify your products",
				"opens": PurifyBenchView},
			{"name": "bench_hood_1", "x": TILE_SIZE * 6.5, "y": TILE_SIZE * 16.5,
				"width": TILE_SIZE * 3, "height": TILE_SIZE,
				"color": arcade.color.DARK_GRAY, "action": "view your hood",
				"opens": ReactionBenchView},
			{"name": "bench_computer_1", "x": TILE_SIZE * 19.5, "y": TILE_SIZE * 16.5,
				"width": TILE_SIZE * 3, "height": TILE_SIZE,
				"color": arcade.color.DARK_SLATE_BLUE, "action": "use the computer",
				"opens": ComputerBenchView},
			{"name": "bench_shipping_1", "x": TILE_SIZE * 19.5, "y": TILE_SIZE * 13.5,
				"width": TILE_SIZE * 3, "height": TILE_SIZE,
				"color": arcade.color.DARK_ORANGE, "action": "use the shipping desk",
				"opens": ShippingBenchView},
			# Additional benches here
			{"name": "door_home", "x": DOOR_COL * TILE_SIZE + TILE_SIZE // 2,
				"y": DOOR_ROW * TILE_SIZE + TILE_SIZE // 2,
				"width": TILE_SIZE, "height": TILE_SIZE,
				"color": arcade.color.SADDLE_BROWN, "action": "go home for the day",
				"is_door": True},
		]
		self.near_bench = None
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


		# Draw bench text (Text object is created once in __init__ and just
		# repositioned/retexted here, rather than rebuilt every frame)
		if self.near_bench:
			bench = self.benches[self.near_bench["name"]]
			self.prompt_text.text = f"Press SPACE to {self.near_bench['action']}"
			self.prompt_text.x = bench.center_x
			self.prompt_text.y = bench.center_y + 40
			self.prompt_text.draw()

		hours = self.day_manager.hours_into_day(self.window.game_clock)
		self.day_text.text = f"Day {self.day_manager.current_day} -- {hours:.1f}h"
		self.day_text.draw()

		if self.status_message:
			self.status_text.text = self.status_message
			self.status_text.draw()
		elif self.day_manager.is_sleepy(self.window.game_clock):
			self.status_text.text = "Getting sleepy... head home soon"
			self.status_text.draw()


	def on_update(self, delta_time):
		self.time_since_move += delta_time

		if self.status_message_timer > 0:
			self.status_message_timer -= delta_time
			if self.status_message_timer <= 0:
				self.status_message = ""

		# In-game time passes while the player is out on the lab floor. It
		# does NOT tick inside mini-games/the reaction bench (those views
		# don't call this), matching "time passes while walking around."
		self.window.game_clock.advance(delta_time * GAME_HOURS_PER_REAL_SECOND)

		if self.day_manager.has_passed_out(self.window.game_clock):
			self.pass_out()

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
			if self.near_bench.get("is_door"):
				self.go_home()
			else:
				view_class = self.near_bench["opens"]
				logger.info("Opening %s from bench '%s'", view_class.__name__, self.near_bench["name"])
				self.window.show_view(view_class(self.window, self))

	def on_key_release(self, key, modifiers):
		self.keys_held.discard(key)

	# ---- day/night: going home through the door, or passing out ----

	def go_home(self):
		new_day = self.day_manager.go_home(self.window.game_clock)
		logger.info("Player went home; day %d begins", new_day)
		self._start_new_day(f"Day {new_day} begins.")

	def pass_out(self):
		new_day = self.day_manager.pass_out(self.window.game_clock)
		logger.info("Player passed out from exhaustion; skipped ahead to day %d", new_day)
		self._start_new_day(f"You passed out from exhaustion! Day {new_day} begins.")

	def _start_new_day(self, message: str):
		self.player.row, self.player.col = DEFAULT_X, DEFAULT_Y
		self.player.target_x = self.player.center_x = DEFAULT_Y * TILE_SIZE + TILE_SIZE // 2
		self.player.target_y = self.player.center_y = DEFAULT_X * TILE_SIZE + TILE_SIZE // 2
		self.player.moving = False

		# Shipments sent the day before are paid out as the new day starts --
		# a one-day delay between shipping an order and getting paid for it.
		paid = self.window.contract_board.process_overnight(self.window.wallet)
		if paid:
			total = sum(c.reward for c in paid)
			logger.info("Overnight payments: %s (total $%.2f)", [c.title for c in paid], total)
			message = f"{message} Payment received: ${total:.2f} ({len(paid)} order(s))."

		self.show_status(message)

	def show_status(self, text: str, duration: float = STATUS_MESSAGE_DURATION):
		self.status_message = text
		self.status_message_timer = duration