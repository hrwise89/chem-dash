"""
Screens shown by more than one place: the notebook (notebook.py) shows
Active Reactions/Known Reactions/Inventory read-only, and the reaction
bench (reaction_bench.py) shows the same Active Reactions/Inventory
screens too (Active Reactions also collectible there) plus reuses Known
Reactions' list-and-detail shape as the first step of its own "start a
reaction" flow. Pulled out here, as small composable objects with their
own cursor/tab state and a draw()/handle_key() pair, rather than each
owner reimplementing the same list+icon+description layout.

Every layout constant here is full-screen scale (see ui_theme.py's
STATUS_PANEL/INSTRUCTIONS_Y for the status bar/instructions every such
screen shares) -- see notebook.py's own module docstring for why that
matters: a shrunk-down copy of these numbers was the direct cause of the
overflow bugs an earlier version had.
"""
import arcade

from benches.ui_theme import (
    DIM_COLOR, FONT_STACK, PANEL_COLOR, Panel,
    draw_description_panel, draw_icon_panel, draw_tab_bar, draw_titled_list_panel,
    truncate_to_width,
)
from units import format_moles, format_native_amount

FLASK_SPRITE_KEY = "rb_flask"  # the one generic flask/jar icon, reused everywhere there's no per-item art

# ---- Active/Known Reactions: list + icon, then (for a running reaction)
# time/solvent/ready, always the reaction's equation, and a "used in" blurb ----
REACTION_LIST_PANEL = Panel(left=40, right=520, bottom=260, top=520)
REACTION_ICON_PANEL = Panel(left=540, right=760, bottom=260, top=520)
REACTION_ROW_HEIGHT = 22
REACTION_LIST_FONT_SIZE = 10
REACTION_INFO_FONT_SIZE = 12
REACTION_INFO_ROW_HEIGHT = 22
REACTION_DESC_PANEL = Panel(left=40, right=760, bottom=50, top=150)

# ---- Inventory: Equipment/Reagents/Consumables tabs -- catalogue_bench.
# py's own buy-screen geometry, verbatim (same tabs, same shape of data:
# a priced/quantified list + icon + description) ----
INVENTORY_TABS = ["Equipment", "Reagents", "Consumables"]
INVENTORY_TAB_Y = 505
INVENTORY_LIST_PANEL = Panel(left=40, right=540, bottom=220, top=480)
INVENTORY_ICON_PANEL = Panel(left=560, right=760, bottom=220, top=480)
INVENTORY_ROW_HEIGHT = 22
INVENTORY_LIST_FONT_SIZE = 10
INVENTORY_DESC_PANEL = Panel(left=40, right=760, bottom=90, top=200)


def display_name(inventory, name: str) -> str:
    """A chemical identity's short display name if the species catalog
    knows it, else the raw identity itself -- some reaction reactants
    (e.g. "HBr", supplied by a solution's `solute`) have no species entry
    of their own to look a short_name up on."""
    return inventory.species_for(name).display_name if name in inventory.species_catalog else name


def equation_text(inventory, definition) -> str:
    reactants = " + ".join(display_name(inventory, n) for n in definition.reactants)
    products = " + ".join(display_name(inventory, n) for n in definition.products)
    return f"{reactants} -> {products}"


def predicted_product(process):
    """(product_name, moles) for the main product a running process will
    yield if collected right now at its current condition_score -- the
    same formula collect_reaction() itself uses, just not committed to
    inventory yet."""
    product_name, stoich = next(iter(process.definition.products.items()))
    efficiency = process.definition.efficiency * process.condition_score
    return product_name, stoich * process.limiting_ratio * efficiency


class ReactionsSection:
    """running=True: the engine's own in-progress processes (Active
    Reactions). running=False: every recipe in the reaction database,
    sorted by its main product's display name (Known Reactions).

    collectible (only meaningful when running) lets ENTER collect a ready
    process and F warp the game clock straight to its end -- the reaction
    bench's own Active Reactions turns this on; the notebook's read-only
    view leaves it off. selectable (only meaningful when not running) lets
    ENTER call on_select(definition) instead of being a no-op -- the
    reaction bench's "start a reaction" flow uses this to pick a recipe
    from what's otherwise the same Known Reactions screen."""

    def __init__(self, running: bool, collectible: bool = False, selectable: bool = False, on_select=None):
        self.running = running
        self.collectible = collectible
        self.selectable = selectable
        self.on_select = on_select
        self.cursor = 0

    def items(self, window):
        engine = window.reaction_engine
        if self.running:
            return list(engine.active_processes.values())
        definitions = list(engine.reaction_db.values())
        inventory = window.chemical_inventory
        definitions.sort(key=lambda d: display_name(inventory, next(iter(d.products))))
        return definitions

    def handle_key(self, key, window, show_message=None):
        items = self.items(window)
        if not items:
            return
        if key in (arcade.key.UP, arcade.key.W):
            self.cursor = (self.cursor - 1) % len(items)
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.cursor = (self.cursor + 1) % len(items)
        elif key == arcade.key.ENTER:
            selected = items[self.cursor]
            if self.collectible and self.running:
                self._try_collect(selected, window, show_message)
            elif self.selectable and not self.running and self.on_select:
                self.on_select(selected)
        elif key == arcade.key.F and self.collectible and self.running:
            self._warp(items[self.cursor], window, show_message)

    def _try_collect(self, process, window, show_message):
        clock = window.game_clock
        if not process.is_ready(clock):
            if show_message:
                show_message(f"Not ready yet: {process.time_remaining(clock):.1f}h remaining",
                              arcade.color.DARK_YELLOW)
            return
        products = window.reaction_engine.collect_reaction(
            process.process_id, window.chemical_inventory, window.equipment_inventory, clock)
        self.cursor = 0
        if show_message:
            summary = ", ".join(f"{amt:.2f} mol {name}" for name, amt in products.items())
            show_message(f"Collected: {summary}", arcade.color.DARK_GREEN)

    def _warp(self, process, window, show_message):
        """Dev/testing shortcut (see the reaction bench's own docstring) --
        deliberately not mentioned in any on-screen instructions line."""
        window.game_clock.advance_to(process.end_time)
        if show_message:
            show_message(f"Warped time to {process.end_time:.1f}h", arcade.color.DARK_YELLOW)

    def draw(self, window, text_pool, instructions: str, title: str | None = None):
        engine = window.reaction_engine
        inventory = window.chemical_inventory
        items = self.items(window)

        probe = text_pool.get("reaction_list_probe", "", 0, 0, PANEL_COLOR,
                               font_size=REACTION_LIST_FONT_SIZE, font_name=FONT_STACK)
        max_width = REACTION_LIST_PANEL.width - 40  # left_margin + cursor_glyph_width + cursor_gap
        rows = []
        row_colors = [] if self.running else None
        for item in items:
            if self.running:
                product_name, moles = predicted_product(item)
                species = inventory.species_for(product_name)
                native = moles / species.moles_per_unit()
                text = (f"{species.display_name}    {format_moles(moles)}, "
                        f"{format_native_amount(species, native)}")
                rows.append(truncate_to_width(probe, text, max_width))
                row_colors.append(arcade.color.GREEN if item.is_ready(window.game_clock) else PANEL_COLOR)
            else:
                product_name = next(iter(item.products))
                rows.append(truncate_to_width(probe, display_name(inventory, product_name), max_width))

        if title is None:
            title = "-Active Reactions-" if self.running else "-Known Reactions-"
        draw_titled_list_panel(REACTION_LIST_PANEL, text_pool, "reaction_list", rows, self.cursor,
                                REACTION_ROW_HEIGHT, title=title, font_size=REACTION_LIST_FONT_SIZE,
                                row_colors=row_colors, empty_label="(none)")
        draw_icon_panel(REACTION_ICON_PANEL, FLASK_SPRITE_KEY, text_pool, "reaction_icon")

        if not items:
            self._draw_instructions(text_pool, instructions)
            return

        selected = items[self.cursor]
        definition = selected.definition if self.running else selected
        product_name = predicted_product(selected)[0] if self.running else next(iter(selected.products))

        y = REACTION_LIST_PANEL.bottom - 18
        if self.running:
            elapsed = min(selected.scheduled_hours, window.game_clock.now() - selected.start_time)
            text_pool.get("reaction_time", f"Time: {elapsed:g}/{selected.scheduled_hours:g} Hr",
                           REACTION_LIST_PANEL.left, y, PANEL_COLOR, font_size=REACTION_INFO_FONT_SIZE,
                           font_name=FONT_STACK, anchor_x="left", anchor_y="center").draw()
            text_pool.get("reaction_solvent", f"Solvent: {selected.solvent or 'None'}",
                           REACTION_LIST_PANEL.left + 280, y, PANEL_COLOR, font_size=REACTION_INFO_FONT_SIZE,
                           font_name=FONT_STACK, anchor_x="left", anchor_y="center").draw()
            y -= REACTION_INFO_ROW_HEIGHT
            if selected.is_ready(window.game_clock):
                text_pool.get("reaction_ready", "(Ready!)", REACTION_LIST_PANEL.left, y, arcade.color.GREEN,
                               font_size=REACTION_INFO_FONT_SIZE, font_name=FONT_STACK,
                               anchor_x="left", anchor_y="center").draw()
                y -= REACTION_INFO_ROW_HEIGHT

        y -= REACTION_INFO_ROW_HEIGHT
        text_pool.get("reaction_equation", equation_text(inventory, definition), 400, y,
                       PANEL_COLOR, font_size=REACTION_INFO_FONT_SIZE, font_name=FONT_STACK,
                       anchor_x="center", anchor_y="center").draw()

        description = engine.used_in_summary(inventory, product_name)
        draw_description_panel(REACTION_DESC_PANEL, text_pool, "reaction_desc", description)
        self._draw_instructions(text_pool, instructions)

    def _draw_instructions(self, text_pool, text: str):
        text_pool.get("reaction_section_instructions", text, 400, 25, DIM_COLOR, font_size=10,
                       font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()


class InventorySection:
    """Equipment/Reagents/Consumables tabs -- read-only everywhere it's
    used so far (the notebook and the reaction bench alike)."""

    def __init__(self):
        self.tab = 0
        self.cursor = 0

    def handle_key(self, key, window):
        if key == arcade.key.LEFT:
            self.tab = (self.tab - 1) % len(INVENTORY_TABS)
            self.cursor = 0
        elif key == arcade.key.RIGHT:
            self.tab = (self.tab + 1) % len(INVENTORY_TABS)
            self.cursor = 0
        else:
            rows = self.rows(window)
            if not rows:
                return
            if key in (arcade.key.UP, arcade.key.W):
                self.cursor = (self.cursor - 1) % len(rows)
            elif key in (arcade.key.DOWN, arcade.key.S):
                self.cursor = (self.cursor + 1) % len(rows)

    def rows(self, window):
        """(label, description, sprite_key) for every row on the current tab."""
        tab = INVENTORY_TABS[self.tab]
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

    def draw(self, window, text_pool, instructions: str):
        draw_tab_bar(text_pool, "inv_tab", 400, INVENTORY_TAB_Y, INVENTORY_TABS, self.tab,
                     spacing=260, font_size=16)

        rows = self.rows(window)
        probe = text_pool.get("inv_list_probe", "", 0, 0, PANEL_COLOR,
                               font_size=INVENTORY_LIST_FONT_SIZE, font_name=FONT_STACK)
        max_width = INVENTORY_LIST_PANEL.width - 40  # left_margin + cursor_glyph_width + cursor_gap
        labels = [truncate_to_width(probe, label, max_width) for label, _, _ in rows]
        draw_titled_list_panel(INVENTORY_LIST_PANEL, text_pool, "inv_list", labels, self.cursor,
                                INVENTORY_ROW_HEIGHT, font_size=INVENTORY_LIST_FONT_SIZE,
                                empty_label="(nothing here yet)")

        icon_key = rows[self.cursor][2] if rows else FLASK_SPRITE_KEY
        draw_icon_panel(INVENTORY_ICON_PANEL, icon_key, text_pool, "inv_icon")

        description = rows[self.cursor][1] if rows else ""
        draw_description_panel(INVENTORY_DESC_PANEL, text_pool, "inv_desc", description)

        text_pool.get("inventory_instructions", instructions, 400, 25, DIM_COLOR, font_size=10,
                       font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()
