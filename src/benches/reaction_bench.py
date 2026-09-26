"""
The reaction bench: browse your equipment/recipes/inventory, start a
reaction, and collect it from your notebook once it's ready.
"""

import arcade
from devtools import logger
from inventory import EquipmentUnavailableError
from reaction_engine import batch_reagents_for_flask
from benches.ui_common import BenchView

# Placeholder category ordering for equipment rows: vessels first, then
# everything else alphabetically by type. A real tagging system (the kind
# that would also group e.g. "generic"/"hardware" equipment together) can
# replace this later -- for now there's only one vessel type anyway.
_VESSEL_TYPES = {"rb_flask"}

INDICATOR_SIZE = 20
INDICATOR_GAP = 8
INDICATOR_MAX_SHOWN = 8


class ReactionBenchView(BenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view, title="Reaction Bench")
        self.mode = "overview"                      # "overview" | "equipment" | "recipes" | "notebook" | "inventory"
        self.sections = ["equipment", "recipes", "notebook", "inventory"]

    # ---- what's in each section ----

    def current_list(self):
        """(label, underlying_object) pairs for whichever section is active,
        so drawing and key-handling share one source of truth."""
        if self.mode == "equipment":
            return self._equipment_rows()

        if self.mode == "recipes":
            labels = []
            for name, definition in self.window.reaction_engine.reaction_db.items():
                batch = batch_reagents_for_flask(definition)
                batch_desc = ", ".join(f"{amt:.2f} mol {chem}" for chem, amt in batch.items())
                labels.append((f"{name}  [batch: {batch_desc}]", definition))
            return labels

        if self.mode == "notebook":
            clock = self.window.game_clock
            procs = self.window.reaction_engine.active_processes.values()
            return [(f"{p.reaction_name} ({p.time_remaining(clock):.1f}h left)", p) for p in procs]

        if self.mode == "inventory":
            contents = self.window.chemical_inventory.contents
            return [(f"{name}: {amount:.2f} mol", name) for name, amount in contents.items()]

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
            capacity_desc = f", {capacity:.2f} mol" if capacity is not None else ""
            label = (f"{group['name']}{capacity_desc}  —  "
                     f"available: {group['available']}, in use: {group['in_use']}")
            rows.append((label, key))
        return rows

    # ---- drawing ----

    def on_draw(self):
        self.clear()
        self.draw_bench()
        self.draw_active_process_indicator()

        if self.mode == "overview":
            self.draw_overview()
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
        if self.mode == "overview":
            self.handle_overview_keys(key)
        else:
            self.handle_section_keys(key)

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
            self.try_start_reaction(obj)      # obj is a ReactionDefinition
        elif self.mode == "notebook":
            self.try_collect_reaction(obj)      # obj is a ReactionProcess
        # "equipment" and "inventory" are read-only for now -- nothing to activate

    def try_start_reaction(self, definition):
        batch = batch_reagents_for_flask(definition)
        try:
            self.window.reaction_engine.start_reaction(
                inventory=self.window.chemical_inventory,
                equipment_inventory=self.window.equipment_inventory,
                reagents=batch,
                solvent=definition.solvent,
                temperature=definition.temperature,
                time_hours=definition.time_hours,
                game_clock=self.window.game_clock,
            )
            self.mode = "notebook"
            self.reset_cursor()
            self.show_message("Reaction started.", arcade.color.DARK_GREEN)
        except (ValueError, EquipmentUnavailableError) as e:
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
