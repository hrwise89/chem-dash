"""
The shipping bench: hand off product against an open order. Shipping
consumes the required product from inventory right away (crude accepted
unless the order requires pure -- see economy.ContractBoard.ship), but
payment is deferred until the shipment is processed overnight (see
day_manager.py / lab_view.go_home / lab_view.pass_out), so there's always a
one-day gap between shipping an order and getting paid for it.
"""

import arcade

from benches.ui_common import wrap_to_width
from benches.ui_theme import (
    CP437_CURSOR,
    FONT_STACK,
    PANEL_COLOR,
    Panel,
    ThemedBenchView,
    draw_panel,
    draw_scrollbar,
    draw_tab_bar,
    scroll_offset_for_cursor,
    visible_item_count,
    wrapped_item_rows,
)
from day_manager import calendar_date_string, clock_time_string
from devtools import logger
from settings import SCREEN_WIDTH

TABS = [("Open Orders", "open_orders"), ("In Transit", "in_transit")]

LIST_PANEL = Panel(left=40, right=760, bottom=140, top=480)
LIST_FONT_SIZE = 12
LIST_ROW_HEIGHT = 22
LIST_LEFT_MARGIN = 10
LIST_CURSOR_GAP = 8
CURSOR_GLYPH_WIDTH = 18  # CP437_CURSOR's rendered width at LIST_FONT_SIZE
LIST_RIGHT_MARGIN = 10


class ShippingBenchView(ThemedBenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view)
        self.mode = "open_orders"
        self.tab_index = 0
        self.cursor_index = 0
        self.scroll_offset = 0

    # ---- what's in each tab ----

    def current_list(self):
        if self.mode == "open_orders":
            return [(self._open_order_label(c), c) for c in self.window.contract_board.accepted]
        return [(self._in_transit_label(c), c) for c in self.window.contract_board.in_transit]

    def _open_order_label(self, contract) -> str:
        board = self.window.contract_board
        have = board.available_product_moles(contract, self.window.chemical_inventory)
        product_desc = f"pure {contract.product}" if contract.requires_pure else contract.product
        ready = "READY" if have + 1e-9 >= contract.amount else "not enough product"
        return (f"{contract.title} -- need {contract.amount:.2f} mol {product_desc} "
                f"(have {have:.2f} mol) for ${contract.reward:.2f} [{ready}]")

    def _in_transit_label(self, contract) -> str:
        return f"{contract.title} -- ${contract.reward:.2f} arriving next morning"

    # ---- wrap-aware list geometry/scrolling ----

    def _list_max_text_width(self) -> float:
        text_x = LIST_PANEL.left + LIST_LEFT_MARGIN + CURSOR_GLYPH_WIDTH + LIST_CURSOR_GAP
        return LIST_PANEL.right - LIST_RIGHT_MARGIN - text_x

    def _list_max_rows(self) -> int:
        return int(LIST_PANEL.height // LIST_ROW_HEIGHT)

    def _list_row_counts(self, items) -> list[int]:
        return wrapped_item_rows([label for label, _ in items], self._list_max_text_width(), LIST_FONT_SIZE)

    # ---- drawing ----

    def on_draw(self):
        self.clear()

        hours = self.window.day_manager.hours_into_day(self.window.game_clock)
        self.draw_status_bar(
            clock_time_string(hours),
            f"${self.window.wallet.balance:.2f}",
            calendar_date_string(self.window.day_manager.current_day),
        )

        draw_tab_bar(SCREEN_WIDTH / 2, 505, [label for label, _ in TABS], self.tab_index, spacing=340)

        draw_panel(LIST_PANEL)
        items = self.current_list()
        self._draw_list(items)
        row_counts = self._list_row_counts(items)
        visible_count = visible_item_count(row_counts, self.scroll_offset, self._list_max_rows())
        draw_scrollbar(LIST_PANEL, len(items), visible_count, self.scroll_offset)

        if self.mode == "open_orders":
            self.draw_instructions("ARROWS: tabs/browse   ENTER: ship   ESC: leave")
        else:
            self.draw_instructions("ARROWS: tabs/browse   ESC: leave")
        self.draw_message()

    def _draw_list(self, items):
        text_x = LIST_PANEL.left + LIST_LEFT_MARGIN + CURSOR_GLYPH_WIDTH + LIST_CURSOR_GAP
        max_text_width = self._list_max_text_width()

        if not items:
            arcade.Text("(none)", LIST_PANEL.center_x, LIST_PANEL.center_y, PANEL_COLOR,
                        font_size=LIST_FONT_SIZE, font_name=FONT_STACK, anchor_x="center").draw()
            return

        i = self.scroll_offset
        y = LIST_PANEL.top - LIST_ROW_HEIGHT
        while i < len(items) and y > LIST_PANEL.bottom:
            label, _ = items[i]
            lines = wrap_to_width(label, max_text_width, font_size=LIST_FONT_SIZE, font_name=FONT_STACK)
            if i == self.cursor_index:
                arcade.Text(CP437_CURSOR, LIST_PANEL.left + LIST_LEFT_MARGIN, y, PANEL_COLOR,
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
        self.scroll_offset = 0
        logger.debug("Shipping bench: switched to '%s' tab", self.mode)

    def _handle_list_keys(self, key):
        items = self.current_list()
        if key in (arcade.key.UP, arcade.key.W) and items:
            self.cursor_index = (self.cursor_index - 1) % len(items)
            self._scroll_to_show_cursor(items)
        elif key in (arcade.key.DOWN, arcade.key.S) and items:
            self.cursor_index = (self.cursor_index + 1) % len(items)
            self._scroll_to_show_cursor(items)
        elif key == arcade.key.ENTER and items and self.mode == "open_orders":
            _, contract = items[self.cursor_index]
            self.try_ship(contract)

    def _scroll_to_show_cursor(self, items):
        row_counts = self._list_row_counts(items)
        self.scroll_offset = scroll_offset_for_cursor(
            row_counts, self.cursor_index, self.scroll_offset, self._list_max_rows())

    def try_ship(self, contract):
        try:
            self.window.contract_board.ship(contract.contract_id, self.window.chemical_inventory)
        except ValueError as e:
            self.show_message(str(e), arcade.color.RED)
            return
        self.cursor_index = 0
        self.scroll_offset = 0
        logger.info("Shipped order '%s', $%.2f arriving next morning", contract.title, contract.reward)
        self.show_message(f"Shipped: {contract.title} -- ${contract.reward:.2f} arrives next morning",
                           arcade.color.DARK_GREEN)
