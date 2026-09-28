"""
The reaction bench: browse your equipment/recipes/inventory, start a
reaction, and collect it from your notebook once it's ready.
"""

import math

import arcade

from benches.ui_common import LIST_START_Y, BenchView, check_pass_out
from devtools import logger
from inventory import EquipmentUnavailableError, bench_for_equipment_type
from reaction_engine import (
    reaction_scale_bounds,
    reagents_for_scale,
    reference_reagent_for,
)

# Placeholder category ordering for equipment rows: vessels first, then
# everything else alphabetically by type. A real tagging system (the kind
# that would also group e.g. "generic"/"hardware" equipment together) can
# replace this later -- for now there's only one vessel type anyway.
_VESSEL_TYPES = {"rb_flask"}

INDICATOR_SIZE = 20
INDICATOR_GAP = 8
INDICATOR_MAX_SHOWN = 8

# The notebook is one bench section with its own tab menu, rather than
# separate top-level sections -- (tab label, internal mode) pairs.
NOTEBOOK_TABS = [
    ("Active Reactions", "notebook_active"),
    ("Open Orders", "notebook_orders"),
    ("History", "notebook_history"),
]
_SECTION_TITLES = {
    "notebook_active": "ACTIVE REACTIONS",
    "notebook_orders": "OPEN ORDERS",
    "notebook_history": "HISTORY",
}

# ---- Amount-picker slider ----
SLIDER_WIDTH = 500
SLIDER_HEIGHT = 26
SLIDER_INITIAL_REPEAT_DELAY = 0.35   # seconds before a held key starts auto-repeating
SLIDER_MIN_REPEAT_INTERVAL = 0.04    # fastest auto-repeat once fully "held"
SLIDER_REPEAT_ACCEL = 0.05           # how fast the repeat interval shrinks with hold time


class ReactionBenchView(BenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view, title="Reaction Bench")
        # "overview" | "equipment" | "recipes" | "notebook" | "inventory"
        # | "select_vessel" | "select_amount" | "notebook_active" |
        # "notebook_orders" | "notebook_history" ("notebook" is a tab menu
        # over the last three -- see NOTEBOOK_TABS. "select_vessel"/
        # "select_amount" are the sub-flow for starting a reaction: pick a
        # recipe -> pick a vessel -> pick an amount. "select_amount" is a
        # single screen with two rows -- "Max" and a hand-adjustable
        # slider -- rather than separate screens.)
        self.mode = "overview"
        self.sections = ["equipment", "recipes", "notebook", "inventory"]

        self.keys_held: set[int] = set()

        # State for the recipe-start sub-flow, set as the player moves
        # through it (definition -> vessel -> amount):
        self.pending_name = None
        self.pending_definition = None
        self.pending_vessel = None
        self.pending_min_moles = 0.0
        self.pending_max_moles = 0.0
        self.pending_max_limiting_factor = None  # "vessel" or a reagent name

        # Slider-specific state (row 1 of the "select_amount" screen):
        self.slider_value = 0.0
        self.slider_hold_elapsed = 0.0
        self.slider_repeat_timer = 0.0

    # ---- what's in each section ----

    def current_list(self):
        """(label, underlying_object) pairs for whichever section is active,
        so drawing and key-handling share one source of truth."""
        if self.mode == "equipment":
            return self._equipment_rows()

        if self.mode == "recipes":
            labels = []
            for name, definition in self.window.reaction_engine.reaction_db.items():
                ratio_desc = ", ".join(f"{coeff:.2f} {chem}" for chem, coeff in definition.reactants.items())
                labels.append((f"{name}  [ratio: {ratio_desc}]", (name, definition)))
            return labels

        if self.mode == "notebook_active":
            clock = self.window.game_clock
            procs = self.window.reaction_engine.active_processes.values()
            return [(f"{p.reaction_name} ({p.time_remaining(clock):.1f}h left)", p) for p in procs]

        if self.mode == "notebook_orders":
            board = self.window.contract_board
            return [(self._open_order_label(c), c) for c in board.accepted]

        if self.mode == "notebook_history":
            # Most recent first within each kind, so the player's latest
            # result is the first thing they see when checking what to
            # expect next time.
            reaction_rows = [(self._history_label(e), e) for e in reversed(self.window.reaction_engine.history)]
            order_rows = [(self._order_history_label(c), c) for c in reversed(self.window.contract_board.history)]
            return reaction_rows + order_rows

        if self.mode == "inventory":
            inventory = self.window.chemical_inventory
            return [(f"{name}: {inventory.describe(name)}", name) for name in inventory.contents]

        return []

    def _history_label(self, entry) -> str:
        solvent_desc = entry.solvent or "no solvent"
        return (f"[Reaction] {entry.reaction_name} -- {entry.yield_fraction * 100:.0f}% yield "
                f"(t={entry.start_time:.1f}h, {solvent_desc}, {entry.temperature:.0f}C, {entry.scheduled_hours:.1f}h)")

    def _open_order_label(self, contract) -> str:
        board = self.window.contract_board
        have = board.available_product_moles(contract, self.window.chemical_inventory)
        product_desc = f"pure {contract.product}" if contract.requires_purity else contract.product
        ready = "ready to ship" if have + 1e-9 >= contract.amount else "not enough product yet"
        return (f"{contract.subject} -- need {contract.amount:.2f} mol {product_desc} "
                f"(have {have:.2f} mol) for ${contract.reward:.2f} ({ready})")

    def _order_history_label(self, contract) -> str:
        product_desc = f"pure {contract.product}" if contract.requires_purity else contract.product
        return f"[Order] {contract.subject} -- delivered {contract.amount:.2f} mol {product_desc}, paid ${contract.reward:.2f}"

    def _equipment_rows(self):
        """
        Group identical equipment (same type + capacity) into one row each,
        showing counts rather than one line per physical item -- otherwise
        owning 3 RB flasks means 3 near-identical rows. Sorted vessels
        (flasks) first, then everything else by type name. Only equipment
        tagged "reaction" in the shared catalog (src/data/equipment.json)
        shows up here -- purify-bench equipment (columns) lives in its own
        bench's supplies screen instead.
        """
        equipment_catalog = self.window.equipment_catalog
        groups = {}  # (type, capacity) -> {"name": str, "available": int, "in_use": int}
        for item in self.window.equipment_inventory.items.values():
            if bench_for_equipment_type(equipment_catalog, item.type) != "reaction":
                continue
            key = (item.type, item.capacity)
            group = groups.setdefault(key, {"name": item.name, "available": 0, "in_use": 0})
            if item.in_use:
                group["in_use"] += 1
            else:
                group["available"] += 1

        def sort_key(key):
            type_, capacity = key
            category = 0 if type_ in _VESSEL_TYPES else 1
            return (category, type_, capacity if capacity is not None else 0.0)

        rows = []
        for key in sorted(groups.keys(), key=sort_key):
            type_, capacity = key
            group = groups[key]
            capacity_desc = f", {capacity:.0f} mL" if capacity is not None else ""
            label = (f"{group['name']}{capacity_desc}  —  "
                     f"available: {group['available']}, in use: {group['in_use']}")
            rows.append((label, key))
        return rows

    # ---- drawing ----

    def on_update(self, delta_time):
        super().on_update(delta_time)          # message timer
        # The slider only responds to a held LEFT/RIGHT while the cursor is
        # actually sitting on its row (row 1) of the amount screen.
        if self.mode == "select_amount" and self.cursor_index == 1:
            self._update_slider_hold(delta_time)

    def on_draw(self):
        self.clear()
        self.draw_bench()
        self.draw_active_process_indicator()

        if self.mode == "overview":
            self.draw_overview()
        elif self.mode == "notebook":
            self.draw_notebook_tabs()
        elif self.mode == "select_vessel":
            self.draw_vessel_picker()
        elif self.mode == "select_amount":
            self.draw_amount_screen()
        else:
            self.draw_section()

        self.draw_message()

    def draw_active_process_indicator(self):
        """Placeholder visual: one white square per reaction currently
        running, along the bottom edge of the bench. Swap for real
        glassware/animation art later."""
        count = len(self.window.reaction_engine.active_processes)
        if count == 0:
            return

        bench = self.benches[0]
        shown = min(count, INDICATOR_MAX_SHOWN)
        total_width = shown * INDICATOR_SIZE + (shown - 1) * INDICATOR_GAP
        start_x = bench.center_x - total_width / 2 + INDICATOR_SIZE / 2
        y = bench.center_y - bench.height / 2 + INDICATOR_SIZE / 2 + 12

        for i in range(shown):
            x = start_x + i * (INDICATOR_SIZE + INDICATOR_GAP)
            arcade.draw_lrbt_rectangle_filled(
                x - INDICATOR_SIZE / 2, x + INDICATOR_SIZE / 2,
                y - INDICATOR_SIZE / 2, y + INDICATOR_SIZE / 2,
                arcade.color.WHITE,
            )

    def draw_overview(self):
        self.draw_title("Reaction Bench")
        self.draw_centered_menu([(section, True) for section in self.sections])
        self.draw_instructions("UP/DOWN to choose, ENTER to select, ESC to leave bench")

    def draw_notebook_tabs(self):
        self.draw_title("Notebook")
        self.draw_centered_menu([(label, True) for label, _ in NOTEBOOK_TABS])
        self.draw_instructions("UP/DOWN to choose, ENTER to select, ESC to go back")

    def draw_section(self):
        self.draw_title(_SECTION_TITLES.get(self.mode, self.mode.upper()))
        items = self.current_list()
        self.draw_scrollable_list([label for label, _ in items])

        if self.mode == "notebook_active":
            self.draw_instructions("UP/DOWN to choose, ENTER to collect, F to warp time, ESC to go back")
        elif self.mode == "recipes":
            self.draw_instructions("UP/DOWN to choose, ENTER to start, ESC to go back")
        else:
            self.draw_instructions("UP/DOWN to browse, ESC to go back")

    # ---- input ----

    def on_key_press(self, key, modifiers):
        self.keys_held.add(key)
        if self.mode == "overview":
            self.handle_overview_keys(key)
        elif self.mode == "notebook":
            self.handle_notebook_tab_keys(key)
        elif self.mode == "select_vessel":
            self.handle_vessel_keys(key)
        elif self.mode == "select_amount":
            self.handle_amount_menu_keys(key)
        else:
            self.handle_section_keys(key)

    def on_key_release(self, key, modifiers):
        self.keys_held.discard(key)

    def handle_overview_keys(self, key):
        if key in (arcade.key.UP, arcade.key.A):
            self.cursor_index = (self.cursor_index - 1) % len(self.sections)
        elif key in (arcade.key.DOWN, arcade.key.D):
            self.cursor_index = (self.cursor_index + 1) % len(self.sections)
        elif key in (arcade.key.ENTER, arcade.key.SPACE):
            self.mode = self.sections[self.cursor_index]
            self.reset_cursor()
            logger.debug("Reaction bench: entered '%s' section", self.mode)
        elif key == arcade.key.ESCAPE:
            logger.debug("Reaction bench: left the bench, returning to lab floor")
            self.window.show_view(self.lab_view)

    def handle_notebook_tab_keys(self, key):
        if key in (arcade.key.UP, arcade.key.W):
            self.cursor_index = (self.cursor_index - 1) % len(NOTEBOOK_TABS)
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.cursor_index = (self.cursor_index + 1) % len(NOTEBOOK_TABS)
        elif key in (arcade.key.ENTER, arcade.key.SPACE):
            _, self.mode = NOTEBOOK_TABS[self.cursor_index]
            self.reset_cursor()
            logger.debug("Reaction bench: entered notebook tab '%s'", self.mode)
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
        elif key == arcade.key.F and self.mode == "notebook_active" and items:
            _, process = items[self.cursor_index]
            self.window.game_clock.advance_to(process.end_time)   # "warp to end"
            logger.info("Warped game clock to t=%.2fh for '%s'", process.end_time, process.reaction_name)
            if check_pass_out(self.window, self.lab_view):
                return  # the warp pushed the player past their limit for the day
            self.show_message(f"Warped time to {process.end_time:.1f}h", arcade.color.DARK_YELLOW)
        elif key == arcade.key.ESCAPE:
            if self.mode.startswith("notebook_"):
                logger.debug("Reaction bench: back to notebook tabs from '%s'", self.mode)
                self.mode = "notebook"
            else:
                logger.debug("Reaction bench: back to overview from '%s'", self.mode)
                self.mode = "overview"
            self.reset_cursor()

    def activate_selected(self, selected):
        _, obj = selected
        if self.mode == "recipes":
            name, definition = obj
            self.begin_recipe_selection(name, definition)
        elif self.mode == "notebook_active":
            self.try_collect_reaction(obj)      # obj is a ReactionProcess
        # "equipment", "inventory", "notebook_orders", and "notebook_history"
        # are read-only for now -- nothing to activate

    # ---- recipe-start sub-flow: pick a recipe -> a vessel -> an amount ----

    def begin_recipe_selection(self, name, definition):
        if not self.window.equipment_inventory.available_items("rb_flask"):
            self.show_message("No free flask available.", arcade.color.RED)
            return
        self.pending_name = name
        self.pending_definition = definition
        self.mode = "select_vessel"
        self.reset_cursor()

    def vessel_choices(self):
        """(label, EquipmentItem) pairs for every free rb_flask, each
        previewing the max reaction scale that vessel would allow (see
        reaction_scale_bounds) so the player can compare vessels before
        committing to one, instead of finding out only after picking it."""
        definition = self.pending_definition
        inventory = self.window.chemical_inventory
        ref = reference_reagent_for(definition)
        rows = []
        for item in self.window.equipment_inventory.available_items("rb_flask"):
            bounds = reaction_scale_bounds(definition, inventory, item.capacity)
            if bounds is None:
                preview = "no chemicals for this reaction"
            else:
                _, max_moles, limiting_factor = bounds
                native = self._native_amount_desc(ref, max_moles)
                preview = f"max {max_moles:.2f} mol {ref} ({native}, limited by {limiting_factor})"
            rows.append((f"{item.name} ({item.capacity:.0f} mL) -- {preview}", item))
        return rows

    def draw_vessel_picker(self):
        self.draw_title("PICK A VESSEL")
        self.draw_scrollable_list([label for label, _ in self.vessel_choices()])
        self.draw_instructions("UP/DOWN to choose, ENTER to select, ESC to go back")

    def handle_vessel_keys(self, key):
        items = self.vessel_choices()
        if key in (arcade.key.UP, arcade.key.W) and items:
            self.cursor_index = (self.cursor_index - 1) % len(items)
            self.scroll_to_show_cursor()
        elif key in (arcade.key.DOWN, arcade.key.S) and items:
            self.cursor_index = (self.cursor_index + 1) % len(items)
            self.scroll_to_show_cursor()
        elif key == arcade.key.ENTER and items:
            _, vessel = items[self.cursor_index]
            self._choose_vessel(vessel)
        elif key == arcade.key.ESCAPE:
            self.mode = "recipes"
            self.reset_cursor()

    def _choose_vessel(self, vessel):
        bounds = reaction_scale_bounds(self.pending_definition, self.window.chemical_inventory, vessel.capacity)
        if bounds is None:
            self.show_message("You don't have the chemicals for this reaction.", arcade.color.RED)
            self.mode = "recipes"
            self.reset_cursor()
            return
        self.pending_vessel = vessel
        self.pending_min_moles, self.pending_max_moles, self.pending_max_limiting_factor = bounds
        self._init_slider_value()
        self.mode = "select_amount"
        self.reset_cursor()

    # ---- the merged Max/Slider amount screen ----

    def _init_slider_value(self):
        """Sets a sensible starting slider_value when the amount screen is
        entered, snapped onto the step grid so it could also be reached by
        stepping left/right from it."""
        step = self.pending_definition.scale_step
        floor = min(step, self.pending_max_moles)
        default = min(1.0, self.pending_max_moles)
        default = math.floor((default / step) + 1e-9) * step
        self.slider_value = max(floor, default)
        self.slider_hold_elapsed = 0.0
        self.slider_repeat_timer = 0.0

    def _selected_reference_moles(self) -> float:
        """The reference-reagent moles implied by whichever row the cursor
        is currently on -- row 0 (Max) or row 1 (the slider)."""
        return self.pending_max_moles if self.cursor_index == 0 else self.slider_value

    def _native_amount_desc(self, identity: str, moles: float) -> str:
        """'<amount> <unit>' for `moles` of `identity`, using whatever
        inventory entry currently supplies it (so a solution's own
        concentration is used, not some other unit) -- or, if nothing
        supplies it yet (e.g. a product not yet in inventory), the species
        catalog entry for its own name. Falls back to plain moles if there's
        no species definition to convert with."""
        inventory = self.window.chemical_inventory
        lookup_name = inventory.resolve_supplier(identity) or identity
        try:
            species = inventory.species_for(lookup_name)
        except KeyError:
            return f"{moles:.2f} mol"
        amount = moles / species.moles_per_unit()
        return f"{amount:.1f} {species.unit_label()}"

    def _max_row_label(self) -> str:
        factor = self.pending_max_limiting_factor
        if factor == "vessel":
            limit_desc = "limited by vessel volume"
        else:
            limit_desc = f"limited by {factor}, {self.pending_max_moles:.2f} mol"
        return f"Max ({limit_desc})"

    def _slider_row_label(self) -> str:
        ref = reference_reagent_for(self.pending_definition)
        native = self._native_amount_desc(ref, self.slider_value)
        return f"{self.slider_value:.2f} mol {ref}, {native}"

    def _preview_lines(self) -> list[str]:
        """Reagent amounts (moles + native units, naming whichever actual
        inventory item supplies each one -- e.g. "HBr as 48% hydrobromic
        acid" -- with the limiting reagent flagged) and theoretical (100%
        efficiency, ignoring condition_score) product yield, for whichever
        amount is currently selected -- Max or the slider. "" entries are
        blank spacer lines for the caller to render as extra vertical gap
        rather than text."""
        definition = self.pending_definition
        inventory = self.window.chemical_inventory
        selected = self._selected_reference_moles()
        reagents = reagents_for_scale(definition, selected)

        lines = ["Reagents"]
        for name, moles in reagents.items():
            supplier = inventory.resolve_supplier(name) or name
            display_name = name if supplier == name else f"{name} as {supplier}"
            tag = " (limiting)" if name == self.pending_max_limiting_factor else ""
            native = self._native_amount_desc(name, moles)
            lines.append(f"{display_name}{tag}: {moles:.2f} mol ({native})")

        lines.append("")
        lines.append("Product(s)")
        ref = reference_reagent_for(definition)
        ref_coeff = definition.reactants[ref]
        scale = selected / ref_coeff if ref_coeff else 0.0
        for product, stoich in definition.products.items():
            moles = stoich * scale
            native = self._native_amount_desc(product, moles)
            lines.append(f"{product} (theoretical): {moles:.2f} mol ({native})")
        return lines

    def draw_amount_screen(self):
        self.draw_title(self.pending_name or "PICK AN AMOUNT")
        self.draw_centered_menu([(self._max_row_label(), True), (self._slider_row_label(), True)])

        center_x = self.title_text.x
        bar_y = LIST_START_Y - 2 * 40 - 30
        left = center_x - SLIDER_WIDTH / 2
        right = center_x + SLIDER_WIDTH / 2
        bottom = bar_y - SLIDER_HEIGHT / 2
        top = bar_y + SLIDER_HEIGHT / 2

        selected = self._selected_reference_moles()
        fraction = 0.0 if self.pending_max_moles <= 0 else selected / self.pending_max_moles
        fraction = max(0.0, min(1.0, fraction))
        fill_x = left + SLIDER_WIDTH * fraction

        arcade.draw_lrbt_rectangle_outline(left, right, bottom, top, arcade.color.BLACK, border_width=2)
        if fraction > 0:
            arcade.draw_lrbt_rectangle_filled(left, fill_x, bottom, top, arcade.color.ORANGE)

        for tick_fraction in (0.25, 0.5, 0.75):
            tick_x = left + SLIDER_WIDTH * tick_fraction
            arcade.draw_line(tick_x, bottom - 4, tick_x, top + 4, arcade.color.GRAY, 1)

        if self.pending_max_moles > 0:
            min_fraction = max(0.0, min(1.0, self.pending_min_moles / self.pending_max_moles))
            min_x = left + SLIDER_WIDTH * min_fraction
            arcade.draw_line(min_x, bottom - 8, min_x, top + 8, arcade.color.DARK_YELLOW, 2)

        arcade.draw_line(fill_x, bottom - 8, fill_x, top + 8, arcade.color.RED, 3)

        below_min = selected < self.pending_min_moles
        value_color = arcade.color.DARK_YELLOW if below_min else arcade.color.BLACK
        self.text_pool.get("amount_selected", f"{selected:.2f} mol selected  (max {self.pending_max_moles:.2f} mol)",
            center_x, bar_y - 34, value_color, font_size=16, anchor_x="center").draw()

        if below_min:
            self.text_pool.get("below_min_warning", "Below recommended minimum -- yield may suffer",
                center_x, bar_y - 56, arcade.color.DARK_YELLOW, font_size=13, anchor_x="center").draw()

        preview_y = bar_y - 56 - (22 if below_min else 0) - 20
        for i, line in enumerate(self._preview_lines()):
            if line == "":
                preview_y -= 10
                continue
            is_header = line in ("Reagents", "Product(s)")
            color = arcade.color.DARK_BLUE if is_header else arcade.color.BLACK
            font_size = 15 if is_header else 14
            self.text_pool.get(f"preview_line_{i}", line, center_x, preview_y,
                color, font_size=font_size, anchor_x="center").draw()
            preview_y -= 22

        self.draw_instructions(
            "UP/DOWN to choose Max/Slider, LEFT/RIGHT to adjust slider, ENTER to confirm, ESC to go back")

    def handle_amount_menu_keys(self, key):
        if key in (arcade.key.UP, arcade.key.W):
            self.cursor_index = (self.cursor_index - 1) % 2
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.cursor_index = (self.cursor_index + 1) % 2
        elif key == arcade.key.LEFT and self.cursor_index == 1:
            self._slider_step(-1)
            self.slider_hold_elapsed = 0.0
            self.slider_repeat_timer = SLIDER_INITIAL_REPEAT_DELAY
        elif key == arcade.key.RIGHT and self.cursor_index == 1:
            self._slider_step(1)
            self.slider_hold_elapsed = 0.0
            self.slider_repeat_timer = SLIDER_INITIAL_REPEAT_DELAY
        elif key == arcade.key.ENTER:
            self._confirm_amount(self._selected_reference_moles())
        elif key == arcade.key.ESCAPE:
            self.mode = "select_vessel"
            self.reset_cursor()

    def _slider_grid_max(self) -> float:
        """The largest value that's an exact multiple of the recipe's
        scale_step and still <= pending_max_moles -- the slider's last
        "nice" stop before a final fractional jump up to the true max."""
        step = self.pending_definition.scale_step
        return math.floor((self.pending_max_moles / step) + 1e-9) * step

    def _slider_step(self, direction: int):
        step = self.pending_definition.scale_step
        floor = min(step, self.pending_max_moles)
        grid_max = self._slider_grid_max()

        if direction > 0:
            if self.slider_value >= grid_max - 1e-9:
                new_value = self.pending_max_moles  # final fractional jump to the true max
            else:
                new_value = min(self.slider_value + step, grid_max)
        else:
            if self.slider_value > grid_max + 1e-9:
                new_value = grid_max  # drop off the fractional top step onto the grid
            else:
                new_value = max(self.slider_value - step, floor)

        self.slider_value = new_value

    def _update_slider_hold(self, delta_time):
        direction = 0
        if arcade.key.LEFT in self.keys_held:
            direction -= 1
        if arcade.key.RIGHT in self.keys_held:
            direction += 1
        if direction == 0:
            self.slider_hold_elapsed = 0.0
            self.slider_repeat_timer = 0.0
            return

        self.slider_hold_elapsed += delta_time
        self.slider_repeat_timer -= delta_time
        if self.slider_repeat_timer <= 0:
            self._slider_step(direction)
            interval = max(SLIDER_MIN_REPEAT_INTERVAL,
                            SLIDER_INITIAL_REPEAT_DELAY - self.slider_hold_elapsed * SLIDER_REPEAT_ACCEL)
            self.slider_repeat_timer = interval

    def _confirm_amount(self, reference_moles: float):
        definition = self.pending_definition
        reagents = reagents_for_scale(definition, reference_moles)
        try:
            self.window.reaction_engine.start_reaction(
                inventory=self.window.chemical_inventory,
                equipment_inventory=self.window.equipment_inventory,
                reagents=reagents,
                solvent=definition.solvent,
                temperature=definition.temperature,
                time_hours=definition.time_hours,
                game_clock=self.window.game_clock,
                preferred_flask_id=self.pending_vessel.id,
                skills=self.window.player_skills,
            )
            self.mode = "notebook_active"
            self.reset_cursor()
            self.show_message("Reaction started.", arcade.color.DARK_GREEN)
        except (ValueError, EquipmentUnavailableError) as e:
            self.mode = "recipes"
            self.reset_cursor()
            self.show_message(str(e), arcade.color.RED)

    def try_collect_reaction(self, process):
        clock = self.window.game_clock
        if not process.is_ready(clock):
            # Checked here (rather than just calling collect_reaction and
            # catching ReactionNotReadyError) so the engine never has to
            # raise for a state the UI can trivially see coming -- but that
            # also means the engine's own logging never fires for this
            # case, so log it here instead.
            logger.debug("Reaction bench: '%s' not ready (%.2fh remaining)",
                          process.reaction_name, process.time_remaining(clock))
            self.show_message(f"Not ready yet: {process.time_remaining(clock):.1f}h remaining",
                arcade.color.DARK_YELLOW)
            return
        products = self.window.reaction_engine.collect_reaction(
            process.process_id, self.window.chemical_inventory,
            self.window.equipment_inventory, clock,
        )
        summary = ", ".join(f"{amt:.2f} mol {name}" for name, amt in products.items())
        self.show_message(f"Collected: {summary}", arcade.color.DARK_GREEN)
