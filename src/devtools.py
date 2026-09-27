"""
Central dev-mode logging for Chem Dash.

Import `logger` from here anywhere game code wants to report what it's
doing, instead of print(). Levels used elsewhere in the codebase:

  DEBUG    fine-grained detail: computed yields/condition scores, equipment
           reserved/released, menu navigation -- only useful when actively
           chasing something.
  INFO     notable, expected events: a reaction started or was collected,
           a mini-game/bench was opened.
  WARNING  a player action was rejected for an in-game reason (missing
           equipment, insufficient chemicals, reaction not ready yet) --
           these also surface as the on-screen message, this is the
           mirror of that for the log.
  ERROR    reserved for genuinely unexpected states/bugs, not normal
           "player tried something invalid" cases.

With DEV_MODE True (the default), DEBUG and up go to both the console and
LOG_FILE_PATH. With DEV_MODE False, only INFO and up show, and only on the
console -- flip that off once things are stable rather than ripping out
log calls.

The log file is truncated (mode="w") at the start of each run, so
`tail -f chem_dash.log` in another terminal always shows just the
current session -- handy for pasting recent output, or for live-watching
play while looking for a specific bug.

DEV_MODE and LOG_FILE_PATH are defined here rather than in settings.py on
purpose: settings.py imports arcade (for color constants), and this module
is imported from reaction_engine.py/inventory.py, which stay arcade-free
so their tests can run headless. Importing settings.py from here would
undo that.
"""

import logging
import sys

DEV_MODE = True
LOG_FILE_PATH = "chem_dash.log"

logger = logging.getLogger("chem_dash")

if not logger.handlers:  # guard against duplicate handlers on re-import
    logger.setLevel(logging.DEBUG if DEV_MODE else logging.INFO)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                                   datefmt="%H:%M:%S")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if DEV_MODE:
        file_handler = logging.FileHandler(LOG_FILE_PATH, mode="w")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.propagate = False


def install_crash_logging():
    """
    Route uncaught exceptions through `logger` (with a full traceback) in
    addition to Python's default stderr printing, so a crash always leaves
    something in LOG_FILE_PATH -- previously an uncaught exception (e.g.
    from inside an arcade/pyglet callback) only ever showed up on the
    console, which is easy to lose. Call this once, as early as possible
    (see main.py).
    """
    default_excepthook = sys.excepthook

    def _log_then_default(exc_type, exc_value, exc_traceback):
        logger.critical("Unhandled exception -- crashing", exc_info=(exc_type, exc_value, exc_traceback))
        default_excepthook(exc_type, exc_value, exc_traceback)

    sys.excepthook = _log_then_default
