import time


def ease_out_cubic(t):
    return 1.0 - (1.0 - t) ** 3


def ease_in_out_cubic(t):
    if t < 0.5:
        return 4 * t * t * t
    return 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


TRANS_FAST = 0.22
TRANS_MEDIUM = 0.30
TRANS_SLOW = 0.40
MORPH_DURATION = 0.28
ANIM_INTERVAL_MS = 8  # ~120fps target for high-refresh-rate monitors


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


class MorphTransition:
    """Interpolates window geometry (x, y, w, h) for mini ↔ full morphing."""

    def __init__(self):
        self.active = False
        self.from_rect = (0, 0, 0, 0)  # (x, y, w, h)
        self.to_rect = (0, 0, 0, 0)
        self.progress = 0.0
        self._start_time = 0.0
        self._duration = MORPH_DURATION

    def begin(self, from_rect, to_rect, duration=MORPH_DURATION):
        self.active = True
        self.from_rect = from_rect
        self.to_rect = to_rect
        self.progress = 0.0
        self._start_time = time.monotonic()
        self._duration = max(0.001, duration)

    def update(self):
        """Returns (eased_progress, current_rect). Deactivates when done."""
        if not self.active:
            return 1.0, self.to_rect
        elapsed = time.monotonic() - self._start_time
        self.progress = min(1.0, elapsed / self._duration)
        if self.progress >= 1.0:
            self.active = False
            return 1.0, self.to_rect
        ep = ease_in_out_cubic(self.progress)
        cx = int(self.from_rect[0] + (self.to_rect[0] - self.from_rect[0]) * ep)
        cy = int(self.from_rect[1] + (self.to_rect[1] - self.from_rect[1]) * ep)
        cw = int(self.from_rect[2] + (self.to_rect[2] - self.from_rect[2]) * ep)
        ch = int(self.from_rect[3] + (self.to_rect[3] - self.from_rect[3]) * ep)
        cw = max(1, cw)
        ch = max(1, ch)
        return ep, (cx, cy, cw, ch)
