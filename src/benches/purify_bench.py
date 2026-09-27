"""
The purification bench: turn a crude reaction product into its pure form,
either instantly via Auto Purify (worse yield, no skill involved) or via a
hands-on technique like manual column chromatography (better yield, not
wired in yet -- see ManualColumnView below).
"""

import arcade
from settings import SCREEN_WIDTH
from devtools import logger
from benches.ui_common import BenchView
from purification import is_crude, auto_purify


class Column(arcade.Sprite):
    """A single chromatography column sprite for the manual purification
    interaction (see ManualColumnView). Solid-rectangle placeholder art."""
    def __init__(self, x, y, width=50, height=200):
        super().__init__()
        self.width = width
        self.height = height
        self.texture = arcade.make_soft_square_texture(width, arcade.color.DARK_BLUE, 255, 255)
        self.center_x = x + width / 2
        self.center_y = y + height / 2


class ManualColumnView(arcade.View):
    """
    Real-time column-chromatography interaction: start/stop each column's
    timer with Y/U/I and H/J/K. Not wired up to anything yet -- kept intact
    here for when "Manual Purify" (see PurifyBenchView) is ready to launch
    it, and it's meant to give a better yield than Auto Purify once it does.
    """
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
        start_keys = [arcade.key.Y, arcade.key.U, arcade.key.I]
        stop_keys = [arcade.key.H, arcade.key.J, arcade.key.K]

        for i, k in enumerate(start_keys, start=1):
            if key == k:
                self.timers.get_timer(f"col{i}").start()

        for i, k in enumerate(stop_keys, start=1):
            if key == k:
                self.timers.get_timer(f"col{i}").stop()

        if key == arcade.key.ESCAPE:
            self.window.show_view(self.lab_view)


class PurifyBenchView(BenchView):
    """
    The menu at the purification bench: choose Auto Purify (instant, worse
    yield) or Manual Purify (the hands-on technique -- not available yet;
    see ManualColumnView above).
    """

    MENU_OPTIONS = ["Auto Purify", "Manual Purify"]

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view, title="Purify")
        self.mode = "menu"          # "menu" | "pick_crude"

    # ---- what's in the crude-picker list ----

    def crude_chemicals(self):
        """(label, chemical_name) pairs for every crude chemical currently
        in stock (amount > 0)."""
        inventory = self.window.chemical_inventory
        return [
            (f"{name}: {inventory.describe(name)}", name)
            for name, amount in inventory.contents.items()
            if is_crude(name) and amount > 0
        ]

    # ---- drawing ----

    def on_draw(self):
        self.clear()
        self.draw_bench()

        if self.mode == "menu":
            self.draw_menu()
        else:
            self.draw_crude_picker()

        self.draw_message()

    def draw_menu(self):
        self.draw_title("Purify")
        options = [
            (opt if opt != "Manual Purify" else f"{opt} (not available)", opt != "Manual Purify")
            for opt in self.MENU_OPTIONS
        ]
        self.draw_centered_menu(options)
        self.draw_instructions("UP/DOWN to choose, ENTER to select, ESC to leave bench")

    def draw_crude_picker(self):
        self.draw_title("AUTO PURIFY -- pick a crude chemical")
        items = self.crude_chemicals()
        self.draw_scrollable_list([label for label, _ in items],
            empty_message="(no crude chemicals on hand)")
        self.draw_instructions("UP/DOWN to choose, ENTER to purify (costs 15 min), ESC to go back")

    # ---- input ----

    def on_key_press(self, key, modifiers):
        if self.mode == "menu":
            self.handle_menu_keys(key)
        else:
            self.handle_crude_picker_keys(key)

    def handle_menu_keys(self, key):
        if key in (arcade.key.UP, arcade.key.W):
            self.cursor_index = (self.cursor_index - 1) % len(self.MENU_OPTIONS)
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.cursor_index = (self.cursor_index + 1) % len(self.MENU_OPTIONS)
        elif key == arcade.key.ENTER:
            choice = self.MENU_OPTIONS[self.cursor_index]
            if choice == "Manual Purify":
                self.show_message("Manual purification isn't available yet.", arcade.color.DARK_YELLOW)
            elif choice == "Auto Purify":
                self.mode = "pick_crude"
                self.reset_cursor()
                logger.debug("Purify bench: entered Auto Purify picker")
        elif key == arcade.key.ESCAPE:
            logger.debug("Purify bench: left the bench, returning to lab floor")
            self.window.show_view(self.lab_view)

    def handle_crude_picker_keys(self, key):
        items = self.crude_chemicals()
        if key in (arcade.key.UP, arcade.key.W) and items:
            self.cursor_index = (self.cursor_index - 1) % len(items)
            self.scroll_to_show_cursor()
        elif key in (arcade.key.DOWN, arcade.key.S) and items:
            self.cursor_index = (self.cursor_index + 1) % len(items)
            self.scroll_to_show_cursor()
        elif key == arcade.key.ENTER and items:
            _, crude_name = items[self.cursor_index]
            self.try_auto_purify(crude_name)
        elif key == arcade.key.ESCAPE:
            logger.debug("Purify bench: back to menu from crude picker")
            self.mode = "menu"
            self.reset_cursor()

    def try_auto_purify(self, crude_name):
        inventory = self.window.chemical_inventory
        try:
            pure_name, amount, yield_fraction = auto_purify(inventory, self.window.game_clock, crude_name)
        except ValueError as e:
            self.show_message(str(e), arcade.color.RED)
            return

        self.reset_cursor()
        unit = inventory.species_for(pure_name).unit_label()
        self.show_message(
            f"Purified {amount:.2f} {unit} {pure_name} ({yield_fraction * 100:.0f}% yield, -15 min)",
            arcade.color.DARK_GREEN,
        )
        if not self.crude_chemicals():
            self.mode = "menu"
