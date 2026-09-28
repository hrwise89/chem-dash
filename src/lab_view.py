import arcade
from settings import (SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE, SPRITE_SCALING, TILE_SIZE,
	ROOM_COLS, ROOM_ROWS, ROOM_ORIGIN_X, ROOM_ORIGIN_Y,
	STATUS_BAR_HEIGHT, MESSAGE_BOX_HEIGHT, MAP_BACKGROUND_COLOR,
	OUTSIDE_ROOM_COLOR, GAME_HOURS_PER_REAL_SECOND)
from benches.computer_bench import ComputerBenchView
from benches.purify_bench import PurifyBenchView
from benches.reaction_bench import ReactionBenchView
from benches.shipping_bench import ShippingBenchView
from benches.ui_common import TextPool
from day_manager import calendar_date_string, clock_time_string
from door_menu import DoorMenu
from player import Player
from room_geometry import (
	BENCH_BOTTOM_ROW, BENCH_TOP_ROW, DEFAULT_X, DEFAULT_Y, DOOR_COL, DOOR_ROW,
	PURIFY_COL, REACTION_COL, draw_door_marker, room_x, room_y, wall_sprites,
)
from save_game import save_game
from sprites import make_sprite
from timer_manager import TimerManager, Timer
from devtools import logger

class LabView(arcade.View):
	def __init__(self, window, player_start: tuple[int, int] | None = None):
		# View level attributes
		super().__init__()
		self.window = window
		self.timer_manager = window.timer_manager
		self.day_manager = window.day_manager
		self.message_log = window.message_log
		# Movement
		self.keys_held = set()
		self.move_speed = 0.3 / 1.15  # ~15% faster tile-to-tile movement than before
		self.slide_speed = self.move_speed * 0.9
		self.time_since_move = 0.0

		# Player -- player_start restores a loaded save's position;
		# defaults to the usual spawn point for a fresh game.
		start_row, start_col = player_start if player_start is not None else (DEFAULT_X, DEFAULT_Y)
		self.player = Player(start_row, start_col)
		self.all_sprites = arcade.SpriteList()
		self.all_sprites.append(self.player)

		self.message_log.add("Use arrow keys to move player tile by tile")
		self._last_near_bench_name = None

	def on_show_view(self):
		# arcade.set_background_color() is global window state, not
		# per-view -- a bench view (BenchView.__init__) sets it to its own
		# light gray, so it has to be reset back here every time the lab
		# floor is (re-)shown, not just once at LabView construction, or
		# the floor stays gray after coming back from a bench.
		arcade.set_background_color(OUTSIDE_ROOM_COLOR)

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
		self.door_menu = DoorMenu()

		self.walls = wall_sprites()

		# Benches
		bench_specs = [
			{"name": "bench_hood_1", "x": room_x(REACTION_COL), "y": room_y(BENCH_TOP_ROW),
				"width": TILE_SIZE * 3, "height": TILE_SIZE,
				"color": arcade.color.DARK_GRAY, "action": "view your hood",
				"opens": ReactionBenchView},
			{"name": "bench_col_1", "x": room_x(PURIFY_COL), "y": room_y(BENCH_TOP_ROW),
				"width": TILE_SIZE * 3, "height": TILE_SIZE,
				"color": arcade.color.BROWN, "action": "purify your products",
				"opens": PurifyBenchView},
			{"name": "bench_shipping_1", "x": room_x(REACTION_COL), "y": room_y(BENCH_BOTTOM_ROW),
				"width": TILE_SIZE * 3, "height": TILE_SIZE,
				"color": arcade.color.DARK_ORANGE, "action": "use the shipping desk",
				"opens": ShippingBenchView},
			{"name": "bench_computer_1", "x": room_x(PURIFY_COL), "y": room_y(BENCH_BOTTOM_ROW),
				"width": TILE_SIZE * 3, "height": TILE_SIZE,
				"color": arcade.color.DARK_SLATE_BLUE, "action": "use the computer",
				"opens": ComputerBenchView},
			# Additional benches here
			{"name": "door_home", "x": room_x(DOOR_COL), "y": room_y(DOOR_ROW),
				"width": TILE_SIZE, "height": TILE_SIZE,
				"color": arcade.color.SADDLE_BROWN, "action": "go to the door",
				"is_door": True},
		]
		self.near_bench = None
		self.bench_specs = bench_specs
		self.benches = {} # name -> sprite
		self.bench_list = arcade.SpriteList()

		for spec in self.bench_specs:
			bench = make_sprite(spec["name"], spec["width"], spec["height"],
				spec["x"], spec["y"], spec["color"])
			self.benches[spec["name"]] = bench
			self.bench_list.append(bench)

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
		draw_door_marker()

		self.draw_status_bar()
		self.draw_message_box()

		if self.door_menu.open:
			self.door_menu.draw()

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

	def on_update(self, delta_time):
		if self.door_menu.open:
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

		if self.door_menu.open:
			self.door_menu.handle_key(key, on_leave_for_day=self.go_home)
			return

		if key == arcade.key.ESCAPE:
			arcade.close_window()
			return

		# Interaction with benches
		if key == arcade.key.SPACE and self.near_bench:
			if self.near_bench.get("is_door"):
				self.door_menu.show()
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
		self.player.target_x = self.player.center_x = room_x(DEFAULT_Y)
		self.player.target_y = self.player.center_y = room_y(DEFAULT_X)
		self.player.moving = False

		# Shipments sent the day before are paid out as the new day starts --
		# a one-day delay between shipping an order and getting paid for it.
		paid = self.window.contract_board.process_overnight(self.window.wallet)
		if paid:
			total = sum(c.reward for c in paid)
			logger.info("Overnight payments: %s (total $%.2f)", [c.title for c in paid], total)
			message = f"{message} Payment received: ${total:.2f} ({len(paid)} order(s))."

		# Autosave at each day boundary -- going home or passing out are
		# the only points a "day" actually ends, so they're the natural
		# place to persist progress without needing a save menu yet.
		save_game(self.window, self.player.row, self.player.col)

		self.show_status(message)

	def show_status(self, text: str):
		self.message_log.add(text)
