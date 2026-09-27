"""
The shipping bench: hand off product against an open order. Shipping
consumes the required product from inventory right away (crude accepted
unless the order requires pure -- see economy.ContractBoard.ship), but
payment is deferred until the shipment is processed overnight (see
day_manager.py / lab_view.go_home / lab_view.pass_out), so there's always a
one-day gap between shipping an order and getting paid for it.
"""

import arcade

from benches.ui_common import BenchView
from devtools import logger


class ShippingBenchView(BenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view, title="Shipping")
        # "overview" | "open_orders" | "in_transit"
        self.mode = "overview"
        self.sections = ["open_orders", "in_transit"]

    # ---- what's in each section ----

    def current_list(self):
        if self.mode == "open_orders":
            return [(self._open_order_label(c), c) for c in self.window.contract_board.accepted]
        if self.mode == "in_transit":
            return [(self._in_transit_label(c), c) for c in self.window.contract_board.in_transit]
        return []

    def _open_order_label(self, contract) -> str:
        board = self.window.contract_board
        have = board.available_product_moles(contract, self.window.chemical_inventory)
        product_desc = f"pure {contract.product}" if contract.requires_pure else contract.product
        ready = "READY" if have + 1e-9 >= contract.amount else "not enough product"
        return (f"{contract.title} -- need {contract.amount:.2f} mol {product_desc} "
                f"(have {have:.2f} mol) for ${contract.reward:.2f} [{ready}]")

    def _in_transit_label(self, contract) -> str:
        return f"{contract.title} -- ${contract.reward:.2f} arriving next morning"

    # ---- drawing ----

    def on_draw(self):
        self.clear()
        self.draw_bench()

        if self.mode == "overview":
            self.draw_overview()
        else:
            self.draw_section()

        self.draw_message()

    def draw_overview(self):
        self.draw_title("Shipping")
        self.draw_centered_menu([(section, True) for section in self.sections])
        self.draw_instructions("UP/DOWN to choose, ENTER to select, ESC to leave bench")

    def draw_section(self):
        self.draw_title(self.mode.replace("_", " ").upper())
        items = self.current_list()
        self.draw_scrollable_list([label for label, _ in items])

        if self.mode == "open_orders":
            self.draw_instructions("UP/DOWN to browse, ENTER to ship, ESC to go back")
        else:
            self.draw_instructions("UP/DOWN to browse, ESC to go back")

    # ---- input ----

    def on_key_press(self, key, modifiers):
        if self.mode == "overview":
            self.handle_overview_keys(key)
        else:
            self.handle_section_keys(key)

    def handle_overview_keys(self, key):
        if key in (arcade.key.UP, arcade.key.W):
            self.cursor_index = (self.cursor_index - 1) % len(self.sections)
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.cursor_index = (self.cursor_index + 1) % len(self.sections)
        elif key in (arcade.key.ENTER, arcade.key.SPACE):
            self.mode = self.sections[self.cursor_index]
            self.reset_cursor()
            logger.debug("Shipping bench: entered '%s' section", self.mode)
        elif key == arcade.key.ESCAPE:
            logger.debug("Shipping bench: left the bench, returning to lab floor")
            self.window.show_view(self.lab_view)

    def handle_section_keys(self, key):
        items = self.current_list()
        if key in (arcade.key.UP, arcade.key.W) and items:
            self.cursor_index = (self.cursor_index - 1) % len(items)
            self.scroll_to_show_cursor()
        elif key in (arcade.key.DOWN, arcade.key.S) and items:
            self.cursor_index = (self.cursor_index + 1) % len(items)
            self.scroll_to_show_cursor()
        elif key == arcade.key.ENTER and items and self.mode == "open_orders":
            _, contract = items[self.cursor_index]
            self.try_ship(contract)
        elif key == arcade.key.ESCAPE:
            logger.debug("Shipping bench: back to overview from '%s'", self.mode)
            self.mode = "overview"
            self.reset_cursor()

    def try_ship(self, contract):
        try:
            self.window.contract_board.ship(contract.contract_id, self.window.chemical_inventory)
        except ValueError as e:
            self.show_message(str(e), arcade.color.RED)
            return
        self.reset_cursor()
        logger.info("Shipped order '%s', $%.2f arriving next morning", contract.title, contract.reward)
        self.show_message(f"Shipped: {contract.title} -- ${contract.reward:.2f} arrives next morning",
                           arcade.color.DARK_GREEN)
