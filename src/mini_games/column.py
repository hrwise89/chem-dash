import arcade
from settings import (SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE, SPRITE_SCALING, TILE_SIZE, 
	GRID_WIDTH, GRID_HEIGHT, PLAYER_COLOR, MAP_BACKGROUND_COLOR)

class Column(arcade.Sprite):
	def __init__(self, x, y, width=50, height=200):
		super().__init__()
		# We'll create a texture with a simple solid rectangle for now
		self.width = width
		self.height = height
		self.texture = arcade.make_soft_square_texture(width, arcade.color.DARK_BLUE, 255, 255)
		self.center_x = x + width / 2
		self.center_y = y + height / 2

class ColumnMiniGameView(arcade.View):
	def __init__(self, window, lab_view):
		super().__init__()
		self.window = window
		self.lab_view = lab_view  # so we can return later
		self.timers = lab_view.timer_manager

		arcade.set_background_color(arcade.color.LIGHT_GRAY)

		# Columns
		self.columns = arcade.SpriteList()
		spacing, width, height, base_y = 150, 50, 600, 0
		start_x = (SCREEN_WIDTH - (3 * width + 2 * spacing)) / 2

		for i in range(3):
			col = Column(start_x + i * (width + spacing), base_y, width, height)
			self.columns.append(col)

		# Guide text
		self.guide_text = arcade.Text("Use the number pad keys to interact with your columns",
						 100, 500, arcade.color.BLACK, 20)

		# One reusable Text object per column timer, instead of calling the
		# (very slow, deprecated-for-per-frame-use) arcade.draw_text() each
		# frame -- see on_draw, which only updates .text on these.
		self.timer_texts = [
			arcade.Text("", column.center_x, column.center_y + column.height / 2 + 10,
				arcade.color.BLACK, font_size=14, anchor_x="center")
			for column in self.columns
		]

	def on_draw(self):
		self.clear()
		self.guide_text.draw()

		# Draw column sprites
		self.columns.draw()

		# Draw timers
		for i, (column, timer_text) in enumerate(zip(self.columns, self.timer_texts), start=1):
			timer = self.timers.get_timer(f"col{i}")
			timer_text.text = f"{timer.get_remaining():.1f}s"
			timer_text.draw()

	def on_key_press(self, key, modifiers):
		if key == arcade.key.ESCAPE:
			self.window.show_view(self.lab_view)

		start_keys = [arcade.key.Y, arcade.key.U, arcade.key.I]
		stop_keys  = [arcade.key.H, arcade.key.J, arcade.key.K]
		collect_keys = [arcade.key.N, arcade.key.M, arcade.key.COMMA]

		for i, k in enumerate(start_keys, start=1):
			if key == k:
				self.timers.get_timer(f"col{i}").start()

		for i, k in enumerate(stop_keys, start=1):
			if key == k:
				self.timers.get_timer(f"col{i}").stop()

		for i, k in enumerate(stop_keys, start=1):
			if key == k:
				pass  # placeholder

		if key == arcade.key.ESCAPE:
			self.window.show_view(self.lab_view)