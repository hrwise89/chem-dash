"""
The shipping bench: hand off product against an order you've already
accepted on the computer bench. Shipping consumes the required product
from inventory right away (crude accepted unless the order requires
purity -- see economy.ContractBoard.ship), but payment is deferred until
the shipment is processed overnight (see day_manager.py / lab_view.go_home
/ lab_view.pass_out), so there's always a one-day gap between shipping an
order and getting paid for it.

Accepting/declining new order offers stays on the computer bench (its
Offers section) -- this bench is only for fulfilling orders already in
`window.contract_board.accepted` or `.in_transit`.

Each order is a fixed 2-line entry -- type symbol, chemical name ("(P)"
suffixed if it requires purity), amount, and reward on the first line,
sender (indented) on the second. The description panel below shows the
selected order's full message, word-wrapped rather than truncated to one
line, since it's now tall enough to hold it. Both the row list and the
description are rebuilt only when they can actually change -- entering
the bench, switching tabs, moving the cursor, or shipping -- not on every
draw call, since nothing here changes on its own between those moments.

Fitting text to a width is done with ui_theme.truncate_to_width's binary
search, never a naive one-character-at-a-time scan -- that scan, run
against a ~250-character order message every time the cursor moved,
measured out at 100+ ms on its own (each `.text =` reassignment forces a
pyglet re-layout), which is what made repeated arrow presses feel like
they were queuing up instead of responding immediately.
"""

import arcade

from benches.ui_theme import (
    FONT_STACK,
    PANEL_COLOR,
    Panel,
    ThemedBenchView,
    draw_multiline_list,
    draw_page_indicator,
    draw_panel,
    draw_tab_bar,
    draw_wrapped_lines,
    truncate_to_width,
    wrap_and_fit,
)
from day_manager import calendar_date_string, clock_time_string
from devtools import logger
from economy import in_transit_description, open_order_description, order_detail_line, order_summary_line
from settings import SCREEN_WIDTH

# "In Transit" is renamed "Awaiting pickup" -- eventually this tab will
# also show a per-order pickup marker ("picking up (morning)" / "picked
# up (afternoon)") once the twice-daily pickup mechanic exists, but that
# backend doesn't exist yet, so there's nothing real to display for it.
TABS = [("Open Orders", "open_orders"), ("Awaiting pickup", "in_transit")]

LIST_FONT_SIZE = 10
LIST_LINE_HEIGHT = 20
LIST_LINES_PER_ENTRY = 2
LIST_ENTRY_HEIGHT = LIST_LINE_HEIGHT * LIST_LINES_PER_ENTRY
LIST_LINE_INDENTS = [0, 20]  # indents the sender line under the summary line above it

ENTRIES_PER_PAGE = 5
LIST_TOP = 480
LIST_CONTENT_HEIGHT = ENTRIES_PER_PAGE * LIST_ENTRY_HEIGHT
# The page indicator lives inside LIST_PANEL (not below/outside it) --
# LAST_LINE_GAP is the clearance between the last entry's bottom line and
# the indicator, PAGE_INDICATOR_BOTTOM_MARGIN between the indicator and
# the panel's own border. The panel is sized to fit exactly
# ENTRIES_PER_PAGE entries plus both of those -- no more, no less --
# rather than however many happen to fit a fixed pixel box.
LAST_LINE_GAP = 24
PAGE_INDICATOR_BOTTOM_MARGIN = 12
PAGE_INDICATOR_Y = LIST_TOP - LIST_CONTENT_HEIGHT - LAST_LINE_GAP
LIST_PANEL = Panel(left=40, right=760, bottom=PAGE_INDICATOR_Y - PAGE_INDICATOR_BOTTOM_MARGIN, top=LIST_TOP)

# Freed up by shrinking LIST_PANEL to only what it needs -- tall enough
# for a full order message to word-wrap into, instead of being truncated
# to one line.
DESCRIPTION_PANEL = Panel(left=40, right=760, bottom=90, top=LIST_PANEL.bottom - 10)
DESCRIPTION_FONT_SIZE = 10
DESCRIPTION_LINE_HEIGHT = 20
DESCRIPTION_MAX_LINES = max(1, int((DESCRIPTION_PANEL.height - 10) // DESCRIPTION_LINE_HEIGHT))

# How long an unfillable-order error stays shown in the description panel
# (replacing the selected order's message) before reverting to it.
DESCRIPTION_OVERRIDE_DURATION = 2.5


class ShippingBenchView(ThemedBenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view)
        self.mode = "open_orders"
        self.tab_index = 0
        self.cursor_index = 0
        self.entries = []             # [([line1, line2], contract), ...] for the current tab
        self.description_lines = []   # the cursor-selected entry's word-wrapped full message
        self.description_override_lines = []
        self.description_override_timer = 0.0
        self._refresh_rows()

    # ---- row/description content (only rebuilt when it can change) ----

    def _entry_lines(self, contract) -> list[str]:
        # Same row format as the contract inbox (see contract_inbox.py) --
        # built with the same primitives/constants on purpose, so the two
        # screens read as one system.
        max_width = LIST_PANEL.width - 60  # leaves room for the cursor glyph + left margin
        probe = self.text_pool.get("_probe_row", "", 0, 0, PANEL_COLOR,
                                    font_size=LIST_FONT_SIZE, font_name=FONT_STACK)
        summary = truncate_to_width(probe, order_summary_line(contract), max_width - LIST_LINE_INDENTS[0])
        detail = truncate_to_width(probe, order_detail_line(contract), max_width - LIST_LINE_INDENTS[1])
        return [summary, detail]

    def _refresh_rows(self):
        pool = self.window.contract_board.accepted if self.mode == "open_orders" \
            else self.window.contract_board.in_transit
        self.entries = [(self._entry_lines(c), c) for c in pool]
        self.cursor_index = min(self.cursor_index, max(0, len(self.entries) - 1))
        self._refresh_description()

    def _refresh_description(self):
        if not self.entries:
            self.description_lines = []
            return
        _, contract = self.entries[self.cursor_index]
        text = (open_order_description(contract, self.window.contract_board, self.window.chemical_inventory)
                if self.mode == "open_orders" else in_transit_description(contract))
        self.description_lines = self._fit_description(text)

    def _fit_description(self, text: str) -> list[str]:
        probe = self.text_pool.get("_probe_description", "", 0, 0, PANEL_COLOR,
                                    font_size=DESCRIPTION_FONT_SIZE, font_name=FONT_STACK)
        max_width = DESCRIPTION_PANEL.width - 20
        return wrap_and_fit(probe, text, max_width, DESCRIPTION_MAX_LINES, font_size=DESCRIPTION_FONT_SIZE)

    def _show_description_override(self, text: str):
        """Briefly replaces the description panel's content with `text`
        (e.g. an unfillable-order error) instead of the selected order's
        message -- reverts on its own after DESCRIPTION_OVERRIDE_DURATION."""
        self.description_override_lines = self._fit_description(text)
        self.description_override_timer = DESCRIPTION_OVERRIDE_DURATION

    # ---- drawing ----

    def on_update(self, delta_time):
        super().on_update(delta_time)
        if self.window.notebook.is_open:
            return
        if self.description_override_timer > 0:
            self.description_override_timer -= delta_time
            if self.description_override_timer <= 0:
                self.description_override_lines = []

    def draw_content(self):
        self.clear()

        hours = self.window.day_manager.hours_into_day(self.window.game_clock)
        self.draw_status_bar(
            clock_time_string(hours),
            f"${self.window.wallet.balance:.2f}",
            calendar_date_string(self.window.day_manager.current_day),
        )

        draw_tab_bar(self.text_pool, "tab", SCREEN_WIDTH / 2, 505,
                     [label for label, _ in TABS], self.tab_index, spacing=320, font_size=14)

        draw_panel(LIST_PANEL)
        draw_multiline_list(LIST_PANEL, self.text_pool, "list", [lines for lines, _ in self.entries],
                             self.cursor_index, ENTRIES_PER_PAGE, LIST_LINE_HEIGHT, LIST_LINES_PER_ENTRY,
                             font_size=LIST_FONT_SIZE, cursor_line=0, line_indents=LIST_LINE_INDENTS)
        draw_page_indicator(self.text_pool, "page", LIST_PANEL.center_x, PAGE_INDICATOR_Y,
                             self.cursor_index, len(self.entries), ENTRIES_PER_PAGE)

        draw_panel(DESCRIPTION_PANEL)
        shown_lines = self.description_override_lines or self.description_lines
        draw_wrapped_lines(DESCRIPTION_PANEL, self.text_pool, "description", shown_lines,
                            DESCRIPTION_LINE_HEIGHT, font_size=DESCRIPTION_FONT_SIZE)

        # font_size=8, smaller than draw_instructions' own default -- the
        # full open-orders line runs past the screen edge at font_size=10.
        if self.mode == "open_orders":
            self.draw_instructions("L/R Arrow: Tabs   U/D Arrow: Scroll   Enter: Ship   ESC: Leave", font_size=8)
        else:
            self.draw_instructions("L/R Arrow: Tabs   U/D Arrow: Scroll   ESC: Leave", font_size=8)
        self.draw_message()

    # ---- input ----

    def handle_content_keys(self, key, modifiers):
        if key == arcade.key.ESCAPE:
            logger.debug("Shipping bench: left the bench, returning to lab floor")
            self.window.show_view(self.lab_view)
            return
        if key == arcade.key.LEFT:
            self._switch_tab((self.tab_index - 1) % len(TABS))
        elif key == arcade.key.RIGHT:
            self._switch_tab((self.tab_index + 1) % len(TABS))
        else:
            self._handle_list_keys(key)

    def _switch_tab(self, new_index):
        self.tab_index = new_index
        _, self.mode = TABS[self.tab_index]
        self.cursor_index = 0
        self._refresh_rows()
        logger.debug("Shipping bench: switched to '%s' tab", self.mode)

    def _handle_list_keys(self, key):
        if key in (arcade.key.UP, arcade.key.W) and self.entries:
            self.cursor_index = (self.cursor_index - 1) % len(self.entries)
            self._refresh_description()
        elif key in (arcade.key.DOWN, arcade.key.S) and self.entries:
            self.cursor_index = (self.cursor_index + 1) % len(self.entries)
            self._refresh_description()
        elif key == arcade.key.ENTER and self.entries and self.mode == "open_orders":
            _, contract = self.entries[self.cursor_index]
            self.try_ship(contract)

    def try_ship(self, contract):
        try:
            self.window.contract_board.ship(contract.contract_id, self.window.chemical_inventory)
        except ValueError as e:
            self.show_message(str(e), arcade.color.RED)
            self._show_description_override(str(e))
            return
        self.cursor_index = 0
        logger.info("Shipped order '%s', $%.2f arriving next morning", contract.subject, contract.reward)
        self.show_message(f"Shipped: {contract.subject} -- ${contract.reward:.2f} arrives next morning",
                           arcade.color.DARK_GREEN)
        self._refresh_rows()
