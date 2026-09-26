import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from devtools import DEV_MODE, LOG_FILE_PATH, logger  # noqa: E402


class TestDevtools(unittest.TestCase):

    def test_logger_is_configured(self):
        self.assertEqual(logger.name, "chem_dash")
        self.assertGreaterEqual(len(logger.handlers), 1)

    def test_dev_mode_sets_debug_level(self):
        # Guards the intent of DEV_MODE: True means DEBUG-level detail is
        # actually visible, not just that the flag exists.
        if DEV_MODE:
            self.assertEqual(logger.level, logging.DEBUG)
        else:
            self.assertEqual(logger.level, logging.INFO)

    def test_devtools_has_no_arcade_or_settings_dependency(self):
        # Regression guard: devtools.py must stay import-able without
        # arcade/settings.py, since reaction_engine.py and inventory.py
        # import it and are relied on to run headless (no display needed).
        import devtools
        self.assertNotIn("arcade", dir(devtools))
        self.assertNotIn("settings", dir(devtools))

    def test_log_file_path_is_a_plain_string(self):
        self.assertIsInstance(LOG_FILE_PATH, str)


if __name__ == "__main__":
    unittest.main()
