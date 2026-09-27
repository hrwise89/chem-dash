import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import sprites


class TestTextureFor(unittest.TestCase):

    def setUp(self):
        # Each test gets a clean manifest/texture cache so one test's
        # monkeypatched manifest can't leak into another's.
        sprites._manifest_cache = None
        sprites._texture_cache = {}
        self.addCleanup(self._reset_caches)

    def _reset_caches(self):
        sprites._manifest_cache = None
        sprites._texture_cache = {}

    def test_missing_manifest_file_yields_no_texture_for_any_key(self):
        sprites._manifest_cache = {}
        self.assertIsNone(sprites.texture_for("player"))

    def test_key_with_no_manifest_entry_yields_no_texture(self):
        sprites._manifest_cache = {"wall": "assets/sprites/wall.png"}
        self.assertIsNone(sprites.texture_for("player"))

    def test_manifest_entry_pointing_at_a_missing_file_yields_no_texture(self):
        sprites._manifest_cache = {"player": "assets/sprites/does_not_exist.png"}
        self.assertIsNone(sprites.texture_for("player"))


if __name__ == "__main__":
    unittest.main()
