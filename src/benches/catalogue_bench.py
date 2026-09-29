"""
The catalogue: buy equipment, reagents, and consumables. Reached from the
computer bench's 6-panel menu (see computer_bench.py) -- laid out per the
"Equipment / Reagents / Consumables" mockup: a tab bar, a price list on
the left, an icon panel for the selected item on the right, and a
description panel below explaining it.

Rows/description are rebuilt only when they can change -- entering the
bench, switching tabs, moving the cursor, or buying -- not on every draw
call, matching shipping_bench.py's/ui_theme.py's performance rules (see
those docstrings for why: rebuilding per frame, or re-truncating text
with a naive per-character scan, measurably costs real keypress latency).
"""

import arcade

from benches.ui_theme import (
    FONT_STACK,
    PANEL_COLOR,
    Panel,
    ThemedBenchView,
    draw_fixed_list,
    draw_icon_panel,
    draw_page_indicator,
    draw_panel,
    draw_tab_bar,
    draw_wrapped_lines,
    truncate_to_width,
    wrap_and_fit,
)
from day_manager import calendar_date_string, clock_time_string
from devtools import logger
from economy import InsufficientFundsError, buy_chemical, buy_consumable, buy_equipment
from settings import SCREEN_WIDTH

# Fixed lot size for a chemical/consumable purchase (native units: mL for
# a liquid/solution, g for a solid) -- a simple starting economy, not
# meant to be the final balance. Equipment is bought one unit at a time.
BUY_LOT_SIZE = 50.0

TABS = [("Equipment", "equipment"), ("Reagents", "reagents"), ("Consumables", "consumables")]

LIST_PANEL = Panel(left=40, right=540, bottom=220, top=480)
ICON_PANEL = Panel(left=560, right=760, bottom=220, top=480)
LIST_FONT_SIZE = 10
LIST_ROW_HEIGHT = 22
LIST_BOTTOM_MARGIN = 36  # room for the page indicator inside the panel
ROWS_PER_PAGE = max(1, int((LIST_PANEL.height - LIST_BOTTOM_MARGIN) // LIST_ROW_HEIGHT))
PAGE_INDICATOR_Y = LIST_PANEL.bottom + 12

DESCRIPTION_PANEL = Panel(left=40, right=760, bottom=90, top=200)
DESCRIPTION_FONT_SIZE = 10
DESCRIPTION_LINE_HEIGHT = 20
DESCRIPTION_MAX_LINES = max(1, int((DESCRIPTION_PANEL.height - 10) // DESCRIPTION_LINE_HEIGHT))

NO_DESCRIPTION = "No description available."


class CatalogueBenchView(ThemedBenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view)
        self.tab_index = 0
        self.mode = "equipment"
        self.cursor_index = 0
        self.rows = []              # [(label, item), ...] for the current tab
        self.description_lines = []
        self._refresh_rows()

    # ---- what's in each tab ----

    def _equipment_items(self):
        return [entry for entry in self.window.equipment_catalog.values() if entry.price is not None]

    def _reagent_items(self):
        inventory = self.window.chemical_inventory
        return [(name, species) for name, species in inventory.species_catalog.items()
                if species.price_per_unit is not None]

    def _consumable_items(self):
        return [entry for entry in self.window.consumable_catalog.values() if entry.price is not None]

    def _equipment_row(self, entry) -> str:
        # entry.display_name already encodes capacity for a vessel (its
        # short_name, e.g. "RBF 250mL") -- no separate capacity suffix.
        return f"{entry.display_name} - ${entry.price:.2f}"

    def _equipment_description(self, entry) -> str:
        owned = sum(1 for item in self.window.equipment_inventory.items.values() if item.type == entry.type)
        return f"{entry.description or NO_DESCRIPTION} Price: ${entry.price:.2f}. Owned: {owned}."

    def _reagent_row(self, name, species) -> str:
        return f"{species.display_name} - ${species.price_per_unit:.2f}/{species.unit_label()}"

    def _reagent_description(self, name, species) -> str:
        inventory = self.window.chemical_inventory
        unit = species.unit_label()
        lot_cost = species.price_per_unit * BUY_LOT_SIZE
        return (f"{species.description or NO_DESCRIPTION} Buy {BUY_LOT_SIZE:.0f} {unit} for ${lot_cost:.2f} "
                f"(have {inventory.describe(name)}).")

    def _consumable_row(self, entry) -> str:
        return f"{entry.display_name} - ${entry.price:.2f}/{entry.unit}"

    def _consumable_description(self, entry) -> str:
        have = self.window.consumables.contents.get(entry.name, 0.0)
        lot_cost = entry.price * BUY_LOT_SIZE
        return (f"{entry.description or NO_DESCRIPTION} Buy {BUY_LOT_SIZE:.0f} {entry.unit} for ${lot_cost:.2f} "
                f"(have {have:.1f} {entry.unit}).")

    def _sprite_key_for(self, item) -> str | None:
        """Equipment shares its manifest key with its `type` (see
        sprites.json/equipment.json) -- reagents/consumables have no art
        yet, so this returns None for them and draw_icon_panel falls back
        to a placeholder box."""
        return getattr(item, "type", None)

    def _refresh_rows(self):
        if self.mode == "equipment":
            items = self._equipment_items()
            labels = [self._equipment_row(e) for e in items]
            objs = items
        elif self.mode == "reagents":
            items = self._reagent_items()
            labels = [self._reagent_row(n, s) for n, s in items]
            objs = items
        else:
            items = self._consumable_items()
            labels = [self._consumable_row(e) for e in items]
            objs = items

        max_width = LIST_PANEL.width - 60  # leaves room for the cursor glyph + left margin
        probe = self.text_pool.get("_probe_row", "", 0, 0, PANEL_COLOR,
                                    font_size=LIST_FONT_SIZE, font_name=FONT_STACK)
        self.rows = [(truncate_to_width(probe, label, max_width), obj) for label, obj in zip(labels, objs)]
        self.cursor_index = min(self.cursor_index, max(0, len(self.rows) - 1))
        self._refresh_description()

    def _refresh_description(self):
        if not self.rows:
            self.description_lines = []
            return
        _, item = self.rows[self.cursor_index]
        if self.mode == "equipment":
            text = self._equipment_description(item)
        elif self.mode == "reagents":
            text = self._reagent_description(*item)
        else:
            text = self._consumable_description(item)
        probe = self.text_pool.get("_probe_description", "", 0, 0, PANEL_COLOR,
                                    font_size=DESCRIPTION_FONT_SIZE, font_name=FONT_STACK)
        max_width = DESCRIPTION_PANEL.width - 20
        self.description_lines = wrap_and_fit(probe, text, max_width, DESCRIPTION_MAX_LINES,
                                               font_size=DESCRIPTION_FONT_SIZE)

    # ---- drawing ----

    def draw_content(self):
        self.clear()

        hours = self.window.day_manager.hours_into_day(self.window.game_clock)
        self.draw_status_bar(
            clock_time_string(hours),
            f"${self.window.wallet.balance:.2f}",
            calendar_date_string(self.window.day_manager.current_day),
        )

        draw_tab_bar(self.text_pool, "tab", SCREEN_WIDTH / 2, 505,
                     [label for label, _ in TABS], self.tab_index, spacing=260, font_size=16)

        draw_panel(LIST_PANEL)
        draw_fixed_list(LIST_PANEL, self.text_pool, "list", [label for label, _ in self.rows],
                         self.cursor_index, ROWS_PER_PAGE, LIST_ROW_HEIGHT, font_size=LIST_FONT_SIZE)
        draw_page_indicator(self.text_pool, "page", LIST_PANEL.center_x, PAGE_INDICATOR_Y,
                             self.cursor_index, len(self.rows), ROWS_PER_PAGE)

        sprite_key = None
        if self.rows:
            sprite_key = self._sprite_key_for(self.rows[self.cursor_index][1])
        draw_icon_panel(ICON_PANEL, sprite_key, self.text_pool, "icon", placeholder_label="(no image set)")

        draw_panel(DESCRIPTION_PANEL)
        draw_wrapped_lines(DESCRIPTION_PANEL, self.text_pool, "description", self.description_lines,
                            DESCRIPTION_LINE_HEIGHT, font_size=DESCRIPTION_FONT_SIZE)

        self.draw_instructions("L/R: Tabs   U/D: Select   Enter: Buy   ESC: Leave", font_size=9)
        self.draw_message()

    # ---- input ----

    def handle_content_keys(self, key, modifiers):
        if key == arcade.key.ESCAPE:
            logger.debug("Catalogue: left the bench, returning to the computer bench menu")
            self.window.show_view(self.lab_view)
            return
        if key == arcade.key.LEFT:
            self._switch_tab((self.tab_index - 1) % len(TABS))
        elif key == arcade.key.RIGHT:
            self._switch_tab((self.tab_index + 1) % len(TABS))
        elif key in (arcade.key.UP, arcade.key.W) and self.rows:
            self.cursor_index = (self.cursor_index - 1) % len(self.rows)
            self._refresh_description()
        elif key in (arcade.key.DOWN, arcade.key.S) and self.rows:
            self.cursor_index = (self.cursor_index + 1) % len(self.rows)
            self._refresh_description()
        elif key == arcade.key.ENTER and self.rows:
            self.try_buy(self.rows[self.cursor_index][1])

    def _switch_tab(self, new_index):
        self.tab_index = new_index
        _, self.mode = TABS[self.tab_index]
        self.cursor_index = 0
        self._refresh_rows()
        logger.debug("Catalogue: switched to '%s' tab", self.mode)

    def try_buy(self, item):
        if self.mode == "equipment":
            self._try_buy_equipment(item)
        elif self.mode == "reagents":
            self._try_buy_reagent(*item)
        else:
            self._try_buy_consumable(item)

    def _try_buy_reagent(self, name, species):
        inventory = self.window.chemical_inventory
        try:
            cost = buy_chemical(inventory, self.window.wallet, name, BUY_LOT_SIZE)
        except InsufficientFundsError as e:
            self.show_message(str(e), arcade.color.RED)
            return
        logger.info("Bought %.1f %s of '%s' for $%.2f", BUY_LOT_SIZE, species.unit_label(), name, cost)
        self.show_message(f"Bought {BUY_LOT_SIZE:.0f} {species.unit_label()} {species.display_name} for ${cost:.2f}",
                           arcade.color.DARK_GREEN)
        self._refresh_description()

    def _try_buy_equipment(self, entry):
        try:
            cost = buy_equipment(self.window.equipment_inventory, self.window.wallet, entry)
        except InsufficientFundsError as e:
            self.show_message(str(e), arcade.color.RED)
            return
        logger.info("Bought '%s' for $%.2f", entry.name, cost)
        self.show_message(f"Bought {entry.display_name} for ${cost:.2f}", arcade.color.DARK_GREEN)
        self._refresh_description()

    def _try_buy_consumable(self, entry):
        try:
            cost = buy_consumable(self.window.consumables, self.window.wallet, entry, BUY_LOT_SIZE)
        except InsufficientFundsError as e:
            self.show_message(str(e), arcade.color.RED)
            return
        logger.info("Bought %.1f %s of '%s' for $%.2f", BUY_LOT_SIZE, entry.unit, entry.name, cost)
        self.show_message(f"Bought {BUY_LOT_SIZE:.0f} {entry.unit} {entry.display_name} for ${cost:.2f}",
                           arcade.color.DARK_GREEN)
        self._refresh_description()
