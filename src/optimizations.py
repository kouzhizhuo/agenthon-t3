"""Exact-order optimizations with no event filtering or extra RNG draws."""
from contextlib import contextmanager
import heapq


class HeapQueue:
    """Single-thread heap preserving PriorityQueue's entire tuple comparison key."""
    def __init__(self):
        self.queue = []

    def put(self, item, block=True, timeout=None):
        heapq.heappush(self.queue, item)

    def get(self, block=True, timeout=None):
        return heapq.heappop(self.queue)

    def empty(self):
        return not self.queue

    def qsize(self):
        return len(self.queue)


def scalar_latency(self, sender_id, recipient_id):
    if sender_id == recipient_id:
        return 0
    if self._model == "log_normal":
        value = self.random_state.lognormal(mean=self._mu, sigma=self._sigma)
    elif self._model == "uniform":
        value = self.random_state.uniform(self._min_ns, self._max_ns)
    elif self._model == "pareto":
        base = self._min_ns if self._min_ns > 0 else 1.0
        value = base * (1.0 + self.random_state.pareto(self._alpha))
    else:
        value = self._mean_ns
    # No reduction/reassociation: same scalar draw, bounds, Python float and round.
    if value < self._min_ns:
        value = self._min_ns
    if value > self._max_ns:
        value = self._max_ns
    return int(round(float(value)))


@contextmanager
def enabled(active=True):
    if not active:
        yield
        return
    from abides_core.kernel import Kernel
    from abides_fork.config import ScenarioLatencyModel
    old_init, old_latency = Kernel.__init__, ScenarioLatencyModel.get_latency

    def initialize(self, *args, **kwargs):
        old_init(self, *args, **kwargs)
        self.messages = HeapQueue()

    Kernel.__init__ = initialize
    ScenarioLatencyModel.get_latency = scalar_latency
    try:
        yield
    finally:
        Kernel.__init__ = old_init
        ScenarioLatencyModel.get_latency = old_latency
