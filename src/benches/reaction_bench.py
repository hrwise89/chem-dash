"""
The reaction bench: run a known reaction (pick a recipe and a vessel
together on one screen, then an amount -- modeled on the purify bench's
own pick -> method -> sliders flow), collect one once it's ready, and
browse equipment/reagents/consumables -- all through the same 4-panel
grid style as the notebook and computer bench.

Active Reactions and Inventory are the exact screens the notebook shows
(see benches/shared_sections.py) -- Active Reactions is also collectible
here (ENTER collects a ready process; F warps the game clock straight to
a selected process's end_time, a dev/testing shortcut deliberately left
out of the on-screen instructions). Start Reaction is new: pick a recipe
(the Known Reactions list, reused for its data/sorting only -- this
screen draws its own smaller copy of that list alongside a vessel list,
rather than the full-width single-list shape ReactionsSection.draw()
itself produces) and a free vessel for it side by side on one screen
(LEFT/RIGHT switches which list has focus, UP/DOWN scrolls it), then an
amount via a slider with the same held-key auto-repeat purify_bench.py's
sliders use.

With only 4 panels (rather than 6), there's room in two of them for a
small at-a-glance indicator: Active Reactions shows a row of small squares
(green = ready) for each reaction currently running, and Start Reaction
shows the player's owned RB flasks, dimmed if in use -- both read straight
off the same window state the sections themselves use, not a separate
tracked count.
"""
import math

import arcade

from benches.shared_sections import FLASK_SPRITE_KEY, InventorySection, ReactionsSection, display_name, equation_text
from benches.ui_common import check_pass_out
from benches.ui_theme import (
    CP437_CURSOR, DIM_COLOR, FONT_STACK, PANEL_COLOR, Panel, ThemedBenchView,
    draw_description_panel, draw_panel, draw_single_sprite, draw_slider, draw_titled_list_panel,
    draw_wrapped_lines, truncate_to_width,
)
from day_manager import calendar_date_string, clock_time_string
from devtools import logger
from inventory import EquipmentUnavailableError
from reaction_engine import reaction_scale_bounds, reagents_for_scale, reference_reagent_for
from sprites import texture_for
from units import format_moles

# ---- main grid: 2x2, more room per panel than the notebook's 2x3 since
# there are only 4 -- used for the running-reactions/flask indicators ----
GRID_COLUMNS = 2
BUTTONS = [
    ("Active\nReactions", "active_reactions"),
    ("Start\nReaction", "start_pick"),
    ("Inventory", "inventory"),
    ("Placeholder", None),
]
GRID_LEFT = 40
GRID_RIGHT = 760
GRID_TOP = 520
GRID_BOTTOM = 60
COLUMN_GAP = 20
ROW_GAP = 20
GRID_ROWS = -(-len(BUTTONS) // GRID_COLUMNS)

_col_width = (GRID_RIGHT - GRID_LEFT - COLUMN_GAP * (GRID_COLUMNS - 1)) / GRID_COLUMNS
_row_height = (GRID_TOP - GRID_BOTTOM - ROW_GAP * (GRID_ROWS - 1)) / GRID_ROWS


def _panel_rect(index: int) -> Panel:
    row, col = divmod(index, GRID_COLUMNS)
    left = GRID_LEFT + col * (_col_width + COLUMN_GAP)
    top = GRID_TOP - row * (_row_height + ROW_GAP)
    return Panel(left=left, right=left + _col_width, bottom=top - _row_height, top=top)


PANEL_RECTS = [_panel_rect(i) for i in range(len(BUTTONS))]

INDICATOR_SQUARE_SIZE = 14
INDICATOR_GAP = 6
INDICATOR_MAX_SHOWN = 10
FLASK_ICON_SIZE = 28
FLASK_ICON_GAP = 8
FLASK_ICON_MAX_SHOWN = 8

# ---- "start_pick": recipe list + vessel list side by side, ala the
# purify bench's own merged scale/method/run-count screen -- both lists
# have plenty of room this way instead of each having its own full-width
# screen with mostly empty space around a short list ----
PICK_ROW_HEIGHT = 22
PICK_LIST_FONT_SIZE = 10
RECIPE_PANEL = Panel(left=40, right=390, bottom=350, top=520)
VESSEL_PANEL = Panel(left=410, right=760, bottom=350, top=520)
PICK_EQUATION_Y = 325
PICK_DESC_PANEL = Panel(left=40, right=760, bottom=50, top=300)
PICK_DESC_FONT_SIZE = 8
PICK_DESC_LINE_HEIGHT = 18

# ---- "start_amount": one slider, held-repeat identical to purify_bench.
# py's own (see that module's HOLD_REPEAT_DELAY/HOLD_TRAVERSAL_SECONDS) ----
HOLD_REPEAT_DELAY = 0.2
HOLD_TRAVERSAL_SECONDS = 1.0
HEADER_PANEL = Panel(left=40, right=760, bottom=490, top=535)
SLIDER_Y = 430
SLIDER_WIDTH = 420
SLIDER_HEIGHT = 22
VALUE_Y = 400
WARNING_FONT_SIZE = 9
WARNING_Y = 368
WARNING_Y2 = 352
PREVIEW_PANEL = Panel(left=40, right=760, bottom=120, top=320)
PREVIEW_LINE_HEIGHT = 20
PREVIEW_FONT_SIZE = 10


class ReactionBenchView(ThemedBenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view)
        self.stage = "grid"
        self.cursor_index = 0

        self.active_reactions = ReactionsSection(running=True, collectible=True)
        self.inventory = InventorySection()
        # Used only for its .items(window) (the known-reaction list, sorted
        # by product) and .cursor -- start_pick draws its own smaller
        # side-by-side layout rather than calling ReactionsSection.draw().
        self.recipe_section = ReactionsSection(running=False)

        # Recipe-start sub-flow state, set as the player moves through it
        # (recipe+vessel picked together on "start_pick" -> amount):
        self.pick_focus = "recipe"  # "recipe" | "vessel"
        self.vessel_cursor = 0
        self.pending_definition = None
        self.pending_vessel = None
        self.pending_min_moles = 0.0
        self.pending_max_moles = 0.0
        self.pending_limiting_factor = None

        self.slider_value = 0.0
        self.held_key = None
        self.held_time = 0.0
        self._repeat_accum = 0.0

    # ---- update ----

    def on_update(self, delta_time):
        super().on_update(delta_time)
        if self.window.notebook.is_open:
            return
        if self.stage != "start_amount" or self.held_key not in (arcade.key.LEFT, arcade.key.RIGHT):
            return
        self.held_time += delta_time
        if self.held_time < HOLD_REPEAT_DELAY:
            return
        last = max(1, int(self.pending_max_moles / self.pending_definition.scale_step))
        steps_per_second = last / HOLD_TRAVERSAL_SECONDS
        self._repeat_accum += steps_per_second * delta_time
        steps = int(self._repeat_accum)
        if steps > 0:
            self._repeat_accum -= steps
            direction = -1 if self.held_key == arcade.key.LEFT else 1
            self._slider_step(direction, steps)

    # ---- drawing ----

    def draw_content(self):
        self.clear()
        hours = self.window.day_manager.hours_into_day(self.window.game_clock)
        self.draw_status_bar(
            clock_time_string(hours),
            f"${self.window.wallet.balance:.2f}",
            calendar_date_string(self.window.day_manager.current_day),
        )

        if self.stage == "grid":
            self._draw_grid()
        elif self.stage == "active_reactions":
            self.active_reactions.draw(self.window, self.text_pool, "Up/Down: Scroll   Enter: Collect   ESC: Back")
        elif self.stage == "inventory":
            self.inventory.draw(self.window, self.text_pool, "L/R: Tabs   Up/Down: Scroll   ESC: Back")
        elif self.stage == "start_pick":
            self._draw_pick_screen()
        elif self.stage == "start_amount":
            self._draw_amount_screen()

        self.draw_message()

    def _draw_grid(self):
        for i, (label, _) in enumerate(BUTTONS):
            panel = PANEL_RECTS[i]
            draw_panel(panel)
            color = arcade.color.WHITE if i == self.cursor_index else PANEL_COLOR
            lines = label.split("\n")
            line_height = 28
            text_x = panel.left + 40
            first_line_y = panel.top - 30 - line_height * (len(lines) - 1) / 2
            for line_num, line in enumerate(lines):
                self.text_pool.get(f"grid_{i}_{line_num}", line, text_x, first_line_y - line_num * line_height,
                                    color, font_size=16, font_name=FONT_STACK,
                                    anchor_x="left", anchor_y="center").draw()
            if i == self.cursor_index:
                self.text_pool.get(f"grid_cursor_{i}", CP437_CURSOR, panel.left + 14, first_line_y,
                                    color, font_size=16, font_name=FONT_STACK,
                                    anchor_x="left", anchor_y="center").draw()

            if label.replace("\n", " ") == "Active Reactions":
                self._draw_active_indicator(panel)
            elif label.replace("\n", " ") == "Start Reaction":
                self._draw_flask_indicator(panel)

        self.draw_instructions("ARROWS: move   ENTER: select   ESC: leave")

    def _draw_active_indicator(self, panel: Panel):
        processes = list(self.window.reaction_engine.active_processes.values())
        if not processes:
            self.text_pool.get("active_indicator_label", "(none running)", panel.center_x, panel.bottom + 50,
                                DIM_COLOR, font_size=11, font_name=FONT_STACK, anchor_x="center").draw()
            return
        ready_count = sum(1 for p in processes if p.is_ready(self.window.game_clock))
        active_count = len(processes) - ready_count
        self.text_pool.get("active_indicator_label", f"{active_count} active   {ready_count} ready",
                            panel.center_x, panel.bottom + 60, PANEL_COLOR, font_size=11,
                            font_name=FONT_STACK, anchor_x="center").draw()

        shown = min(len(processes), INDICATOR_MAX_SHOWN)
        total_width = shown * INDICATOR_SQUARE_SIZE + (shown - 1) * INDICATOR_GAP
        start_x = panel.center_x - total_width / 2 + INDICATOR_SQUARE_SIZE / 2
        y = panel.bottom + 30
        for i in range(shown):
            x = start_x + i * (INDICATOR_SQUARE_SIZE + INDICATOR_GAP)
            color = arcade.color.GREEN if processes[i].is_ready(self.window.game_clock) else PANEL_COLOR
            half = INDICATOR_SQUARE_SIZE / 2
            arcade.draw_lrbt_rectangle_filled(x - half, x + half, y - half, y + half, color)

    def _draw_flask_indicator(self, panel: Panel):
        flasks = [item for item in self.window.equipment_inventory.items.values() if item.type == "rb_flask"]
        if not flasks:
            self.text_pool.get("flask_indicator_label", "(no flasks owned)", panel.center_x, panel.bottom + 50,
                                DIM_COLOR, font_size=11, font_name=FONT_STACK, anchor_x="center").draw()
            return
        free = sum(1 for f in flasks if not f.in_use)
        self.text_pool.get("flask_indicator_label", f"Flasks: {free}/{len(flasks)} free",
                            panel.center_x, panel.bottom + 60, PANEL_COLOR, font_size=11,
                            font_name=FONT_STACK, anchor_x="center").draw()

        shown = min(len(flasks), FLASK_ICON_MAX_SHOWN)
        total_width = shown * FLASK_ICON_SIZE + (shown - 1) * FLASK_ICON_GAP
        start_x = panel.center_x - total_width / 2 + FLASK_ICON_SIZE / 2
        y = panel.bottom + 30
        texture = texture_for(FLASK_SPRITE_KEY)
        for i in range(shown):
            x = start_x + i * (FLASK_ICON_SIZE + FLASK_ICON_GAP)
            if texture is None:
                half = FLASK_ICON_SIZE / 2
                color = PANEL_COLOR if not flasks[i].in_use else DIM_COLOR
                arcade.draw_lrbt_rectangle_outline(x - half, x + half, y - half, y + half, color, border_width=2)
                continue
            sprite = arcade.Sprite(texture, center_x=x, center_y=y)
            sprite.width = sprite.height = FLASK_ICON_SIZE
            if flasks[i].in_use:
                sprite.alpha = 90
            draw_single_sprite(sprite)

    def _draw_pick_screen(self):
        window = self.window
        inventory = window.chemical_inventory
        recipes = self.recipe_section.items(window)
        probe = self.text_pool.get("pick_probe", "", 0, 0, PANEL_COLOR,
                                    font_size=PICK_LIST_FONT_SIZE, font_name=FONT_STACK)

        recipe_color = PANEL_COLOR if self.pick_focus == "recipe" else DIM_COLOR
        recipe_rows = [truncate_to_width(probe, display_name(inventory, next(iter(d.products))),
                                          RECIPE_PANEL.width - 40)
                       for d in recipes]
        draw_titled_list_panel(RECIPE_PANEL, self.text_pool, "pick_recipe", recipe_rows, self.recipe_section.cursor,
                                PICK_ROW_HEIGHT, title="-Pick a Recipe-", font_size=PICK_LIST_FONT_SIZE,
                                color=recipe_color)

        definition = recipes[self.recipe_section.cursor] if recipes else None
        vessel_color = PANEL_COLOR if self.pick_focus == "vessel" else DIM_COLOR
        vessel_choices = self._vessel_choices_for(definition)
        vessel_rows = [truncate_to_width(probe, label, VESSEL_PANEL.width - 40) for label, _ in vessel_choices]
        draw_titled_list_panel(VESSEL_PANEL, self.text_pool, "pick_vessel", vessel_rows, self.vessel_cursor,
                                PICK_ROW_HEIGHT, title="-Pick a Vessel-", font_size=PICK_LIST_FONT_SIZE,
                                color=vessel_color, empty_label="(no free flask available)")

        if definition is not None:
            self.text_pool.get("pick_equation", equation_text(inventory, definition), 400, PICK_EQUATION_Y,
                                PANEL_COLOR, font_size=14, font_name=FONT_STACK,
                                anchor_x="center", anchor_y="center").draw()
            if self.pick_focus == "vessel" and vessel_choices:
                _, vessel = vessel_choices[self.vessel_cursor]
                self._draw_vessel_preview(definition, vessel)
            else:
                product_name = next(iter(definition.products))
                description = window.reaction_engine.used_in_summary(inventory, product_name)
                draw_description_panel(PICK_DESC_PANEL, self.text_pool, "pick_desc", description,
                                        font_size=PICK_DESC_FONT_SIZE)
        else:
            draw_panel(PICK_DESC_PANEL)

        self.draw_instructions("L/R: Focus   U/D: Scroll   Enter: Pick   ESC: Back", font_size=8)

    def _draw_amount_screen(self):
        definition = self.pending_definition
        inventory = self.window.chemical_inventory
        draw_panel(HEADER_PANEL)
        self.text_pool.get("amount_header", equation_text(inventory, definition), HEADER_PANEL.center_x,
                            HEADER_PANEL.center_y, PANEL_COLOR, font_size=16, font_name=FONT_STACK,
                            anchor_x="center", anchor_y="center").draw()

        fraction = 0.0 if self.pending_max_moles <= 0 else self.slider_value / self.pending_max_moles
        ref = reference_reagent_for(definition)
        native = self._native_amount_desc(ref, self.slider_value)
        draw_slider(self.text_pool, "amount_slider", 400, SLIDER_Y, SLIDER_WIDTH, SLIDER_HEIGHT, fraction,
                    min_label="0", max_label=f"{self.pending_max_moles:.2f} mol", label_font_size=11)

        below_min = self.slider_value < self.pending_min_moles
        value_color = arcade.color.DARK_YELLOW if below_min else PANEL_COLOR
        self.text_pool.get("amount_value", f"{self.slider_value:.2f} mol {ref} ({native}) selected",
                            400, VALUE_Y, value_color, font_size=14, font_name=FONT_STACK,
                            anchor_x="center", anchor_y="center").draw()
        if below_min:
            self.text_pool.get("amount_warning_1", "Below minimum recommended volume for glassware.",
                                400, WARNING_Y, arcade.color.DARK_YELLOW, font_size=WARNING_FONT_SIZE,
                                font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()
            self.text_pool.get("amount_warning_2", "Yield may suffer.",
                                400, WARNING_Y2, arcade.color.DARK_YELLOW, font_size=WARNING_FONT_SIZE,
                                font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()

        draw_panel(PREVIEW_PANEL)
        preview_probe = self.text_pool.get("preview_probe", "", 0, 0, PANEL_COLOR,
                                            font_size=PREVIEW_FONT_SIZE, font_name=FONT_STACK)
        max_width = PREVIEW_PANEL.width - 24
        y = PREVIEW_PANEL.top - PREVIEW_LINE_HEIGHT
        for i, line in enumerate(self._preview_lines()):
            if line == "":
                y -= PREVIEW_LINE_HEIGHT / 2
                continue
            line = truncate_to_width(preview_probe, line, max_width)
            self.text_pool.get(f"preview_{i}", line, PREVIEW_PANEL.left + 12, y, PANEL_COLOR,
                                font_size=PREVIEW_FONT_SIZE, font_name=FONT_STACK,
                                anchor_x="left", anchor_y="center").draw()
            y -= PREVIEW_LINE_HEIGHT

        self.draw_instructions("LEFT/RIGHT: adjust   ENTER: confirm   ESC: back")

    # ---- input ----

    def handle_content_keys(self, key, modifiers):
        if self.stage == "grid":
            self._handle_grid_keys(key)
        elif self.stage == "active_reactions":
            if key == arcade.key.ESCAPE:
                self.stage = "grid"
            else:
                self.active_reactions.handle_key(key, self.window, show_message=self.show_message)
                if key == arcade.key.F:
                    check_pass_out(self.window, self.lab_view)
        elif self.stage == "inventory":
            if key == arcade.key.ESCAPE:
                self.stage = "grid"
            else:
                self.inventory.handle_key(key, self.window)
        elif self.stage == "start_pick":
            self._handle_pick_keys(key)
        elif self.stage == "start_amount":
            self._handle_amount_keys(key)

    def on_key_release(self, key, modifiers):
        if key == self.held_key:
            self.held_key = None

    def _handle_grid_keys(self, key):
        if key == arcade.key.ESCAPE:
            logger.debug("Reaction bench: left the bench, returning to lab floor")
            self.window.show_view(self.lab_view)
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
            self._activate_grid()
            return
        else:
            return
        self.cursor_index = row * GRID_COLUMNS + col

    def _activate_grid(self):
        _, target = BUTTONS[self.cursor_index]
        if target is None:
            return
        self.stage = target

    # ---- recipe+vessel picking (one merged screen) -> amount ----

    def _vessel_choices_for(self, definition):
        """(label, EquipmentItem) pairs for every free rb_flask -- just its
        own name (the vessel list panel is only half-width on this merged
        screen, not enough room for a preview in the row itself; see
        _vessel_preview_for for that, shown in the description panel
        instead while a vessel is focused). Empty if no recipe is selected
        (no known reactions at all) rather than raising."""
        if definition is None:
            return []
        return [(item.name, item) for item in self.window.equipment_inventory.available_items("rb_flask")]

    def _draw_vessel_preview(self, definition, item):
        """What running `definition` at `item`'s max scale would actually
        take and make: max consumed per reagent, theoretical yield per
        product, and how much of each is currently on hand -- so the
        player can compare vessels/recipes without having to go start one
        to find out. Drawn as discrete lines (like the amount screen's own
        preview), not wrapped prose, since it's tabular data."""
        inventory = self.window.chemical_inventory
        bounds = reaction_scale_bounds(definition, inventory, item.capacity)
        if bounds is None:
            draw_panel(PICK_DESC_PANEL)
            draw_wrapped_lines(PICK_DESC_PANEL, self.text_pool, "pick_desc",
                                [f"{item.name}: no chemicals on hand for this reaction."],
                                PICK_DESC_LINE_HEIGHT, font_size=PICK_DESC_FONT_SIZE)
            return
        _, max_moles, limiting_factor = bounds
        reagents = reagents_for_scale(definition, max_moles)

        lines = [f"{item.name} at max scale ({max_moles:.2f} mol, limited by {limiting_factor}):",
                 "Reagents consumed:"]
        for name, moles in reagents.items():
            lines.extend(self._item_lines(name, moles, name == limiting_factor, show_on_hand=True))

        lines.append("")
        lines.append("Product(s) (theoretical):")
        ref = reference_reagent_for(definition)
        ref_coeff = definition.reactants[ref]
        scale = max_moles / ref_coeff if ref_coeff else 0.0
        for product, stoich in definition.products.items():
            moles = stoich * scale
            lines.extend(self._item_lines(product, moles, limiting=False, show_on_hand=True))

        draw_panel(PICK_DESC_PANEL)
        probe = self.text_pool.get("pick_desc_probe", "", 0, 0, PANEL_COLOR,
                                    font_size=PICK_DESC_FONT_SIZE, font_name=FONT_STACK)
        max_width = PICK_DESC_PANEL.width - 24
        lines = [truncate_to_width(probe, line, max_width) for line in lines]
        draw_wrapped_lines(PICK_DESC_PANEL, self.text_pool, "pick_desc", lines,
                            PICK_DESC_LINE_HEIGHT, font_size=PICK_DESC_FONT_SIZE)

    def _handle_pick_keys(self, key):
        if key == arcade.key.ESCAPE:
            if self.pick_focus == "vessel":
                self.pick_focus = "recipe"
            else:
                self.stage = "grid"
            return

        recipes = self.recipe_section.items(self.window)
        if key == arcade.key.LEFT:
            self.pick_focus = "recipe"
            return
        if key == arcade.key.RIGHT:
            definition = recipes[self.recipe_section.cursor] if recipes else None
            if self._vessel_choices_for(definition):
                self.pick_focus = "vessel"
            return

        if self.pick_focus == "recipe":
            if not recipes:
                return
            if key in (arcade.key.UP, arcade.key.W):
                self.recipe_section.cursor = (self.recipe_section.cursor - 1) % len(recipes)
                self.vessel_cursor = 0
            elif key in (arcade.key.DOWN, arcade.key.S):
                self.recipe_section.cursor = (self.recipe_section.cursor + 1) % len(recipes)
                self.vessel_cursor = 0
            elif key == arcade.key.ENTER:
                definition = recipes[self.recipe_section.cursor]
                if self._vessel_choices_for(definition):
                    self.pick_focus = "vessel"
            return

        definition = recipes[self.recipe_section.cursor] if recipes else None
        rows = self._vessel_choices_for(definition)
        if not rows:
            return
        if key in (arcade.key.UP, arcade.key.W):
            self.vessel_cursor = (self.vessel_cursor - 1) % len(rows)
        elif key in (arcade.key.DOWN, arcade.key.S):
            self.vessel_cursor = (self.vessel_cursor + 1) % len(rows)
        elif key == arcade.key.ENTER:
            _, vessel = rows[self.vessel_cursor]
            self._choose_vessel(definition, vessel)

    def _choose_vessel(self, definition, vessel):
        bounds = reaction_scale_bounds(definition, self.window.chemical_inventory, vessel.capacity)
        if bounds is None:
            self.show_message("You don't have the chemicals for this reaction.", arcade.color.RED)
            return
        self.pending_definition = definition
        self.pending_vessel = vessel
        self.pending_min_moles, self.pending_max_moles, self.pending_limiting_factor = bounds
        self._init_slider_value()
        self.stage = "start_amount"

    def dev_prime(self, stage: str):
        """Populates whatever pending_* state `stage` needs to draw at all,
        for dev/menu_lab.py jumping straight to it -- "start_amount" only
        exists once a recipe and vessel have actually been picked in the
        normal flow, so jumping there cold would draw against a None
        pending_definition. Auto-picks the first known recipe and first
        free vessel that actually has enough chemicals on hand; a no-op
        for every other stage (they don't need anything pre-filled)."""
        if stage != "start_amount":
            return
        recipes = self.recipe_section.items(self.window)
        for definition in recipes:
            vessels = self._vessel_choices_for(definition)
            for _, vessel in vessels:
                bounds = reaction_scale_bounds(definition, self.window.chemical_inventory, vessel.capacity)
                if bounds is not None:
                    self._choose_vessel(definition, vessel)
                    return

    # ---- amount screen ----

    def _init_slider_value(self):
        """A sensible starting slider_value, snapped onto the step grid so
        it could also be reached by stepping left/right from it."""
        step = self.pending_definition.scale_step
        floor = min(step, self.pending_max_moles)
        default = min(1.0, self.pending_max_moles)
        default = math.floor((default / step) + 1e-9) * step
        self.slider_value = max(floor, default)
        self.held_key = None
        self.held_time = 0.0
        self._repeat_accum = 0.0

    def _native_amount_desc(self, identity: str, moles: float) -> str:
        """'<amount> <unit>' for `moles` of `identity`, using whatever
        inventory entry currently supplies it -- or, if nothing supplies
        it yet (e.g. a product not yet in inventory), the species catalog
        entry for its own name. Falls back to plain moles if there's no
        species definition to convert with."""
        inventory = self.window.chemical_inventory
        lookup_name = inventory.resolve_supplier(identity) or identity
        try:
            species = inventory.species_for(lookup_name)
        except KeyError:
            return f"{moles:.2f} mol"
        amount = moles / species.moles_per_unit()
        return f"{amount:.1f} {species.unit_label()}"

    def _slider_grid_max(self) -> float:
        step = self.pending_definition.scale_step
        return math.floor((self.pending_max_moles / step) + 1e-9) * step

    def _slider_step(self, direction: int, count: int = 1):
        for _ in range(count):
            self._slider_step_once(direction)

    def _slider_step_once(self, direction: int):
        step = self.pending_definition.scale_step
        floor = min(step, self.pending_max_moles)
        grid_max = self._slider_grid_max()
        if direction > 0:
            if self.slider_value >= grid_max - 1e-9:
                self.slider_value = self.pending_max_moles  # final fractional jump to the true max
            else:
                self.slider_value = min(self.slider_value + step, grid_max)
        else:
            if self.slider_value > grid_max + 1e-9:
                self.slider_value = grid_max  # drop off the fractional top step onto the grid
            else:
                self.slider_value = max(self.slider_value - step, floor)

    def _on_hand_native_desc(self, name: str) -> str:
        """How much of `name` (resolved through whatever inventory entry
        actually supplies it) is currently on hand, in its native unit --
        "0" if nothing does, rather than raising."""
        inventory = self.window.chemical_inventory
        supplier = inventory.resolve_supplier(name) or name
        amount = inventory.contents.get(supplier, 0.0)
        try:
            species = inventory.species_for(supplier)
        except KeyError:
            return "0"
        return f"{amount:.1f} {species.unit_label()}"

    def _item_lines(self, name: str, moles: float, limiting: bool, show_on_hand: bool = False) -> list[str]:
        """Two lines for one reagent/product row: short name, moles, and
        native amount on the first; the full (unabbreviated) name (plus,
        if requested, how much is currently on hand) in parentheses on the
        second -- e.g.:
            HBr (aq): 0.60 mol, 68.2 mL (limiting)
              (48% hydrobromic acid) -- have 1500.0 mL
        `name` is looked up through whatever inventory entry actually
        supplies it (a solution's own concentration, not some other
        unit), same as the slider's own native readout."""
        inventory = self.window.chemical_inventory
        supplier = inventory.resolve_supplier(name) or name
        try:
            short = inventory.species_for(supplier).display_name
        except KeyError:
            short = name
        native = self._native_amount_desc(name, moles)
        tag = " (limiting)" if limiting else ""
        row2 = f"    ({supplier})"
        if show_on_hand:
            row2 = f"{row2} -- have {self._on_hand_native_desc(name)}"
        return [
            f"  {short}: {format_moles(moles)}, {native}{tag}",
            row2,
        ]

    def _preview_lines(self) -> list[str]:
        """Reagent amounts (moles + native units, naming whichever actual
        inventory item supplies each one, with the limiting reagent
        flagged, and how much is on hand) and theoretical (100%
        efficiency) product yield -- the "at a glance" info for whatever
        amount the slider is currently at."""
        definition = self.pending_definition
        reagents = reagents_for_scale(definition, self.slider_value)

        lines = ["Reagents consumed:"]
        for name, moles in reagents.items():
            lines.extend(self._item_lines(name, moles, name == self.pending_limiting_factor, show_on_hand=True))

        lines.append("")
        lines.append("Product(s) (theoretical):")
        ref = reference_reagent_for(definition)
        ref_coeff = definition.reactants[ref]
        scale = self.slider_value / ref_coeff if ref_coeff else 0.0
        for product, stoich in definition.products.items():
            moles = stoich * scale
            lines.extend(self._item_lines(product, moles, limiting=False, show_on_hand=True))
        return lines

    def _handle_amount_keys(self, key):
        if key == arcade.key.LEFT:
            self._slider_step(-1)
            self.held_key = arcade.key.LEFT
            self.held_time = 0.0
            self._repeat_accum = 0.0
        elif key == arcade.key.RIGHT:
            self._slider_step(1)
            self.held_key = arcade.key.RIGHT
            self.held_time = 0.0
            self._repeat_accum = 0.0
        elif key == arcade.key.ENTER:
            self._confirm_amount()
        elif key == arcade.key.ESCAPE:
            self.pick_focus = "vessel"
            self.stage = "start_pick"

    def _confirm_amount(self):
        definition = self.pending_definition
        reagents = reagents_for_scale(definition, self.slider_value)
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
            logger.info("Reaction bench: started a reaction for %.2f mol reference reagent", self.slider_value)
            self.show_message("Reaction started.", arcade.color.DARK_GREEN)
            self.stage = "grid"
        except (ValueError, EquipmentUnavailableError) as e:
            self.show_message(str(e), arcade.color.RED)
            self.pick_focus = "recipe"
            self.stage = "start_pick"
