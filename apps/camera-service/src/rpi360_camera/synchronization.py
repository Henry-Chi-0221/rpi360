"""Bounded pairing using the sensor clock, never callback arrival time."""

from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SensorFrame:
    camera: int
    sequence: int
    sensor_ns: int
    exposure_us: int
    duration_us: int
    sync_ready: bool
    planes: Any = None


@dataclass(frozen=True)
class FramePair:
    sequence: int
    first: SensorFrame
    second: SensorFrame

    @property
    def delta_ns(self):
        return abs(self.first.sensor_ns - self.second.sensor_ns)


class Pairer:
    def __init__(self, tolerance_ns=1_000_000, lock_ns=1_000_000_000):
        self.queues = [deque(), deque()]
        self.tolerance_ns = tolerance_ns
        self.lock_ns = lock_ns
        self.good_since = None
        self.last_good = None
        self.locked = False
        self.sequence = 0
        self.discarded = [0, 0]
        self.deltas = deque(maxlen=1800)
        self.last_sensor = [None, None]

    def push(self, frame):
        i = frame.camera
        previous = self.last_sensor[i]
        if previous is not None and frame.sensor_ns <= previous:
            self.queues = [deque(), deque()]
            self.good_since = None
            self.locked = False
            self.last_sensor = [None, None]
            self.last_good = None
        self.last_sensor[i] = frame.sensor_ns
        self.queues[i].append(frame)
        if len(self.queues[i]) > 4:
            self.queues[i].popleft()
            self.discarded[i] += 1
        result = None
        while self.queues[0] and self.queues[1]:
            a, b = self.queues[0][0], self.queues[1][0]
            delta = a.sensor_ns - b.sensor_ns
            if abs(delta) > self.tolerance_ns:
                old = 0 if delta < 0 else 1
                self.queues[old].popleft()
                self.discarded[old] += 1
                # An unmatched dropped frame does not imply loss of sensor phase.
                # Invalidate readiness only when no qualifying pair survives for 100 ms.
                if (
                    self.last_good is None
                    or max(a.sensor_ns, b.sensor_ns) - self.last_good > 100_000_000
                ):
                    self.good_since = None
                    self.locked = False
                continue
            self.queues[0].popleft()
            self.queues[1].popleft()
            self.deltas.append(abs(delta))
            if (
                self.last_good is not None
                and min(a.sensor_ns, b.sensor_ns) - self.last_good > 100_000_000
            ):
                self.good_since = None
                self.locked = False
            self.last_good = min(a.sensor_ns, b.sensor_ns)
            ready = a.sync_ready and b.sync_ready
            if ready:
                if self.good_since is None:
                    self.good_since = min(a.sensor_ns, b.sensor_ns)
                self.locked = (
                    min(a.sensor_ns, b.sensor_ns) - self.good_since >= self.lock_ns
                )
            else:
                self.good_since = None
                self.locked = False
            if self.locked:
                self.sequence += 1
                result = FramePair(self.sequence, a, b)
        return result

    def status(self):
        values = sorted(self.deltas)
        return {
            "locked": self.locked,
            "pairs": self.sequence,
            "discarded_preview_frames": list(self.discarded),
            "p95_delta_us": values[min(len(values) - 1, int(len(values) * 0.95))] / 1000
            if values
            else None,
        }
