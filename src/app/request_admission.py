import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass


DEFAULT_MAX_CONCURRENT_ANALYSES = 4
DEFAULT_MAX_QUEUED_ANALYSES = 4
DEFAULT_QUEUE_TIMEOUT_SECONDS = 5.0
MAX_CONCURRENT_ANALYSES = 16
MAX_QUEUED_ANALYSES = 32
MAX_QUEUE_TIMEOUT_SECONDS = 30.0
MAX_CONCURRENT_ANALYSES_ENV = "PII_MAX_CONCURRENT_ANALYSES"
MAX_QUEUED_ANALYSES_ENV = "PII_MAX_QUEUED_ANALYSES"
QUEUE_TIMEOUT_SECONDS_ENV = "PII_QUEUE_TIMEOUT_SECONDS"
_QUEUE_CLOCK = time.monotonic


@dataclass(frozen=True, slots=True)
class AdmissionConfig:
    max_concurrent_analyses: int
    max_queued_analyses: int
    queue_timeout_seconds: float


def _bounded_count(name, default, minimum, maximum):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip(), 10)
    except (AttributeError, TypeError, ValueError):
        return default
    if value < minimum:
        return default
    return min(value, maximum)


def _queue_timeout():
    raw = os.environ.get(QUEUE_TIMEOUT_SECONDS_ENV)
    if raw is None:
        return DEFAULT_QUEUE_TIMEOUT_SECONDS
    try:
        seconds = float(raw.strip())
    except (AttributeError, TypeError, ValueError):
        return DEFAULT_QUEUE_TIMEOUT_SECONDS
    if not math.isfinite(seconds) or seconds <= 0.0:
        return DEFAULT_QUEUE_TIMEOUT_SECONDS
    return min(seconds, MAX_QUEUE_TIMEOUT_SECONDS)


def resolve_admission_config():
    return AdmissionConfig(
        max_concurrent_analyses=_bounded_count(
            MAX_CONCURRENT_ANALYSES_ENV,
            DEFAULT_MAX_CONCURRENT_ANALYSES,
            1,
            MAX_CONCURRENT_ANALYSES,
        ),
        max_queued_analyses=_bounded_count(
            MAX_QUEUED_ANALYSES_ENV,
            DEFAULT_MAX_QUEUED_ANALYSES,
            0,
            MAX_QUEUED_ANALYSES,
        ),
        queue_timeout_seconds=_queue_timeout(),
    )


class _AdmissionLease:
    __slots__ = ("_release", "_released", "_lock")

    def __init__(self, release):
        self._release = release
        self._released = False
        self._lock = threading.Lock()

    def release(self):
        with self._lock:
            if self._released:
                return
            self._released = True
        self._release()


class RequestAdmission:
    def __init__(self, config=None):
        self.config = config if config is not None else resolve_admission_config()
        self._condition = threading.Condition()
        self._active = 0
        self._waiters = deque()

    @property
    def active_count(self):
        with self._condition:
            return self._active

    @property
    def queued_count(self):
        with self._condition:
            return len(self._waiters)

    def wait_for_queue_size(self, count, timeout=None):
        with self._condition:
            return self._condition.wait_for(
                lambda: len(self._waiters) == count,
                timeout=timeout,
            )

    def acquire(self):
        lease = _AdmissionLease(self._release)
        with self._condition:
            if self._active < self.config.max_concurrent_analyses and not self._waiters:
                self._active += 1
                return lease
            if (self.config.max_queued_analyses == 0
                    or len(self._waiters) >= self.config.max_queued_analyses):
                return None
            waiter = object()
            self._waiters.append(waiter)
            self._condition.notify_all()
            try:
                deadline = _QUEUE_CLOCK() + self.config.queue_timeout_seconds
                while True:
                    remaining = deadline - _QUEUE_CLOCK()
                    if remaining <= 0:
                        self._waiters.remove(waiter)
                        self._condition.notify_all()
                        return None
                    if (self._waiters[0] is waiter
                            and self._active < self.config.max_concurrent_analyses):
                        self._waiters.popleft()
                        self._active += 1
                        self._condition.notify_all()
                        return lease
                    self._condition.wait(remaining)
            except BaseException:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)
                    self._condition.notify_all()
                raise

    def _release(self):
        with self._condition:
            if self._active < 1:
                raise RuntimeError("admission permit released without an active lease")
            self._active -= 1
            self._condition.notify_all()
