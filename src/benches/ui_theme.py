"""
The retro-terminal chrome system: rounded panels, a drawn scrollbar, a
horizontal tab bar with paging arrows, a min-to-max amount slider, and an
icon-slot row/panel that pulls from the sprites.py manifest. Built against
the "menu-mockups" design (rounded boxed panels, Perfect DOS VGA 437, real
scrollbar/slider graphics instead of text) so every bench can draw through
one shared set of primitives instead of hand-rolling
`arcade.draw_lrbt_rectangle_*` calls -- see ui_demo_bench.py for a screen
exercising all of them.

Layout is plain data (Panel below), not baked into draw-call arithmetic,
so moving/resizing a panel on any screen is editing four numbers in that
screen's own layout constants, not re-deriving geometry.
"""

from dataclasses import dataclass

import arcade

from benches.ui_common import TextPool, wrap_to_width
from devtools import logger
from settings import SCREEN_WIDTH
from sprites import texture_for

# ---- Font ----
# THEME_FONT_NAME matches the .ttf's own registered family name (checked
# via its name table -- not always the same as the filename). FONT_STACK
# is what every Text call should pass as font_name: arcade/pyglet tries
# each entry in order, so a screen still renders (just with a system
# monospace) on a checkout that's missing assets/fonts/ for some reason.
THEME_FONT_NAME = "Perfect DOS VGA 437"
THEME_FONT_PATH = "assets/fonts/Perfect DOS VGA 437.ttf"
FONT_STACK = (THEME_FONT_NAME, "courier new", "monospace")

# Perfect DOS VGA 437 (see int10h.org) maps Unicode code points 0x00-0xFF
# directly onto the ORIGINAL CP437 codepage bytes at that same numeric
# position -- not onto their real Unicode meaning. That's documented,
# intentional behavior for this specific font (a straight port of the DOS
# VGA text-mode glyph table), not a bug -- but it means the "correct"
# Unicode character for something like "»" (U+00BB) renders as the wrong
# glyph in it, while chr(0xAF) (really MACRON in Unicode) renders as the
# authentic pixel-perfect "»" this font was drawn with. These constants
# name the ones this module/its callers use, so nothing has to rediscover
# this quirk again -- they'll show a different (but still legible)
# character if FONT_STACK ever falls back to a real Unicode font, which
# is an acceptable trade for pixel-perfect glyphs once the real font
# is loaded.
CP437_CURSOR = chr(0xAF)       # »
CP437_ARROW_LEFT = chr(0x11)   # ◄
CP437_ARROW_RIGHT = chr(0x10)  # ►
CP437_ARROW_UP = chr(0x1E)     # ▲
CP437_ARROW_DOWN = chr(0x1F)   # ▼

_font_load_attempted = False


def ensure_theme_font_loaded():
    """Loads THEME_FONT_PATH once (call from main.py at startup) --
    silently a no-op if the file's missing, so FONT_STACK's fallback
    entries carry the look instead."""
    global _font_load_attempted
    if _font_load_attempted:
        return
    _font_load_attempted = True
    try:
        arcade.load_font(THEME_FONT_PATH)
    except FileNotFoundError:
        logger.debug("Theme font not found at '%s' -- using fallback font stack %s",
                     THEME_FONT_PATH, FONT_STACK[1:])


# ---- Palette ----
# A DOS-terminal look: black background, white chrome/text, dimmed grey
# for inactive/disabled elements -- everything else in this module takes
# a color explicitly instead of hardcoding these, but this is what every
# screen built with it should default to.
PANEL_COLOR = arcade.color.WHITE
PANEL_BG_COLOR = arcade.color.BLACK
DIM_COLOR = arcade.color.GRAY
HIGHLIGHT_COLOR = arcade.color.WHITE

PANEL_RADIUS = 16
PANEL_BORDER_WIDTH = 2
# arcade's draw_arc_* defaults to num_segments=128 -- way more tessellation
# than a ~16px UI corner needs (that default is sized for large decorative
# circles). Every rounded panel draws 4 of these, every frame, so this
# alone was a real per-frame cost; 20 is visually indistinguishable at
# this radius.
ARC_SEGMENTS = 20


def truncate_to_width(probe: arcade.Text, text: str, max_width: float, suffix: str = "...") -> str:
    """Shortens `text` (plus `suffix`) until it fits max_width, using
    `probe` (an already-positioned/sized/fonted Text) to measure --
    binary search over the cut point rather than trimming one character
    at a time, so a long string costs O(log n) layout recomputations
    instead of O(n). That matters: each `probe.text = ...` assignment
    forces pyglet to re-shape the text, and a naive one-char-at-a-time
    scan over a ~250-character order message was measured costing over
    100ms on its own -- long enough on its own to make a single arrow
    keypress feel stuck. Only call this from a rebuild path (entering a
    screen, moving a cursor, changing a tab), never from on_draw."""
    probe.text = text
    if probe.content_width <= max_width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        probe.text = text[:mid] + suffix
        if probe.content_width <= max_width:
            lo = mid
        else:
            hi = mid - 1
    probe.text = text[:lo] + suffix
    return probe.text


def wrap_and_fit(probe: arcade.Text, text: str, max_width: float, max_lines: int,
                  font_size: int = 12, font_name=FONT_STACK) -> list[str]:
    """Word-wraps `text` to max_width (see ui_common.wrap_to_width -- a
    handful of per-word measurements, cheap even for a long paragraph),
    then caps it at max_lines, truncating only the last kept line (via
    truncate_to_width, one more O(log n) measurement) if it had to cut
    anything. Call this from a rebuild path (cursor move, tab switch),
    not on_draw -- the result is a list of plain lines to draw top-down."""
    lines = wrap_to_width(text, max_width, font_size=font_size, font_name=font_name, probe=probe)
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    kept[-1] = truncate_to_width(probe, kept[-1], max_width)
    return kept


@dataclass
class Panel:
    """A chrome panel's position/size in screen pixels -- the single
    source of truth a screen's own layout constants feed into."""
    left: float
    right: float
    bottom: float
    top: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.top - self.bottom

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def center_y(self) -> float:
        return (self.bottom + self.top) / 2


# ---- Rounded rectangles ----
# No built-in rounded-rect primitive in arcade 3.x -- composed here from
# straight edges/fills plus a quarter-circle arc at each corner.

def draw_rounded_rect_outline(panel: Panel, color=PANEL_COLOR, radius: float = PANEL_RADIUS,
                               border_width: float = PANEL_BORDER_WIDTH):
    radius = min(radius, panel.width / 2, panel.height / 2)
    left, right, bottom, top = panel.left, panel.right, panel.bottom, panel.top

    arcade.draw_line(left + radius, top, right - radius, top, color, border_width)
    arcade.draw_line(left + radius, bottom, right - radius, bottom, color, border_width)
    arcade.draw_line(left, bottom + radius, left, top - radius, color, border_width)
    arcade.draw_line(right, bottom + radius, right, top - radius, color, border_width)

    corners = [
        (left + radius, top - radius, 90, 180),      # top-left
        (right - radius, top - radius, 0, 90),       # top-right
        (left + radius, bottom + radius, 180, 270),  # bottom-left
        (right - radius, bottom + radius, 270, 360),  # bottom-right
    ]
    for cx, cy, start, end in corners:
        arcade.draw_arc_outline(cx, cy, radius * 2, radius * 2, color, start, end, border_width,
                                 num_segments=ARC_SEGMENTS)


def draw_rounded_rect_filled(panel: Panel, color=PANEL_BG_COLOR, radius: float = PANEL_RADIUS):
    radius = min(radius, panel.width / 2, panel.height / 2)
    left, right, bottom, top = panel.left, panel.right, panel.bottom, panel.top

    arcade.draw_lrbt_rectangle_filled(left + radius, right - radius, bottom, top, color)
    arcade.draw_lrbt_rectangle_filled(left, right, bottom + radius, top - radius, color)

    corners = [
        (left + radius, top - radius, 90, 180),
        (right - radius, top - radius, 0, 90),
        (left + radius, bottom + radius, 180, 270),
        (right - radius, bottom + radius, 270, 360),
    ]
    for cx, cy, start, end in corners:
        arcade.draw_arc_filled(cx, cy, radius * 2, radius * 2, color, start, end,
                                num_segments=ARC_SEGMENTS)


def draw_panel(panel: Panel, color=PANEL_COLOR, bg_color=PANEL_BG_COLOR,
               radius: float = PANEL_RADIUS, border_width: float = PANEL_BORDER_WIDTH):
    """A filled-background rounded panel with an outline -- the standard
    "box" every screen built with this theme sits its content inside."""
    draw_rounded_rect_filled(panel, bg_color, radius)
    draw_rounded_rect_outline(panel, color, radius, border_width)


def draw_wrapped_lines(panel: Panel, text_pool: TextPool, key_prefix: str, lines: list[str],
                        line_height: float, font_size: int = 12, left_margin: float = 10,
                        color=PANEL_COLOR):
    """Draws precomputed `lines` (see wrap_and_fit) top-down, left-aligned
    inside `panel` -- text_pool is keyed by line index, same reuse-not-
    rebuild reasoning as draw_fixed_list/draw_multiline_list."""
    y = panel.top - line_height
    for i, line in enumerate(lines):
        text_pool.get(f"{key_prefix}_{i}", line, panel.left + left_margin, y, color,
                      font_size=font_size, font_name=FONT_STACK,
                      anchor_x="left", anchor_y="center").draw()
        y -= line_height


def draw_description_panel(panel: Panel, text_pool: TextPool, key_prefix: str, text: str,
                            font_size: int = 10, line_height: float | None = None, color=PANEL_COLOR):
    """The other recurring box: a rounded panel with a single blurb of
    prose, word-wrapped and truncated to whatever fits -- e.g. purify_
    bench.py's/shipping_bench.py's description panels, and the notebook's
    (notebook.py) per-item descriptions. One call in place of hand-rolling
    a probe Text + wrap_and_fit + draw_wrapped_lines with panel-specific
    margins/line counts each time."""
    draw_panel(panel)
    line_height = line_height or font_size * 2.0
    probe = text_pool.get(f"{key_prefix}_probe", "", 0, 0, color, font_size=font_size, font_name=FONT_STACK)
    max_lines = max(1, int((panel.height - 10) // line_height))
    lines = wrap_and_fit(probe, text, panel.width - 20, max_lines, font_size=font_size)
    draw_wrapped_lines(panel, text_pool, key_prefix, lines, line_height, font_size=font_size, color=color)


# ---- Fixed-row paged lists ----
# Retro-RPG-style: rows are a fixed height, one item per row (no word
# wrap, no variable-height entries), and a list longer than one page flips
# by a whole page at a time instead of scrolling by arbitrary offsets --
# simpler to reason about, and cheap to draw: which page a cursor is on,
# and which items are on a given page, are both O(1)/O(rows_per_page)
# arithmetic, never a per-frame text-measurement pass over the whole list.

def page_start_for_cursor(cursor_index: int, rows_per_page: int) -> int:
    """The index of the first item on cursor_index's page."""
    return (cursor_index // rows_per_page) * rows_per_page


def page_count(total_items: int, rows_per_page: int) -> int:
    """How many pages `total_items` split into (at least 1, even for an
    empty list, so "Page 1/1" is always a valid thing to show)."""
    if total_items <= 0:
        return 1
    return -(-total_items // rows_per_page)  # ceil division


def draw_page_indicator(text_pool: TextPool, key: str, center_x: float, y: float,
                         cursor_index: int, total_items: int, rows_per_page: int,
                         font_size: int = 10, color=DIM_COLOR):
    """A plain "Page X/Y" label -- the paged-list equivalent of
    draw_scrollbar, without needing a thumb-size/position computed from
    variable row heights."""
    current_page = cursor_index // rows_per_page + 1 if total_items > 0 else 1
    total_pages = page_count(total_items, rows_per_page)
    text_pool.get(key, f"Page {current_page}/{total_pages}", center_x, y, color,
                  font_size=font_size, font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()


def draw_fixed_list(panel: Panel, text_pool: TextPool, key_prefix: str, rows: list[str],
                     cursor_index: int, rows_per_page: int, row_height: float,
                     font_size: int = 12, left_margin: float = 10, cursor_gap: float = 8,
                     cursor_glyph_width: float = 18, color=PANEL_COLOR,
                     empty_label: str = "(none)", row_colors: list | None = None):
    """One page (rows_per_page items starting at cursor_index's page) of
    `rows` (already-short, single-line strings -- see inventory.py's/
    economy.py's display_name), each a fixed-height row with CP437_CURSOR
    marking cursor_index. text_pool is keyed by row SLOT (0..rows_per_page-1,
    plus f"{key_prefix}_cursor"), not by item index, so paging or scrolling
    through a long list only ever touches a handful of Text objects,
    reused/mutated in place rather than rebuilt. row_colors, if given, is
    one color per entry in `rows` (e.g. green for a reaction that's ready)
    -- the cursor glyph itself still always draws in `color`, matching
    every other cursor in the theme."""
    if not rows:
        text_pool.get(f"{key_prefix}_empty", empty_label, panel.center_x, panel.center_y, color,
                      font_size=font_size, font_name=FONT_STACK, anchor_x="center").draw()
        return

    text_x = panel.left + left_margin + cursor_glyph_width + cursor_gap
    page_start = page_start_for_cursor(cursor_index, rows_per_page)
    page_items = rows[page_start:page_start + rows_per_page]

    y = panel.top - row_height
    for slot, label in enumerate(page_items):
        item_index = page_start + slot
        if item_index == cursor_index:
            text_pool.get(f"{key_prefix}_cursor", CP437_CURSOR, panel.left + left_margin, y, color,
                          font_size=font_size, font_name=FONT_STACK,
                          anchor_x="left", anchor_y="center").draw()
        row_color = row_colors[item_index] if row_colors else color
        text_pool.get(f"{key_prefix}_row_{slot}", label, text_x, y, row_color,
                      font_size=font_size, font_name=FONT_STACK,
                      anchor_x="left", anchor_y="center").draw()
        y -= row_height


TITLE_HEADER_HEIGHT = 26
TITLE_HEADER_FONT_SIZE = 12
LIST_PAGE_INDICATOR_MARGIN = 16


def draw_titled_list_panel(panel: Panel, text_pool: TextPool, key_prefix: str, rows: list[str],
                            cursor_index: int, row_height: float, title: str | None = None,
                            font_size: int = 12, color=PANEL_COLOR, empty_label: str = "(none)",
                            row_colors: list | None = None) -> int:
    """The recurring "rounded box, dim title across the top, a fixed-row
    paged list, 'Page X/Y' centered along the bottom" composite -- e.g.
    purify_bench.py's crude-product picker and every list-with-a-label the
    notebook (notebook.py) shows. One call in place of hand-assembling
    draw_panel + a title Text + draw_fixed_list + draw_page_indicator with
    their own margins each time, so every such box keeps the same title
    clearance, row spacing, and page-indicator placement without a caller
    having to re-derive them. Returns rows_per_page (callers need it to
    move the cursor by a whole page, same as page_count/page_start_for_
    cursor elsewhere in this module)."""
    draw_panel(panel)
    content_top = panel.top
    if title:
        text_pool.get(f"{key_prefix}_title", title, panel.center_x, panel.top - TITLE_HEADER_HEIGHT / 2,
                      DIM_COLOR, font_size=TITLE_HEADER_FONT_SIZE, font_name=FONT_STACK,
                      anchor_x="center", anchor_y="center").draw()
        content_top = panel.top - TITLE_HEADER_HEIGHT
    content_bottom = panel.bottom + LIST_PAGE_INDICATOR_MARGIN * 2
    content_panel = Panel(panel.left, panel.right, content_bottom, content_top)
    rows_per_page = max(1, int(content_panel.height // row_height))
    draw_fixed_list(content_panel, text_pool, key_prefix, rows, cursor_index, rows_per_page, row_height,
                     font_size=font_size, color=color, empty_label=empty_label, row_colors=row_colors)
    draw_page_indicator(text_pool, f"{key_prefix}_page", panel.center_x, panel.bottom + LIST_PAGE_INDICATOR_MARGIN,
                         cursor_index, len(rows), rows_per_page)
    return rows_per_page


def draw_multiline_list(panel: Panel, text_pool: TextPool, key_prefix: str, entries: list[list[str]],
                         cursor_index: int, entries_per_page: int, line_height: float, lines_per_entry: int,
                         font_size: int = 12, left_margin: float = 10, cursor_gap: float = 8,
                         cursor_glyph_width: float = 18, color=PANEL_COLOR, empty_label: str = "(none)",
                         cursor_line: int = 0, line_indents: list[float] | None = None):
    """Like draw_fixed_list, but each entry is `lines_per_entry` fixed,
    non-wrapping lines (e.g. a summary line, a sender line) instead of
    one -- CP437_CURSOR marks the whole entry, aligned with line
    `cursor_line` of it (0 = the entry's top line). `line_indents`, if
    given, is one extra-left-offset-in-pixels per line index (e.g. to
    indent a sender line under the summary line above it) -- leading
    spaces in the string itself don't work for this: pyglet's left anchor
    positions off the first non-space glyph, not the string's start, so
    it silently ignores them. text_pool is keyed by (slot, line) pairs,
    same reuse-not-rebuild reasoning as draw_fixed_list."""
    if not entries:
        text_pool.get(f"{key_prefix}_empty", empty_label, panel.center_x, panel.center_y, color,
                      font_size=font_size, font_name=FONT_STACK, anchor_x="center").draw()
        return

    text_x = panel.left + left_margin + cursor_glyph_width + cursor_gap
    page_start = page_start_for_cursor(cursor_index, entries_per_page)
    page_items = entries[page_start:page_start + entries_per_page]

    y = panel.top - line_height
    for slot, lines in enumerate(page_items):
        item_index = page_start + slot
        if item_index == cursor_index:
            cursor_y = y - line_height * cursor_line
            text_pool.get(f"{key_prefix}_cursor", CP437_CURSOR, panel.left + left_margin, cursor_y, color,
                          font_size=font_size, font_name=FONT_STACK,
                          anchor_x="left", anchor_y="center").draw()
        for line_num, line in enumerate(lines):
            indent = line_indents[line_num] if line_indents else 0
            text_pool.get(f"{key_prefix}_row_{slot}_{line_num}", line, text_x + indent, y, color,
                          font_size=font_size, font_name=FONT_STACK,
                          anchor_x="left", anchor_y="center").draw()
            y -= line_height


# ---- Tab bar ----
# A horizontal row of tab labels (the current one bright, the rest
# dimmed), with optional big paging arrows flanking a panel below it.

def draw_tab_bar(text_pool: TextPool, key_prefix: str, center_x: float, y: float,
                  labels: list[str], current_index: int, spacing: float = 220, font_size: int = 18,
                  active_color=HIGHLIGHT_COLOR, dim_color=DIM_COLOR):
    """`labels` drawn centered as a row around (center_x, y), spacing
    apart -- the tab at current_index in active_color, everything else
    dimmed. `spacing`'s default is just a starting point: Perfect DOS VGA
    437's glyphs are noticeably wider than a typical sans font at the same
    size, so a caller with longer labels (or more of them) should check
    they don't overlap/run off-screen and pass a wider spacing if not."""
    start_x = center_x - spacing * (len(labels) - 1) / 2
    for i, label in enumerate(labels):
        color = active_color if i == current_index else dim_color
        text_pool.get(f"{key_prefix}_{i}", label, start_x + i * spacing, y, color,
                      font_size=font_size, font_name=FONT_STACK,
                      anchor_x="center", anchor_y="center").draw()


PAGE_ARROW_SIZE = 24
PAGE_ARROW_MARGIN = 30


def draw_page_arrows(panel: Panel, color=PANEL_COLOR):
    """Big triangle arrows flanking `panel`, hinting that LEFT/RIGHT pages
    between tabs/sections -- purely decorative, doesn't know how many
    tabs there are."""
    y = panel.center_y
    half = PAGE_ARROW_SIZE / 2
    left_x = panel.left - PAGE_ARROW_MARGIN
    arcade.draw_triangle_filled(left_x + half, y + half, left_x + half, y - half,
                                 left_x - half, y, color)
    right_x = panel.right + PAGE_ARROW_MARGIN
    arcade.draw_triangle_filled(right_x - half, y + half, right_x - half, y - half,
                                 right_x + half, y, color)


# ---- Slider ----
# A bar ranging from a fixed min endpoint to a fixed max endpoint (each
# marked with a small square), filled solid from min up to the current
# value and dotted the rest of the way to max -- the filled/dotted
# boundary is what grows right or shrinks left as the value changes, never
# the endpoints themselves.

SLIDER_ENDPOINT_WIDTH = 6
SLIDER_HANDLE_WIDTH = 4
SLIDER_DASH_LENGTH = 6
SLIDER_GAP_LENGTH = 6


def draw_slider(text_pool: TextPool, key_prefix: str, center_x: float, y: float,
                 width: float, height: float, fraction: float,
                 min_label: str | None = None, max_label: str | None = None,
                 color=PANEL_COLOR, fill_color=arcade.color.ORANGE, handle_color=arcade.color.RED,
                 label_font_size: int = 14):
    """`fraction` (0-1) is how far along [min, max] the current value
    sits -- 0 at the min endpoint, 1 at the max endpoint. min_label/
    max_label, if given, are drawn just outside each endpoint (e.g.
    "0.5 g" / "100 g")."""
    left = center_x - width / 2
    right = center_x + width / 2
    bottom = y - height / 2
    top = y + height / 2
    fraction = max(0.0, min(1.0, fraction))
    fill_x = left + width * fraction

    arcade.draw_lrbt_rectangle_outline(left, right, bottom, top, color, border_width=2)
    if fraction > 0:
        arcade.draw_lrbt_rectangle_filled(left, fill_x, bottom, top, fill_color)
    if fraction < 1:
        x = fill_x
        while x < right:
            dash_end = min(x + SLIDER_DASH_LENGTH, right)
            arcade.draw_line(x, y, dash_end, y, color, 2)
            x = dash_end + SLIDER_GAP_LENGTH

    endpoint_half = SLIDER_ENDPOINT_WIDTH / 2
    arcade.draw_lrbt_rectangle_filled(left - endpoint_half, left + endpoint_half, bottom - 4, top + 4, color)
    arcade.draw_lrbt_rectangle_filled(right - endpoint_half, right + endpoint_half, bottom - 4, top + 4, color)

    handle_half = SLIDER_HANDLE_WIDTH / 2
    arcade.draw_lrbt_rectangle_filled(fill_x - handle_half, fill_x + handle_half,
                                       bottom - 8, top + 8, handle_color)

    if min_label:
        text_pool.get(f"{key_prefix}_min", min_label, left - 14, y, color, font_size=label_font_size,
                      font_name=FONT_STACK, anchor_x="right", anchor_y="center").draw()
    if max_label:
        text_pool.get(f"{key_prefix}_max", max_label, right + 14, y, color, font_size=label_font_size,
                      font_name=FONT_STACK, anchor_x="left", anchor_y="center").draw()


# ---- Icon slots ----
# A row of small square panels showing a texture (via sprites.py) if one
# exists for that slot's key, otherwise just an empty/dimmed placeholder
# box -- e.g. page 2's row of column icons (eventually one per owned
# unit, highlighted if in use). No game-state knowledge here: callers
# pass whatever keys/active flags they want shown.

def draw_single_sprite(sprite: arcade.Sprite):
    """arcade 3.x removed Sprite.draw() -- only a SpriteList can be drawn
    now, even for a single one-off sprite like an item's icon. This is a
    real (if small) per-call cost -- fine for the handful of icon panels
    a screen shows, not something to call from inside a per-row loop."""
    sprite_list = arcade.SpriteList()
    sprite_list.append(sprite)
    sprite_list.draw()


ICON_SLOT_MARGIN = 8


def draw_icon_slot_row(panel: Panel, count: int, sprite_key_for=lambda i: None,
                        active_flags: list[bool] | None = None,
                        active_color=HIGHLIGHT_COLOR, inactive_color=DIM_COLOR):
    """`count` evenly-spaced square slots across `panel`. sprite_key_for(i)
    returns the sprites.py manifest key for slot i (or None for a bare
    placeholder box); active_flags marks which slots draw bright vs
    dimmed (defaults to all bright)."""
    if count <= 0:
        return
    active_flags = active_flags if active_flags is not None else [True] * count
    slot_width = panel.width / count
    slot_size = min(slot_width - ICON_SLOT_MARGIN * 2, panel.height - ICON_SLOT_MARGIN * 2)

    for i in range(count):
        slot_center_x = panel.left + slot_width * (i + 0.5)
        color = active_color if active_flags[i] else inactive_color
        slot = Panel(slot_center_x - slot_size / 2, slot_center_x + slot_size / 2,
                     panel.center_y - slot_size / 2, panel.center_y + slot_size / 2)
        texture = texture_for(sprite_key_for(i)) if sprite_key_for(i) else None
        if texture is not None:
            sprite = arcade.Sprite(texture, center_x=slot.center_x, center_y=slot.center_y)
            sprite.width = slot_size
            sprite.height = slot_size
            draw_single_sprite(sprite)
        else:
            draw_rounded_rect_outline(slot, color, radius=4, border_width=2)


# ---- Decorative icon panel ----

def draw_icon_panel(panel: Panel, sprite_key: str, text_pool: TextPool, key: str,
                     placeholder_label: str = "", color=PANEL_COLOR, placeholder_font_size: int = 11):
    """A rounded panel showing sprites.py's texture for `sprite_key` if
    one exists, scaled to fit -- otherwise just the panel's outline (and
    placeholder_label, if given) so it's obvious in dev that no image is
    set yet."""
    draw_panel(panel, color)
    texture = texture_for(sprite_key)
    if texture is not None:
        inset = PANEL_RADIUS
        max_size = min(panel.width - inset * 2, panel.height - inset * 2)
        sprite = arcade.Sprite(texture, center_x=panel.center_x, center_y=panel.center_y)
        sprite.width = max_size
        sprite.height = max_size
        draw_single_sprite(sprite)
    elif placeholder_label:
        text_pool.get(key, placeholder_label, panel.center_x, panel.center_y, DIM_COLOR,
                      font_size=placeholder_font_size, font_name=FONT_STACK,
                      anchor_x="center", anchor_y="center").draw()


# ---- Themed bench base ----
# What BenchView (ui_common.py) is for the old flat-rectangle chrome, this
# is for the new one: background color, the status pill (time/money/date),
# and a status-message toast -- the handful of things every bench built
# with this theme needs regardless of what it otherwise shows. A bench
# still owns its own mode/state machine and draws its own panels/tabs/
# lists through the primitives above.

STATUS_PANEL = Panel(left=20, right=780, bottom=545, top=585)
MESSAGE_Y = 55
INSTRUCTIONS_Y = 25
MESSAGE_DURATION = 3.5


def draw_status_bar(text_pool: TextPool, time_str: str, money_str: str, date_str: str):
    """The time/money/date pill every full-screen chrome-using surface
    shows at the same spot -- a module-level function (not only a
    ThemedBenchView method) so the notebook overlay (notebook.py), which
    now draws itself at the same full-screen scale as a bench but isn't a
    View, can show the identical status bar without duplicating it."""
    draw_panel(STATUS_PANEL, radius=STATUS_PANEL.height / 2)
    text_pool.get("status_time", time_str, STATUS_PANEL.left + 30, STATUS_PANEL.center_y,
                  PANEL_COLOR, font_size=14, font_name=FONT_STACK,
                  anchor_x="left", anchor_y="center").draw()
    text_pool.get("status_money", money_str, STATUS_PANEL.center_x, STATUS_PANEL.center_y,
                  PANEL_COLOR, font_size=14, font_name=FONT_STACK,
                  anchor_x="center", anchor_y="center").draw()
    text_pool.get("status_date", date_str, STATUS_PANEL.right - 30, STATUS_PANEL.center_y,
                  PANEL_COLOR, font_size=14, font_name=FONT_STACK,
                  anchor_x="right", anchor_y="center").draw()


MESSAGE_FONT_SIZE = 11
MESSAGE_MAX_WIDTH = SCREEN_WIDTH - 80


class ThemedBenchView(arcade.View):

    def __init__(self, window, lab_view):
        super().__init__()
        self.window = window
        self.lab_view = lab_view
        self.text_pool = TextPool()
        self.message = ""
        self.message_color = PANEL_COLOR
        self.message_timer = 0.0

    def on_show_view(self):
        # arcade.set_background_color() is global window state, not
        # per-view -- see lab_view.py's own on_show_view for why this has
        # to happen every time this view is (re-)shown, not just once at
        # construction.
        arcade.set_background_color(arcade.color.BLACK)

    def on_draw(self):
        self.draw_content()
        if self.window.notebook.is_open:
            self.window.notebook.draw(self.window)

    def draw_content(self):
        raise NotImplementedError

    def on_key_press(self, key, modifiers):
        if key == arcade.key.N:
            self.window.notebook.toggle()
            return
        if self.window.notebook.is_open:
            self.window.notebook.handle_key(key, self.window)
            return
        self.handle_content_keys(key, modifiers)

    def handle_content_keys(self, key, modifiers):
        raise NotImplementedError

    def on_update(self, delta_time):
        if self.window.notebook.is_open:
            return  # time (and everything else) pauses while the notebook is open
        if self.message_timer > 0:
            self.message_timer -= delta_time
            if self.message_timer <= 0:
                self.message = ""

    def show_message(self, text: str, color=PANEL_COLOR, duration: float = MESSAGE_DURATION):
        """Truncates `text` to one line, once, right here -- a message is
        set rarely (a handful of times per bench visit) but drawn every
        frame it's showing, so this is where the (one-time) cost of
        fitting it belongs, not in draw_message()."""
        probe = self.text_pool.get("message", text, 0, 0, color,
                                    font_size=MESSAGE_FONT_SIZE, font_name=FONT_STACK)
        self.message = truncate_to_width(probe, text, MESSAGE_MAX_WIDTH)
        self.message_color = color
        self.message_timer = duration

    def draw_status_bar(self, time_str: str, money_str: str, date_str: str):
        draw_status_bar(self.text_pool, time_str, money_str, date_str)

    def draw_message(self):
        if not self.message:
            return
        self.text_pool.get("message", self.message, SCREEN_WIDTH / 2, MESSAGE_Y, self.message_color,
                            font_size=MESSAGE_FONT_SIZE, font_name=FONT_STACK, anchor_x="center").draw()

    def draw_instructions(self, text: str, font_size: int = 10):
        """Perfect DOS VGA 437's glyphs are wide enough that a full
        "LEFT/RIGHT: tabs   UP/DOWN: browse   ENTER: ship   ESC: leave"
        -style line easily runs off both edges of an 800px-wide screen
        even at a small font_size -- keep this short, or check its
        content_width against SCREEN_WIDTH before shipping it."""
        self.text_pool.get("instructions", text, SCREEN_WIDTH / 2, INSTRUCTIONS_Y, DIM_COLOR,
                            font_size=font_size, font_name=FONT_STACK, anchor_x="center").draw()
