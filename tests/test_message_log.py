import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from message_log import MessageLog


class TestMessageLog(unittest.TestCase):

    def test_add_appends(self):
        log = MessageLog()
        log.add("hello")
        log.add("world")
        self.assertEqual(log.messages, ["hello", "world"])

    def test_repeating_the_last_message_is_a_no_op(self):
        log = MessageLog()
        log.add("Getting sleepy")
        log.add("Getting sleepy")
        log.add("Getting sleepy")
        self.assertEqual(log.messages, ["Getting sleepy"])

    def test_a_repeat_after_a_different_message_is_added_again(self):
        log = MessageLog()
        log.add("a")
        log.add("b")
        log.add("a")
        self.assertEqual(log.messages, ["a", "b", "a"])

    def test_oldest_messages_scroll_off_past_max(self):
        log = MessageLog(max_messages=3)
        for text in ["one", "two", "three", "four", "five"]:
            log.add(text)
        self.assertEqual(log.messages, ["three", "four", "five"])


if __name__ == "__main__":
    unittest.main()
