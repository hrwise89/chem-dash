import arcade
from settings import SCREEN_WIDTH, SCREEN_HEIGHT
from devtools import logger
from inventory import EquipmentUnavailableError
from reaction_engine import batch_reagents_for_flask

# ---- Layout ----
# The bench sprite lives in its own strip at the top of the screen so the
# menu text below it never overlaps it. The reaction-count indicator (white
# squares, for now) is drawn along the bench's bottom edge.
BENCH_CENTER_X = SCREEN_WIDTH // 2
BENCH_CENTER_Y = SCREEN_HEIGHT - 90
BENCH_WIDTH = 400
BENCH_HEIGHT = 140

TITLE_Y = BENCH_CENTER_Y - BENCH_HEIGHT / 2 - 30
LIST_START_Y = TITLE_Y - 50
INSTRUCTIONS_Y = 40
MESSAGE_Y = 80

INDICATOR_SIZE = 20
INDICATOR_GAP = 8
INDICATOR_MAX_SHOWN = 8

MESSAGE_DURATION = 3.5


class Bench(arcade.SpriteSolidColor):
    def __init__(self, center_x, center_y, width=500, height=200, color=arcade.color.BLACK):
        super().__init__(width, height, center_x, center_y, color)


class TextPool:
    """
    A small pool of reusable arcade.Text objects, indexed by position.
    arcade.draw_text() is a known-slow function when called every frame (it
    builds a fresh pyglet Label from scratch each time); the recommended fix
    is arcade.Text objects, but creating a NEW Text object every frame is
    still wasteful. This pool grows as needed and hands back the same Text
    object for a given index on every call, so on_draw only ever updates a
    couple of attributes on already-built Text objects.
    """

    def __init__(self):
        self._pool: list[arcade.Text] = []

    def get(self, index: int, text: str, x: float, y: float, color,
            font_size: int = 16, anchor_x: str = "left") -> arcade.Text:
        while len(self._pool) <= index:
            self._pool.append(arcade.Text("", 0, 0, arcade.color.BLACK, anchor_x="left"))
        t = self._pool[index]
        t.text = text
        t.x = x
        t.y = y
        t.color = color
        t.font_size = font_size
        t.anchor_x = anchor_x
        return t

    def size(self) -> int:
        return len(self._pool)


class ReactionBenchView(arcade.View):
    def __init__(self, window, lab_view):
        super().__init__()
        self.window = window
        self.lab_view = lab_view

        self.mode = "overview"                      # "overview" | "equipment" | "recipes" | "notebook" | "inventory"
        self.sections = ["equipment", "recipes", "notebook", "inventory"]
        self.selected_index = 0                      # cursor within self.sections (overview mode)
        self.cursor_index = 0                         # cursor within whatever list the section shows

        # On-screen status/error message (replaces printing to the console,
        # which is invisible during normal play).
        self.message = ""
        self.message_color = arcade.color.BLACK
        self.message_timer = 0.0

        arcade.set_background_color(arcade.color.LIGHT_GRAY)

        self.benches = arcade.SpriteList()
        self.benches.append(Bench(BENCH_CENTER_X, BENCH_CENTER_Y, BENCH_WIDTH, BENCH_HEIGHT))

        # Reused Text objects -- see TextPool's docstring for why.
        self.text_pool = TextPool()
        self.title_text = arcade.Text("", SCREEN_WIDTH / 2, TITLE_Y,
            arcade.color.BLACK, font_size=24, anchor_x="center")
        self.instructions_text = arcade.Text("", SCREEN_WIDTH / 2, INSTRUCTIONS_Y,
            arcade.color.DARK_GRAY, font_size=14, anchor_x="center")
        self.message_text = arcade.Text("", SCREEN_WIDTH / 2, MESSAGE_Y,
            arcade.color.BLACK, font_size=14, anchor_x="center")

    # ---- status messages ----

    def show_message(self, text: str, color=arcade.color.BLACK, duration: float = MESSAGE_DURATION):
        self.message = text
        self.message_color = color
        self.message_timer = duration

    def on_update(self, delta_time):
        if self.message_timer > 0:
            self.message_timer -= delta_time
            if self.message_timer <= 0:
                self.message = ""

    # ---- what's in each section ----

    def current_list(self):
        """(label, underlying_object) pairs for whichever section is active,
        so drawing and key-handling share one source of truth."""
        if self.mode == "equipment":
            items = self.window.equipment_inventory.items.values()
            labels = []
            for i in items:
                status = "IN USE" if i.in_use else "free"
                capacity = f", {i.capacity:.2f} mol" if i.capacity is not None else ""
                labels.append((f"{i.name} ({status}{capacity})", i))
            return labels

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

    # ---- drawing ----

    def on_draw(self):
        self.clear()
        self.benches.draw()
        self.draw_active_process_indicator()

        if self.mode == "overview":
            self.draw_overview()
        else:
            self.draw_section()

        if self.message:
            self.message_text.text = self.message
            self.message_text.color = self.message_color
            self.message_text.draw()

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
        self.title_text.text = "Reaction Bench"
        self.title_text.draw()

        for i, section in enumerate(self.sections):
            color = arcade.color.RED if i == self.selected_index else arcade.color.ORANGE
            prefix = "> " if i == self.selected_index else "  "
            self.text_pool.get(i, f"{prefix}{section}", SCREEN_WIDTH / 2,
                LIST_START_Y - i * 40, color, font_size=20, anchor_x="center").draw()

        self.instructions_text.text = "UP/DOWN to choose, ENTER to select, ESC to leave bench"
        self.instructions_text.draw()

    def draw_section(self):
        self.title_text.text = self.mode.upper()
        self.title_text.draw()

        items = self.current_list()
        if not items:
            self.text_pool.get(0, "(nothing here yet)", SCREEN_WIDTH / 2, LIST_START_Y,
                arcade.color.DARK_GRAY, font_size=16, anchor_x="center").draw()
        else:
            for i, (label, _) in enumerate(items):
                color = arcade.color.RED if i == self.cursor_index else arcade.color.BLACK
                prefix = "> " if i == self.cursor_index else "  "
                self.text_pool.get(i, f"{prefix}{label}", 80,
                    LIST_START_Y - i * 30, color, font_size=16).draw()

        if self.mode == "notebook":
            self.instructions_text.text = "UP/DOWN to choose, ENTER to collect, F to warp time, ESC to go back"
        elif self.mode == "recipes":
            self.instructions_text.text = "UP/DOWN to choose, ENTER to start, ESC to go back"
        else:
            self.instructions_text.text = "UP/DOWN to browse, ESC to go back"
        self.instructions_text.draw()

    # ---- input ----

    def on_key_press(self, key, modifiers):
        if self.mode == "overview":
            self.handle_overview_keys(key)
        else:
            self.handle_section_keys(key)

    def handle_overview_keys(self, key):
        if key in (arcade.key.UP, arcade.key.A):
            self.selected_index = (self.selected_index - 1) % len(self.sections)
        elif key in (arcade.key.DOWN, arcade.key.D):
            self.selected_index = (self.selected_index + 1) % len(self.sections)
        elif key in (arcade.key.ENTER, arcade.key.SPACE):
            self.mode = self.sections[self.selected_index]
            self.cursor_index = 0
            logger.debug("Bench: entered '%s' section", self.mode)
        elif key == arcade.key.ESCAPE:
            logger.debug("Bench: left the bench, returning to lab floor")
            self.window.show_view(self.lab_view)

    def handle_section_keys(self, key):
        items = self.current_list()
        if key in (arcade.key.UP, arcade.key.W) and items:
            self.cursor_index = (self.cursor_index - 1) % len(items)
        elif key in (arcade.key.DOWN, arcade.key.S) and items:
            self.cursor_index = (self.cursor_index + 1) % len(items)
        elif key == arcade.key.ENTER and items:
            self.activate_selected(items[self.cursor_index])
        elif key == arcade.key.F and self.mode == "notebook" and items:
            _, process = items[self.cursor_index]
            self.window.game_clock.advance_to(process.end_time)   # "warp to end"
            logger.info("Warped game clock to t=%.2fh for '%s'", process.end_time, process.reaction_name)
            self.show_message(f"Warped time to {process.end_time:.1f}h", arcade.color.DARK_YELLOW)
        elif key == arcade.key.ESCAPE:
            logger.debug("Bench: back to overview from '%s'", self.mode)
            self.mode = "overview"

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
            self.cursor_index = 0
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
            logger.debug("Bench: '%s' not ready (%.2fh remaining)",
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
