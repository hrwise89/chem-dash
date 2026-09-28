"""
A dev-only screen exercising every ui_theme.py primitive at once (rounded
panels, the scrollbar, the tab bar, the min-to-max slider, the icon panel,
and the icon slot row) against sample/placeholder data -- no real menus,
inventories, or game state. The point is to see the new chrome running
before reskinning a real bench with it; reachable by walking up to its
bench tile (south of the shipping bench) or from the door menu's "UI Demo
(dev)" option.
"""

import arcade

from benches.ui_common import wrap_to_width
from benches.ui_theme import (
    CP437_CURSOR,
    FONT_STACK,
    PANEL_COLOR,
    Panel,
    draw_icon_panel,
    draw_icon_slot_row,
    draw_panel,
    draw_scrollbar,
    draw_slider,
    draw_tab_bar,
)
from settings import SCREEN_WIDTH

TAB_LABELS = ["Tab A", "Tab B", "Tab C"]
SAMPLE_LIST_ITEMS = [f"Sample item {i}" for i in range(1, 21)]
SAMPLE_LIST_ITEMS[5] = "Sample item 6 with some much longer text that has to wrap"
VISIBLE_ROWS = 16  # (list_panel's height 340) / LIST_ROW_HEIGHT, unwrapped
ICON_SLOT_COUNT = 5

# The list's own layout -- font_size=10 (Perfect DOS VGA 437 renders much
# larger than a typical sans font at the same point size; the bigger
# sizes elsewhere on this screen -- status bar, tab bar, slider labels --
# are fine as-is). LIST_LEFT_MARGIN (box -> cursor column) and
# LIST_CURSOR_GAP (cursor -> text) are each half of this screen's first
# pass. CURSOR_GLYPH_WIDTH is CP437_CURSOR's own rendered width at
# LIST_FONT_SIZE in this monospace font.
LIST_FONT_SIZE = 10
LIST_ROW_HEIGHT = 20
LIST_LEFT_MARGIN = 10
LIST_CURSOR_GAP = 8
CURSOR_GLYPH_WIDTH = 15
LIST_RIGHT_MARGIN = 10


class UIDemoBenchView(arcade.View):

    def __init__(self, window, lab_view):
        super().__init__()
        self.window = window
        self.lab_view = lab_view

        self.tab_index = 0
        self.list_cursor = 0
        self.scroll_offset = 0
        self.slider_fraction = 0.6
        self.active_icon_slot = 0

    def on_show_view(self):
        arcade.set_background_color(arcade.color.BLACK)

    # ---- drawing ----

    def on_draw(self):
        self.clear()

        status_panel = Panel(left=20, right=780, bottom=545, top=585)
        draw_panel(status_panel, radius=status_panel.height / 2)
        arcade.Text("12:04 PM", status_panel.left + 30, status_panel.center_y, PANEL_COLOR,
                    font_size=14, font_name=FONT_STACK, anchor_x="left", anchor_y="center").draw()
        arcade.Text("$200.00", status_panel.center_x, status_panel.center_y, PANEL_COLOR,
                    font_size=14, font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()
        arcade.Text("29 Mar 1994", status_panel.right - 30, status_panel.center_y, PANEL_COLOR,
                    font_size=14, font_name=FONT_STACK, anchor_x="right", anchor_y="center").draw()

        draw_tab_bar(SCREEN_WIDTH / 2, 505, TAB_LABELS, self.tab_index, spacing=200)

        # The list panel is widened by exactly what shrinking the icon
        # panels to 4/5 their original width frees up (340 -> 272, a
        # 68px difference -- see the icon panels below).
        list_panel = Panel(left=40, right=448, bottom=140, top=480)
        draw_panel(list_panel)
        self._draw_sample_list(list_panel)
        draw_scrollbar(list_panel, len(SAMPLE_LIST_ITEMS), VISIBLE_ROWS, self.scroll_offset)

        # Icon panels at 4/5 their original size (340x180 and 340x80),
        # anchored to the same top-right corner they had before.
        icon_panel = Panel(left=488, right=760, bottom=336, top=480)
        draw_icon_panel(icon_panel, "demo_notebook", placeholder_label="(no image set)")

        icon_row_panel = Panel(left=488, right=760, bottom=216, top=280)
        draw_panel(icon_row_panel)
        active_flags = [i == self.active_icon_slot for i in range(ICON_SLOT_COUNT)]
        draw_icon_slot_row(icon_row_panel, ICON_SLOT_COUNT, active_flags=active_flags)

        draw_slider(SCREEN_WIDTH / 2, 90, 500, 26, self.slider_fraction,
                    min_label="0.5 g", max_label="100 g")
        arcade.Text(
            "LEFT/RIGHT: tabs   UP/DOWN: list   A/D: slider   "
            "TAB: cycle icon slot   ESC: leave",
            SCREEN_WIDTH / 2, 30, arcade.color.GRAY, font_size=12, font_name=FONT_STACK,
            anchor_x="center").draw()

    def _draw_sample_list(self, panel: Panel):
        text_x = panel.left + LIST_LEFT_MARGIN + CURSOR_GLYPH_WIDTH + LIST_CURSOR_GAP
        max_text_width = panel.right - LIST_RIGHT_MARGIN - text_x

        i = self.scroll_offset
        y = panel.top - LIST_ROW_HEIGHT
        while i < len(SAMPLE_LIST_ITEMS) and y > panel.bottom:
            label = SAMPLE_LIST_ITEMS[i]
            lines = wrap_to_width(label, max_text_width, font_size=LIST_FONT_SIZE, font_name=FONT_STACK)

            if i == self.list_cursor:
                arcade.Text(CP437_CURSOR, panel.left + LIST_LEFT_MARGIN, y, PANEL_COLOR,
                            font_size=LIST_FONT_SIZE, font_name=FONT_STACK,
                            anchor_x="left", anchor_y="center").draw()
            for line in lines:
                arcade.Text(line, text_x, y, PANEL_COLOR, font_size=LIST_FONT_SIZE,
                            font_name=FONT_STACK, anchor_x="left", anchor_y="center").draw()
                y -= LIST_ROW_HEIGHT
            i += 1

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
            self._scroll_to_show_cursor()
        elif key == arcade.key.DOWN:
            self.list_cursor = (self.list_cursor + 1) % len(SAMPLE_LIST_ITEMS)
            self._scroll_to_show_cursor()
        elif key == arcade.key.A:
            self.slider_fraction = max(0.0, self.slider_fraction - 0.05)
        elif key == arcade.key.D:
            self.slider_fraction = min(1.0, self.slider_fraction + 0.05)
        elif key == arcade.key.TAB:
            self.active_icon_slot = (self.active_icon_slot + 1) % ICON_SLOT_COUNT

    def _scroll_to_show_cursor(self):
        if self.list_cursor < self.scroll_offset:
            self.scroll_offset = self.list_cursor
        elif self.list_cursor >= self.scroll_offset + VISIBLE_ROWS:
            self.scroll_offset = self.list_cursor - VISIBLE_ROWS + 1
