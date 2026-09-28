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

from devtools import logger
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
        arcade.draw_arc_outline(cx, cy, radius * 2, radius * 2, color, start, end, border_width)


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
        arcade.draw_arc_filled(cx, cy, radius * 2, radius * 2, color, start, end)


def draw_panel(panel: Panel, color=PANEL_COLOR, bg_color=PANEL_BG_COLOR,
               radius: float = PANEL_RADIUS, border_width: float = PANEL_BORDER_WIDTH):
    """A filled-background rounded panel with an outline -- the standard
    "box" every screen built with this theme sits its content inside."""
    draw_rounded_rect_filled(panel, bg_color, radius)
    draw_rounded_rect_outline(panel, color, radius, border_width)


# ---- Scrollbar ----
# A vertical arrow/track/thumb scrollbar, drawn along a panel's right
# edge -- replaces the "X-Y of N" text indicator with the mockup's actual
# scrollbar graphic.

SCROLLBAR_WIDTH = 18
SCROLLBAR_ARROW_HEIGHT = 14
SCROLLBAR_MARGIN = 10


def draw_scrollbar(panel: Panel, total_items: int, visible_items: int, scroll_offset: int,
                    color=PANEL_COLOR):
    """Draws a scrollbar for a list of `total_items`, `visible_items` of
    which are shown starting at `scroll_offset` -- a no-op if everything
    already fits (nothing to scroll)."""
    if total_items <= visible_items:
        return

    x = panel.right - SCROLLBAR_MARGIN - SCROLLBAR_WIDTH / 2
    top = panel.top - SCROLLBAR_MARGIN
    bottom = panel.bottom + SCROLLBAR_MARGIN
    track_top = top - SCROLLBAR_ARROW_HEIGHT
    track_bottom = bottom + SCROLLBAR_ARROW_HEIGHT
    track_height = track_top - track_bottom

    # Up/down arrows
    arrow_half = SCROLLBAR_WIDTH / 2
    arcade.draw_triangle_filled(x - arrow_half, top - SCROLLBAR_ARROW_HEIGHT,
                                 x + arrow_half, top - SCROLLBAR_ARROW_HEIGHT,
                                 x, top, color)
    arcade.draw_triangle_filled(x - arrow_half, bottom + SCROLLBAR_ARROW_HEIGHT,
                                 x + arrow_half, bottom + SCROLLBAR_ARROW_HEIGHT,
                                 x, bottom, color)

    # Track
    arcade.draw_line(x, track_top, x, track_bottom, color, 2)

    # Thumb -- sized proportionally to how much of the list is visible,
    # positioned proportionally to scroll_offset.
    thumb_height = max(track_height * (visible_items / total_items), SCROLLBAR_WIDTH)
    max_scroll = total_items - visible_items
    scroll_fraction = 0.0 if max_scroll <= 0 else scroll_offset / max_scroll
    thumb_top = track_top - (track_height - thumb_height) * scroll_fraction
    thumb_bottom = thumb_top - thumb_height
    arcade.draw_lrbt_rectangle_filled(x - arrow_half, x + arrow_half, thumb_bottom, thumb_top, color)


# ---- Tab bar ----
# A horizontal row of tab labels (the current one bright, the rest
# dimmed), with optional big paging arrows flanking a panel below it.

def draw_tab_bar(center_x: float, y: float, labels: list[str], current_index: int,
                  spacing: float = 220, font_size: int = 18,
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
        arcade.Text(label, start_x + i * spacing, y, color, font_size=font_size,
                    font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()


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


def draw_slider(center_x: float, y: float, width: float, height: float, fraction: float,
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
        arcade.Text(min_label, left - 14, y, color, font_size=label_font_size,
                    font_name=FONT_STACK, anchor_x="right", anchor_y="center").draw()
    if max_label:
        arcade.Text(max_label, right + 14, y, color, font_size=label_font_size,
                    font_name=FONT_STACK, anchor_x="left", anchor_y="center").draw()


# ---- Icon slots ----
# A row of small square panels showing a texture (via sprites.py) if one
# exists for that slot's key, otherwise just an empty/dimmed placeholder
# box -- e.g. page 2's row of column icons (eventually one per owned
# unit, highlighted if in use). No game-state knowledge here: callers
# pass whatever keys/active flags they want shown.

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
            sprite.draw()
        else:
            draw_rounded_rect_outline(slot, color, radius=4, border_width=2)


# ---- Decorative icon panel ----

def draw_icon_panel(panel: Panel, sprite_key: str, placeholder_label: str = "",
                     color=PANEL_COLOR):
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
        sprite.draw()
    elif placeholder_label:
        arcade.Text(placeholder_label, panel.center_x, panel.center_y, DIM_COLOR,
                    font_size=14, font_name=FONT_STACK, anchor_x="center", anchor_y="center").draw()
