"""
Shared building blocks still used across the codebase now that every bench
view is built on ui_theme.ThemedBenchView: TextPool (a reusable-Text-object
pool -- see its own docstring), wrap_to_width (word-wrapping against an
actual pixel width), and check_pass_out (the exhaustion check any bench
that can advance game_clock on its own needs to run afterward).

The old flat-rectangle BenchView/Bench chrome this module used to also
provide is gone -- every bench migrated to ui_theme.ThemedBenchView's
rounded-panel look over the course of this project, and ReactionBenchView
(the last holdout) followed suit, so nothing built on the old chrome
remained to keep it around for.
"""

import arcade


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
    drawing one line per item, where the index IS the identity) or a short
    descriptive string for a one-off line a method draws by hand (e.g.
    "available", "cost_summary") -- prefer a string there. Two draw calls
    that use the same string key always share one Text object, so a string
    key only needs to be unique among the lines drawn *together* on one
    screen, not across the whole view -- unlike a hand-picked int offset,
    there's nothing to reserve or collide with.
    """

    def __init__(self):
        self._pool: dict[object, arcade.Text] = {}

    def get(self, key, text: str, x: float, y: float, color,
            font_size: int = 16, anchor_x: str = "left", anchor_y: str = "baseline",
            font_name: str | tuple[str, ...] = ("calibri", "arial")) -> arcade.Text:
        t = self._pool.get(key)
        if t is None:
            t = arcade.Text(text, x, y, color, font_size=font_size, anchor_x=anchor_x,
                             anchor_y=anchor_y, font_name=font_name)
            self._pool[key] = t
            return t
        # x/text already no-op internally when unchanged (arcade.Text's own
        # setters check first). font_size/font_name/anchor_x/anchor_y do
        # NOT -- each one unconditionally pushes a full pyglet document
        # re-layout (_init_document/_update/_create_vertex_lists), which
        # showed up as the dominant per-frame cost once lists got busier
        # (shipping bench's multi-line rows: ~3x the get() calls per frame
        # of a single-line list). Guarding these here, so a call that
        # hands back the *same* font_size/name/anchors it already has
        # skips that relayout entirely, is what makes a busy list as cheap
        # per frame as a sparse one.
        t.text = text
        t.x = x
        t.y = y
        t.color = color
        if t.font_size != font_size:
            t.font_size = font_size
        if t.font_name != font_name:
            t.font_name = font_name
        if t.anchor_x != anchor_x:
            t.anchor_x = anchor_x
        if t.anchor_y != anchor_y:
            t.anchor_y = anchor_y
        return t


def wrap_to_width(text: str, max_width: float, font_size: int = 16,
                   font_name: str | tuple[str, ...] = ("calibri", "arial"),
                   probe: arcade.Text | None = None) -> list[str]:
    """
    Word-wrap `text` into however many lines it takes to keep each one no
    wider than max_width pixels at font_size, measuring with `probe` (an
    existing arcade.Text to reuse) if given, else a scratch one built here
    (arcade.Text.content_width needs an active window, so this can't be
    computed without one -- fine when called from on_draw, but a caller
    that wraps from a cursor-move/rebuild path, not every frame, should
    pass a pooled probe -- building a fresh pyglet Label costs more than
    reassigning .text on one that already exists, and a paragraph-length
    string reassigns it once per word). Returns [text] unchanged if it
    already fits on one line.

    A single word wider than max_width on its own is kept whole rather than
    split mid-word -- rare (a very long chemical name at a narrow width) and
    a mid-word break reads worse than a slightly-too-wide line.

    font_name matters here, not just cosmetically: a wider font (e.g.
    ui_theme.py's Perfect DOS VGA 437) wraps at a different point than the
    default, so pass whatever font_name the actual draw call will use or
    this measures against the wrong glyph widths.
    """
    if probe is None:
        probe = arcade.Text("", 0, 0, arcade.color.BLACK, font_size=font_size, font_name=font_name)
    else:
        probe.font_size = font_size
        probe.font_name = font_name
    probe.text = text
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
