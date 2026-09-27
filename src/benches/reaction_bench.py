"""
The reaction bench: browse your equipment/recipes/inventory, start a
reaction, and collect it from your notebook once it's ready.
"""

import math

import arcade
from devtools import logger
from inventory import EquipmentUnavailableError
from reaction_engine import reaction_scale_bounds, reagents_for_scale
from benches.ui_common import BenchView

# Placeholder category ordering for equipment rows: vessels first, then
# everything else alphabetically by type. A real tagging system (the kind
# that would also group e.g. "generic"/"hardware" equipment together) can
# replace this later -- for now there's only one vessel type anyway.
_VESSEL_TYPES = {"rb_flask"}

INDICATOR_SIZE = 20
INDICATOR_GAP = 8
INDICATOR_MAX_SHOWN = 8

# ---- Amount-picker slider ----
SLIDER_WIDTH = 500
SLIDER_HEIGHT = 26
SLIDER_Y_OFFSET = -10          # relative to LIST_START_Y
SLIDER_INITIAL_REPEAT_DELAY = 0.35   # seconds before a held key starts auto-repeating
SLIDER_MIN_REPEAT_INTERVAL = 0.04    # fastest auto-repeat once fully "held"
SLIDER_REPEAT_ACCEL = 0.05           # how fast the repeat interval shrinks with hold time


class ReactionBenchView(BenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view, title="Reaction Bench")
        # "overview" | "equipment" | "recipes" | "notebook" | "inventory"
        # | "select_vessel" | "select_amount" | "slider" (the last three are
        # the sub-flow for starting a reaction: pick a recipe -> pick a
        # vessel -> pick an amount, either "Max" or a hand-adjusted slider)
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
        self.amount_menu_options = ["Max", "Slider"]

        # Slider-specific state:
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

        if self.mode == "notebook":
            clock = self.window.game_clock
            procs = self.window.reaction_engine.active_processes.values()
            return [(f"{p.reaction_name} ({p.time_remaining(clock):.1f}h left)", p) for p in procs]

        if self.mode == "inventory":
            inventory = self.window.chemical_inventory
            return [(f"{name}: {inventory.describe(name)}", name) for name in inventory.contents]

        return []

    def _equipment_rows(self):
        """
        Group identical equipment (same type + capacity) into one row each,
        showing counts rather than one line per physical item -- otherwise
        owning 3 RB flasks means 3 near-identical rows. Sorted vessels
        (flasks) first, then everything else by type name.
        """
        groups = {}  # (type, capacity) -> {"name": str, "available": int, "in_use": int}
        for item in self.window.equipment_inventory.items.values():
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
        if self.mode == "slider":
            self._update_slider_hold(delta_time)

    def on_draw(self):
        self.clear()
        self.draw_bench()
        self.draw_active_process_indicator()

        if self.mode == "overview":
            self.draw_overview()
        elif self.mode == "select_vessel":
            self.draw_vessel_picker()
        elif self.mode == "select_amount":
            self.draw_amount_menu()
        elif self.mode == "slider":
            self.draw_slider_screen()
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

    def draw_section(self):
        self.draw_title(self.mode.upper())
        items = self.current_list()
        self.draw_scrollable_list([label for label, _ in items])

        if self.mode == "notebook":
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
        elif self.mode == "select_vessel":
            self.handle_vessel_keys(key)
        elif self.mode == "select_amount":
            self.handle_amount_menu_keys(key)
        elif self.mode == "slider":
            self.handle_slider_keys(key)
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
        elif key == arcade.key.F and self.mode == "notebook" and items:
            _, process = items[self.cursor_index]
            self.window.game_clock.advance_to(process.end_time)   # "warp to end"
            logger.info("Warped game clock to t=%.2fh for '%s'", process.end_time, process.reaction_name)
            self.show_message(f"Warped time to {process.end_time:.1f}h", arcade.color.DARK_YELLOW)
        elif key == arcade.key.ESCAPE:
            logger.debug("Reaction bench: back to overview from '%s'", self.mode)
            self.mode = "overview"
            self.reset_cursor()

    def activate_selected(self, selected):
        label, obj = selected
        if self.mode == "recipes":
            name, definition = obj
            self.begin_recipe_selection(name, definition)
        elif self.mode == "notebook":
            self.try_collect_reaction(obj)      # obj is a ReactionProcess
        # "equipment" and "inventory" are read-only for now -- nothing to activate

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
        """(label, EquipmentItem) pairs for every free rb_flask."""
        return [
            (f"{item.name} ({item.capacity:.0f} mL)", item)
            for item in self.window.equipment_inventory.available_items("rb_flask")
        ]

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
        self.pending_min_moles, self.pending_max_moles = bounds
        self.mode = "select_amount"
        self.reset_cursor()

    def draw_amount_menu(self):
        self.draw_title("PICK AN AMOUNT")
        self.draw_centered_menu([(option, True) for option in self.amount_menu_options])
        self.draw_instructions("UP/DOWN to choose, ENTER to select, ESC to go back")

    def handle_amount_menu_keys(self, key):
        if key in (arcade.key.UP, arcade.key.W):
            self.cursor_index = (self.cursor_index - 1) % len(self.amount_menu_options)
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.cursor_index = (self.cursor_index + 1) % len(self.amount_menu_options)
        elif key == arcade.key.ENTER:
            choice = self.amount_menu_options[self.cursor_index]
            if choice == "Max":
                self._confirm_amount(self.pending_max_moles)
            elif choice == "Slider":
                self._enter_slider()
        elif key == arcade.key.ESCAPE:
            self.mode = "select_vessel"
            self.reset_cursor()

    # ---- the slider itself ----

    def _enter_slider(self):
        step = self.pending_definition.scale_step
        floor = min(step, self.pending_max_moles)
        default = min(1.0, self.pending_max_moles)
        # Snap the default onto the step grid so the slider starts somewhere
        # it could also land on by stepping.
        default = math.floor((default / step) + 1e-9) * step
        self.slider_value = max(floor, default)
        self.slider_hold_elapsed = 0.0
        self.slider_repeat_timer = 0.0
        self.mode = "slider"

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

    def draw_slider_screen(self):
        self.draw_title(self.pending_name or "AMOUNT")

        center_x = self.title_text.x
        bar_y = self.title_text.y + SLIDER_Y_OFFSET - 60
        left = center_x - SLIDER_WIDTH / 2
        right = center_x + SLIDER_WIDTH / 2
        bottom = bar_y - SLIDER_HEIGHT / 2
        top = bar_y + SLIDER_HEIGHT / 2

        fraction = 0.0 if self.pending_max_moles <= 0 else self.slider_value / self.pending_max_moles
        fraction = max(0.0, min(1.0, fraction))
        fill_x = left + SLIDER_WIDTH * fraction

        arcade.draw_lrbt_rectangle_outline(left, right, bottom, top, arcade.color.BLACK, border_width=2)
        if fraction > 0:
            arcade.draw_lrbt_rectangle_filled(left, fill_x, bottom, top, arcade.color.ORANGE)

        # 1/4, 1/2, 3/4 tick marks
        for tick_fraction in (0.25, 0.5, 0.75):
            tick_x = left + SLIDER_WIDTH * tick_fraction
            arcade.draw_line(tick_x, bottom - 4, tick_x, top + 4, arcade.color.GRAY, 1)

        # Recommended-minimum marker
        if self.pending_max_moles > 0:
            min_fraction = max(0.0, min(1.0, self.pending_min_moles / self.pending_max_moles))
            min_x = left + SLIDER_WIDTH * min_fraction
            arcade.draw_line(min_x, bottom - 8, min_x, top + 8, arcade.color.DARK_YELLOW, 2)

        # Current-value indicator (doesn't need to land exactly on the fill edge)
        arcade.draw_line(fill_x, bottom - 8, fill_x, top + 8, arcade.color.RED, 3)

        below_min = self.slider_value < self.pending_min_moles
        value_color = arcade.color.DARK_YELLOW if below_min else arcade.color.BLACK
        self.text_pool.get(0, f"{self.slider_value:.2f} mol  (max {self.pending_max_moles:.2f} mol)",
            center_x, bar_y - 34, value_color, font_size=16, anchor_x="center").draw()

        if below_min:
            self.text_pool.get(1, "Below recommended minimum -- yield may suffer",
                center_x, bar_y - 56, arcade.color.DARK_YELLOW, font_size=13, anchor_x="center").draw()

        self.draw_instructions("LEFT/RIGHT to adjust, ENTER to confirm, ESC to go back")

    def handle_slider_keys(self, key):
        if key == arcade.key.LEFT:
            self._slider_step(-1)
            self.slider_hold_elapsed = 0.0
            self.slider_repeat_timer = SLIDER_INITIAL_REPEAT_DELAY
        elif key == arcade.key.RIGHT:
            self._slider_step(1)
            self.slider_hold_elapsed = 0.0
            self.slider_repeat_timer = SLIDER_INITIAL_REPEAT_DELAY
        elif key == arcade.key.ENTER:
            self._confirm_amount(self.slider_value)
        elif key == arcade.key.ESCAPE:
            self.mode = "select_amount"
            self.reset_cursor()

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
            )
            self.mode = "notebook"
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
