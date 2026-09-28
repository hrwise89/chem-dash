"""
The shipping bench: hand off product against an open order. Shipping
consumes the required product from inventory right away (crude accepted
unless the order requires pure -- see economy.ContractBoard.ship), but
payment is deferred until the shipment is processed overnight (see
day_manager.py / lab_view.go_home / lab_view.pass_out), so there's always a
one-day gap between shipping an order and getting paid for it.

List rows show each contract's short display_name only; full details for
whichever row the cursor is on show in the description panel below the
list (see economy.Contract.display_name). Both the row list and the
description are rebuilt only when they can actually change -- entering
the bench, switching tabs, moving the cursor, or shipping -- not on every
draw call, since nothing here changes on its own between those moments.
"""

import arcade

from benches.ui_theme import (
    FONT_STACK,
    PANEL_COLOR,
    Panel,
    ThemedBenchView,
    draw_fixed_list,
    draw_page_indicator,
    draw_panel,
    draw_tab_bar,
)
from day_manager import calendar_date_string, clock_time_string
from devtools import logger
from settings import SCREEN_WIDTH

TABS = [("Open Orders", "open_orders"), ("In Transit", "in_transit")]

LIST_PANEL = Panel(left=40, right=760, bottom=220, top=480)
LIST_FONT_SIZE = 12
LIST_ROW_HEIGHT = 22
LIST_BOTTOM_MARGIN = 20  # keeps the last row clear of the panel border
ROWS_PER_PAGE = int((LIST_PANEL.height - LIST_BOTTOM_MARGIN) // LIST_ROW_HEIGHT)

PAGE_INDICATOR_Y = 202

DESCRIPTION_PANEL = Panel(left=40, right=760, bottom=140, top=185)
DESCRIPTION_FONT_SIZE = 12


class ShippingBenchView(ThemedBenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view)
        self.mode = "open_orders"
        self.tab_index = 0
        self.cursor_index = 0
        self.rows = []          # [(short_label, contract), ...] for the current tab
        self.description = ""   # the cursor-selected row's full detail line
        self._refresh_rows()

    # ---- row/description content (only rebuilt when it can change) ----

    def _open_order_row(self, contract) -> str:
        have = self.window.contract_board.available_product_moles(contract, self.window.chemical_inventory)
        status = "READY" if have + 1e-9 >= contract.amount else "WAIT"
        return f"{contract.display_name} - ${contract.reward:.0f} [{status}]"

    def _open_order_description(self, contract) -> str:
        board = self.window.contract_board
        have = board.available_product_moles(contract, self.window.chemical_inventory)
        product_desc = f"pure {contract.product}" if contract.requires_pure else contract.product
        ready = "READY" if have + 1e-9 >= contract.amount else "not enough product"
        return (f"{contract.title} -- need {contract.amount:.2f} mol {product_desc} "
                f"(have {have:.2f} mol) for ${contract.reward:.2f} [{ready}]")

    def _in_transit_row(self, contract) -> str:
        return f"{contract.display_name} - ${contract.reward:.0f}"

    def _in_transit_description(self, contract) -> str:
        return f"{contract.title} -- ${contract.reward:.2f} arriving next morning"

    def _refresh_rows(self):
        if self.mode == "open_orders":
            self.rows = [(self._open_order_row(c), c) for c in self.window.contract_board.accepted]
        else:
            self.rows = [(self._in_transit_row(c), c) for c in self.window.contract_board.in_transit]
        self.cursor_index = min(self.cursor_index, max(0, len(self.rows) - 1))
        self._refresh_description()

    def _refresh_description(self):
        if not self.rows:
            self.description = ""
            return
        _, contract = self.rows[self.cursor_index]
        text = (self._open_order_description(contract) if self.mode == "open_orders"
                else self._in_transit_description(contract))
        self.description = self._fit_description(text)

    def _fit_description(self, text: str) -> str:
        """One-time (per selection change) truncation to a single line --
        the description is built from a live contract title/amount with
        no fixed length to just shorten, but it's cached here rather than
        re-measured every frame."""
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
                     [label for label, _ in TABS], self.tab_index, spacing=340)

        draw_panel(LIST_PANEL)
        draw_fixed_list(LIST_PANEL, self.text_pool, "list", [label for label, _ in self.rows],
                         self.cursor_index, ROWS_PER_PAGE, LIST_ROW_HEIGHT, font_size=LIST_FONT_SIZE)
        draw_page_indicator(self.text_pool, "page", LIST_PANEL.center_x, PAGE_INDICATOR_Y,
                             self.cursor_index, len(self.rows), ROWS_PER_PAGE)

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
        if key in (arcade.key.UP, arcade.key.W) and self.rows:
            self.cursor_index = (self.cursor_index - 1) % len(self.rows)
            self._refresh_description()
        elif key in (arcade.key.DOWN, arcade.key.S) and self.rows:
            self.cursor_index = (self.cursor_index + 1) % len(self.rows)
            self._refresh_description()
        elif key == arcade.key.ENTER and self.rows and self.mode == "open_orders":
            _, contract = self.rows[self.cursor_index]
            self.try_ship(contract)

    def try_ship(self, contract):
        try:
            self.window.contract_board.ship(contract.contract_id, self.window.chemical_inventory)
        except ValueError as e:
            self.show_message(str(e), arcade.color.RED)
            return
        self.cursor_index = 0
        logger.info("Shipped order '%s', $%.2f arriving next morning", contract.title, contract.reward)
        self.show_message(f"Shipped: {contract.title} -- ${contract.reward:.2f} arrives next morning",
                           arcade.color.DARK_GREEN)
        self._refresh_rows()
