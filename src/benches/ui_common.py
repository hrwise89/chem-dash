"""
Shared building blocks for the lab's bench views (ReactionBenchView,
PurifyBenchView, and future ones like it): a bench sprite, a scrollable or
centered menu, an on-screen status message, and word-wrapping so labels
never run off the edge of the screen.
"""

import arcade

from settings import SCREEN_HEIGHT, SCREEN_WIDTH

# ---- Shared layout ----
# Every bench view puts its bench sprite in the same strip at the top of
# the screen, with title/instructions/message on the same lines below it,
# and (when it shows a list) the same scrollable window below that -- so
# this lives here once instead of being copy-pasted into every view.
BENCH_CENTER_X = SCREEN_WIDTH // 2
BENCH_CENTER_Y = SCREEN_HEIGHT - 90
BENCH_WIDTH = 400
BENCH_HEIGHT = 140

TITLE_Y = BENCH_CENTER_Y - BENCH_HEIGHT / 2 - 30
LIST_START_Y = TITLE_Y - 50
INSTRUCTIONS_Y = 40
MESSAGE_Y = 80
MESSAGE_DURATION = 3.5

LIST_ROW_HEIGHT = 30
MAX_VISIBLE_ROWS = 8
LIST_LEFT_X = 80
LIST_RIGHT_MARGIN = 20
LIST_ROW_FONT_SIZE = 16


class Bench(arcade.SpriteSolidColor):
    """A simple solid-color desk/bench sprite. Swap for real art later."""
    def __init__(self, center_x, center_y, width=BENCH_WIDTH, height=BENCH_HEIGHT, color=arcade.color.BLACK):
        super().__init__(width, height, center_x, center_y, color)


class TextPool:
    """
    A small pool of reusable arcade.Text objects, keyed by whatever a
    caller wants to identify a given line with.
    arcade.draw_text() is a known-slow function when called every frame (it
    builds a fresh pyglet Label from scratch each time); the recommended fix
    is arcade.Text objects, but creating a NEW Text object every frame is
    still wasteful. This pool grows as needed and hands back the same Text
    object for a given key on every call, so on_draw only ever updates a
    couple of attributes on already-built Text objects.

    A key can be a plain int for a mechanically-generated row (a loop
    drawing one line per item, where the index IS the identity -- see
    draw_centered_menu/draw_scrollable_list below) or a short descriptive
    string for a one-off line a method draws by hand (e.g. "available",
    "cost_summary") -- prefer a string there. Two draw calls that use the
    same string key always share one Text object, so a string key only
    needs to be unique among the lines drawn *together* on one screen, not
    across the whole view -- unlike a hand-picked int offset, there's
    nothing to reserve or collide with.
    """

    def __init__(self):
        self._pool: dict[object, arcade.Text] = {}

    def get(self, key, text: str, x: float, y: float, color,
            font_size: int = 16, anchor_x: str = "left") -> arcade.Text:
        t = self._pool.get(key)
        if t is None:
            t = arcade.Text("", 0, 0, arcade.color.BLACK, anchor_x="left")
            self._pool[key] = t
        t.text = text
        t.x = x
        t.y = y
        t.color = color
        t.font_size = font_size
        t.anchor_x = anchor_x
        return t


def wrap_to_width(text: str, max_width: float, font_size: int = 16,
                   font_name: str | tuple[str, ...] = ("calibri", "arial")) -> list[str]:
    """
    Word-wrap `text` into however many lines it takes to keep each one no
    wider than max_width pixels at font_size, using a scratch arcade.Text to
    measure (arcade.Text.content_width needs an active window, so this can't
    be computed without one -- fine here since it's only ever called from
    on_draw). Returns [text] unchanged if it already fits on one line.

    A single word wider than max_width on its own is kept whole rather than
    split mid-word -- rare (a very long chemical name at a narrow width) and
    a mid-word break reads worse than a slightly-too-wide line.

    font_name matters here, not just cosmetically: a wider font (e.g.
    ui_theme.py's Perfect DOS VGA 437) wraps at a different point than the
    default, so pass whatever font_name the actual draw call will use or
    this measures against the wrong glyph widths.
    """
    probe = arcade.Text(text, 0, 0, arcade.color.BLACK, font_size=font_size, font_name=font_name)
    if probe.content_width <= max_width:
        return [text]

    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        probe.text = candidate
        if probe.content_width <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


class BenchView(arcade.View):
    """
    Common scaffolding for a "walk up to a bench, press SPACE" view: a bench
    sprite, an on-screen status message (replacing print(), which nobody
    sees during play), and two ways to lay out a menu:

      - draw_centered_menu(): a short vertical list of options centered
        under the title (a section overview, an Auto/Manual choice, ...).
      - draw_scrollable_list(): a left-aligned list that windows itself to
        MAX_VISIBLE_ROWS with a scroll indicator, and elides any label that
        would otherwise run off the right edge (equipment, recipes, ...).

    Subclasses own their own mode/state machine and cursor_index/
    scroll_offset (both initialized here to 0); they call these helpers
    from their own on_draw/on_key_press rather than this class assuming a
    particular menu structure.
    """

    def __init__(self, window, lab_view, title="", bench_color=arcade.color.BLACK):
        super().__init__()
        self.window = window
        self.lab_view = lab_view

        self.cursor_index = 0
        self.scroll_offset = 0

        self.message = ""
        self.message_color = arcade.color.BLACK
        self.message_timer = 0.0

        self.benches = arcade.SpriteList()
        self.benches.append(Bench(BENCH_CENTER_X, BENCH_CENTER_Y, color=bench_color))

        # Reused Text objects -- see TextPool's docstring for why.
        self.text_pool = TextPool()
        self.title_text = arcade.Text(title, SCREEN_WIDTH / 2, TITLE_Y,
            arcade.color.BLACK, font_size=24, anchor_x="center")
        self.scroll_indicator_text = arcade.Text("", SCREEN_WIDTH - LIST_RIGHT_MARGIN, TITLE_Y,
            arcade.color.DARK_GRAY, font_size=12, anchor_x="right")
        self.instructions_text = arcade.Text("", SCREEN_WIDTH / 2, INSTRUCTIONS_Y,
            arcade.color.DARK_GRAY, font_size=14, anchor_x="center")
        self.message_text = arcade.Text("", SCREEN_WIDTH / 2, MESSAGE_Y,
            arcade.color.BLACK, font_size=14, anchor_x="center")

    def on_show_view(self):
        # arcade.set_background_color() is global window state, not
        # per-view -- set it here (rather than only once in __init__) so
        # it's correct every time this bench is (re-)shown, regardless of
        # which view was showing before it.
        arcade.set_background_color(arcade.color.LIGHT_GRAY)

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

    # ---- drawing helpers ----

    def draw_bench(self):
        self.benches.draw()

    def draw_title(self, text: str):
        self.title_text.text = text
        self.title_text.draw()

    def draw_instructions(self, text: str):
        self.instructions_text.text = text
        self.instructions_text.draw()

    def draw_message(self):
        if self.message:
            self.message_text.text = self.message
            self.message_text.color = self.message_color
            self.message_text.draw()

    def draw_centered_menu(self, options: list[tuple[str, bool]]):
        """
        A short vertical menu centered under the title. `options` is a list
        of (label, enabled) pairs; a disabled option is greyed out even
        when the cursor sits on it (its label should already say why, e.g.
        "Manual Purify (not available)").
        """
        for i, (label, enabled) in enumerate(options):
            if i == self.cursor_index:
                color = arcade.color.RED if enabled else arcade.color.GRAY
            else:
                color = arcade.color.ORANGE if enabled else arcade.color.DARK_GRAY
            prefix = "> " if i == self.cursor_index else "  "
            self.text_pool.get(i, f"{prefix}{label}", SCREEN_WIDTH / 2,
                LIST_START_Y - i * 40, color, font_size=20, anchor_x="center").draw()
        # No scroll indicator makes sense for a short centered menu.
        self.scroll_indicator_text.text = ""
        self.scroll_indicator_text.draw()

    def draw_scrollable_list(self, labels: list[str], empty_message: str = "(nothing here yet)"):
        """
        A left-aligned list windowed to MAX_VISIBLE_ROWS *items* (not
        wrapped lines) around self.scroll_offset, highlighting
        self.cursor_index, word-wrapping any label too long for one line
        rather than truncating it, and showing an "X-Y of N" indicator once
        the list is longer than one screenful.
        """
        if not labels:
            self.scroll_indicator_text.text = ""
            self.text_pool.get(0, empty_message, SCREEN_WIDTH / 2, LIST_START_Y,
                arcade.color.DARK_GRAY, font_size=16, anchor_x="center").draw()
            self.scroll_indicator_text.draw()
            return

        visible = labels[self.scroll_offset:self.scroll_offset + MAX_VISIBLE_ROWS]
        # Reserve room for the "> "/"  " prefix so a wrapped line still fits
        # inside the screen alongside it.
        max_label_width = SCREEN_WIDTH - LIST_LEFT_X - LIST_RIGHT_MARGIN - 20
        text_index = 0
        y = LIST_START_Y
        for row, label in enumerate(visible):
            i = self.scroll_offset + row  # actual index into `labels`
            color = arcade.color.RED if i == self.cursor_index else arcade.color.BLACK
            wrapped_lines = wrap_to_width(label, max_label_width, font_size=LIST_ROW_FONT_SIZE)
            for line_num, line in enumerate(wrapped_lines):
                if line_num == 0:
                    prefix = "> " if i == self.cursor_index else "  "
                else:
                    prefix = "   "  # continuation lines indent past the prefix, no marker
                self.text_pool.get(text_index, f"{prefix}{line}", LIST_LEFT_X, y,
                    color, font_size=LIST_ROW_FONT_SIZE).draw()
                y -= LIST_ROW_HEIGHT
                text_index += 1

        if len(labels) > MAX_VISIBLE_ROWS:
            last_shown = min(self.scroll_offset + MAX_VISIBLE_ROWS, len(labels))
            self.scroll_indicator_text.text = f"{self.scroll_offset + 1}-{last_shown} of {len(labels)}"
        else:
            self.scroll_indicator_text.text = ""
        self.scroll_indicator_text.draw()

    # ---- shared scroll/cursor bookkeeping ----

    def scroll_to_show_cursor(self):
        """Keeps self.cursor_index inside the visible window by adjusting
        self.scroll_offset -- call after moving the cursor in any
        scrollable-list mode."""
        if self.cursor_index < self.scroll_offset:
            self.scroll_offset = self.cursor_index
        elif self.cursor_index >= self.scroll_offset + MAX_VISIBLE_ROWS:
            self.scroll_offset = self.cursor_index - MAX_VISIBLE_ROWS + 1

    def reset_cursor(self):
        """Call whenever switching modes/sections so the new list/menu
        starts at the top rather than wherever the cursor previously was."""
        self.cursor_index = 0
        self.scroll_offset = 0


def check_pass_out(window, lab_view) -> bool:
    """
    Call right after any "time-consuming action" (auto-purify, warping to
    collect a reaction, ...) advances game_clock -- those are the only ways
    time can move while the player isn't out walking the lab floor, so
    they're also the only place a bench needs to check whether that push
    was enough to cross the pass-out threshold. If so, send the player back
    to the lab floor (LabView.pass_out() resets the day) instead of leaving
    them mid-bench on a day that's already supposed to be over. Returns
    True when this happened -- the caller should stop touching its own
    view state afterward, since window.show_view() has already replaced it.
    """
    if window.day_manager.has_passed_out(window.game_clock):
        window.show_view(lab_view)
        lab_view.pass_out()
        return True
    return False
