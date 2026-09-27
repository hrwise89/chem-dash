"""
The computer bench: order reagents/equipment/consumables from the
catalogue, and browse/accept/reject contract offers ("orders"). Once
accepted, an order becomes an open order tracked in the reaction bench's
notebook -- shipping (and payment) happens at the shipping bench, not here.
"""

from typing import ClassVar

import arcade

from benches.ui_common import BenchView
from devtools import logger
from economy import InsufficientFundsError, buy_chemical, buy_consumable, buy_equipment

# Fixed lot size for a chemical/consumable catalogue purchase -- a simple
# starting economy (native units: mL for a liquid/solution, g for a
# solid), not meant to be the final balance. Equipment is bought one unit
# at a time instead (see try_buy_equipment).
BUY_LOT_SIZE = 50.0

# The catalogue is one bench section with its own tab menu, rather than
# three separate top-level sections -- (tab label, internal mode) pairs.
CATALOGUE_TABS = [
    ("Reagents", "catalogue_reagents"),
    ("Equipment", "catalogue_equipment"),
    ("Consumables", "catalogue_consumables"),
]


class ComputerBenchView(BenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view, title="Computer")
        # "overview" | "catalogue" | "catalogue_reagents" |
        # "catalogue_equipment" | "catalogue_consumables" | "offers"
        # ("catalogue" is a tab menu over the three catalogue_* modes.)
        self.mode = "overview"
        self.sections = ["catalogue", "offers"]

    # ---- what's in each section ----

    def current_list(self):
        if self.mode == "catalogue_reagents":
            return self._reagent_rows()
        if self.mode == "catalogue_equipment":
            return self._equipment_rows()
        if self.mode == "catalogue_consumables":
            return self._consumable_rows()
        if self.mode == "offers":
            return [(self._offer_label(c), c) for c in self.window.contract_board.available]
        return []

    def _reagent_rows(self):
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

    def _equipment_rows(self):
        equipment = self.window.equipment_inventory
        rows = []
        for name, entry in self.window.equipment_catalog.items():
            if entry.price is None:
                continue  # not sold in the catalogue
            own = sum(1 for item in equipment.items.values() if item.type == entry.type)
            capacity_desc = f", {entry.capacity:.0f} mL" if entry.capacity is not None else ""
            label = f"{name}{capacity_desc} -- ${entry.price:.2f} (own: {own})"
            rows.append((label, entry))
        return rows

    def _consumable_rows(self):
        consumables = self.window.consumables
        rows = []
        for name, entry in self.window.consumable_catalog.items():
            if entry.price is None:
                continue  # not sold in the catalogue
            lot_cost = entry.price * BUY_LOT_SIZE
            have = consumables.contents.get(name, 0.0)
            label = (f"{name} -- ${entry.price:.2f}/{entry.unit}, "
                     f"buy {BUY_LOT_SIZE:.0f} {entry.unit} for ${lot_cost:.2f} "
                     f"(have {have:.1f} {entry.unit})")
            rows.append((label, entry))
        return rows

    def _offer_label(self, contract) -> str:
        product_desc = f"pure {contract.product}" if contract.requires_pure else contract.product
        return f"{contract.title} -- deliver {contract.amount:.2f} mol {product_desc} for ${contract.reward:.2f}"

    # ---- drawing ----

    def on_draw(self):
        self.clear()
        self.draw_bench()

        if self.mode == "overview":
            self.draw_overview()
        elif self.mode == "catalogue":
            self.draw_catalogue_tabs()
        else:
            self.draw_section()

        self.draw_message()

    def _title_with_balance(self, label: str) -> str:
        return f"{label}  (${self.window.wallet.balance:.2f})"

    def draw_overview(self):
        self.draw_title(self._title_with_balance("Computer"))
        self.draw_centered_menu([(section, True) for section in self.sections])
        self.draw_instructions("UP/DOWN to choose, ENTER to select, ESC to leave bench")

    def draw_catalogue_tabs(self):
        self.draw_title(self._title_with_balance("Catalogue"))
        self.draw_centered_menu([(label, True) for label, _ in CATALOGUE_TABS])
        self.draw_instructions("UP/DOWN to choose, ENTER to select, ESC to go back")

    _SECTION_TITLES: ClassVar[dict[str, str]] = {
        "catalogue_reagents": "REAGENTS",
        "catalogue_equipment": "EQUIPMENT",
        "catalogue_consumables": "CONSUMABLES",
    }

    def draw_section(self):
        title = self._SECTION_TITLES.get(self.mode, self.mode.upper())
        self.draw_title(self._title_with_balance(title))
        items = self.current_list()
        self.draw_scrollable_list([label for label, _ in items])

        if self.mode.startswith("catalogue_"):
            self.draw_instructions("UP/DOWN to browse, ENTER to buy, ESC to go back")
        elif self.mode == "offers":
            self.draw_instructions("UP/DOWN to browse, ENTER to accept, R to reject, ESC to go back")
        else:
            self.draw_instructions("UP/DOWN to browse, ESC to go back")

    # ---- input ----

    def on_key_press(self, key, modifiers):
        if self.mode == "overview":
            self.handle_overview_keys(key)
        elif self.mode == "catalogue":
            self.handle_catalogue_tab_keys(key)
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

    def handle_catalogue_tab_keys(self, key):
        if key in (arcade.key.UP, arcade.key.W):
            self.cursor_index = (self.cursor_index - 1) % len(CATALOGUE_TABS)
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.cursor_index = (self.cursor_index + 1) % len(CATALOGUE_TABS)
        elif key in (arcade.key.ENTER, arcade.key.SPACE):
            _, self.mode = CATALOGUE_TABS[self.cursor_index]
            self.reset_cursor()
            logger.debug("Computer bench: entered catalogue tab '%s'", self.mode)
        elif key == arcade.key.ESCAPE:
            self.mode = "overview"
            self.reset_cursor()

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
            logger.debug("Computer bench: back from '%s'", self.mode)
            if self.mode.startswith("catalogue_"):
                self.mode = "catalogue"
            else:
                self.mode = "overview"
            self.reset_cursor()

    def activate_selected(self, selected):
        _, obj = selected
        if self.mode == "catalogue_reagents":
            self.try_buy_reagent(obj)
        elif self.mode == "catalogue_equipment":
            self.try_buy_equipment(obj)
        elif self.mode == "catalogue_consumables":
            self.try_buy_consumable(obj)
        elif self.mode == "offers":
            self.try_accept(obj)

    def try_buy_reagent(self, name: str):
        inventory = self.window.chemical_inventory
        try:
            cost = buy_chemical(inventory, self.window.wallet, name, BUY_LOT_SIZE)
        except InsufficientFundsError as e:
            self.show_message(str(e), arcade.color.RED)
            return
        unit = inventory.species_for(name).unit_label()
        logger.info("Bought %.1f %s of '%s' for $%.2f", BUY_LOT_SIZE, unit, name, cost)
        self.show_message(f"Bought {BUY_LOT_SIZE:.0f} {unit} {name} for ${cost:.2f}", arcade.color.DARK_GREEN)

    def try_buy_equipment(self, entry):
        try:
            cost = buy_equipment(self.window.equipment_inventory, self.window.wallet, entry)
        except InsufficientFundsError as e:
            self.show_message(str(e), arcade.color.RED)
            return
        logger.info("Bought '%s' for $%.2f", entry.name, cost)
        self.show_message(f"Bought {entry.name} for ${cost:.2f}", arcade.color.DARK_GREEN)

    def try_buy_consumable(self, entry):
        try:
            cost = buy_consumable(self.window.consumables, self.window.wallet, entry, BUY_LOT_SIZE)
        except InsufficientFundsError as e:
            self.show_message(str(e), arcade.color.RED)
            return
        logger.info("Bought %.1f %s of '%s' for $%.2f", BUY_LOT_SIZE, entry.unit, entry.name, cost)
        self.show_message(f"Bought {BUY_LOT_SIZE:.0f} {entry.unit} {entry.name} for ${cost:.2f}",
                           arcade.color.DARK_GREEN)

    def try_accept(self, contract):
        self.window.contract_board.accept(contract.contract_id)
        self.reset_cursor()
        logger.info("Accepted contract '%s'", contract.title)
        self.show_message(f"Accepted: {contract.title} -- check the notebook for open orders", arcade.color.DARK_GREEN)
