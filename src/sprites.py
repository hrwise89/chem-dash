"""
Sprite manifest: a path from today's solid-color placeholder rectangles
to real art, without a rewrite when it arrives.

src/data/sprites.json maps a sprite key (e.g. "player", "bench_hood") to
an image file path, relative to the repo root -- e.g.
{"player": "assets/sprites/player.png"}. A key with no manifest entry, or
whose file doesn't exist yet, falls back to a plain SpriteSolidColor --
exactly today's look -- so art can be dropped in one image at a time
without breaking anything else or touching the call sites that place
these sprites (LabView's bench specs, Player, room_geometry's walls).

Deliberately minimal: one texture per key, no animation/spritesheet
support -- add that once there's actual art to need it.
"""

import json
import os

import arcade

from devtools import logger

SPRITE_MANIFEST_PATH = "src/data/sprites.json"

_manifest_cache: dict[str, str] | None = None
_texture_cache: dict[str, arcade.Texture] = {}


def _load_manifest(path: str = SPRITE_MANIFEST_PATH) -> dict[str, str]:
    global _manifest_cache
    if _manifest_cache is None:
        try:
            with open(path, "r") as f:
                _manifest_cache = json.load(f)
        except FileNotFoundError:
            _manifest_cache = {}
    return _manifest_cache


def texture_for(key: str) -> arcade.Texture | None:
    """The manifest's texture for `key`, loaded and cached on first use --
    or None if there's no entry for it, or its file doesn't exist yet.
    Callers should fall back to a solid color in that case (see
    make_sprite below)."""
    manifest = _load_manifest()
    path = manifest.get(key)
    if not path:
        return None
    if key not in _texture_cache:
        if not os.path.exists(path):
            logger.warning("sprites.json entry '%s' points at missing file '%s'", key, path)
            return None
        _texture_cache[key] = arcade.load_texture(path)
    return _texture_cache[key]


def make_sprite(key: str, width: float, height: float, center_x: float, center_y: float,
                fallback_color) -> arcade.Sprite:
    """A Sprite for `key`, textured and scaled to (width, height) if the
    manifest defines a real image for it -- otherwise a plain
    SpriteSolidColor in fallback_color, exactly today's placeholder
    rectangle."""
    texture = texture_for(key)
    if texture is None:
        return arcade.SpriteSolidColor(int(width), int(height), center_x, center_y, fallback_color)
    sprite = arcade.Sprite(texture, center_x=center_x, center_y=center_y)
    sprite.width = width
    sprite.height = height
    return sprite
