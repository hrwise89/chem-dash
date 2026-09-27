import arcade
from settings import (SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE, SPRITE_SCALING, TILE_SIZE,
	GRID_WIDTH, GRID_HEIGHT, ROOM_COLS, ROOM_ROWS, ROOM_ORIGIN_X, ROOM_ORIGIN_Y,
	STATUS_BAR_HEIGHT, MESSAGE_BOX_HEIGHT, PLAYER_COLOR, MAP_BACKGROUND_COLOR,
	OUTSIDE_ROOM_COLOR, GAME_HOURS_PER_REAL_SECOND)
from benches.computer_bench import ComputerBenchView
from benches.purify_bench import PurifyBenchView
from benches.reaction_bench import ReactionBenchView
from benches.shipping_bench import ShippingBenchView
from benches.ui_common import TextPool
from day_manager import calendar_date_string, clock_time_string
from timer_manager import TimerManager, Timer
from devtools import logger

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
REACTION_COL = 5.5
PURIFY_COL = 13.5

DOOR_MENU_OPTIONS = ["Leave for the day", "Stay in the lab", "Visit university", "Visit the city"]

# The door's own activation tile is the same color as the wall (it IS a
# chunk of the wall), so it'd otherwise be invisible -- this thin strip
# just outside it marks where it actually is.
DOOR_MARKER_WIDTH = TILE_SIZE / 4
DOOR_MARKER_COLOR = arcade.color.SADDLE_BROWN


def _room_x(local_col: float) -> float:
	"""Local room column (0 at the interior's left edge) -> screen x."""
	return ROOM_ORIGIN_X + local_col * TILE_SIZE + TILE_SIZE / 2


def _room_y(local_row: float) -> float:
	"""Local room row (0 at the interior's bottom edge) -> screen y."""
	return ROOM_ORIGIN_Y + local_row * TILE_SIZE + TILE_SIZE / 2


class Player(arcade.Sprite):
	def __init__(self, row: int, col: int, color: tuple[int,int,int] = PLAYER_COLOR):
		super().__init__()
		self.texture = arcade.make_soft_square_texture(TILE_SIZE - 2, color,
			outer_alpha=255)
		self.row = row
		self.col = col
		self.target_x = _room_x(self.col)
		self.target_y = _room_y(self.row)
		self.center_x = self.target_x
		self.center_y = self.target_y
		self.moving = False
		self.near_bench = False

	def move(self, d_row: int, d_col: int, collidables: list) -> None:
		new_row = max(0, min(self.row + d_row, GRID_HEIGHT - 1))
		new_col = max(0, min(self.col + d_col, GRID_WIDTH - 1))

		# Compute target position
		target_x = _room_x(new_col)
		target_y = _room_y(new_row)

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
			self.target_x = _room_x(self.col)
			self.target_y = _room_y(self.row)
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
		self.message_log = window.message_log
		arcade.set_background_color(OUTSIDE_ROOM_COLOR)
		# Movement
		self.keys_held = set()
		self.move_speed = 0.3 / 1.15  # ~15% faster tile-to-tile movement than before
		self.slide_speed = self.move_speed * 0.9
		self.time_since_move = 0.0

		# Player
		self.player = Player(DEFAULT_X, DEFAULT_Y)
		self.all_sprites = arcade.SpriteList()
		self.all_sprites.append(self.player)

		self.message_log.add("Use arrow keys to move player tile by tile")
		self._last_near_bench_name = None

		# Status bar (top): time / date / money.
		status_bar_y = SCREEN_HEIGHT - STATUS_BAR_HEIGHT / 2
		self.time_text = arcade.Text("", 14, status_bar_y, arcade.color.WHITE,
			font_size=14, anchor_x="left", anchor_y="center")
		self.date_text = arcade.Text("", SCREEN_WIDTH / 2, status_bar_y, arcade.color.WHITE,
			font_size=14, anchor_x="center", anchor_y="center")
		self.money_text = arcade.Text("", SCREEN_WIDTH - 14, status_bar_y, arcade.color.WHITE,
			font_size=14, anchor_x="right", anchor_y="center")

		# Message box (bottom): a small scrolling log -- see message_log.py.
		self.message_text_pool = TextPool()

		# Door menu overlay (drawn on top of everything else when open).
		self.door_menu_open = False
		self.door_menu_cursor = 0
		self.door_menu_text_pool = TextPool()

		# Walls: a 1-tile-thick perimeter around the room's interior, with a
		# gap at the door's row in the left wall (the door itself fills it).
		self.walls = arcade.SpriteList()
		for local_col in range(-1, ROOM_COLS + 1):
			self.walls.append(self._wall_tile(ROOM_ROWS, local_col))       # top
			self.walls.append(self._wall_tile(-1, local_col))              # bottom
		for local_row in range(ROOM_ROWS):
			if local_row != DOOR_ROW:
				self.walls.append(self._wall_tile(local_row, -1))          # left (minus door gap)
			self.walls.append(self._wall_tile(local_row, ROOM_COLS))       # right

		# Benches
		bench_specs = [
			{"name": "bench_hood_1", "x": _room_x(REACTION_COL), "y": _room_y(BENCH_TOP_ROW),
				"width": TILE_SIZE * 3, "height": TILE_SIZE,
				"color": arcade.color.DARK_GRAY, "action": "view your hood",
				"opens": ReactionBenchView},
			{"name": "bench_col_1", "x": _room_x(PURIFY_COL), "y": _room_y(BENCH_TOP_ROW),
				"width": TILE_SIZE * 3, "height": TILE_SIZE,
				"color": arcade.color.BROWN, "action": "purify your products",
				"opens": PurifyBenchView},
			{"name": "bench_shipping_1", "x": _room_x(REACTION_COL), "y": _room_y(BENCH_BOTTOM_ROW),
				"width": TILE_SIZE * 3, "height": TILE_SIZE,
				"color": arcade.color.DARK_ORANGE, "action": "use the shipping desk",
				"opens": ShippingBenchView},
			{"name": "bench_computer_1", "x": _room_x(PURIFY_COL), "y": _room_y(BENCH_BOTTOM_ROW),
				"width": TILE_SIZE * 3, "height": TILE_SIZE,
				"color": arcade.color.DARK_SLATE_BLUE, "action": "use the computer",
				"opens": ComputerBenchView},
			# Additional benches here
			{"name": "door_home", "x": _room_x(DOOR_COL), "y": _room_y(DOOR_ROW),
				"width": TILE_SIZE, "height": TILE_SIZE,
				"color": arcade.color.BLACK, "action": "go to the door",
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

	@staticmethod
	def _wall_tile(local_row: int, local_col: int) -> arcade.SpriteSolidColor:
		return arcade.SpriteSolidColor(TILE_SIZE, TILE_SIZE, _room_x(local_col), _room_y(local_row),
			arcade.color.BLACK)

	def on_draw(self):
		self.clear()

		# Room background + grid, confined to the room's own bounds rather
		# than the whole window (everything outside it is OUTSIDE_ROOM_COLOR,
		# already set as the window's clear color).
		room_left, room_bottom = ROOM_ORIGIN_X, ROOM_ORIGIN_Y
		room_right, room_top = ROOM_ORIGIN_X + ROOM_COLS * TILE_SIZE, ROOM_ORIGIN_Y + ROOM_ROWS * TILE_SIZE
		arcade.draw_lrbt_rectangle_filled(room_left, room_right, room_bottom, room_top, MAP_BACKGROUND_COLOR)
		for row in range(ROOM_ROWS):
			for col in range(ROOM_COLS):
				x, y = ROOM_ORIGIN_X + col * TILE_SIZE, ROOM_ORIGIN_Y + row * TILE_SIZE
				arcade.draw_lrbt_rectangle_outline(x, x + TILE_SIZE, y, y + TILE_SIZE,
					arcade.color.DARK_GRAY, border_width=1)

		# Draw all sprites via sprite list, walls, benches
		self.all_sprites.draw()
		self.walls.draw()
		self.bench_list.draw()
		self.draw_door_marker()

		self.draw_status_bar()
		self.draw_message_box()

		if self.door_menu_open:
			self.draw_door_menu()

	def draw_door_marker(self):
		door_left = _room_x(DOOR_COL) - TILE_SIZE / 2
		door_bottom = _room_y(DOOR_ROW) - TILE_SIZE / 2
		door_top = door_bottom + TILE_SIZE
		arcade.draw_lrbt_rectangle_filled(door_left - DOOR_MARKER_WIDTH, door_left, door_bottom, door_top,
			DOOR_MARKER_COLOR)

	def draw_status_bar(self):
		arcade.draw_lrbt_rectangle_filled(0, SCREEN_WIDTH, SCREEN_HEIGHT - STATUS_BAR_HEIGHT, SCREEN_HEIGHT,
			arcade.color.DARK_SLATE_GRAY)
		hours = self.day_manager.hours_into_day(self.window.game_clock)
		self.time_text.text = clock_time_string(hours)
		self.date_text.text = calendar_date_string(self.day_manager.current_day)
		self.money_text.text = f"${self.window.wallet.balance:.2f}"
		self.time_text.draw()
		self.date_text.draw()
		self.money_text.draw()

	def draw_message_box(self):
		arcade.draw_lrbt_rectangle_filled(0, SCREEN_WIDTH, 0, MESSAGE_BOX_HEIGHT, arcade.color.LIGHT_GRAY)
		arcade.draw_lrbt_rectangle_outline(0, SCREEN_WIDTH, 0, MESSAGE_BOX_HEIGHT, arcade.color.BLACK,
			border_width=2)
		messages = self.message_log.messages
		line_height = 18
		# Newest message at the bottom, older ones stacked upward -- so a
		# new message reads as "entering" at the bottom and pushing the rest
		# up, same direction as it'll eventually scroll off the top.
		y = 12
		for i, text in enumerate(reversed(messages)):
			self.message_text_pool.get(i, text, 10, y, arcade.color.BLACK, font_size=13).draw()
			y += line_height

	def draw_door_menu(self):
		box_width, box_height = 320, 40 + 24 * len(DOOR_MENU_OPTIONS)
		center_x, center_y = SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2
		left, right = center_x - box_width / 2, center_x + box_width / 2
		bottom, top = center_y - box_height / 2, center_y + box_height / 2

		arcade.draw_lrbt_rectangle_filled(left, right, bottom, top, arcade.color.WHITE)
		arcade.draw_lrbt_rectangle_outline(left, right, bottom, top, arcade.color.BLACK, border_width=2)

		self.door_menu_text_pool.get(0, "Where to?", center_x, top - 24,
			arcade.color.BLACK, font_size=16, anchor_x="center").draw()
		for i, option in enumerate(DOOR_MENU_OPTIONS):
			color = arcade.color.RED if i == self.door_menu_cursor else arcade.color.BLACK
			prefix = "> " if i == self.door_menu_cursor else "  "
			self.door_menu_text_pool.get(i + 1, f"{prefix}{i + 1}. {option}", left + 20, top - 56 - i * 24,
				color, font_size=14, anchor_x="left").draw()

	def on_update(self, delta_time):
		if self.door_menu_open:
			return  # time (and everything else) pauses while the menu is open

		self.time_since_move += delta_time

		# In-game time passes while the player is out on the lab floor. It
		# does NOT tick inside mini-games/the reaction bench (those views
		# don't call this), matching "time passes while walking around."
		self.window.game_clock.advance(delta_time * GAME_HOURS_PER_REAL_SECOND)

		if self.day_manager.has_passed_out(self.window.game_clock):
			self.pass_out()
			return

		if self.day_manager.is_sleepy(self.window.game_clock):
			self.message_log.add("Getting sleepy... head home soon")

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
			bench_row = int((bench.center_y - ROOM_ORIGIN_Y) // TILE_SIZE)
			bench_col = int((bench.center_x - ROOM_ORIGIN_X) // TILE_SIZE)

			if abs(self.player.row - bench_row) + abs(self.player.col - bench_col) == 1:
				self.near_bench = spec
				break

		near_name = self.near_bench["name"] if self.near_bench else None
		if near_name != self._last_near_bench_name and self.near_bench:
			self.message_log.add(f"Press SPACE to {self.near_bench['action']}")
		self._last_near_bench_name = near_name

	def on_key_press(self, key, modifiers):
		self.keys_held.add(key)

		if key == arcade.key.ESCAPE:
			if self.door_menu_open:
				self.door_menu_open = False
			else:
				arcade.close_window()
			return

		if self.door_menu_open:
			self.handle_door_menu_keys(key)
			return

		# Interaction with benches
		if key == arcade.key.SPACE and self.near_bench:
			if self.near_bench.get("is_door"):
				self.door_menu_open = True
				self.door_menu_cursor = 0
			else:
				view_class = self.near_bench["opens"]
				logger.info("Opening %s from bench '%s'", view_class.__name__, self.near_bench["name"])
				self.window.show_view(view_class(self.window, self))

	def handle_door_menu_keys(self, key):
		if key in (arcade.key.UP, arcade.key.W):
			self.door_menu_cursor = (self.door_menu_cursor - 1) % len(DOOR_MENU_OPTIONS)
		elif key in (arcade.key.DOWN, arcade.key.S):
			self.door_menu_cursor = (self.door_menu_cursor + 1) % len(DOOR_MENU_OPTIONS)
		elif key in (arcade.key.ENTER, arcade.key.SPACE):
			choice = DOOR_MENU_OPTIONS[self.door_menu_cursor]
			self.door_menu_open = False
			if choice == "Leave for the day":
				self.go_home()
			else:
				# "Stay in the lab", "Visit university", and "Visit the
				# city" are all a no-op for now -- just close the menu.
				logger.debug("Door menu: '%s' selected (currently a no-op)", choice)

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
		self.player.target_x = self.player.center_x = _room_x(DEFAULT_Y)
		self.player.target_y = self.player.center_y = _room_y(DEFAULT_X)
		self.player.moving = False

		# Shipments sent the day before are paid out as the new day starts --
		# a one-day delay between shipping an order and getting paid for it.
		paid = self.window.contract_board.process_overnight(self.window.wallet)
		if paid:
			total = sum(c.reward for c in paid)
			logger.info("Overnight payments: %s (total $%.2f)", [c.title for c in paid], total)
			message = f"{message} Payment received: ${total:.2f} ({len(paid)} order(s))."

		self.show_status(message)

	def show_status(self, text: str):
		self.message_log.add(text)
