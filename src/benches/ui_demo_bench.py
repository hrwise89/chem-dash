"""
A dev-only screen exercising every ui_theme.py primitive at once (rounded
panels, the fixed-row paged list, the tab bar, the min-to-max slider, the
icon panel, and the icon slot row) against sample/placeholder data -- no
real menus, inventories, or game state. The point is to see the new
chrome running before reskinning a real bench with it; reachable by
walking up to its bench tile (south of the shipping bench) or from the
door menu's "UI Demo (dev)" option.
"""

import arcade

from benches.ui_theme import (
    Panel,
    ThemedBenchView,
    draw_fixed_list,
    draw_icon_panel,
    draw_icon_slot_row,
    draw_page_indicator,
    draw_panel,
    draw_slider,
    draw_tab_bar,
)
from day_manager import calendar_date_string, clock_time_string
from settings import SCREEN_WIDTH

TAB_LABELS = ["Tab A", "Tab B", "Tab C"]
SAMPLE_LIST_ITEMS = [f"Sample item {i}" for i in range(1, 21)]
ICON_SLOT_COUNT = 5

# Fixed-row list layout -- font_size=10 (Perfect DOS VGA 437 renders much
# larger than a typical sans font at the same point size; the bigger sizes
# elsewhere on this screen -- status bar, tab bar, slider labels -- are
# fine as-is). Rows never wrap, so ROWS_PER_PAGE is exact arithmetic, not
# a per-frame text-measurement pass over the list.
LIST_PANEL = Panel(left=40, right=448, bottom=140, top=480)
LIST_FONT_SIZE = 10
LIST_ROW_HEIGHT = 20
# The page indicator lives inside LIST_PANEL (not below/outside it), so
# its own line's height is reserved here too -- trading a couple of rows
# per page for not floating a page number outside the content area.
LIST_BOTTOM_MARGIN = 36
ROWS_PER_PAGE = int((LIST_PANEL.height - LIST_BOTTOM_MARGIN) // LIST_ROW_HEIGHT)
PAGE_INDICATOR_Y = LIST_PANEL.bottom + 12


class UIDemoBenchView(ThemedBenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view)
        self.tab_index = 0
        self.list_cursor = 0
        self.slider_fraction = 0.6
        self.active_icon_slot = 0

    # ---- drawing ----

    def on_draw(self):
        self.clear()

        hours = self.window.day_manager.hours_into_day(self.window.game_clock)
        self.draw_status_bar(
            clock_time_string(hours),
            f"${self.window.wallet.balance:.2f}",
            calendar_date_string(self.window.day_manager.current_day),
        )

        draw_tab_bar(self.text_pool, "tab", SCREEN_WIDTH / 2, 505, TAB_LABELS, self.tab_index, spacing=200)

        draw_panel(LIST_PANEL)
        draw_fixed_list(LIST_PANEL, self.text_pool, "list", SAMPLE_LIST_ITEMS, self.list_cursor,
                         ROWS_PER_PAGE, LIST_ROW_HEIGHT, font_size=LIST_FONT_SIZE)
        draw_page_indicator(self.text_pool, "page", LIST_PANEL.center_x, PAGE_INDICATOR_Y,
                             self.list_cursor, len(SAMPLE_LIST_ITEMS), ROWS_PER_PAGE)

        # Icon panels at 4/5 their original size (340x180 and 340x80),
        # anchored to the same top-right corner they had before.
        icon_panel = Panel(left=488, right=760, bottom=336, top=480)
        draw_icon_panel(icon_panel, "demo_notebook", self.text_pool, "icon_placeholder",
                         placeholder_label="(no image set)")

        icon_row_panel = Panel(left=488, right=760, bottom=216, top=280)
        draw_panel(icon_row_panel)
        active_flags = [i == self.active_icon_slot for i in range(ICON_SLOT_COUNT)]
        draw_icon_slot_row(icon_row_panel, ICON_SLOT_COUNT, active_flags=active_flags)

        draw_slider(self.text_pool, "slider", SCREEN_WIDTH / 2, 90, 500, 26, self.slider_fraction,
                    min_label="0.5 g", max_label="100 g")
        self.draw_instructions("ARROWS: nav  A/D: slider  TAB: slot  ESC: leave")

    # ---- input ----

    def on_key_press(self, key, modifiers):
        if key == arcade.key.ESCAPE:
            self.window.show_view(self.lab_view)
            return
        if key == arcade.key.LEFT:
            self.tab_index = (self.tab_index - 1) % len(TAB_LABELS)
        elif key == arcade.key.RIGHT:
            self.tab_index = (self.tab_index + 1) % len(TAB_LABELS)
        elif key == arcade.key.UP:
            self.list_cursor = (self.list_cursor - 1) % len(SAMPLE_LIST_ITEMS)
        elif key == arcade.key.DOWN:
            self.list_cursor = (self.list_cursor + 1) % len(SAMPLE_LIST_ITEMS)
        elif key == arcade.key.A:
            self.slider_fraction = max(0.0, self.slider_fraction - 0.05)
        elif key == arcade.key.D:
            self.slider_fraction = min(1.0, self.slider_fraction + 0.05)
        elif key == arcade.key.TAB:
            self.active_icon_slot = (self.active_icon_slot + 1) % ICON_SLOT_COUNT
