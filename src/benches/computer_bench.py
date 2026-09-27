"""
The computer bench: order chemicals from the catalogue, and browse/accept/
fulfill contracts ("orders") for products the player can already produce.
"""

import arcade

from benches.ui_common import BenchView
from devtools import logger
from economy import InsufficientFundsError, buy_chemical

# Fixed lot size for a catalogue purchase -- a simple starting economy
# (native units: mL for a liquid/solution, g for a solid), not meant to be
# the final balance.
BUY_LOT_SIZE = 50.0


class ComputerBenchView(BenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view, title="Computer")
        # "overview" | "catalogue" | "offers" | "accepted"
        self.mode = "overview"
        self.sections = ["catalogue", "offers", "accepted"]

    # ---- what's in each section ----

    def current_list(self):
        if self.mode == "catalogue":
            return self._catalogue_rows()
        if self.mode == "offers":
            return [(self._offer_label(c), c) for c in self.window.contract_board.available]
        if self.mode == "accepted":
            return [(self._accepted_label(c), c) for c in self.window.contract_board.accepted]
        return []

    def _catalogue_rows(self):
        inventory = self.window.chemical_inventory
        rows = []
        for name, species in inventory.species_catalog.items():
            if species.price_per_unit is None:
                continue  # not sold in the catalogue (e.g. a product the player makes)
            unit = species.unit_label()
            lot_cost = species.price_per_unit * BUY_LOT_SIZE
            label = (f"{name} -- ${species.price_per_unit:.2f}/{unit}, "
                     f"buy {BUY_LOT_SIZE:.0f} {unit} for ${lot_cost:.2f} "
                     f"(have {inventory.describe(name)})")
            rows.append((label, name))
        return rows

    def _offer_label(self, contract) -> str:
        return f"{contract.title} -- deliver {contract.amount:.2f} mol {contract.product} for ${contract.reward:.2f}"

    def _accepted_label(self, contract) -> str:
        have = self.window.chemical_inventory.available_moles(contract.product)
        return (f"{contract.title} -- need {contract.amount:.2f} mol {contract.product} "
                f"(have {have:.2f} mol) for ${contract.reward:.2f}")

    # ---- drawing ----

    def on_draw(self):
        self.clear()
        self.draw_bench()

        if self.mode == "overview":
            self.draw_overview()
        else:
            self.draw_section()

        self.draw_message()

    def _title_with_balance(self, label: str) -> str:
        return f"{label}  (${self.window.wallet.balance:.2f})"

    def draw_overview(self):
        self.draw_title(self._title_with_balance("Computer"))
        self.draw_centered_menu([(section, True) for section in self.sections])
        self.draw_instructions("UP/DOWN to choose, ENTER to select, ESC to leave bench")

    def draw_section(self):
        self.draw_title(self._title_with_balance(self.mode.upper()))
        items = self.current_list()
        self.draw_scrollable_list([label for label, _ in items])

        if self.mode == "catalogue":
            self.draw_instructions("UP/DOWN to browse, ENTER to buy, ESC to go back")
        elif self.mode == "offers":
            self.draw_instructions("UP/DOWN to browse, ENTER to accept, R to reject, ESC to go back")
        elif self.mode == "accepted":
            self.draw_instructions("UP/DOWN to browse, ENTER to deliver, ESC to go back")
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
            logger.debug("Computer bench: entered '%s' section", self.mode)
        elif key == arcade.key.ESCAPE:
            logger.debug("Computer bench: left the bench, returning to lab floor")
            self.window.show_view(self.lab_view)

    def handle_section_keys(self, key):
        items = self.current_list()
        if key in (arcade.key.UP, arcade.key.W) and items:
            self.cursor_index = (self.cursor_index - 1) % len(items)
            self.scroll_to_show_cursor()
        elif key in (arcade.key.DOWN, arcade.key.S) and items:
            self.cursor_index = (self.cursor_index + 1) % len(items)
            self.scroll_to_show_cursor()
        elif key == arcade.key.ENTER and items:
            self.activate_selected(items[self.cursor_index])
        elif key == arcade.key.R and self.mode == "offers" and items:
            _, contract = items[self.cursor_index]
            self.window.contract_board.reject(contract.contract_id)
            self.reset_cursor()
            self.show_message(f"Rejected: {contract.title}", arcade.color.DARK_YELLOW)
        elif key == arcade.key.ESCAPE:
            logger.debug("Computer bench: back to overview from '%s'", self.mode)
            self.mode = "overview"
            self.reset_cursor()

    def activate_selected(self, selected):
        _, obj = selected
        if self.mode == "catalogue":
            self.try_buy(obj)
        elif self.mode == "offers":
            self.try_accept(obj)
        elif self.mode == "accepted":
            self.try_fulfill(obj)

    def try_buy(self, name: str):
        inventory = self.window.chemical_inventory
        try:
            cost = buy_chemical(inventory, self.window.wallet, name, BUY_LOT_SIZE)
        except InsufficientFundsError as e:
            self.show_message(str(e), arcade.color.RED)
            return
        unit = inventory.species_for(name).unit_label()
        logger.info("Bought %.1f %s of '%s' for $%.2f", BUY_LOT_SIZE, unit, name, cost)
        self.show_message(f"Bought {BUY_LOT_SIZE:.0f} {unit} {name} for ${cost:.2f}", arcade.color.DARK_GREEN)

    def try_accept(self, contract):
        self.window.contract_board.accept(contract.contract_id)
        self.reset_cursor()
        logger.info("Accepted contract '%s'", contract.title)
        self.show_message(f"Accepted: {contract.title}", arcade.color.DARK_GREEN)

    def try_fulfill(self, contract):
        try:
            self.window.contract_board.fulfill(contract.contract_id, self.window.chemical_inventory, self.window.wallet)
        except ValueError as e:
            self.show_message(str(e), arcade.color.RED)
            return
        self.reset_cursor()
        logger.info("Fulfilled contract '%s' for $%.2f", contract.title, contract.reward)
        self.show_message(f"Delivered: {contract.title} (+${contract.reward:.2f})", arcade.color.DARK_GREEN)
