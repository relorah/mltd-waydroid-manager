"""Select a game FPS tier from sustained SurfaceFlinger samples."""
import math
from collections import deque
from statistics import median


def read_mode(path):
    try:
        mode = path.read_text().strip().lower()
    except OSError:
        mode = '120'
    return mode if mode in ('auto', '60', '120', 'off') else '120'


class FPSPolicy:
    """Observe at a 120 ceiling, then latch 60 or 120 for an active session.

    Do not chase GPU-bound dips. A latched 60 ceiling hides higher rates,
    so re-observation requires ten seconds without valid frames, a new
    compositor, or an explicit mode change. Fixed 120 is available for games
    that change their target rate while continuously submitting frames.
    """
    def __init__(self, mode='120', window=5.0, idle_reset=10.0):
        self.mode = mode
        self.window = window
        self.idle_reset = idle_reset
        self.samples = deque()
        self.last_valid = None
        self.observing = mode == 'auto'
        self.limit = {'auto': 120, '60': 60, '120': 120, 'off': 0}[mode]

    def update(self, fps, now):
        if self.mode != 'auto':
            return self.limit
        if not math.isfinite(fps) or fps <= 0 or fps > 240:
            self.samples.clear()
            if self.last_valid is not None and now - self.last_valid >= self.idle_reset:
                self.observing = True
                self.limit = 120
                self.last_valid = None
            return self.limit
        self.last_valid = now
        self.samples.append((now, fps))
        while len(self.samples) > 1 and now - self.samples[1][0] >= self.window:
            self.samples.popleft()
        if now - self.samples[0][0] < self.window or len(self.samples) < 10:
            return self.limit
        values = [value for _, value in self.samples]
        # Only recognize sustained cadence close to an intended rate. Low
        # throughput is not evidence of a lower target rate.
        stable_120 = sum(114 <= value <= 123 for value in values) / len(values) >= .9
        stable_60 = sum(57 <= value <= 63 for value in values) / len(values) >= .9
        if stable_120 and median(values) >= 116:
            self.limit = 120
            self.observing = False
        elif self.observing and stable_60:
            self.limit = 60
            self.observing = False
        return self.limit
