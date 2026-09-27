"""
A small rolling log of on-screen status/prompt messages -- backs the
message box below the lab room (see lab_view.py's draw_message_box).
Lives on the window (not any one View) rather than inside LabView, since a
later pass is meant to let bench views push into the same log while it's
still visible. Kept arcade-free so it stays headless-testable, like
reaction_engine.py/inventory.py.
"""

MAX_VISIBLE_MESSAGES = 5


class MessageLog:
    """Newest message last. Appending the same text as the current last
    message is a no-op, so a continuously-true condition (e.g. standing
    next to a bench, or being sleepy) doesn't spam duplicate lines every
    frame just because the caller re-adds it every frame."""

    def __init__(self, max_messages: int = MAX_VISIBLE_MESSAGES):
        self.max_messages = max_messages
        self.messages: list[str] = []

    def add(self, text: str) -> None:
        if self.messages and self.messages[-1] == text:
            return
        self.messages.append(text)
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
