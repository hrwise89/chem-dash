"""
The contract inbox: browse incoming order offers, accept or reject them,
and retrieve a just-rejected one before its recovery window closes (see
economy.ContractBoard/REJECTED_RECOVERY_HOURS). Reached from the computer
bench's 6-panel menu.

Deliberately built on the shipping bench's own layout constants (panel
sizes, fonts, row/line heights, page indicator placement) rather than
picking new ones -- the two screens should look and feel like the same
system, and importing the numbers directly guarantees that instead of
just eyeballing a match (see shipping_bench.py's own docstring for why
those particular numbers/primitives were chosen).
"""

import arcade

from benches.shipping_bench import (
    DESCRIPTION_FONT_SIZE,
    DESCRIPTION_LINE_HEIGHT,
    DESCRIPTION_MAX_LINES,
    DESCRIPTION_PANEL,
    ENTRIES_PER_PAGE,
    LIST_FONT_SIZE,
    LIST_LINE_HEIGHT,
    LIST_LINE_INDENTS,
    LIST_LINES_PER_ENTRY,
    LIST_PANEL,
    PAGE_INDICATOR_Y,
)
from benches.ui_theme import (
    FONT_STACK,
    PANEL_COLOR,
    ThemedBenchView,
    draw_multiline_list,
    draw_page_indicator,
    draw_panel,
    draw_tab_bar,
    draw_wrapped_lines,
    truncate_to_width,
    wrap_and_fit,
)
from day_manager import calendar_date_string, clock_time_string
from devtools import logger
from settings import SCREEN_WIDTH

TABS = [("Inbox", "available"), ("Accepted", "accepted"), ("Rejected", "rejected")]


class ContractInboxView(ThemedBenchView):

    def __init__(self, window, lab_view):
        super().__init__(window, lab_view)
        self.mode = "available"
        self.tab_index = 0
        self.cursor_index = 0
        self.entries = []             # [([line1, line2], contract), ...] for the current tab
        self.description_lines = []
        self._refresh_rows()

    def on_show_view(self):
        super().on_show_view()
        # Time may have passed (a day boundary, or just browsing elsewhere)
        # since this view last refreshed -- sweep before showing anything.
        self._refresh_rows()

    # ---- row/description content (only rebuilt when it can change) ----

    def _summary_line(self, contract) -> str:
        return f"[{contract.order_type_letter}] {contract.subject}"

    def _detail_line(self, contract) -> str:
        return f"{contract.sender} - Due: {contract.due_date_label} - ${contract.reward:.2f}"

    def _entry_lines(self, contract) -> list[str]:
        max_width = LIST_PANEL.width - 60
        probe = self.text_pool.get("_probe_row", "", 0, 0, PANEL_COLOR,
                                    font_size=LIST_FONT_SIZE, font_name=FONT_STACK)
        summary = truncate_to_width(probe, self._summary_line(contract), max_width - LIST_LINE_INDENTS[0])
        detail = truncate_to_width(probe, self._detail_line(contract), max_width - LIST_LINE_INDENTS[1])
        return [summary, detail]

    def _description_text(self, contract) -> str:
        base = f"{contract.sender}: {contract.message} (${contract.reward:.2f}, due {contract.due_date_label})"
        if self.mode == "rejected":
            return f"{base} [rejected -- retrieve it before it expires]"
        if self.mode == "accepted" and contract.unfulfilled_recorded:
            return f"{base} [overdue]"
        return base

    def _refresh_rows(self):
        self.window.contract_board.sweep_expirations(self.window.game_clock.now())
        pool = getattr(self.window.contract_board, self.mode)
        self.entries = [(self._entry_lines(c), c) for c in pool]
        self.cursor_index = min(self.cursor_index, max(0, len(self.entries) - 1))
        self._refresh_description()

    def _refresh_description(self):
        if not self.entries:
            self.description_lines = []
            return
        _, contract = self.entries[self.cursor_index]
        probe = self.text_pool.get("_probe_description", "", 0, 0, PANEL_COLOR,
                                    font_size=DESCRIPTION_FONT_SIZE, font_name=FONT_STACK)
        max_width = DESCRIPTION_PANEL.width - 20
        self.description_lines = wrap_and_fit(probe, self._description_text(contract), max_width,
                                               DESCRIPTION_MAX_LINES, font_size=DESCRIPTION_FONT_SIZE)

    # ---- drawing ----

    def draw_content(self):
        self.clear()

        hours = self.window.day_manager.hours_into_day(self.window.game_clock)
        self.draw_status_bar(
            clock_time_string(hours),
            f"${self.window.wallet.balance:.2f}",
            calendar_date_string(self.window.day_manager.current_day),
        )

        draw_tab_bar(self.text_pool, "tab", SCREEN_WIDTH / 2, 505,
                     [label for label, _ in TABS], self.tab_index, spacing=220, font_size=14)

        draw_panel(LIST_PANEL)
        draw_multiline_list(LIST_PANEL, self.text_pool, "list", [lines for lines, _ in self.entries],
                             self.cursor_index, ENTRIES_PER_PAGE, LIST_LINE_HEIGHT, LIST_LINES_PER_ENTRY,
                             font_size=LIST_FONT_SIZE, cursor_line=0, line_indents=LIST_LINE_INDENTS)
        draw_page_indicator(self.text_pool, "page", LIST_PANEL.center_x, PAGE_INDICATOR_Y,
                             self.cursor_index, len(self.entries), ENTRIES_PER_PAGE)

        draw_panel(DESCRIPTION_PANEL)
        draw_wrapped_lines(DESCRIPTION_PANEL, self.text_pool, "description", self.description_lines,
                            DESCRIPTION_LINE_HEIGHT, font_size=DESCRIPTION_FONT_SIZE)

        if self.mode == "available":
            instructions = "L/R: Tabs   U/D: Scroll   Enter: Accept   R: Reject   ESC: Leave"
        elif self.mode == "rejected":
            instructions = "L/R: Tabs   U/D: Scroll   Enter: Retrieve   ESC: Leave"
        else:
            instructions = "L/R: Tabs   U/D: Scroll   ESC: Leave"
        self.draw_instructions(instructions, font_size=8)
        self.draw_message()

    # ---- input ----

    def handle_content_keys(self, key, modifiers):
        if key == arcade.key.ESCAPE:
            logger.debug("Contract inbox: left the bench, returning to the computer bench menu")
            self.window.show_view(self.lab_view)
            return
        if key == arcade.key.LEFT:
            self._switch_tab((self.tab_index - 1) % len(TABS))
        elif key == arcade.key.RIGHT:
            self._switch_tab((self.tab_index + 1) % len(TABS))
        else:
            self._handle_list_keys(key)

    def _switch_tab(self, new_index):
        self.tab_index = new_index
        _, self.mode = TABS[self.tab_index]
        self.cursor_index = 0
        self._refresh_rows()
        logger.debug("Contract inbox: switched to '%s' tab", self.mode)

    def _handle_list_keys(self, key):
        if key in (arcade.key.UP, arcade.key.W) and self.entries:
            self.cursor_index = (self.cursor_index - 1) % len(self.entries)
            self._refresh_description()
        elif key in (arcade.key.DOWN, arcade.key.S) and self.entries:
            self.cursor_index = (self.cursor_index + 1) % len(self.entries)
            self._refresh_description()
        elif key == arcade.key.ENTER and self.entries and self.mode == "available":
            self._accept_selected()
        elif key == arcade.key.R and self.entries and self.mode == "available":
            self._reject_selected()
        elif key == arcade.key.ENTER and self.entries and self.mode == "rejected":
            self._retrieve_selected()

    def _accept_selected(self):
        _, contract = self.entries[self.cursor_index]
        self.window.contract_board.accept(contract.contract_id, self.window.day_manager.day_start_time)
        logger.info("Accepted contract '%s'", contract.subject)
        self.show_message(f"Accepted: {contract.subject}", arcade.color.DARK_GREEN)
        self.cursor_index = 0
        self._refresh_rows()

    def _reject_selected(self):
        _, contract = self.entries[self.cursor_index]
        self.window.contract_board.reject(contract.contract_id, self.window.game_clock.now(),
                                           self.window.day_manager.current_day)
        logger.info("Rejected contract '%s'", contract.subject)
        self.show_message(f"Rejected: {contract.subject} -- recoverable from the Rejected tab", arcade.color.DARK_YELLOW)
        self.cursor_index = 0
        self._refresh_rows()

    def _retrieve_selected(self):
        _, contract = self.entries[self.cursor_index]
        self.window.contract_board.retrieve(contract.contract_id)
        logger.info("Retrieved contract '%s' back to the inbox", contract.subject)
        self.show_message(f"Retrieved: {contract.subject}", arcade.color.DARK_GREEN)
        self.cursor_index = 0
        self._refresh_rows()
