import time

class Timer:
	"""A simple timer that counts down in real time."""
	def __init__(self, duration: float):
		self.duration = duration      # Total duration in seconds
		self.start_time = None        # Timestamp when timer was started
		self.running = False
		self.elapsed_before_pause = 0 # Time already elapsed before last pause

	def start(self):
		if not self.running:
			self.start_time = time.time()
			self.running = True

	def stop(self):
		if self.running:
			self.elapsed_before_pause += time.time() - self.start_time
			self.running = False
			self.start_time = None

	def reset(self):
		self.running = False
		self.start_time = None
		self.elapsed_before_pause = 0

	def get_remaining(self):
		"""Return remaining time in seconds."""
		if self.running:
			elapsed = self.elapsed_before_pause + (time.time() - self.start_time)
		else:
			elapsed = self.elapsed_before_pause
		remaining = max(0.0, self.duration - elapsed)
		return remaining

	def is_finished(self):
		return self.get_remaining() <= 0


class TimerManager:
	"""Keeps track of multiple timers."""
	def __init__(self):
		self.timers = {}

	def add_timer(self, name: str, timer: Timer):
		self.timers[name] = timer

	def get_timer(self, name: str) -> Timer:
		return self.timers[name]

	def update_all(self):
		"""Optional: you can call this if you want per-frame updates; not strictly needed for real-time."""
		pass