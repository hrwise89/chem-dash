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

Each order is a fixed 2-line entry -- just the type symbol, the chemical
(short name, "(P)" suffixed if it requires purity), amount, and reward on
the first line, sender on the second -- not sender/subject/message, which
only show in the description panel below for whichever entry the cursor
is on. Both the row list and the description are rebuilt only when they
can actually change -- entering the bench, switching tabs, moving the
cursor, or shipping -- not on every draw call, since nothing here changes
on its own between those moments.
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
)
from day_manager import calendar_date_string, clock_time_string
from devtools import logger
from settings import SCREEN_WIDTH

# "In Transit" is renamed "Awaiting pickup" -- eventually this tab will
# also show a per-order pickup marker ("picking up (morning)" / "picked
# up (afternoon)") once the twice-daily pickup mechanic exists, but that
# backend doesn't exist yet, so there's nothing real to display for it.
TABS = [("Open Orders", "open_orders"), ("Awaiting pickup", "in_transit")]

LIST_PANEL = Panel(left=40, right=760, bottom=160, top=480)
LIST_FONT_SIZE = 10
LIST_LINE_HEIGHT = 20
LIST_LINES_PER_ENTRY = 2
LIST_ENTRY_HEIGHT = LIST_LINE_HEIGHT * LIST_LINES_PER_ENTRY
# The page indicator lives inside LIST_PANEL now (not below/outside it),
# so its own line's height is reserved here too, trading a bit of visible
# rows for not floating a page number outside the content area.
PAGE_INDICATOR_MARGIN = 26
ENTRIES_PER_PAGE = max(1, int((LIST_PANEL.height - PAGE_INDICATOR_MARGIN) // LIST_ENTRY_HEIGHT))
PAGE_INDICATOR_Y = LIST_PANEL.bottom + 12

DESCRIPTION_PANEL = Panel(left=40, right=760, bottom=100, top=150)
DESCRIPTION_FONT_SIZE = 12


class ShippingBenchView(ThemedBenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view)
        self.mode = "open_orders"
        self.tab_index = 0
        self.cursor_index = 0
        self.entries = []       # [([line1, line2], contract), ...] for the current tab
        self.description = ""   # the cursor-selected entry's full message
        self._refresh_rows()

    # ---- row/description content (only rebuilt when it can change) ----

    def _summary_line(self, contract) -> str:
        purity_tag = " (P)" if contract.requires_purity else ""
        return (f"[{contract.order_type_letter}] {contract.product_short_name}{purity_tag}  "
                f"x{contract.amount:.2f}   ${contract.reward:.2f}")

    def _fit_line(self, key: str, text: str, max_width: float, font_size: int) -> str:
        """One-time (per rebuild) truncation to a single line -- rows are
        only rebuilt on real state changes (see class docstring), so this
        cost is paid once per rebuild, not once per frame."""
        probe = self.text_pool.get(key, text, 0, 0, PANEL_COLOR, font_size=font_size, font_name=FONT_STACK)
        while probe.content_width > max_width and len(text) > 1:
            text = text[:-1]
            probe.text = text + "..."
        return probe.text

    def _entry_lines(self, contract) -> list[str]:
        max_width = LIST_PANEL.width - 60  # leaves room for the cursor glyph + left margin
        return [
            self._fit_line("_probe_summary", self._summary_line(contract), max_width, LIST_FONT_SIZE),
            self._fit_line("_probe_sender", contract.sender, max_width, LIST_FONT_SIZE),
        ]

    def _open_order_description(self, contract) -> str:
        board = self.window.contract_board
        have = board.available_product_moles(contract, self.window.chemical_inventory)
        ready = "READY" if have + 1e-9 >= contract.amount else "not enough product yet"
        return f"{contract.sender}: {contract.message} (${contract.reward:.2f}) [{ready}]"

    def _in_transit_description(self, contract) -> str:
        return f"{contract.sender}: {contract.message} (${contract.reward:.2f} arriving next morning)"

    def _refresh_rows(self):
        pool = self.window.contract_board.accepted if self.mode == "open_orders" \
            else self.window.contract_board.in_transit
        self.entries = [(self._entry_lines(c), c) for c in pool]
        self.cursor_index = min(self.cursor_index, max(0, len(self.entries) - 1))
        self._refresh_description()

    def _refresh_description(self):
        if not self.entries:
            self.description = ""
            return
        _, contract = self.entries[self.cursor_index]
        text = (self._open_order_description(contract) if self.mode == "open_orders"
                else self._in_transit_description(contract))
        self.description = self._fit_description(text)

    def _fit_description(self, text: str) -> str:
        probe = self.text_pool.get("description", text, 0, 0, PANEL_COLOR,
                                    font_size=DESCRIPTION_FONT_SIZE, font_name=FONT_STACK)
        max_width = DESCRIPTION_PANEL.width - 20
        while probe.content_width > max_width and len(text) > 1:
            text = text[:-1]
            probe.text = text + "..."
        return probe.text

    # ---- drawing ----

    def on_draw(self):
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
                             font_size=LIST_FONT_SIZE)
        draw_page_indicator(self.text_pool, "page", LIST_PANEL.center_x, PAGE_INDICATOR_Y,
                             self.cursor_index, len(self.entries), ENTRIES_PER_PAGE)

        draw_panel(DESCRIPTION_PANEL)
        if self.description:
            self.text_pool.get("description", self.description, DESCRIPTION_PANEL.center_x,
                                DESCRIPTION_PANEL.center_y, PANEL_COLOR, font_size=DESCRIPTION_FONT_SIZE,
                                font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()

        if self.mode == "open_orders":
            self.draw_instructions("ARROWS: tabs/browse   ENTER: ship   ESC: leave")
        else:
            self.draw_instructions("ARROWS: tabs/browse   ESC: leave")
        self.draw_message()

    # ---- input ----

    def on_key_press(self, key, modifiers):
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
            return
        self.cursor_index = 0
        logger.info("Shipped order '%s', $%.2f arriving next morning", contract.subject, contract.reward)
        self.show_message(f"Shipped: {contract.subject} -- ${contract.reward:.2f} arrives next morning",
                           arcade.color.DARK_GREEN)
        self._refresh_rows()
