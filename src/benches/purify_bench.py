"""
The purification bench: pick a scale (Micro/Bench for now -- Pilot and
Production are visible but always disabled), a method (Column
Chromatography or Distillation, each gated on owning the matching column
for that scale), a crude chemical, and how much of it to purify. Running
it is a "time-consuming action" -- see purification.purify() and
benches.ui_common.check_pass_out.
"""

import arcade

from benches.ui_common import LIST_START_Y, BenchView, check_pass_out
from devtools import logger
from inventory import bench_for_equipment_type
from purification import (
    PURIFY_METHOD_ORDER,
    PURIFY_SCALE_ORDER,
    PURIFY_SCALES,
    SILICA_NAME,
    available_slider_values,
    effective_time_hours,
    is_crude,
    mass_grams,
    method_is_available,
    purify,
    scale_is_available,
)

PURIFY_SLIDER_WIDTH = 500
PURIFY_SLIDER_HEIGHT = 26
PURIFY_BENCH_TAG = "purify"


class PurifyBenchView(BenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view, title="Purify")
        # "menu" | "method" | "pick_crude" | "pick_amount" | "supplies"
        self.mode = "menu"
        self.scale_key = None
        self.method_key = None
        self.pending_crude_name = None
        self.available_values: list[float] = []   # ascending mass-in-grams notches
        self.amount_index = 0

    # ---- scale menu ----

    def _scale_menu_options(self):
        """(label, enabled) pairs for the top-level scale menu, in
        PURIFY_SCALE_ORDER, plus a always-enabled Supplies entry."""
        equipment = self.window.equipment_inventory
        options = []
        for key in PURIFY_SCALE_ORDER:
            spec = PURIFY_SCALES[key]
            enabled = scale_is_available(key, equipment, self.window.player_skills)
            label = spec.range_label() if enabled else f"{spec.range_label()} (not available)"
            options.append((label, enabled))
        options.append(("Supplies", True))
        return options

    def draw_menu(self):
        self.draw_title("Purify")
        self.draw_centered_menu(self._scale_menu_options())
        self._draw_crude_summary(LIST_START_Y - len(self._scale_menu_options()) * 40 - 20)
        self.draw_instructions("UP/DOWN to choose, ENTER to select, ESC to leave bench")

    def handle_menu_keys(self, key):
        options = self._scale_menu_options()
        if key in (arcade.key.UP, arcade.key.W):
            self.cursor_index = (self.cursor_index - 1) % len(options)
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.cursor_index = (self.cursor_index + 1) % len(options)
        elif key == arcade.key.ENTER:
            label, enabled = options[self.cursor_index]
            if not enabled:
                return
            if label == "Supplies":
                self.mode = "supplies"
                self.reset_cursor()
            else:
                self.scale_key = PURIFY_SCALE_ORDER[self.cursor_index]
                self.mode = "method"
                self.reset_cursor()
                logger.debug("Purify bench: entered '%s' scale", self.scale_key)
        elif key == arcade.key.ESCAPE:
            logger.debug("Purify bench: left the bench, returning to lab floor")
            self.window.show_view(self.lab_view)

    # ---- method menu (Column Chromatography / Distillation) ----

    def _method_menu_options(self):
        """(label, method_key) pairs for only the methods actually
        runnable at this scale -- unlike the top-level scale menu, a
        method you don't own the column for is left off the list
        entirely rather than shown greyed out."""
        equipment = self.window.equipment_inventory
        options = []
        for method_key in PURIFY_METHOD_ORDER:
            if not method_is_available(self.scale_key, method_key, equipment, self.window.player_skills):
                continue
            method = PURIFY_SCALES[self.scale_key].methods[method_key]
            options.append((method.label, method_key))
        return options

    def draw_method_menu(self):
        self.draw_title(f"{PURIFY_SCALES[self.scale_key].label} Purification")
        options = self._method_menu_options()
        self.draw_centered_menu([(label, True) for label, _ in options])
        self._draw_crude_summary(LIST_START_Y - len(options) * 40 - 20)
        self.draw_instructions("UP/DOWN to choose, ENTER to select, ESC to go back")

    def handle_method_keys(self, key):
        options = self._method_menu_options()
        if key in (arcade.key.UP, arcade.key.W) and options:
            self.cursor_index = (self.cursor_index - 1) % len(options)
        elif key in (arcade.key.DOWN, arcade.key.S) and options:
            self.cursor_index = (self.cursor_index + 1) % len(options)
        elif key == arcade.key.ENTER and options:
            _, method_key = options[self.cursor_index]
            self.method_key = method_key
            self.mode = "pick_crude"
            self.reset_cursor()
        elif key == arcade.key.ESCAPE:
            self.mode = "menu"
            self.reset_cursor()

    def _draw_crude_summary(self, top_y: float):
        """A read-only "what crude product do I have" panel, shown on the
        scale and method menus (not just the crude picker) per the design
        note that this should be visible "from the first menu page and at
        each level as appropriate". Uses its own named text_pool keys, so
        it can't collide with draw_centered_menu's own int-keyed rows no
        matter how many the menu above it has."""
        center_x = self.title_text.x
        self.text_pool.get("crude_summary_header", "Crude products on hand:", center_x, top_y,
                            arcade.color.DARK_BLUE, font_size=14, anchor_x="center").draw()
        lines = [label for label, _ in self.crude_chemicals()] or ["(none)"]
        for i, line in enumerate(lines[:6]):
            self.text_pool.get(f"crude_summary_row_{i}", line, center_x, top_y - 22 - i * 20,
                                arcade.color.BLACK, font_size=13, anchor_x="center").draw()

    # ---- crude chemical picker ----

    def _crude_product_label(self, name: str, native_amount: float) -> str:
        """"<name>: <mass> g[, <volume> mL]" -- volume only shown for a
        liquid/solution, since a solid has no meaningful volume here."""
        inventory = self.window.chemical_inventory
        mass_g = mass_grams(inventory, name, native_amount)
        species = inventory.species_for(name)
        if species.state == "solid":
            return f"{name}: {mass_g:.2f} g"
        return f"{name}: {mass_g:.2f} g, {native_amount:.2f} mL"

    def crude_chemicals(self):
        """(label, chemical_name) pairs for every crude chemical currently
        in stock (amount > 0), showing name, mass, and volume (if any)."""
        inventory = self.window.chemical_inventory
        return [
            (self._crude_product_label(name, amount), name)
            for name, amount in inventory.contents.items()
            if is_crude(name) and amount > 0
        ]

    def draw_crude_picker(self):
        method = PURIFY_SCALES[self.scale_key].methods[self.method_key]
        self.draw_title(f"{PURIFY_SCALES[self.scale_key].label} {method.label} -- pick a crude chemical")
        items = self.crude_chemicals()
        self.draw_scrollable_list([label for label, _ in items],
            empty_message="(no crude chemicals on hand)")
        self.draw_instructions("UP/DOWN to choose, ENTER to select, ESC to go back")

    def handle_crude_picker_keys(self, key):
        items = self.crude_chemicals()
        if key in (arcade.key.UP, arcade.key.W) and items:
            self.cursor_index = (self.cursor_index - 1) % len(items)
            self.scroll_to_show_cursor()
        elif key in (arcade.key.DOWN, arcade.key.S) and items:
            self.cursor_index = (self.cursor_index + 1) % len(items)
            self.scroll_to_show_cursor()
        elif key == arcade.key.ENTER and items:
            _, crude_name = items[self.cursor_index]
            self._begin_amount_selection(crude_name)
        elif key == arcade.key.ESCAPE:
            self.mode = "method"
            self.reset_cursor()

    # ---- amount slider ----

    def _begin_amount_selection(self, crude_name):
        inventory = self.window.chemical_inventory
        have_native = inventory.contents.get(crude_name, 0.0)
        have_mass_g = mass_grams(inventory, crude_name, have_native)
        self.available_values = available_slider_values(self.scale_key, have_mass_g)
        if not self.available_values:
            min_notch = PURIFY_SCALES[self.scale_key].slider_values_g[0]
            self.show_message(
                f"Not enough {crude_name} on hand (need at least "
                f"{self._format_amount(min_notch)}).", arcade.color.RED,
            )
            return
        self.pending_crude_name = crude_name
        self.amount_index = len(self.available_values) - 1  # default to the most you can afford
        self.mode = "pick_amount"
        self.reset_cursor()

    def _format_amount(self, mass_g: float) -> str:
        return PURIFY_SCALES[self.scale_key].format_amount(mass_g)

    def draw_amount_screen(self):
        scale = PURIFY_SCALES[self.scale_key]
        method = scale.methods[self.method_key]
        mass_g = self.available_values[self.amount_index]
        silica_g, solvent_ml = method.cost(mass_g)

        inventory = self.window.chemical_inventory
        have_native = inventory.contents.get(self.pending_crude_name, 0.0)
        have_mass_g = mass_grams(inventory, self.pending_crude_name, have_native)

        self.draw_title(f"{scale.label} {method.label} -- {self.pending_crude_name}")
        self.draw_centered_menu([(f"{self._format_amount(mass_g)} selected", True)])

        center_x = self.title_text.x
        self.text_pool.get("available", f"Available: {self._format_amount(have_mass_g)}",
                            center_x, LIST_START_Y - 45,
                            arcade.color.DARK_BLUE, font_size=13, anchor_x="center").draw()
        bar_y = LIST_START_Y - 40 - 30
        left = center_x - PURIFY_SLIDER_WIDTH / 2
        right = center_x + PURIFY_SLIDER_WIDTH / 2
        bottom = bar_y - PURIFY_SLIDER_HEIGHT / 2
        top = bar_y + PURIFY_SLIDER_HEIGHT / 2

        last_index = len(self.available_values) - 1
        fraction = 0.0 if last_index == 0 else self.amount_index / last_index
        fill_x = left + PURIFY_SLIDER_WIDTH * fraction

        arcade.draw_lrbt_rectangle_outline(left, right, bottom, top, arcade.color.BLACK, border_width=2)
        if fraction > 0:
            arcade.draw_lrbt_rectangle_filled(left, fill_x, bottom, top, arcade.color.ORANGE)
        arcade.draw_line(fill_x, bottom - 8, fill_x, top + 8, arcade.color.RED, 3)

        cost_lines = [f"Cost: {silica_g:.1f} g {SILICA_NAME}" if silica_g > 0 else None,
                      f"{solvent_ml:.1f} mL {method.solvent_name}" if solvent_ml > 0 else None]
        summary = ", ".join(line for line in cost_lines if line) or "Cost: none"
        self.text_pool.get("cost_summary", summary, center_x, bar_y - 34, arcade.color.DARK_BLUE,
                            font_size=13, anchor_x="center").draw()
        time_hours = effective_time_hours(method, self.window.player_skills)
        self.text_pool.get("time_yield",
            f"Time: {time_hours * 60:.0f} min   Yield: {method.min_yield * 100:.0f}"
            f"-{method.max_yield * 100:.0f}%",
            center_x, bar_y - 54, arcade.color.DARK_BLUE, font_size=13, anchor_x="center").draw()

        self.draw_instructions("LEFT/RIGHT to adjust amount, ENTER to confirm, ESC to go back")

    def handle_amount_keys(self, key):
        if key == arcade.key.LEFT:
            self.amount_index = max(0, self.amount_index - 1)
        elif key == arcade.key.RIGHT:
            self.amount_index = min(len(self.available_values) - 1, self.amount_index + 1)
        elif key == arcade.key.ENTER:
            self.try_purify()
        elif key == arcade.key.ESCAPE:
            self.mode = "pick_crude"
            self.reset_cursor()

    def try_purify(self):
        mass_g = self.available_values[self.amount_index]
        scale = PURIFY_SCALES[self.scale_key]
        method = scale.methods[self.method_key]
        skills = self.window.player_skills
        try:
            pure_name, purified_mass_g, yield_fraction = purify(
                self.scale_key, self.method_key, self.window.chemical_inventory,
                self.window.equipment_inventory, self.window.consumables, self.window.game_clock,
                self.pending_crude_name, mass_g, skills=skills,
            )
        except ValueError as e:
            self.show_message(str(e), arcade.color.RED)
            return

        if check_pass_out(self.window, self.lab_view):
            return  # the elapsed purification time pushed the player past their limit for the day

        self.mode = "menu"
        self.reset_cursor()
        purified_display = purified_mass_g * scale.display_divisor
        time_hours = effective_time_hours(method, skills)
        self.show_message(
            f"Purified {purified_display:.2f} {scale.display_unit} {pure_name} "
            f"({yield_fraction * 100:.0f}% yield, -{time_hours * 60:.0f} min)",
            arcade.color.DARK_GREEN,
        )

    # ---- supplies (read-only) ----

    def supplies_lines(self):
        """Equipment listed here is only what's actually in your
        inventory and tagged for the purify bench -- a column you don't
        own doesn't show up at all (the catalog is only consulted to know
        which bench an owned item belongs to). Consumables still come
        from the shared catalog (src/data/consumables.json) so you can
        see you're out of one."""
        equipment = self.window.equipment_inventory
        equipment_catalog = self.window.equipment_catalog
        consumables = self.window.consumables
        consumable_catalog = self.window.consumable_catalog

        groups = {}  # equipment type -> {"name": str, "available": int, "total": int}
        for item in equipment.items.values():
            if bench_for_equipment_type(equipment_catalog, item.type) != PURIFY_BENCH_TAG:
                continue
            group = groups.setdefault(item.type, {"name": item.name, "available": 0, "total": 0})
            group["total"] += 1
            if not item.in_use:
                group["available"] += 1

        lines = ["Equipment"]
        if groups:
            for group in sorted(groups.values(), key=lambda g: g["name"]):
                lines.append(f"{group['name']}: {group['available']} available / {group['total']} total")
        else:
            lines.append("(none)")

        lines.append("")
        lines.append("Consumables")
        for name, entry in consumable_catalog.items():
            if PURIFY_BENCH_TAG not in entry.bench:
                continue
            amount = consumables.contents.get(name, 0.0)
            lines.append(f"{name}: {amount:.1f} {entry.unit}")
        return lines

    def draw_supplies(self):
        self.draw_title("SUPPLIES")
        self.draw_scrollable_list(self.supplies_lines())
        self.draw_instructions("UP/DOWN to browse, ESC to go back")

    def handle_supplies_keys(self, key):
        if key == arcade.key.ESCAPE:
            self.mode = "menu"
            self.reset_cursor()

    # ---- drawing / input dispatch ----

    def on_draw(self):
        self.clear()
        self.draw_bench()

        if self.mode == "menu":
            self.draw_menu()
        elif self.mode == "method":
            self.draw_method_menu()
        elif self.mode == "pick_crude":
            self.draw_crude_picker()
        elif self.mode == "pick_amount":
            self.draw_amount_screen()
        elif self.mode == "supplies":
            self.draw_supplies()

        self.draw_message()

    def on_key_press(self, key, modifiers):
        if self.mode == "menu":
            self.handle_menu_keys(key)
        elif self.mode == "method":
            self.handle_method_keys(key)
        elif self.mode == "pick_crude":
            self.handle_crude_picker_keys(key)
        elif self.mode == "pick_amount":
            self.handle_amount_keys(key)
        elif self.mode == "supplies":
            self.handle_supplies_keys(key)
