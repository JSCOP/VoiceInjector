import time


def ease_out_cubic(t):
    return 1.0 - (1.0 - t) ** 3


def ease_in_out_cubic(t):
    if t < 0.5:
        return 4 * t * t * t
    return 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


TRANS_FAST = 0.20
TRANS_MEDIUM = 0.25
TRANS_SLOW = 0.35
ANIM_INTERVAL_MS = 33


class TransitionState:
    """Tracks crossfade transition between two overlay states."""

    def __init__(self):
        self.active = False
        self.from_state = "idle"
        self.to_state = "idle"
        self.progress = 0.0
        self._start_time = 0.0
        self._duration = TRANS_FAST

    def begin(self, from_state, to_state, duration=TRANS_FAST):
        self.active = True
        self.from_state = from_state
        self.to_state = to_state
        self.progress = 0.0
        self._start_time = time.monotonic()
        self._duration = max(0.001, duration)

    def update(self):
        """Update progress. Returns eased progress value. Deactivates when done."""
        if not self.active:
            return 1.0
        elapsed = time.monotonic() - self._start_time
        self.progress = min(1.0, elapsed / self._duration)
        if self.progress >= 1.0:
            self.active = False
        return ease_out_cubic(self.progress)
