"""
The computer bench: a 6-panel menu (per the mockup) leading to the
contract inbox and the catalogue. Two panels are functional; the other
four (Correspondence, BBS, and two Placeholders) are no-ops for now --
selecting one just flashes a status message rather than opening anything.
"""

import arcade

from benches.catalogue_bench import CatalogueBenchView
from benches.contract_inbox import ContractInboxView
from benches.ui_theme import FONT_STACK, PANEL_COLOR, Panel, ThemedBenchView, draw_panel
from day_manager import calendar_date_string, clock_time_string
from devtools import logger

# 2 columns x 3 rows, matching the mockup -- (label, view_class) for the
# two functional panels, (label, None) for a no-op placeholder.
GRID_COLUMNS = 2
PANELS = [
    ("Contract Inbox", ContractInboxView),
    ("Catalogue", CatalogueBenchView),
    ("Correspondence", None),
    ("BBS", None),
    ("Placeholder", None),
    ("Placeholder", None),
]

GRID_LEFT = 40
GRID_RIGHT = 760
GRID_TOP = 520
GRID_BOTTOM = 60
COLUMN_GAP = 20
ROW_GAP = 20
GRID_ROWS = -(-len(PANELS) // GRID_COLUMNS)  # ceil division

_col_width = (GRID_RIGHT - GRID_LEFT - COLUMN_GAP * (GRID_COLUMNS - 1)) / GRID_COLUMNS
_row_height = (GRID_TOP - GRID_BOTTOM - ROW_GAP * (GRID_ROWS - 1)) / GRID_ROWS


def _panel_rect(index: int) -> Panel:
    row, col = divmod(index, GRID_COLUMNS)
    left = GRID_LEFT + col * (_col_width + COLUMN_GAP)
    top = GRID_TOP - row * (_row_height + ROW_GAP)
    return Panel(left=left, right=left + _col_width, bottom=top - _row_height, top=top)


PANEL_RECTS = [_panel_rect(i) for i in range(len(PANELS))]


class ComputerBenchView(ThemedBenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view)
        self.cursor_index = 0

    # ---- drawing ----

    def on_draw(self):
        self.clear()

        hours = self.window.day_manager.hours_into_day(self.window.game_clock)
        self.draw_status_bar(
            clock_time_string(hours),
            f"${self.window.wallet.balance:.2f}",
            calendar_date_string(self.window.day_manager.current_day),
        )

        for i, (label, _) in enumerate(PANELS):
            panel = PANEL_RECTS[i]
            draw_panel(panel)
            color = arcade.color.WHITE if i == self.cursor_index else PANEL_COLOR
            lines = label.split("\n")
            line_height = 22
            text_x = panel.left + 40  # leaves room for the cursor glyph at panel.left + 14
            y = panel.center_y + line_height * (len(lines) - 1) / 2
            for line_num, line in enumerate(lines):
                self.text_pool.get(f"panel_{i}_{line_num}", line, text_x, y - line_num * line_height,
                                    color, font_size=14, font_name=FONT_STACK,
                                    anchor_x="left", anchor_y="center").draw()
            if i == self.cursor_index:
                self.text_pool.get(f"cursor_{i}", "»", panel.left + 14, panel.center_y, color,
                                    font_size=14, font_name=FONT_STACK, anchor_x="left", anchor_y="center").draw()

        self.draw_instructions("ARROWS: move   ENTER: select   ESC: leave")
        self.draw_message()

    # ---- input ----

    def on_key_press(self, key, modifiers):
        if key == arcade.key.ESCAPE:
            logger.debug("Computer bench: left the bench, returning to lab floor")
            self.window.show_view(self.lab_view)
            return
        row, col = divmod(self.cursor_index, GRID_COLUMNS)
        if key in (arcade.key.LEFT, arcade.key.A):
            col = (col - 1) % GRID_COLUMNS
        elif key in (arcade.key.RIGHT, arcade.key.D):
            col = (col + 1) % GRID_COLUMNS
        elif key in (arcade.key.UP, arcade.key.W):
            row = (row - 1) % GRID_ROWS
        elif key in (arcade.key.DOWN, arcade.key.S):
            row = (row + 1) % GRID_ROWS
        elif key == arcade.key.ENTER:
            self._activate(self.cursor_index)
            return
        else:
            return
        self.cursor_index = row * GRID_COLUMNS + col

    def _activate(self, index: int):
        label, view_class = PANELS[index]
        plain_label = label.replace("\n", " ")
        if view_class is None:
            logger.debug("Computer bench: '%s' isn't implemented yet", plain_label)
            self.show_message(f"{plain_label}: not yet implemented", arcade.color.DARK_YELLOW)
            return
        logger.debug("Computer bench: opening '%s'", plain_label)
        self.window.show_view(view_class(self.window, self))
