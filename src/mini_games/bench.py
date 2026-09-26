import arcade
from settings import (SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE, SPRITE_SCALING, TILE_SIZE, 
	GRID_WIDTH, GRID_HEIGHT, PLAYER_COLOR, MAP_BACKGROUND_COLOR)

class Bench(arcade.SpriteSolidColor):
    def __init__(self, center_x, center_y, width=500, height=200, color=arcade.color.BLACK):
        super().__init__(width, height, center_x, center_y, color)

class ReactionBenchView(arcade.View):
    def __init__(self, window, lab_view):
        super().__init__()
        self.window = window
        self.lab_view = lab_view

        self.mode = "overview"                      # "overview" | "equipment" | "recipes" | "notebook"
        self.sections = ["equipment", "recipes", "notebook"]
        self.selected_index = 0                      # cursor within self.sections (overview mode)
        self.cursor_index = 0                         # cursor within whatever list the section shows

        arcade.set_background_color(arcade.color.LIGHT_GRAY)

        self.benches = arcade.SpriteList()
        self.benches.append(Bench(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, 400, 200))

    def current_list(self):
        """(label, underlying_object) pairs for whichever section is active,
        so drawing and key-handling share one source of truth."""
        if self.mode == "equipment":
            items = self.window.equipment_inventory.items.values()
            return [(f"{i.name} ({'IN USE' if i.in_use else 'free'})", i) for i in items]

        if self.mode == "recipes":
            return list(self.window.reaction_engine.reaction_db.items())

        if self.mode == "notebook":
            clock = self.window.game_clock
            procs = self.window.reaction_engine.active_processes.values()
            return [(f"{p.reaction_name} ({p.time_remaining(clock):.1f}h left)", p) for p in procs]

        return []

    # ---- drawing ----

    def on_draw(self):
        self.clear()
        self.benches.draw()
        if self.mode == "overview":
            self.draw_overview()
        else:
            self.draw_section()

    def draw_overview(self):
        arcade.draw_text("Reaction Bench", SCREEN_WIDTH / 2, SCREEN_HEIGHT - 60,
            arcade.color.BLACK, font_size=24, anchor_x="center")
        start_y = SCREEN_HEIGHT / 2
        for i, section in enumerate(self.sections):
            color = arcade.color.RED if i == self.selected_index else arcade.color.ORANGE
            prefix = "> " if i == self.selected_index else "  "
            arcade.draw_text(f"{prefix}{section}", SCREEN_WIDTH / 2, start_y - i * 40,
                color, font_size=20, anchor_x="center")
        arcade.draw_text("UP/DOWN to choose, ENTER to select, ESC to leave bench",
            SCREEN_WIDTH / 2, 40, arcade.color.DARK_GRAY, font_size=14, anchor_x="center")

    def draw_section(self):
        arcade.draw_text(self.mode.upper(), SCREEN_WIDTH / 2, SCREEN_HEIGHT - 60,
            arcade.color.ORANGE, font_size=24, anchor_x="center")
        items = self.current_list()
        if not items:
            arcade.draw_text("(nothing here yet)", SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2,
                arcade.color.DARK_GRAY, font_size=16, anchor_x="center")
        else:
            start_y = SCREEN_HEIGHT - 120
            for i, (label, _) in enumerate(items):
                color = arcade.color.RED if i == self.cursor_index else arcade.color.BLACK
                prefix = "> " if i == self.cursor_index else "  "
                arcade.draw_text(f"{prefix}{label}", 80, start_y - i * 30, color, font_size=16)
        arcade.draw_text("UP/DOWN to choose, ENTER to act, F to warp time, ESC to go back",
            SCREEN_WIDTH / 2, 40, arcade.color.DARK_GRAY, font_size=14, anchor_x="center")

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
        elif key == arcade.key.ESCAPE:
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
        elif key == arcade.key.ESCAPE:
            self.mode = "overview"

    def activate_selected(self, selected):
        label, obj = selected
        if self.mode == "recipes":
            self.try_start_reaction(obj)      # obj is a ReactionDefinition
        elif self.mode == "notebook":
            self.try_collect_reaction(obj)      # obj is a ReactionProcess
        # "equipment" is read-only for now -- nothing to activate

    def try_start_reaction(self, definition):
        try:
            self.window.reaction_engine.start_reaction(
                inventory=self.window.chemical_inventory,
                equipment_inventory=self.window.equipment_inventory,
                reagents=definition.reactants,
                solvent=definition.solvent,
                temperature=definition.temperature,
                time_hours=definition.time_hours,
                game_clock=self.window.game_clock,
            )
            self.mode = "notebook"
            self.cursor_index = 0
        except (ValueError, EquipmentUnavailableError) as e:
            print(f"Can't start reaction: {e}")   # swap for an on-screen message later

    def try_collect_reaction(self, process):
        clock = self.window.game_clock
        if not process.is_ready(clock):
            print(f"Not ready yet: {process.time_remaining(clock):.1f}h remaining")
            return
        products = self.window.reaction_engine.collect_reaction(
            process.process_id, self.window.chemical_inventory,
            self.window.equipment_inventory, clock,
        )
        print(f"Collected: {products}")