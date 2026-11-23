"""A discrete-event simulator. Same seed, same log."""

import heapq
import random


class Sim:
    """Events run in time order; ties run in the order they were scheduled."""

    def __init__(self, seed):
        self.now = 0.0
        self.rng = random.Random(seed)
        self.log = []
        self._queue = []
        self._count = 0

    def at(self, delay, fn, *args):
        """Schedule fn(sim, *args) at now + delay."""
        if not delay >= 0:  # also rejects NaN, which would break the heap order
            raise ValueError("delay must be a number, not negative or NaN")
        heapq.heappush(self._queue, (self.now + delay, self._count, fn, args))
        self._count += 1

    def run(self, until=None, max_events=None):
        """Run events in order; return how many ran. Stop before time > until."""
        ran = 0
        while self._queue and (max_events is None or ran < max_events):
            if until is not None and self._queue[0][0] > until:
                break
            self.now, _, fn, args = heapq.heappop(self._queue)
            fn(self, *args)
            ran += 1
        return ran

    def record(self, kind, **data):
        """Append a log row stamped with the current time. 't' and 'kind' are reserved."""
        if "t" in data or "kind" in data:
            raise ValueError("'t' and 'kind' are reserved in record()")
        self.log.append({"t": self.now, "kind": kind, **data})
