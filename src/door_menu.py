"""The door's own "Where to?" overlay menu -- separate from LabView so the
view doesn't have to carry this alongside room rendering/movement/day
transitions. Only "Leave for the day" does anything yet (plus "UI Demo
(dev)", shown only in DEV_MODE); the rest are still no-ops until those
destinations exist."""

import arcade

from benches.ui_common import TextPool
from devtools import DEV_MODE, logger
from settings import SCREEN_HEIGHT, SCREEN_WIDTH

BASE_OPTIONS = ["Leave for the day", "Stay in the lab", "Visit university", "Visit the city"]
UI_DEMO_OPTION = "UI Demo (dev)"


class DoorMenu:
    def __init__(self):
        self.open = False
        self.cursor = 0
        self.text_pool = TextPool()

    @property
    def options(self) -> list[str]:
        return BASE_OPTIONS + ([UI_DEMO_OPTION] if DEV_MODE else [])

    def show(self):
        self.open = True
        self.cursor = 0

    def handle_key(self, key, on_leave_for_day, on_ui_demo=None):
        """on_leave_for_day is called if that option is chosen; on_ui_demo
        (only reachable in DEV_MODE) if that one is -- the only two
        options LabView needs to react to right now."""
        options = self.options
        if key in (arcade.key.UP, arcade.key.W):
            self.cursor = (self.cursor - 1) % len(options)
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.cursor = (self.cursor + 1) % len(options)
        elif key in (arcade.key.ENTER, arcade.key.SPACE):
            choice = options[self.cursor]
            self.open = False
            if choice == "Leave for the day":
                on_leave_for_day()
            elif choice == UI_DEMO_OPTION and on_ui_demo is not None:
                on_ui_demo()
            else:
                # "Stay in the lab", "Visit university", and "Visit the
                # city" are all a no-op for now -- just close the menu.
                logger.debug("Door menu: '%s' selected (currently a no-op)", choice)
        elif key == arcade.key.ESCAPE:
            self.open = False

    def draw(self):
        options = self.options
        box_width, box_height = 320, 40 + 24 * len(options)
        center_x, center_y = SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2
        left, right = center_x - box_width / 2, center_x + box_width / 2
        bottom, top = center_y - box_height / 2, center_y + box_height / 2

        arcade.draw_lrbt_rectangle_filled(left, right, bottom, top, arcade.color.WHITE)
        arcade.draw_lrbt_rectangle_outline(left, right, bottom, top, arcade.color.BLACK, border_width=2)

        self.text_pool.get("header", "Where to?", center_x, top - 24,
            arcade.color.BLACK, font_size=16, anchor_x="center").draw()
        for i, option in enumerate(options):
            color = arcade.color.RED if i == self.cursor else arcade.color.BLACK
            prefix = "> " if i == self.cursor else "  "
            self.text_pool.get(i, f"{prefix}{i + 1}. {option}", left + 20, top - 56 - i * 24,
                color, font_size=14, anchor_x="left").draw()
