"""
The notebook: a cross-cutting overlay (opened with N, from the lab floor or
from inside any bench) showing player-wide info -- reactions running,
inventory, equipment, consumables -- that doesn't belong to one specific
bench. Composition, not a View: whatever view is showing (LabView or any
ThemedBenchView) keeps drawing/updating itself underneath, then draws this
on top if window.notebook.is_open, mirroring door_menu.py's DoorMenu.

State survives being closed with N (unlike ESC, which also closes it but
is meant as "leave the notebook" -- both close it the same way here, since
what to show next time is remembered either way): which section it's on,
and its cursor within that section, so opening it again with N shows
exactly what was showing before.
"""
import arcade

from benches.ui_common import TextPool
from benches.ui_theme import (
    CP437_CURSOR, DIM_COLOR, FONT_STACK, PANEL_COLOR, Panel,
    draw_fixed_list, draw_page_indicator, draw_panel, truncate_to_width,
)

# 2 columns x 3 rows, matching the mockup -- (label, section_key) for the
# one functional panel, (label, None) for a no-op placeholder.
GRID_COLUMNS = 2
PANELS = [
    ("Active\nReactions", None),
    ("Chemical\nInventory", "chemical_inventory"),
    ("Equipment", None),
    ("Consumables", None),
    ("Placeholder", None),
    ("Placeholder", None),
]
GRID_ROWS = -(-len(PANELS) // GRID_COLUMNS)  # ceil division

# The overlay frame itself: scaled from the mockup image (1536x1152,
# matching this game's 4:3 800x600 canvas exactly) by 800/1536 = 0.521 --
# big enough to obscure whatever bench-specific controls sit at the bottom
# of the screen beneath it, but leaving the shared top status bar (drawn by
# whatever view is underneath) visible above it, per the mockup.
NOTEBOOK_PANEL = Panel(left=50, right=750, bottom=40, top=500)

GRID_LEFT = NOTEBOOK_PANEL.left + 20
GRID_RIGHT = NOTEBOOK_PANEL.right - 20
GRID_TOP = NOTEBOOK_PANEL.top - 20
GRID_BOTTOM = NOTEBOOK_PANEL.bottom + 40  # leaves room for the instructions line
COLUMN_GAP = 16
ROW_GAP = 14

_col_width = (GRID_RIGHT - GRID_LEFT - COLUMN_GAP * (GRID_COLUMNS - 1)) / GRID_COLUMNS
_row_height = (GRID_TOP - GRID_BOTTOM - ROW_GAP * (GRID_ROWS - 1)) / GRID_ROWS

SECTION_PANEL = Panel(left=GRID_LEFT, right=GRID_RIGHT, bottom=GRID_BOTTOM, top=GRID_TOP)
SECTION_ROW_HEIGHT = 24
SECTION_ROWS_PER_PAGE = max(1, int(SECTION_PANEL.height // SECTION_ROW_HEIGHT))


def _panel_rect(index: int) -> Panel:
    row, col = divmod(index, GRID_COLUMNS)
    left = GRID_LEFT + col * (_col_width + COLUMN_GAP)
    top = GRID_TOP - row * (_row_height + ROW_GAP)
    return Panel(left=left, right=left + _col_width, bottom=top - _row_height, top=top)


PANEL_RECTS = [_panel_rect(i) for i in range(len(PANELS))]


class Notebook:

    def __init__(self):
        self.is_open = False
        self.section = None       # None = showing the 6-panel grid; else a PANELS section key
        self.cursor_index = 0     # grid cursor
        self.section_cursor = 0   # cursor/scroll position within an open section
        self.text_pool = TextPool()

    def toggle(self):
        """N key: opens/closes the notebook. Deliberately does NOT reset
        section/cursor_index/section_cursor -- reopening must show exactly
        what was showing before, per spec."""
        self.is_open = not self.is_open

    # ---- input ----

    def handle_key(self, key, window):
        if self.section is not None:
            self._handle_section_keys(key, window)
            return

        if key == arcade.key.ESCAPE:
            self.is_open = False
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
            self._activate()
            return
        else:
            return
        self.cursor_index = row * GRID_COLUMNS + col

    def _activate(self):
        _, section = PANELS[self.cursor_index]
        if section is None:
            return  # no-op placeholder
        self.section = section
        self.section_cursor = 0

    def _handle_section_keys(self, key, window):
        if key == arcade.key.ESCAPE:
            self.section = None
            return
        if self.section == "chemical_inventory":
            items = sorted(window.chemical_inventory.contents.keys())
            if items and key in (arcade.key.UP, arcade.key.W):
                self.section_cursor = (self.section_cursor - 1) % len(items)
            elif items and key in (arcade.key.DOWN, arcade.key.S):
                self.section_cursor = (self.section_cursor + 1) % len(items)

    # ---- drawing ----

    def draw(self, window):
        draw_panel(NOTEBOOK_PANEL)
        if self.section is None:
            self._draw_grid()
        else:
            self._draw_section(window)

    def _draw_grid(self):
        for i, (label, _) in enumerate(PANELS):
            panel = PANEL_RECTS[i]
            draw_panel(panel)
            color = arcade.color.WHITE if i == self.cursor_index else PANEL_COLOR
            lines = label.split("\n")
            line_height = 20
            text_x = panel.left + 36
            y = panel.center_y + line_height * (len(lines) - 1) / 2
            for line_num, line in enumerate(lines):
                self.text_pool.get(f"grid_{i}_{line_num}", line, text_x, y - line_num * line_height,
                                    color, font_size=13, font_name=FONT_STACK,
                                    anchor_x="left", anchor_y="center").draw()
            if i == self.cursor_index:
                self.text_pool.get(f"grid_cursor_{i}", CP437_CURSOR, panel.left + 12, panel.center_y,
                                    color, font_size=13, font_name=FONT_STACK,
                                    anchor_x="left", anchor_y="center").draw()
        self._draw_instructions("Arrows: Move Cursor   Enter: Cont.   ESC: Go back")

    def _draw_section(self, window):
        if self.section == "chemical_inventory":
            self._draw_chemical_inventory(window)
        self._draw_instructions("Up/Down: Scroll   ESC: Back   N: Close")

    def _draw_chemical_inventory(self, window):
        inventory = window.chemical_inventory
        names = sorted(inventory.contents.keys())
        row_font_size = 13
        probe = self.text_pool.get("chem_inv_probe", "", 0, 0, PANEL_COLOR,
                                    font_size=row_font_size, font_name=FONT_STACK)
        max_width = SECTION_PANEL.width - 36  # left_margin + cursor_glyph_width + cursor_gap
        rows = [truncate_to_width(probe, f"{name}: {inventory.describe(name)}", max_width)
                for name in names]
        draw_fixed_list(SECTION_PANEL, self.text_pool, "chem_inv", rows, self.section_cursor,
                         SECTION_ROWS_PER_PAGE, SECTION_ROW_HEIGHT, font_size=row_font_size,
                         empty_label="(no chemicals in inventory)")
        draw_page_indicator(self.text_pool, "chem_inv_page", SECTION_PANEL.right - 50,
                             SECTION_PANEL.top - 12, self.section_cursor, len(names),
                             SECTION_ROWS_PER_PAGE)

    def _draw_instructions(self, text: str):
        self.text_pool.get("notebook_instructions", text, NOTEBOOK_PANEL.center_x,
                            NOTEBOOK_PANEL.bottom + 16, DIM_COLOR, font_size=10,
                            font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()
