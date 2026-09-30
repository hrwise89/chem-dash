"""
The notebook: a cross-cutting overlay (opened with N, from the lab floor or
from inside any bench) showing player-wide info -- reactions running,
inventory, equipment, consumables -- that doesn't belong to one specific
bench. Composition, not a View: whatever view is showing (LabView or any
ThemedBenchView) keeps updating itself paused-out-of-frame underneath
(on_update short-circuits while it's open -- see ThemedBenchView.on_update/
LabView.on_update), then the notebook draws itself on top if window.
notebook.is_open, mirroring door_menu.py's DoorMenu composition pattern.

It draws at the same full-screen scale as any bench (status bar, content,
instructions at the same coordinates ui_theme.py's STATUS_PANEL/
INSTRUCTIONS_Y already fix for every bench) rather than a smaller inset
panel -- an earlier version drew it as a shrunken overlay with the bench
underneath peeking around its edges, but that meant every section's list/
icon/description panels needed their own smaller, one-off layout numbers
instead of the exact proven geometry catalogue_bench.py/purify_bench.py/
shipping_bench.py already use at full scale, which was the direct cause of
several rows and tab labels overflowing their boxes. A doubled border
(_draw_frame) drawn just inside the screen edge is the only visual cue
left that this is the notebook rather than a bench -- everything else
about its chrome is identical on purpose.

State survives being closed with N (unlike ESC, which also closes it but
is meant as "leave the notebook" -- both close it the same way here, since
what to show next time is remembered either way): which section it's on,
each section's own cursor, and (for the tabbed sections) which tab -- so
opening it again with N shows exactly what was showing before.

Active/Known Reactions and Inventory are shared_sections.py objects (see
that module's own docstring) rather than logic living here directly -- the
reaction bench (reaction_bench.py) shows the same three screens (Active
Reactions also collectible there), so the screens themselves are owned by
one module both can compose instead of each having their own copy.
"""
import arcade

from benches.shared_sections import INVENTORY_TABS, InventorySection, ReactionsSection
from benches.ui_common import TextPool
from benches.ui_theme import (
    CP437_CURSOR, DIM_COLOR, FONT_STACK, INSTRUCTIONS_Y, PANEL_COLOR, Panel,
    draw_description_panel, draw_multiline_list, draw_page_indicator,
    draw_panel, draw_status_bar, draw_tab_bar,
)
from day_manager import calendar_date_string, clock_time_string, due_date_calendar_string
from economy import in_transit_description, open_order_description, order_email_header, order_row_lines
from settings import SCREEN_HEIGHT, SCREEN_WIDTH

# ---- the doubled screen-edge border that's the notebook's whole visual
# distinction from a bench (see the module docstring) ----
FRAME_MARGIN = 6
FRAME_GAP = 4
FRAME_BORDER_WIDTH = 2

# 2 columns x 3 rows, matching the mockup -- (label, section_key) for a
# functional panel, (label, None) for a no-op placeholder. Full-screen
# geometry copied from computer_bench.py's own 6-panel grid.
GRID_COLUMNS = 2
PANELS = [
    ("Active\nReactions", "active_reactions"),
    ("Orders", "orders"),
    ("Inventory", "inventory"),
    ("History", None),
    ("Known\nReactions", "known_reactions"),
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

# ---- Orders: tabs + a 2-line-per-entry list (shipping_bench.py's own
# Open Orders/Awaiting pickup geometry) + description, but read-only ----
ORDER_TABS = [("Open Orders", "open_orders"), ("Awaiting pickup", "in_transit")]
ORDERS_TAB_Y = 505
ORDERS_LIST_FONT_SIZE = 10
ORDERS_LIST_LINE_HEIGHT = 20
ORDERS_LIST_LINES_PER_ENTRY = 2
ORDERS_ENTRIES_PER_PAGE = 5
ORDERS_LIST_TOP = 480
_orders_list_content_height = ORDERS_ENTRIES_PER_PAGE * ORDERS_LIST_LINE_HEIGHT * ORDERS_LIST_LINES_PER_ENTRY
ORDERS_PAGE_INDICATOR_Y = ORDERS_LIST_TOP - _orders_list_content_height - 24
ORDERS_LIST_PANEL = Panel(left=40, right=760, bottom=ORDERS_PAGE_INDICATOR_Y - 12, top=ORDERS_LIST_TOP)
ORDERS_DESC_PANEL = Panel(left=40, right=760, bottom=50, top=ORDERS_LIST_PANEL.bottom - 10)
ORDERS_DESC_FONT_SIZE = 9


class Notebook:

    def __init__(self):
        self.is_open = False
        self.section = None       # None = showing the 6-panel grid; else a PANELS section key
        self.cursor_index = 0     # grid cursor
        self.active_reactions = ReactionsSection(running=True)
        self.known_reactions = ReactionsSection(running=False)
        self.inventory = InventorySection()
        self.orders_tab = 0
        self.orders_cursor = 0
        self.text_pool = TextPool()

    def toggle(self):
        """N key: opens/closes the notebook. Deliberately does NOT reset
        any section/cursor/tab state -- reopening must show exactly what
        was showing before, per spec."""
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
            return  # no-op placeholder (or "History", not implemented yet)
        self.section = section

    def _handle_section_keys(self, key, window):
        if key == arcade.key.ESCAPE:
            self.section = None
            return
        if self.section == "active_reactions":
            self.active_reactions.handle_key(key, window)
        elif self.section == "known_reactions":
            self.known_reactions.handle_key(key, window)
        elif self.section == "orders":
            self._handle_orders_keys(key, window)
        elif self.section == "inventory":
            self.inventory.handle_key(key, window)

    def _handle_orders_keys(self, key, window):
        if key == arcade.key.LEFT:
            self.orders_tab = (self.orders_tab - 1) % len(ORDER_TABS)
            self.orders_cursor = 0
        elif key == arcade.key.RIGHT:
            self.orders_tab = (self.orders_tab + 1) % len(ORDER_TABS)
            self.orders_cursor = 0
        else:
            contracts = self._orders_items(window)
            if not contracts:
                return
            if key in (arcade.key.UP, arcade.key.W):
                self.orders_cursor = (self.orders_cursor - 1) % len(contracts)
            elif key in (arcade.key.DOWN, arcade.key.S):
                self.orders_cursor = (self.orders_cursor + 1) % len(contracts)

    def _orders_items(self, window):
        board = window.contract_board
        _, mode = ORDER_TABS[self.orders_tab]
        return board.accepted if mode == "open_orders" else board.in_transit

    # ---- drawing ----

    def draw(self, window):
        arcade.draw_lrbt_rectangle_filled(0, SCREEN_WIDTH, 0, SCREEN_HEIGHT, arcade.color.BLACK)
        self._draw_frame()

        hours = window.day_manager.hours_into_day(window.game_clock)
        draw_status_bar(self.text_pool, clock_time_string(hours), f"${window.wallet.balance:.2f}",
                         calendar_date_string(window.day_manager.current_day))

        if self.section is None:
            self._draw_grid()
        elif self.section == "active_reactions":
            self.active_reactions.draw(window, self.text_pool, "Up/Down: Scroll   ESC: Back   N: Close")
        elif self.section == "known_reactions":
            self.known_reactions.draw(window, self.text_pool, "Up/Down: Scroll   ESC: Back   N: Close")
        elif self.section == "orders":
            self._draw_orders_section(window)
        elif self.section == "inventory":
            self.inventory.draw(window, self.text_pool, "L/R: Tabs   Up/Down: Scroll   ESC: Back   N: Close")

    def _draw_frame(self):
        """A doubled border just inside the screen edge -- the notebook's
        one bit of chrome that's different from a bench, otherwise drawn
        at the exact same scale (see the module docstring)."""
        m = FRAME_MARGIN
        arcade.draw_lrbt_rectangle_outline(m, SCREEN_WIDTH - m, m, SCREEN_HEIGHT - m,
                                            PANEL_COLOR, border_width=FRAME_BORDER_WIDTH)
        m2 = m + FRAME_GAP
        arcade.draw_lrbt_rectangle_outline(m2, SCREEN_WIDTH - m2, m2, SCREEN_HEIGHT - m2,
                                            PANEL_COLOR, border_width=1)

    def _draw_grid(self):
        for i, (label, _) in enumerate(PANELS):
            panel = PANEL_RECTS[i]
            draw_panel(panel)
            color = arcade.color.WHITE if i == self.cursor_index else PANEL_COLOR
            lines = label.split("\n")
            line_height = 22
            text_x = panel.left + 40
            y = panel.center_y + line_height * (len(lines) - 1) / 2
            for line_num, line in enumerate(lines):
                self.text_pool.get(f"grid_{i}_{line_num}", line, text_x, y - line_num * line_height,
                                    color, font_size=14, font_name=FONT_STACK,
                                    anchor_x="left", anchor_y="center").draw()
            if i == self.cursor_index:
                self.text_pool.get(f"grid_cursor_{i}", CP437_CURSOR, panel.left + 14, panel.center_y,
                                    color, font_size=14, font_name=FONT_STACK,
                                    anchor_x="left", anchor_y="center").draw()
        self._draw_instructions("ARROWS: move   ENTER: select   ESC: leave")

    def _draw_orders_section(self, window):
        draw_tab_bar(self.text_pool, "orders_tab", SCREEN_WIDTH / 2, ORDERS_TAB_Y,
                     [label for label, _ in ORDER_TABS], self.orders_tab, spacing=320, font_size=14)

        contracts = self._orders_items(window)
        inventory = window.chemical_inventory
        entries = [order_row_lines(c, inventory, due_date_calendar_string(c.is_rush, c.days_to_complete, c.due_date))
                   for c in contracts]
        draw_panel(ORDERS_LIST_PANEL)
        draw_multiline_list(ORDERS_LIST_PANEL, self.text_pool, "orders_list", entries, self.orders_cursor,
                             ORDERS_ENTRIES_PER_PAGE, ORDERS_LIST_LINE_HEIGHT, ORDERS_LIST_LINES_PER_ENTRY,
                             font_size=ORDERS_LIST_FONT_SIZE, cursor_line=0, line_indents=[0, 20],
                             empty_label="(no orders)")
        draw_page_indicator(self.text_pool, "orders_page", ORDERS_LIST_PANEL.center_x, ORDERS_PAGE_INDICATOR_Y,
                             self.orders_cursor, len(contracts), ORDERS_ENTRIES_PER_PAGE)

        if contracts:
            contract = contracts[self.orders_cursor]
            _, mode = ORDER_TABS[self.orders_tab]
            description = (open_order_description(contract, window.contract_board, inventory)
                            if mode == "open_orders" else in_transit_description(contract))
            draw_description_panel(ORDERS_DESC_PANEL, self.text_pool, "orders_desc", description,
                                    font_size=ORDERS_DESC_FONT_SIZE, header_lines=order_email_header(contract))
        else:
            draw_panel(ORDERS_DESC_PANEL)

        self._draw_instructions("L/R: Tabs   Up/Down: Scroll   ESC: Back   N: Close")

    def _draw_instructions(self, text: str):
        self.text_pool.get("notebook_instructions", text, SCREEN_WIDTH / 2, INSTRUCTIONS_Y, DIM_COLOR,
                            font_size=10, font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()
