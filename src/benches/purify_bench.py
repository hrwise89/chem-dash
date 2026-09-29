"""
The purification bench: pick a crude chemical, a scale/method, how many
columns/distillations to run concurrently (up to purification.
MAX_CONCURRENT_RUNS), and how much each one should purify. Running it is
a "time-consuming action" -- see purification.purify_batch() and
benches.ui_common.check_pass_out.

Three stages, each its own screen:
  "pick_crude" -- which crude chemical (list + icon + "used in" blurb).
  "method"     -- scale (tabs) x method (list, with owned column count),
                  and how many of that method to run at once (Tab).
  "sliders"    -- one slider per concurrent run (all sharing the same
                  min/max notches -- see purification.available_slider_
                  values), a live consumables total, and Enter to begin.

Built on the same ui_theme primitives (panels, fixed lists, the icon
panel, truncate_to_width/wrap_and_fit) as every other redesigned bench,
for the same reasons documented in shipping_bench.py/catalogue_bench.py.
"""

import arcade

from benches.ui_theme import (
    CP437_CURSOR,
    DIM_COLOR,
    FONT_STACK,
    PANEL_COLOR,
    Panel,
    ThemedBenchView,
    draw_fixed_list,
    draw_icon_panel,
    draw_page_indicator,
    draw_panel,
    draw_single_sprite,
    draw_slider,
    draw_tab_bar,
    draw_wrapped_lines,
    truncate_to_width,
    wrap_and_fit,
)
from benches.ui_common import check_pass_out
from day_manager import calendar_date_string, clock_time_string
from devtools import logger
from purification import (
    MAX_CONCURRENT_RUNS,
    PURIFY_METHOD_ORDER,
    PURIFY_SCALE_ORDER,
    PURIFY_SCALES,
    SILICA_NAME,
    available_slider_values,
    effective_time_hours,
    is_crude,
    mass_grams,
    max_concurrent_runs,
    method_is_available,
    purify_batch,
)
from settings import SCREEN_WIDTH
from sprites import texture_for

FLASK_SPRITE_KEY = "rb_flask"  # the one generic flask icon, reused everywhere there's no per-chemical art

# ---- "pick_crude" layout ----
CRUDE_LIST_PANEL = Panel(left=40, right=460, bottom=220, top=520)
CRUDE_ICON_PANEL = Panel(left=480, right=760, bottom=220, top=520)
CRUDE_LIST_FONT_SIZE = 12
CRUDE_LIST_ROW_HEIGHT = 24
CRUDE_LIST_BOTTOM_MARGIN = 36
CRUDE_ROWS_PER_PAGE = max(1, int((CRUDE_LIST_PANEL.height - CRUDE_LIST_BOTTOM_MARGIN) // CRUDE_LIST_ROW_HEIGHT))
CRUDE_PAGE_INDICATOR_Y = CRUDE_LIST_PANEL.bottom + 12

# ---- shared bottom description panel (all three stages) ----
DESCRIPTION_PANEL = Panel(left=40, right=760, bottom=90, top=200)
DESCRIPTION_FONT_SIZE = 10
DESCRIPTION_LINE_HEIGHT = 20
DESCRIPTION_MAX_LINES = max(1, int((DESCRIPTION_PANEL.height - 10) // DESCRIPTION_LINE_HEIGHT))

# ---- "method" layout ----
METHOD_LIST_PANEL = Panel(left=40, right=500, bottom=220, top=480)
CRUDE_NAME_PANEL = Panel(left=520, right=760, bottom=420, top=480)
COLUMNS_PANEL = Panel(left=520, right=760, bottom=220, top=400)
METHOD_LIST_FONT_SIZE = 10
METHOD_LIST_ROW_HEIGHT = 24
METHOD_LIST_BOTTOM_MARGIN = 36
METHOD_ROWS_PER_PAGE = max(1, int((METHOD_LIST_PANEL.height - METHOD_LIST_BOTTOM_MARGIN) // METHOD_LIST_ROW_HEIGHT))
METHOD_PAGE_INDICATOR_Y = METHOD_LIST_PANEL.bottom + 12
COLUMN_ICON_SIZE = 44

# ---- "sliders" layout ----
HEADER_PANEL = Panel(left=40, right=760, bottom=490, top=535)
SLIDER_ROW_CENTERS = [420, 340, 260]  # one per MAX_CONCURRENT_RUNS slot, top to bottom
SLIDER_ICON_X = 60
SLIDER_ICON_SIZE = 44
SLIDER_WIDTH = 220
SLIDER_CENTER_X = 430
SLIDER_HEIGHT = 22
SLIDER_LABEL_FONT_SIZE = 10
CONSUMABLES_PANEL = Panel(left=40, right=460, bottom=90, top=200)
TIME_PURITY_X = 500


class PurifyBenchView(ThemedBenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view)
        self.stage = "pick_crude"
        self.cursor_index = 0
        self.crude_name: str | None = None

        self.scale_index = 0
        self.method_cursor = 0
        self.run_count = 1
        self.slider_cursor = 0
        self.available_values: list[float] = []
        self.slider_indices: list[int] = []

        self.rows = []               # [(label, obj), ...] for the current list-based stage
        self.description_lines = []
        self._refresh_crude_rows()

    @property
    def scale_key(self) -> str:
        return PURIFY_SCALE_ORDER[self.scale_index]

    # ---- stage 1: pick a crude chemical ----

    def _crude_items(self):
        inventory = self.window.chemical_inventory
        return [name for name, amount in inventory.contents.items() if is_crude(name) and amount > 0]

    def _crude_row(self, name) -> str:
        inventory = self.window.chemical_inventory
        species = inventory.species_for(name)
        moles = inventory.moles_of(name)
        return f"{species.display_name} ({moles:.3f} mol)"

    def _crude_description(self, name) -> str:
        inventory = self.window.chemical_inventory
        species = inventory.species_for(name)
        pure_name = species.name  # crude's species entry is shared with its pure form
        products = self.window.reaction_engine.products_using(pure_name)
        if products:
            labels = [inventory.species_for(p).display_name if p in inventory.species_catalog else p
                      for p in products]
            used_in = ", ".join(labels)
        else:
            used_in = "nothing yet"
        return f"{species.name.title()}, Used in: {used_in}"

    def _refresh_crude_rows(self):
        items = self._crude_items()
        probe = self.text_pool.get("_probe_row", "", 0, 0, PANEL_COLOR,
                                    font_size=CRUDE_LIST_FONT_SIZE, font_name=FONT_STACK)
        max_width = CRUDE_LIST_PANEL.width - 60
        self.rows = [(truncate_to_width(probe, self._crude_row(n), max_width), n) for n in items]
        self.cursor_index = min(self.cursor_index, max(0, len(self.rows) - 1))
        self._refresh_crude_description()

    def _refresh_crude_description(self):
        if not self.rows:
            self.description_lines = []
            return
        _, name = self.rows[self.cursor_index]
        probe = self.text_pool.get("_probe_description", "", 0, 0, PANEL_COLOR,
                                    font_size=DESCRIPTION_FONT_SIZE, font_name=FONT_STACK)
        max_width = DESCRIPTION_PANEL.width - 20
        self.description_lines = wrap_and_fit(probe, self._crude_description(name), max_width,
                                               DESCRIPTION_MAX_LINES, font_size=DESCRIPTION_FONT_SIZE)

    def draw_pick_crude(self):
        draw_panel(CRUDE_LIST_PANEL)
        draw_fixed_list(CRUDE_LIST_PANEL, self.text_pool, "crude_list", [label for label, _ in self.rows],
                         self.cursor_index, CRUDE_ROWS_PER_PAGE, CRUDE_LIST_ROW_HEIGHT,
                         font_size=CRUDE_LIST_FONT_SIZE, empty_label="(no crude chemicals on hand)")
        draw_page_indicator(self.text_pool, "crude_page", CRUDE_LIST_PANEL.center_x, CRUDE_PAGE_INDICATOR_Y,
                             self.cursor_index, len(self.rows), CRUDE_ROWS_PER_PAGE)
        draw_icon_panel(CRUDE_ICON_PANEL, FLASK_SPRITE_KEY, self.text_pool, "crude_icon")
        draw_panel(DESCRIPTION_PANEL)
        draw_wrapped_lines(DESCRIPTION_PANEL, self.text_pool, "description", self.description_lines,
                            DESCRIPTION_LINE_HEIGHT, font_size=DESCRIPTION_FONT_SIZE)
        self.draw_instructions("U/D: Select   Enter: Choose   ESC: Leave", font_size=10)

    def handle_pick_crude_keys(self, key):
        if key == arcade.key.ESCAPE:
            logger.debug("Purify bench: left the bench, returning to lab floor")
            self.window.show_view(self.lab_view)
        elif key in (arcade.key.UP, arcade.key.W) and self.rows:
            self.cursor_index = (self.cursor_index - 1) % len(self.rows)
            self._refresh_crude_description()
        elif key in (arcade.key.DOWN, arcade.key.S) and self.rows:
            self.cursor_index = (self.cursor_index + 1) % len(self.rows)
            self._refresh_crude_description()
        elif key == arcade.key.ENTER and self.rows:
            _, self.crude_name = self.rows[self.cursor_index]
            self.scale_index = 0
            self.method_cursor = 0
            self.run_count = 1
            self.stage = "method"
            self._refresh_method_rows()
            logger.debug("Purify bench: picked crude '%s'", self.crude_name)

    # ---- stage 2: scale (tabs) x method (list) x run count (Tab) ----

    def _have_mass_g(self) -> float:
        inventory = self.window.chemical_inventory
        have_native = inventory.contents.get(self.crude_name, 0.0)
        return mass_grams(inventory, self.crude_name, have_native)

    def _method_items(self):
        """(label, method_key) pairs for methods actually runnable (owned
        equipment > 0) at the current scale tab -- a method with none
        owned is left off entirely, same as the old single-run menu."""
        equipment = self.window.equipment_inventory
        skills = self.window.player_skills
        probe = self.text_pool.get("_probe_row", "", 0, 0, PANEL_COLOR,
                                    font_size=METHOD_LIST_FONT_SIZE, font_name=FONT_STACK)
        max_width = METHOD_LIST_PANEL.width - 60
        options = []
        for method_key in PURIFY_METHOD_ORDER:
            if not method_is_available(self.scale_key, method_key, equipment, skills):
                continue
            method = PURIFY_SCALES[self.scale_key].methods[method_key]
            owned = len(equipment.available_items(method.equipment_type))
            label = method.label.replace("Column Chromatography", "Col. Chromatography")
            row = truncate_to_width(probe, f"{label}/({owned})", max_width)
            options.append((row, method_key))
        return options

    def _refresh_method_rows(self):
        self.rows = self._method_items()
        self.method_cursor = min(self.method_cursor, max(0, len(self.rows) - 1))
        self.run_count = 1
        self._refresh_method_description()

    def _current_method_key(self):
        if not self.rows:
            return None
        return self.rows[self.method_cursor][1]

    def _current_max_runs(self) -> int:
        method_key = self._current_method_key()
        if method_key is None:
            return 0
        return max_concurrent_runs(self.scale_key, method_key, self.window.equipment_inventory,
                                    self.window.player_skills)

    def _refresh_method_description(self):
        method_key = self._current_method_key()
        if method_key is None:
            self.description_lines = ["No equipment available at this scale."]
            return
        method = PURIFY_SCALES[self.scale_key].methods[method_key]
        values = available_slider_values(self.scale_key, self._have_mass_g())
        if values:
            lo_silica, lo_solvent = method.cost(values[0])
            hi_silica, hi_solvent = method.cost(values[-1])
        else:
            lo_silica = hi_silica = lo_solvent = hi_solvent = 0.0
        time_min = effective_time_hours(method, self.window.player_skills) * 60
        parts = [f"Time: {time_min:.0f} min.", f"Purity: {method.min_yield * 100:.0f}-{method.max_yield * 100:.0f}%"]
        consumes = []
        if method.solvent_name and (lo_solvent > 0 or hi_solvent > 0):
            consumes.append(f"{method.solvent_name} ({lo_solvent:.0f}-{hi_solvent:.0f} mL)")
        if lo_silica > 0 or hi_silica > 0:
            consumes.append(f"{SILICA_NAME} ({lo_silica:.0f}-{hi_silica:.0f} g)")
        if consumes:
            parts.append(f"Consumes: {', '.join(consumes)}.")
        text = ", ".join(parts)
        probe = self.text_pool.get("_probe_description", "", 0, 0, PANEL_COLOR,
                                    font_size=DESCRIPTION_FONT_SIZE, font_name=FONT_STACK)
        max_width = DESCRIPTION_PANEL.width - 20
        self.description_lines = wrap_and_fit(probe, text, max_width, DESCRIPTION_MAX_LINES,
                                               font_size=DESCRIPTION_FONT_SIZE)

    def draw_method(self):
        draw_tab_bar(self.text_pool, "scale_tab", SCREEN_WIDTH / 2, 505,
                     [PURIFY_SCALES[k].label.replace("-Scale", "") for k in PURIFY_SCALE_ORDER],
                     self.scale_index, spacing=160, font_size=12)

        draw_panel(METHOD_LIST_PANEL)
        draw_fixed_list(METHOD_LIST_PANEL, self.text_pool, "method_list", [label for label, _ in self.rows],
                         self.method_cursor, METHOD_ROWS_PER_PAGE, METHOD_LIST_ROW_HEIGHT,
                         font_size=METHOD_LIST_FONT_SIZE, empty_label="(no equipment at this scale)")
        draw_page_indicator(self.text_pool, "method_page", METHOD_LIST_PANEL.center_x, METHOD_PAGE_INDICATOR_Y,
                             self.method_cursor, len(self.rows), METHOD_ROWS_PER_PAGE)

        draw_panel(CRUDE_NAME_PANEL)
        inventory = self.window.chemical_inventory
        crude_label = inventory.species_for(self.crude_name).display_name
        self.text_pool.get("crude_name", crude_label, CRUDE_NAME_PANEL.center_x, CRUDE_NAME_PANEL.center_y,
                            PANEL_COLOR, font_size=16, font_name=FONT_STACK,
                            anchor_x="center", anchor_y="center").draw()

        draw_panel(COLUMNS_PANEL)
        max_runs = self._current_max_runs()
        slot_width = COLUMNS_PANEL.width / MAX_CONCURRENT_RUNS
        for i in range(MAX_CONCURRENT_RUNS):
            slot_center_x = COLUMNS_PANEL.left + slot_width * (i + 0.5)
            icon_y = COLUMNS_PANEL.top - 35
            texture = texture_for(FLASK_SPRITE_KEY)
            if i < max_runs and texture is not None:
                sprite = arcade.Sprite(texture, center_x=slot_center_x, center_y=icon_y)
                sprite.width = sprite.height = COLUMN_ICON_SIZE
                if i >= self.run_count:
                    sprite.alpha = 90
                draw_single_sprite(sprite)
        have_native = inventory.contents.get(self.crude_name, 0.0)
        have_moles = inventory.moles_of(self.crude_name)
        self.text_pool.get("columns_native", f"{have_native:.0f} mL" if inventory.species_for(self.crude_name).state
                            != "solid" else f"{have_native:.0f} g", COLUMNS_PANEL.left + 14,
                            COLUMNS_PANEL.bottom + 40, PANEL_COLOR, font_size=13, font_name=FONT_STACK,
                            anchor_x="left", anchor_y="center").draw()
        self.text_pool.get("columns_moles", f"{have_moles:.2f} mol", COLUMNS_PANEL.left + 14,
                            COLUMNS_PANEL.bottom + 18, PANEL_COLOR, font_size=13, font_name=FONT_STACK,
                            anchor_x="left", anchor_y="center").draw()

        draw_panel(DESCRIPTION_PANEL)
        draw_wrapped_lines(DESCRIPTION_PANEL, self.text_pool, "description", self.description_lines,
                            DESCRIPTION_LINE_HEIGHT, font_size=DESCRIPTION_FONT_SIZE)

        self.draw_instructions("L/R: Scale   U/D: Method   Tab: # Col.   Enter: Next   ESC: Back", font_size=8)

    def handle_method_keys(self, key):
        if key == arcade.key.ESCAPE:
            self.stage = "pick_crude"
            self._refresh_crude_rows()
        elif key == arcade.key.LEFT:
            self.scale_index = (self.scale_index - 1) % len(PURIFY_SCALE_ORDER)
            self.method_cursor = 0
            self._refresh_method_rows()
        elif key == arcade.key.RIGHT:
            self.scale_index = (self.scale_index + 1) % len(PURIFY_SCALE_ORDER)
            self.method_cursor = 0
            self._refresh_method_rows()
        elif key in (arcade.key.UP, arcade.key.W) and self.rows:
            self.method_cursor = (self.method_cursor - 1) % len(self.rows)
            self.run_count = 1
            self._refresh_method_description()
        elif key in (arcade.key.DOWN, arcade.key.S) and self.rows:
            self.method_cursor = (self.method_cursor + 1) % len(self.rows)
            self.run_count = 1
            self._refresh_method_description()
        elif key == arcade.key.TAB and self.rows:
            max_runs = self._current_max_runs()
            if max_runs > 0:
                self.run_count = self.run_count % max_runs + 1
        elif key == arcade.key.ENTER and self.rows:
            self._begin_sliders()

    def _begin_sliders(self):
        self.available_values = available_slider_values(self.scale_key, self._have_mass_g())
        if not self.available_values:
            self.show_message(f"Not enough {self.crude_name} on hand to purify.", arcade.color.RED)
            return
        self.slider_indices = [len(self.available_values) - 1] * self.run_count  # default to each row's max
        self.slider_cursor = 0
        self.stage = "sliders"
        self._refresh_slider_description()

    # ---- stage 3: one slider per concurrent run ----

    def _method(self):
        return PURIFY_SCALES[self.scale_key].methods[self._current_method_key()]

    def _slider_masses(self) -> list[float]:
        return [self.available_values[i] for i in self.slider_indices]

    def _refresh_slider_description(self):
        method = self._method()
        time_min = effective_time_hours(method, self.window.player_skills) * 60
        self.description_lines = [f"Time: {time_min:.0f} min.",
                                   f"Purity: {method.min_yield * 100:.0f}-{method.max_yield * 100:.0f}%"]

    def draw_sliders(self):
        inventory = self.window.chemical_inventory
        species = inventory.species_for(self.crude_name)
        have_native = inventory.contents.get(self.crude_name, 0.0)
        unit = "mL" if species.state != "solid" else "g"
        have_moles = inventory.moles_of(self.crude_name)

        draw_panel(HEADER_PANEL)
        header_text = (f"{species.display_name}, {species.name.title()}: "
                        f"{have_native:.0f} {unit}, {have_moles:.2f} mol")
        probe = self.text_pool.get("_probe_header", "", 0, 0, PANEL_COLOR, font_size=14, font_name=FONT_STACK)
        header_text = truncate_to_width(probe, header_text, HEADER_PANEL.width - 20)
        self.text_pool.get("header", header_text, HEADER_PANEL.center_x, HEADER_PANEL.center_y, PANEL_COLOR,
                            font_size=14, font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()

        method = self._method()
        for i in range(MAX_CONCURRENT_RUNS):
            active = i < self.run_count
            y = SLIDER_ROW_CENTERS[i]
            color = PANEL_COLOR if active else DIM_COLOR
            texture = texture_for(FLASK_SPRITE_KEY)
            if texture is not None:
                sprite = arcade.Sprite(texture, center_x=SLIDER_ICON_X, center_y=y)
                sprite.width = sprite.height = SLIDER_ICON_SIZE
                if not active:
                    sprite.alpha = 80
                draw_single_sprite(sprite)
            if active and i == self.slider_cursor:
                self.text_pool.get(f"slider_cursor_{i}", CP437_CURSOR, 20, y, color,
                                    font_size=14, font_name=FONT_STACK, anchor_x="left", anchor_y="center").draw()
            if active:
                mass_g = self.available_values[self.slider_indices[i]]
                fraction = 0.0 if len(self.available_values) <= 1 else (
                    self.slider_indices[i] / (len(self.available_values) - 1))
                min_label = PURIFY_SCALES[self.scale_key].format_amount(self.available_values[0])
                max_label = PURIFY_SCALES[self.scale_key].format_amount(self.available_values[-1])
                draw_slider(self.text_pool, f"slider_{i}", SLIDER_CENTER_X, y, SLIDER_WIDTH, SLIDER_HEIGHT,
                            fraction, min_label=f"{min_label} (min)", max_label=f"{max_label} (max)",
                            color=PANEL_COLOR, fill_color=PANEL_COLOR, handle_color=DIM_COLOR,
                            label_font_size=SLIDER_LABEL_FONT_SIZE)
                value_label = PURIFY_SCALES[self.scale_key].format_amount(mass_g)
                self.text_pool.get(f"slider_value_{i}", value_label, SLIDER_CENTER_X, y - 22, color,
                                    font_size=12, font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()
            else:
                self.text_pool.get(f"slider_value_{i}", "0", SLIDER_CENTER_X, y - 22, color,
                                    font_size=12, font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()

        draw_panel(CONSUMABLES_PANEL)
        masses = self._slider_masses()
        total_silica_g = sum(method.cost(m)[0] for m in masses)
        total_solvent_ml = sum(method.cost(m)[1] for m in masses)
        consumables = self.window.consumables
        lines_y = CONSUMABLES_PANEL.top - 24
        self.text_pool.get("cons_header", "Consumed / Owned", CONSUMABLES_PANEL.left + 14,
                            lines_y, PANEL_COLOR, font_size=11, font_name=FONT_STACK,
                            anchor_x="left", anchor_y="center").draw()
        row_i = 0
        if method.solvent_name and total_solvent_ml > 0:
            owned = consumables.contents.get(method.solvent_name, 0.0)
            catalog_entry = self.window.consumable_catalog.get(method.solvent_name)
            solvent_display = catalog_entry.display_name if catalog_entry else method.solvent_name
            solvent_probe = self.text_pool.get("_probe_cons", "", 0, 0, PANEL_COLOR,
                                                font_size=11, font_name=FONT_STACK)
            solvent_line = truncate_to_width(
                solvent_probe, f"{solvent_display}: {total_solvent_ml:.1f} / {owned:.1f} mL",
                CONSUMABLES_PANEL.width - 28)
            self.text_pool.get("cons_solvent", solvent_line,
                                CONSUMABLES_PANEL.left + 14, lines_y - 24 - row_i * 22, PANEL_COLOR,
                                font_size=11, font_name=FONT_STACK, anchor_x="left", anchor_y="center").draw()
            row_i += 1
        if total_silica_g > 0:
            owned = consumables.contents.get(SILICA_NAME, 0.0)
            self.text_pool.get("cons_silica", f"{SILICA_NAME}: {total_silica_g:.1f} / {owned:.1f} g",
                                CONSUMABLES_PANEL.left + 14, lines_y - 24 - row_i * 22, PANEL_COLOR,
                                font_size=11, font_name=FONT_STACK, anchor_x="left", anchor_y="center").draw()

        for i, line in enumerate(self.description_lines):
            self.text_pool.get(f"time_purity_{i}", line, TIME_PURITY_X, CONSUMABLES_PANEL.top - 24 - i * 22,
                                PANEL_COLOR, font_size=12, font_name=FONT_STACK,
                                anchor_x="left", anchor_y="center").draw()

        self.draw_instructions("U/D: Row   L/R: Slider   Enter: Begin   ESC: Back   M/Z: Max/Min", font_size=8)

    def handle_slider_keys(self, key):
        if key == arcade.key.ESCAPE:
            self.stage = "method"
            self._refresh_method_rows()
        elif key in (arcade.key.UP, arcade.key.W) and self.run_count > 1:
            self.slider_cursor = (self.slider_cursor - 1) % self.run_count
        elif key in (arcade.key.DOWN, arcade.key.S) and self.run_count > 1:
            self.slider_cursor = (self.slider_cursor + 1) % self.run_count
        elif key == arcade.key.LEFT:
            i = self.slider_cursor
            self.slider_indices[i] = max(0, self.slider_indices[i] - 1)
        elif key == arcade.key.RIGHT:
            i = self.slider_cursor
            self.slider_indices[i] = min(len(self.available_values) - 1, self.slider_indices[i] + 1)
        elif key == arcade.key.M:
            self.slider_indices[self.slider_cursor] = len(self.available_values) - 1
        elif key == arcade.key.Z:
            self.slider_indices[self.slider_cursor] = 0
        elif key == arcade.key.ENTER:
            self.try_purify()

    def try_purify(self):
        method_key = self._current_method_key()
        skills = self.window.player_skills
        try:
            results = purify_batch(
                self.scale_key, method_key, self.window.chemical_inventory, self.window.equipment_inventory,
                self.window.consumables, self.window.game_clock, self.crude_name, self._slider_masses(),
                skills=skills,
            )
        except ValueError as e:
            self.show_message(str(e), arcade.color.RED)
            return

        if check_pass_out(self.window, self.lab_view):
            return  # the elapsed purification time pushed the player past their limit for the day

        scale = PURIFY_SCALES[self.scale_key]
        pure_name = results[0][0]
        total_purified = sum(m for _, m, _ in results)
        total_display = total_purified * scale.display_divisor
        method = self._method()
        time_min = effective_time_hours(method, skills) * 60
        self.show_message(
            f"Purified {total_display:.2f} {scale.display_unit} {pure_name} across {len(results)} run(s), "
            f"-{time_min:.0f} min", arcade.color.DARK_GREEN,
        )
        self.stage = "pick_crude"
        self.cursor_index = 0
        self._refresh_crude_rows()

    # ---- drawing / input dispatch ----

    def on_draw(self):
        self.clear()

        hours = self.window.day_manager.hours_into_day(self.window.game_clock)
        self.draw_status_bar(
            clock_time_string(hours),
            f"${self.window.wallet.balance:.2f}",
            calendar_date_string(self.window.day_manager.current_day),
        )

        if self.stage == "pick_crude":
            self.draw_pick_crude()
        elif self.stage == "method":
            self.draw_method()
        elif self.stage == "sliders":
            self.draw_sliders()

        self.draw_message()

    def on_key_press(self, key, modifiers):
        if self.stage == "pick_crude":
            self.handle_pick_crude_keys(key)
        elif self.stage == "method":
            self.handle_method_keys(key)
        elif self.stage == "sliders":
            self.handle_slider_keys(key)
