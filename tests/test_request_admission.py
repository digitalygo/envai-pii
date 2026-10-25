import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "src" / "app"
sys.path.insert(0, str(APP_DIR))

import request_admission


class AdmissionConfigTests(unittest.TestCase):
    def test_defaults_and_count_bounds(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                request_admission.resolve_admission_config(),
                request_admission.AdmissionConfig(4, 4, 5.0),
            )
        with patch.dict(os.environ, {
            "PII_MAX_CONCURRENT_ANALYSES": "99",
            "PII_MAX_QUEUED_ANALYSES": "99",
            "PII_QUEUE_TIMEOUT_SECONDS": "99",
        }, clear=True):
            self.assertEqual(
                request_admission.resolve_admission_config(),
                request_admission.AdmissionConfig(16, 32, 30.0),
            )
        with patch.dict(os.environ, {
            "PII_MAX_CONCURRENT_ANALYSES": "0",
            "PII_MAX_QUEUED_ANALYSES": "0",
            "PII_QUEUE_TIMEOUT_SECONDS": "0.25",
        }, clear=True):
            self.assertEqual(
                request_admission.resolve_admission_config(),
                request_admission.AdmissionConfig(4, 0, 0.25),
            )

    def test_invalid_count_and_timeout_values_fall_back_safely(self):
        for value in ("", "  ", "nope", "1.5", "-2"):
            with self.subTest(variable="PII_MAX_CONCURRENT_ANALYSES", value=value):
                with patch.dict(os.environ, {
                    "PII_MAX_CONCURRENT_ANALYSES": value,
                }, clear=True):
                    config = request_admission.resolve_admission_config()
                    self.assertEqual(config.max_concurrent_analyses, 4)
            with self.subTest(variable="PII_MAX_QUEUED_ANALYSES", value=value):
                with patch.dict(os.environ, {
                    "PII_MAX_QUEUED_ANALYSES": value,
                }, clear=True):
                    config = request_admission.resolve_admission_config()
                    self.assertEqual(config.max_queued_analyses, 4)
        for value in ("", "  ", "nope", "nan", "inf", "-inf", "0", "-1"):
            with self.subTest(variable="PII_QUEUE_TIMEOUT_SECONDS", value=value):
                with patch.dict(os.environ, {
                    "PII_QUEUE_TIMEOUT_SECONDS": value,
                }, clear=True):
                    config = request_admission.resolve_admission_config()
                    self.assertEqual(config.queue_timeout_seconds, 5.0)

    def test_gunicorn_threads_are_resolved_from_admission_settings(self):
        script = (
            "import json, runpy; "
            f"settings = runpy.run_path({str(APP_DIR / 'gunicorn_config.py')!r}); "
            "print(json.dumps({key: settings[key] for key in "
            "('workers', 'worker_class', 'threads', 'preload_app')}))"
        )
        environment = os.environ.copy()
        environment.update({
            "PII_MAX_CONCURRENT_ANALYSES": "6",
            "PII_MAX_QUEUED_ANALYSES": "3",
        })
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=directory,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
        self.assertEqual(json.loads(result.stdout), {
            "workers": 1,
            "worker_class": "gthread",
            "threads": 11,
            "preload_app": False,
        })


class RequestAdmissionTests(unittest.TestCase):
    def test_fifo_capacity_bounds_and_no_queue_jump(self):
        config = request_admission.AdmissionConfig(4, 4, 3.0)
        admission = request_admission.RequestAdmission(config)
        active_leases = [admission.acquire() for _ in range(4)]
        self.assertTrue(all(active_leases))
        self.assertEqual(admission.active_count, 4)

        admitted = []
        admitted_events = [threading.Event() for _ in range(4)]
        release_events = [threading.Event() for _ in range(4)]
        workers = []

        def queued_worker(index):
            lease = admission.acquire()
            if lease is None:
                return
            admitted.append(index)
            admitted_events[index].set()
            release_events[index].wait(2.0)
            lease.release()

        for index in range(4):
            worker = threading.Thread(target=queued_worker, args=(index,))
            worker.start()
            workers.append(worker)
            self.assertTrue(admission.wait_for_queue_size(index + 1, 1.0))

        self.assertEqual(admission.acquire(), None)
        for index, active_lease in enumerate(active_leases):
            active_lease.release()
            self.assertTrue(admitted_events[index].wait(1.0))
            self.assertEqual(admitted, list(range(index + 1)))

        for event in release_events:
            event.set()
        for worker in workers:
            worker.join(1.0)
            self.assertFalse(worker.is_alive())
        self.assertEqual(admission.active_count, 0)
        self.assertEqual(admission.queued_count, 0)

    def test_enqueue_notifies_queue_observers(self):
        admission = request_admission.RequestAdmission(
            request_admission.AdmissionConfig(1, 1, 1.0)
        )
        active_lease = admission.acquire()
        condition_waiting = threading.Event()
        observer_woke = threading.Event()
        observer_done = threading.Event()
        observed = []
        original_wait = admission._condition.wait

        def tracked_wait(timeout=None):
            is_observer = threading.current_thread().name == "queue-observer"
            if is_observer:
                condition_waiting.set()
            result = original_wait(timeout)
            if is_observer:
                observer_woke.set()
            return result

        def observe_queue():
            observed.append(admission.wait_for_queue_size(1, timeout=2.0))
            observer_done.set()

        observer = threading.Thread(target=observe_queue, name="queue-observer")
        queued = None
        queued_done = threading.Event()

        def acquire_and_release():
            lease = admission.acquire()
            if lease is not None:
                lease.release()
            queued_done.set()

        try:
            with patch.object(admission._condition, "wait", side_effect=tracked_wait):
                observer.start()
                self.assertTrue(condition_waiting.wait(1.0))
                queued = threading.Thread(target=acquire_and_release)
                queued.start()
                self.assertTrue(observer_woke.wait(0.5))
                self.assertTrue(observer_done.wait(1.0))
                self.assertEqual(observed, [True])
                self.assertEqual(admission.queued_count, 1)
                active_lease.release()
                self.assertTrue(queued_done.wait(1.0))
        finally:
            active_lease.release()
            observer.join(2.0)
            if queued is not None:
                queued.join(2.0)
        self.assertFalse(observer.is_alive())
        self.assertIsNotNone(queued)
        self.assertFalse(queued.is_alive())
        self.assertEqual(admission.active_count, 0)
        self.assertEqual(admission.queued_count, 0)

    def test_queue_clock_base_exception_removes_enqueued_waiter(self):
        class ClockInterrupted(BaseException):
            pass

        admission = request_admission.RequestAdmission(
            request_admission.AdmissionConfig(1, 1, 1.0)
        )
        active_lease = admission.acquire()
        with patch.object(request_admission, "_QUEUE_CLOCK",
                          side_effect=ClockInterrupted):
            with self.assertRaises(ClockInterrupted):
                admission.acquire()
        self.assertEqual(admission.active_count, 1)
        self.assertEqual(admission.queued_count, 0)
        active_lease.release()
        recovered = admission.acquire()
        self.assertIsNotNone(recovered)
        recovered.release()
        self.assertEqual(admission.active_count, 0)

    def test_zero_queue_rejects_waiters_but_keeps_active_capacity(self):
        admission = request_admission.RequestAdmission(
            request_admission.AdmissionConfig(1, 0, 1.0)
        )
        active_lease = admission.acquire()
        self.assertIsNone(admission.acquire())
        self.assertEqual(admission.active_count, 1)
        self.assertEqual(admission.queued_count, 0)
        active_lease.release()
        recovered = admission.acquire()
        self.assertIsNotNone(recovered)
        recovered.release()

    def test_lease_release_is_idempotent_and_capacity_never_goes_negative(self):
        admission = request_admission.RequestAdmission(
            request_admission.AdmissionConfig(1, 0, 1.0)
        )
        lease = admission.acquire()
        lease.release()
        lease.release()
        self.assertEqual(admission.active_count, 0)
        with self.assertRaises(RuntimeError):
            admission._release()
        self.assertEqual(admission.active_count, 0)

    def test_timeout_removes_waiter_and_permit_recovers(self):
        admission = request_admission.RequestAdmission(
            request_admission.AdmissionConfig(1, 1, 0.05)
        )
        active_lease = admission.acquire()
        outcomes = []
        finished = threading.Event()

        def wait_for_permit():
            outcomes.append(admission.acquire())
            finished.set()

        waiter = threading.Thread(target=wait_for_permit)
        waiter.start()
        self.assertTrue(admission.wait_for_queue_size(1, 1.0))
        self.assertTrue(finished.wait(1.0))
        waiter.join(1.0)
        self.assertEqual(outcomes, [None])
        self.assertEqual(admission.queued_count, 0)
        active_lease.release()
        recovered = admission.acquire()
        self.assertIsNotNone(recovered)
        recovered.release()
        self.assertEqual(admission.active_count, 0)

    def test_base_exception_cleans_waiter_and_releases_capacity(self):
        class Cancelled(BaseException):
            pass

        admission = request_admission.RequestAdmission(
            request_admission.AdmissionConfig(1, 1, 2.0)
        )
        active_lease = admission.acquire()
        finished = threading.Event()
        failures = []

        def cancel_waiter():
            try:
                admission.acquire()
            except Cancelled:
                failures.append("cancelled")
            finally:
                finished.set()

        with patch.object(admission._condition, "wait", side_effect=Cancelled):
            waiter = threading.Thread(target=cancel_waiter)
            waiter.start()
            self.assertTrue(finished.wait(1.0))
            waiter.join(1.0)
        self.assertEqual(failures, ["cancelled"])
        self.assertEqual(admission.queued_count, 0)
        active_lease.release()
        recovered = admission.acquire()
        self.assertIsNotNone(recovered)
        recovered.release()
        self.assertEqual(admission.active_count, 0)


if __name__ == "__main__":
    unittest.main()
