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
each section's own cursor, and (for the two tabbed sections) which tab --
so opening it again with N shows exactly what was showing before.

Built on the same ui_theme.py composites every other redesigned bench
draws through -- draw_titled_list_panel/draw_description_panel in
particular exist because this module needed the same "titled box + paged
list + page counter" and "box + wrapped blurb" shapes as purify_bench.py's
crude-product picker, five times over (Active/Known Reactions, and all
three Inventory tabs) -- one call each here instead of five more
hand-rolled copies of that layout math.
"""
import arcade

from benches.ui_common import TextPool
from benches.ui_theme import (
    CP437_CURSOR, DIM_COLOR, FONT_STACK, PANEL_COLOR, Panel,
    draw_description_panel, draw_icon_panel, draw_multiline_list, draw_page_indicator,
    draw_panel, draw_tab_bar, draw_titled_list_panel, truncate_to_width,
)
from economy import in_transit_description, open_order_description, order_detail_line, order_summary_line
from units import format_moles, format_native_amount

FLASK_SPRITE_KEY = "rb_flask"  # the one generic flask/jar icon, reused everywhere there's no per-item art

# 2 columns x 3 rows, matching the mockup -- (label, section_key) for a
# functional panel, (label, None) for a no-op placeholder.
GRID_COLUMNS = 2
PANELS = [
    ("Active\nReactions", "active_reactions"),
    ("Orders", "orders"),
    ("Inventory", "inventory"),
    ("History", None),
    ("Known\nReactions", "known_reactions"),
    ("Placeholder", None),
]
GRID_ROWS = -(-len(PANELS) // GRID_COLUMNS)  # ceil division

# The overlay frame itself: scaled from the mockup image (1536x1152,
# matching this game's 4:3 800x600 canvas exactly) by 800/1536 = 0.521 --
# big enough to obscure whatever bench-specific controls sit at the bottom
# of the screen beneath it, but leaving the shared top status bar (drawn by
# whatever view is underneath) visible above it, per the mockup.
NOTEBOOK_PANEL = Panel(left=50, right=750, bottom=40, top=500)

# ---- main grid ----
GRID_LEFT = NOTEBOOK_PANEL.left + 20
GRID_RIGHT = NOTEBOOK_PANEL.right - 20
GRID_TOP = NOTEBOOK_PANEL.top - 20
GRID_BOTTOM = NOTEBOOK_PANEL.bottom + 40  # leaves room for the instructions line
COLUMN_GAP = 16
ROW_GAP = 14

_col_width = (GRID_RIGHT - GRID_LEFT - COLUMN_GAP * (GRID_COLUMNS - 1)) / GRID_COLUMNS
_row_height = (GRID_TOP - GRID_BOTTOM - ROW_GAP * (GRID_ROWS - 1)) / GRID_ROWS


def _panel_rect(index: int) -> Panel:
    row, col = divmod(index, GRID_COLUMNS)
    left = GRID_LEFT + col * (_col_width + COLUMN_GAP)
    top = GRID_TOP - row * (_row_height + ROW_GAP)
    return Panel(left=left, right=left + _col_width, bottom=top - _row_height, top=top)


PANEL_RECTS = [_panel_rect(i) for i in range(len(PANELS))]

# ---- shared content area every drilled-in section draws inside ----
CONTENT = Panel(left=NOTEBOOK_PANEL.left + 15, right=NOTEBOOK_PANEL.right - 15,
                 bottom=GRID_BOTTOM, top=NOTEBOOK_PANEL.top - 15)

# ---- Active/Known Reactions: list + icon, (for a running one) time/
# solvent/ready, the reaction's equation, and a "used in" blurb ----
REACTION_LIST_PANEL = Panel(CONTENT.left, CONTENT.left + 480, CONTENT.top - 150, CONTENT.top)
REACTION_ICON_PANEL = Panel(REACTION_LIST_PANEL.right + 15, CONTENT.right,
                             REACTION_LIST_PANEL.bottom, REACTION_LIST_PANEL.top)
REACTION_ROW_HEIGHT = 22
REACTION_LIST_FONT_SIZE = 10
REACTION_INFO_FONT_SIZE = 12
REACTION_INFO_ROW_HEIGHT = 24
REACTION_DESC_PANEL = Panel(CONTENT.left, CONTENT.right, CONTENT.bottom, CONTENT.bottom + 95)

# ---- Orders: tabs + a 2-line-per-entry list (like the shipping bench's
# own Open Orders/Awaiting pickup view) + description, but read-only ----
ORDER_TABS = [("Open Orders", "open_orders"), ("Awaiting pickup", "in_transit")]
ORDERS_TAB_Y = NOTEBOOK_PANEL.top - 32
ORDERS_LIST_PANEL = Panel(CONTENT.left, CONTENT.right, CONTENT.bottom + 150, CONTENT.top - 45)
ORDERS_LIST_FONT_SIZE = 10
ORDERS_LIST_LINE_HEIGHT = 20
ORDERS_LIST_LINES_PER_ENTRY = 2
ORDERS_LIST_LINE_INDENTS = [0, 20]
ORDERS_ENTRIES_PER_PAGE = max(1, int(ORDERS_LIST_PANEL.height // (ORDERS_LIST_LINE_HEIGHT * ORDERS_LIST_LINES_PER_ENTRY)))
ORDERS_PAGE_INDICATOR_Y = ORDERS_LIST_PANEL.bottom + 12
ORDERS_DESC_PANEL = Panel(CONTENT.left, CONTENT.right, CONTENT.bottom, CONTENT.bottom + 120)

# ---- Inventory: Equipment/Reagents/Consumables tabs, list + icon, desc ----
INVENTORY_TABS = ["Equipment", "Reagents", "Consumables"]
INVENTORY_TAB_Y = NOTEBOOK_PANEL.top - 32
INVENTORY_LIST_PANEL = Panel(CONTENT.left, CONTENT.left + 480, CONTENT.top - 195, CONTENT.top - 45)
INVENTORY_ICON_PANEL = Panel(INVENTORY_LIST_PANEL.right + 15, CONTENT.right,
                              INVENTORY_LIST_PANEL.bottom, INVENTORY_LIST_PANEL.top)
INVENTORY_ROW_HEIGHT = 22
INVENTORY_LIST_FONT_SIZE = 10
INVENTORY_DESC_PANEL = Panel(CONTENT.left, CONTENT.right, CONTENT.bottom, INVENTORY_LIST_PANEL.bottom - 15)


def _display_name(inventory, name: str) -> str:
    """A chemical identity's short display name if the species catalog
    knows it, else the raw identity itself -- some reaction reactants
    (e.g. "HBr", supplied by a solution's `solute`) have no species entry
    of their own to look a short_name up on."""
    return inventory.species_for(name).display_name if name in inventory.species_catalog else name


def _equation_text(inventory, definition) -> str:
    reactants = " + ".join(_display_name(inventory, n) for n in definition.reactants)
    products = " + ".join(_display_name(inventory, n) for n in definition.products)
    return f"{reactants} -> {products}"


def _predicted_product(process):
    """(product_name, moles) for the main product a running process will
    yield if collected right now at its current condition_score -- the
    same formula collect_reaction() itself uses, just not committed to
    inventory yet."""
    product_name, stoich = next(iter(process.definition.products.items()))
    efficiency = process.definition.efficiency * process.condition_score
    return product_name, stoich * process.limiting_ratio * efficiency


class Notebook:

    def __init__(self):
        self.is_open = False
        self.section = None       # None = showing the 6-panel grid; else a PANELS section key
        self.cursor_index = 0     # grid cursor
        self.reactions_cursor = 0
        self.known_reactions_cursor = 0
        self.orders_tab = 0
        self.orders_cursor = 0
        self.inventory_tab = 0
        self.inventory_cursor = 0
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
        if self.section in ("active_reactions", "known_reactions"):
            self._handle_reaction_list_keys(key, window)
        elif self.section == "orders":
            self._handle_orders_keys(key, window)
        elif self.section == "inventory":
            self._handle_inventory_keys(key, window)

    def _handle_reaction_list_keys(self, key, window):
        items = self._reaction_items(window)
        attr = "reactions_cursor" if self.section == "active_reactions" else "known_reactions_cursor"
        cursor = getattr(self, attr)
        if not items:
            return
        if key in (arcade.key.UP, arcade.key.W):
            setattr(self, attr, (cursor - 1) % len(items))
        elif key in (arcade.key.DOWN, arcade.key.S):
            setattr(self, attr, (cursor + 1) % len(items))

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

    def _handle_inventory_keys(self, key, window):
        if key == arcade.key.LEFT:
            self.inventory_tab = (self.inventory_tab - 1) % len(INVENTORY_TABS)
            self.inventory_cursor = 0
        elif key == arcade.key.RIGHT:
            self.inventory_tab = (self.inventory_tab + 1) % len(INVENTORY_TABS)
            self.inventory_cursor = 0
        else:
            rows = self._inventory_rows(window)
            if not rows:
                return
            if key in (arcade.key.UP, arcade.key.W):
                self.inventory_cursor = (self.inventory_cursor - 1) % len(rows)
            elif key in (arcade.key.DOWN, arcade.key.S):
                self.inventory_cursor = (self.inventory_cursor + 1) % len(rows)

    # ---- data (kept as plain lookups -- there's little enough of it per
    # section that rebuilding on every draw is cheap, unlike the fixed-
    # width row text the other benches cache between cursor moves) ----

    def _reaction_items(self, window):
        """Active reactions: the engine's own in-progress processes.
        Known reactions: every recipe in the reaction database, sorted by
        its main product's display name."""
        engine = window.reaction_engine
        if self.section == "active_reactions":
            return list(engine.active_processes.values())
        definitions = list(engine.reaction_db.values())
        inventory = window.chemical_inventory
        definitions.sort(key=lambda d: _display_name(inventory, next(iter(d.products))))
        return definitions

    def _orders_items(self, window):
        board = window.contract_board
        _, mode = ORDER_TABS[self.orders_tab]
        return board.accepted if mode == "open_orders" else board.in_transit

    def _inventory_rows(self, window):
        """(label, description, sprite_key) for every row on the current
        Inventory tab."""
        tab = INVENTORY_TABS[self.inventory_tab]
        if tab == "Equipment":
            return self._equipment_rows(window)
        if tab == "Reagents":
            return self._reagent_rows(window)
        return self._consumable_rows(window)

    def _equipment_rows(self, window):
        items = sorted(window.equipment_inventory.items.values(), key=lambda i: (i.type, i.name))
        rows = []
        for item in items:
            label = f"{item.name} [in use]" if item.in_use else item.name
            description = self._equipment_description(window, item)
            rows.append((label, description, item.type))
        return rows

    def _equipment_description(self, window, item) -> str:
        for entry in window.equipment_catalog.values():
            if entry.type == item.type and (item.capacity is None or entry.capacity == item.capacity):
                return entry.description or "(no description yet)"
        return "(no description yet)"

    def _reagent_rows(self, window):
        inventory = window.chemical_inventory
        rows = []
        for name in sorted(inventory.contents.keys()):
            species = inventory.species_for(name)
            label = f"{species.display_name}: {inventory.describe(name)}"
            description = window.reaction_engine.used_in_summary(inventory, name)
            rows.append((label, description, FLASK_SPRITE_KEY))
        return rows

    def _consumable_rows(self, window):
        rows = []
        for name in sorted(window.consumables.contents.keys()):
            amount = window.consumables.contents[name]
            entry = window.consumable_catalog.get(name)
            display = entry.display_name if entry else name
            unit = entry.unit if entry else "unit"
            description = entry.description if entry and entry.description else "(no description yet)"
            rows.append((f"{display}: {amount:.1f} {unit}", description, FLASK_SPRITE_KEY))
        return rows

    # ---- drawing ----

    def draw(self, window):
        draw_panel(NOTEBOOK_PANEL)
        if self.section is None:
            self._draw_grid()
        elif self.section in ("active_reactions", "known_reactions"):
            self._draw_reaction_section(window)
        elif self.section == "orders":
            self._draw_orders_section(window)
        elif self.section == "inventory":
            self._draw_inventory_section(window)

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

    def _draw_reaction_section(self, window):
        engine = window.reaction_engine
        inventory = window.chemical_inventory
        running = self.section == "active_reactions"
        items = self._reaction_items(window)
        cursor = self.reactions_cursor if running else self.known_reactions_cursor

        probe = self.text_pool.get("reaction_list_probe", "", 0, 0, PANEL_COLOR,
                                    font_size=REACTION_LIST_FONT_SIZE, font_name=FONT_STACK)
        max_width = REACTION_LIST_PANEL.width - 40  # left_margin + cursor_glyph_width + cursor_gap
        rows = []
        row_colors = [] if running else None
        for item in items:
            if running:
                product_name, moles = _predicted_product(item)
                species = inventory.species_for(product_name)
                native = moles / species.moles_per_unit()
                text = (f"{species.display_name}    {format_moles(moles)}, "
                        f"{format_native_amount(species, native)}")
                rows.append(truncate_to_width(probe, text, max_width))
                row_colors.append(arcade.color.GREEN if item.is_ready(window.game_clock) else PANEL_COLOR)
            else:
                product_name = next(iter(item.products))
                rows.append(truncate_to_width(probe, _display_name(inventory, product_name), max_width))

        title = "-Active Reactions-" if running else "-Known Reactions-"
        draw_titled_list_panel(REACTION_LIST_PANEL, self.text_pool, "reaction_list", rows, cursor,
                                REACTION_ROW_HEIGHT, title=title, font_size=REACTION_LIST_FONT_SIZE,
                                row_colors=row_colors, empty_label="(none)")
        draw_icon_panel(REACTION_ICON_PANEL, FLASK_SPRITE_KEY, self.text_pool, "reaction_icon")

        if not items:
            self._draw_instructions("Up/Down: Scroll   ESC: Back   N: Close")
            return

        selected = items[cursor]
        definition = selected.definition if running else selected
        product_name = _predicted_product(selected)[0] if running else next(iter(selected.products))

        y = REACTION_LIST_PANEL.bottom - 20
        if running:
            elapsed = min(selected.scheduled_hours, window.game_clock.now() - selected.start_time)
            self.text_pool.get("reaction_time", f"Time: {elapsed:g}/{selected.scheduled_hours:g} Hr",
                                CONTENT.left, y, PANEL_COLOR, font_size=REACTION_INFO_FONT_SIZE,
                                font_name=FONT_STACK, anchor_x="left", anchor_y="center").draw()
            self.text_pool.get("reaction_solvent", f"Solvent: {selected.solvent or 'None'}",
                                CONTENT.left + 280, y, PANEL_COLOR, font_size=REACTION_INFO_FONT_SIZE,
                                font_name=FONT_STACK, anchor_x="left", anchor_y="center").draw()
            y -= REACTION_INFO_ROW_HEIGHT
            if selected.is_ready(window.game_clock):
                self.text_pool.get("reaction_ready", "(Ready!)", CONTENT.left, y, arcade.color.GREEN,
                                    font_size=REACTION_INFO_FONT_SIZE, font_name=FONT_STACK,
                                    anchor_x="left", anchor_y="center").draw()
                y -= REACTION_INFO_ROW_HEIGHT

        y -= REACTION_INFO_ROW_HEIGHT * 0.6
        self.text_pool.get("reaction_equation", _equation_text(inventory, definition), CONTENT.center_x, y,
                            PANEL_COLOR, font_size=REACTION_INFO_FONT_SIZE, font_name=FONT_STACK,
                            anchor_x="center", anchor_y="center").draw()

        description = engine.used_in_summary(inventory, product_name)
        draw_description_panel(REACTION_DESC_PANEL, self.text_pool, "reaction_desc", description)
        self._draw_instructions("Up/Down: Scroll   ESC: Back   N: Close")

    def _draw_orders_section(self, window):
        draw_tab_bar(self.text_pool, "orders_tab", NOTEBOOK_PANEL.center_x, ORDERS_TAB_Y,
                     [label for label, _ in ORDER_TABS], self.orders_tab, spacing=320, font_size=14)

        contracts = self._orders_items(window)
        entries = [self._order_lines(c) for c in contracts]
        draw_panel(ORDERS_LIST_PANEL)
        draw_multiline_list(ORDERS_LIST_PANEL, self.text_pool, "orders_list", entries, self.orders_cursor,
                             ORDERS_ENTRIES_PER_PAGE, ORDERS_LIST_LINE_HEIGHT, ORDERS_LIST_LINES_PER_ENTRY,
                             font_size=ORDERS_LIST_FONT_SIZE, cursor_line=0, line_indents=ORDERS_LIST_LINE_INDENTS,
                             empty_label="(no orders)")
        draw_page_indicator(self.text_pool, "orders_page", ORDERS_LIST_PANEL.center_x, ORDERS_PAGE_INDICATOR_Y,
                             self.orders_cursor, len(contracts), ORDERS_ENTRIES_PER_PAGE)

        if contracts:
            contract = contracts[self.orders_cursor]
            _, mode = ORDER_TABS[self.orders_tab]
            description = (open_order_description(contract, window.contract_board, window.chemical_inventory)
                            if mode == "open_orders" else in_transit_description(contract))
            draw_description_panel(ORDERS_DESC_PANEL, self.text_pool, "orders_desc", description)
        else:
            draw_panel(ORDERS_DESC_PANEL)

        self._draw_instructions("L/R: Tabs   Up/Down: Scroll   ESC: Back   N: Close")

    def _order_lines(self, contract) -> list[str]:
        return [order_summary_line(contract), order_detail_line(contract)]

    def _draw_inventory_section(self, window):
        draw_tab_bar(self.text_pool, "inv_tab", NOTEBOOK_PANEL.center_x, INVENTORY_TAB_Y,
                     INVENTORY_TABS, self.inventory_tab, spacing=260, font_size=16)

        rows = self._inventory_rows(window)
        probe = self.text_pool.get("inv_list_probe", "", 0, 0, PANEL_COLOR,
                                    font_size=INVENTORY_LIST_FONT_SIZE, font_name=FONT_STACK)
        max_width = INVENTORY_LIST_PANEL.width - 40  # left_margin + cursor_glyph_width + cursor_gap
        labels = [truncate_to_width(probe, label, max_width) for label, _, _ in rows]
        draw_titled_list_panel(INVENTORY_LIST_PANEL, self.text_pool, "inv_list", labels, self.inventory_cursor,
                                INVENTORY_ROW_HEIGHT, font_size=INVENTORY_LIST_FONT_SIZE,
                                empty_label="(nothing here yet)")

        icon_key = rows[self.inventory_cursor][2] if rows else FLASK_SPRITE_KEY
        draw_icon_panel(INVENTORY_ICON_PANEL, icon_key, self.text_pool, "inv_icon")

        description = rows[self.inventory_cursor][1] if rows else ""
        draw_description_panel(INVENTORY_DESC_PANEL, self.text_pool, "inv_desc", description)

        self._draw_instructions("L/R: Tabs   Up/Down: Scroll   ESC: Back   N: Close")

    def _draw_instructions(self, text: str):
        self.text_pool.get("notebook_instructions", text, NOTEBOOK_PANEL.center_x,
                            NOTEBOOK_PANEL.bottom + 16, DIM_COLOR, font_size=10,
                            font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()
