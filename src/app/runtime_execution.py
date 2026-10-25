from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
import threading
from typing import Any


class NativeExecutionLane:
    def __init__(self, name: str, wait_interval: float = 0.05):
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"native-{name}")
        self._gate = threading.Lock()
        self._owner = threading.local()
        self._wait_interval = wait_interval
        self._closed = False

    def run(self, function: Callable[..., Any], *args: Any,
            check_deadline: Callable[[], Any] | None = None,
            **kwargs: Any) -> Any:
        def check() -> None:
            if check_deadline is not None:
                check_deadline()

        if getattr(self._owner, "active", False):
            check()
            result = function(*args, **kwargs)
            check()
            return result

        acquired = self._gate.acquire(blocking=False)
        waited = not acquired
        while not acquired:
            check()
            acquired = self._gate.acquire(timeout=self._wait_interval)
        release_gate = True
        try:
            if waited:
                check()
            if self._closed:
                raise RuntimeError("native execution lane is closed")
            try:
                future = self._executor.submit(
                    self._invoke, function, args, kwargs, check_deadline)
            except BaseException:
                self._closed = True
                self._executor.shutdown(wait=True, cancel_futures=True)
                raise
            try:
                result = future.result()
            except BaseException:
                if not future.done():
                    release_gate = False
                    future.add_done_callback(
                        lambda _future: self._gate.release())
                    wait((future,))
                raise
            check()
            return result
        finally:
            if release_gate:
                self._gate.release()

    def _invoke(self, function: Callable[..., Any], args: tuple[Any, ...],
                kwargs: dict[str, Any],
                check_deadline: Callable[[], Any] | None) -> Any:
        previous = getattr(self._owner, "active", False)
        self._owner.active = True
        try:
            if check_deadline is not None:
                check_deadline()
            return function(*args, **kwargs)
        finally:
            self._owner.active = previous

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)


MODEL_LANE = NativeExecutionLane("model")
PDF_LANE = NativeExecutionLane("pdf")
