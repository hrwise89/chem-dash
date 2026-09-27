"""
The purification bench: turn a crude reaction product into its pure form,
either instantly via Auto Purify (worse yield, no skill involved) or via a
hands-on technique like manual column chromatography (better yield, not
wired in yet -- see ManualColumnView below).
"""

import arcade

from benches.ui_common import LIST_START_Y, BenchView, check_pass_out
from devtools import logger
from purification import (
    DIETHYL_ETHER_REQUIRED_ML,
    GLASS_COLUMN_TYPE,
    SILICA_REQUIRED_G,
    auto_purify,
    is_crude,
)
from settings import SCREEN_WIDTH

# ---- Purify amount slider ----
PURIFY_SLIDER_WIDTH = 500
PURIFY_SLIDER_HEIGHT = 26
PURIFY_SLIDER_STEPS = 10  # how many stops the slider has between 0 and the full amount on hand


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
    The menu at the purification bench: choose Auto Purify (pick a crude
    chemical, then how much of it to run -- a "time-consuming action" that
    costs a fixed 20 minutes and a fixed amount of column supplies
    regardless of quantity), Manual Purify (the hands-on technique -- not
    available yet; see ManualColumnView above), or check what columns/
    solvents are on hand.
    """

    MENU_OPTIONS = ["Auto Purify", "Manual Purify", "Supplies"]

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view, title="Purify")
        self.mode = "menu"          # "menu" | "pick_crude" | "pick_amount" | "supplies"
        self.pending_crude_name = None
        self.pending_max_amount = 0.0
        self.purify_amount = 0.0

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

    def supplies_lines(self):
        """Lines for the read-only "Supplies" screen: how many purification
        columns are free, and every chemical tagged is_solvent with its
        current stock -- e.g. diethyl ether, required for Auto Purify."""
        equipment = self.window.equipment_inventory
        inventory = self.window.chemical_inventory

        columns = equipment.available_items(GLASS_COLUMN_TYPE)
        total_columns = sum(1 for item in equipment.items.values() if item.type == GLASS_COLUMN_TYPE)
        lines = [f"Columns: {len(columns)} available / {total_columns} total"]

        lines.append("")
        lines.append("Solvents")
        solvent_names = [
            name for name, species in inventory.species_catalog.items() if species.is_solvent
        ]
        if not solvent_names:
            lines.append("(none known)")
        for name in solvent_names:
            lines.append(f"{name}: {inventory.describe(name)}")
        return lines

    # ---- drawing ----

    def on_draw(self):
        self.clear()
        self.draw_bench()

        if self.mode == "menu":
            self.draw_menu()
        elif self.mode == "pick_crude":
            self.draw_crude_picker()
        elif self.mode == "pick_amount":
            self.draw_amount_screen()
        elif self.mode == "supplies":
            self.draw_supplies()

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
        self.draw_instructions("UP/DOWN to choose, ENTER to select, ESC to go back")

    def draw_supplies(self):
        self.draw_title("SUPPLIES")
        self.draw_scrollable_list(self.supplies_lines())
        self.draw_instructions("UP/DOWN to browse, ESC to go back")

    # ---- the amount slider (row 0: "All", row 1: hand-adjustable slider) ----

    def _purify_step(self) -> float:
        return max(self.pending_max_amount / PURIFY_SLIDER_STEPS, 1e-6)

    def _selected_amount(self) -> float:
        return self.pending_max_amount if self.cursor_index == 0 else self.purify_amount

    def draw_amount_screen(self):
        self.draw_title(f"AUTO PURIFY -- {self.pending_crude_name}")
        unit = self.window.chemical_inventory.species_for(self.pending_crude_name).unit_label()
        self.draw_centered_menu([
            (f"All ({self.pending_max_amount:.1f} {unit})", True),
            (f"{self.purify_amount:.1f} {unit} selected", True),
        ])

        center_x = self.title_text.x
        bar_y = LIST_START_Y - 2 * 40 - 30
        left = center_x - PURIFY_SLIDER_WIDTH / 2
        right = center_x + PURIFY_SLIDER_WIDTH / 2
        bottom = bar_y - PURIFY_SLIDER_HEIGHT / 2
        top = bar_y + PURIFY_SLIDER_HEIGHT / 2

        fraction = 0.0 if self.pending_max_amount <= 0 else self._selected_amount() / self.pending_max_amount
        fraction = max(0.0, min(1.0, fraction))
        fill_x = left + PURIFY_SLIDER_WIDTH * fraction

        arcade.draw_lrbt_rectangle_outline(left, right, bottom, top, arcade.color.BLACK, border_width=2)
        if fraction > 0:
            arcade.draw_lrbt_rectangle_filled(left, fill_x, bottom, top, arcade.color.ORANGE)
        arcade.draw_line(fill_x, bottom - 8, fill_x, top + 8, arcade.color.RED, 3)

        self.text_pool.get(2,
            f"Uses {SILICA_REQUIRED_G:.0f} g silica + {DIETHYL_ETHER_REQUIRED_ML:.0f} mL diethyl ether, "
            "20 min, regardless of amount",
            center_x, bar_y - 34, arcade.color.DARK_BLUE, font_size=13, anchor_x="center").draw()

        self.draw_instructions(
            "UP/DOWN to choose All/slider, LEFT/RIGHT to adjust slider, ENTER to confirm, ESC to go back")

    # ---- input ----

    def on_key_press(self, key, modifiers):
        if self.mode == "menu":
            self.handle_menu_keys(key)
        elif self.mode == "pick_crude":
            self.handle_crude_picker_keys(key)
        elif self.mode == "pick_amount":
            self.handle_amount_keys(key)
        elif self.mode == "supplies":
            self.handle_supplies_keys(key)

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
            elif choice == "Supplies":
                self.mode = "supplies"
                self.reset_cursor()
        elif key == arcade.key.ESCAPE:
            logger.debug("Purify bench: left the bench, returning to lab floor")
            self.window.show_view(self.lab_view)

    def handle_supplies_keys(self, key):
        if key == arcade.key.ESCAPE:
            self.mode = "menu"
            self.reset_cursor()

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
            self._begin_amount_selection(crude_name)
        elif key == arcade.key.ESCAPE:
            logger.debug("Purify bench: back to menu from crude picker")
            self.mode = "menu"
            self.reset_cursor()

    def _begin_amount_selection(self, crude_name):
        self.pending_crude_name = crude_name
        self.pending_max_amount = self.window.chemical_inventory.contents.get(crude_name, 0.0)
        self.purify_amount = self.pending_max_amount
        self.mode = "pick_amount"
        self.reset_cursor()

    def handle_amount_keys(self, key):
        if key in (arcade.key.UP, arcade.key.W):
            self.cursor_index = (self.cursor_index - 1) % 2
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.cursor_index = (self.cursor_index + 1) % 2
        elif key == arcade.key.LEFT and self.cursor_index == 1:
            step = self._purify_step()
            self.purify_amount = max(step, self.purify_amount - step)
        elif key == arcade.key.RIGHT and self.cursor_index == 1:
            step = self._purify_step()
            self.purify_amount = min(self.pending_max_amount, self.purify_amount + step)
        elif key == arcade.key.ENTER:
            self.try_auto_purify(self.pending_crude_name, self._selected_amount())
        elif key == arcade.key.ESCAPE:
            self.mode = "pick_crude"
            self.reset_cursor()

    def try_auto_purify(self, crude_name, amount):
        inventory = self.window.chemical_inventory
        try:
            pure_name, purified_amount, yield_fraction = auto_purify(
                inventory, self.window.equipment_inventory, self.window.consumables,
                self.window.game_clock, crude_name, amount,
            )
        except ValueError as e:
            self.show_message(str(e), arcade.color.RED)
            return

        if check_pass_out(self.window, self.lab_view):
            return  # the 20 minutes pushed the player past their limit for the day

        self.mode = "menu"
        self.reset_cursor()
        unit = inventory.species_for(pure_name).unit_label()
        self.show_message(
            f"Purified {purified_amount:.2f} {unit} {pure_name} ({yield_fraction * 100:.0f}% yield, -20 min)",
            arcade.color.DARK_GREEN,
        )
