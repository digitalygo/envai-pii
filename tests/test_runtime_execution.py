import ast
import importlib
import io
import logging
import os
import queue
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "src" / "app"
sys.path.insert(0, str(APP_DIR))

import runtime_execution

try:
    import fitz
    HAVE_FITZ = not isinstance(fitz, MagicMock)
except ImportError:
    fitz = None
    HAVE_FITZ = False

try:
    from flask import Flask
    HAVE_FLASK = True
except ImportError:
    Flask = None
    HAVE_FLASK = False


class DeadlineExpired(Exception):
    pass


def _join(thread, timeout=2):
    thread.join(timeout)
    if thread.is_alive():
        raise AssertionError("execution thread did not finish")


def _app_module():
    if "app" in sys.modules:
        return sys.modules["app"]
    saved = {name: sys.modules.get(name) for name in ("torch", "transformers")}
    for name in saved:
        sys.modules[name] = MagicMock()
    previous = os.environ.get("PII_MODEL_DIR")
    os.environ["PII_MODEL_DIR"] = str(ROOT / "tests")
    try:
        import app
    finally:
        if previous is None:
            os.environ.pop("PII_MODEL_DIR", None)
        else:
            os.environ["PII_MODEL_DIR"] = previous
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
    return app


def _safe_output(value):
    if value is None or isinstance(value, (str, bytes, bool, int, float)):
        return True
    if isinstance(value, (tuple, list)):
        return all(_safe_output(item) for item in value)
    if isinstance(value, dict):
        return all(_safe_output(key) and _safe_output(item)
                   for key, item in value.items())
    return False


class NativeExecutionLaneTests(unittest.TestCase):
    def setUp(self):
        self.lane = runtime_execution.NativeExecutionLane("test")
        self.addCleanup(self.lane.shutdown)

    def test_separate_lanes_have_distinct_stable_owner_threads(self):
        model_lane = runtime_execution.NativeExecutionLane("model-test")
        pdf_lane = runtime_execution.NativeExecutionLane("pdf-test")
        self.addCleanup(model_lane.shutdown)
        self.addCleanup(pdf_lane.shutdown)
        rendezvous = threading.Barrier(3)
        owner_ids = {}

        def record(lane_name):
            owner_ids[lane_name] = threading.get_ident()
            rendezvous.wait(timeout=2)
            return threading.current_thread().name

        outputs = {}
        workers = [
            threading.Thread(
                target=lambda: outputs.setdefault(
                    "model", model_lane.run(record, "model"))),
            threading.Thread(
                target=lambda: outputs.setdefault(
                    "pdf", pdf_lane.run(record, "pdf"))),
        ]
        for worker in workers:
            worker.start()
        rendezvous.wait(timeout=2)
        for worker in workers:
            _join(worker)

        self.assertNotEqual(owner_ids["model"], owner_ids["pdf"])
        self.assertTrue(outputs["model"].startswith("native-model-test"))
        self.assertTrue(outputs["pdf"].startswith("native-pdf-test"))

    def test_only_one_submission_is_pending_or_running_per_lane(self):
        started = threading.Event()
        release = threading.Event()
        second_started = threading.Event()
        active = 0
        maximum_active = 0
        state_lock = threading.Lock()
        submitted = []
        real_submit = self.lane._executor.submit

        def submit(*args, **kwargs):
            submitted.append(args)
            return real_submit(*args, **kwargs)

        self.lane._executor.submit = submit

        def first_work():
            nonlocal active, maximum_active
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            started.set()
            if not release.wait(2):
                raise AssertionError("first work was not released")
            with state_lock:
                active -= 1
            return "first"

        def second_work():
            nonlocal active, maximum_active
            second_started.set()
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            with state_lock:
                active -= 1
            return "second"

        results = {}
        first = threading.Thread(
            target=lambda: results.setdefault("first", self.lane.run(first_work)))
        second = threading.Thread(
            target=lambda: results.setdefault("second", self.lane.run(second_work)))
        first.start()
        self.assertTrue(started.wait(1))
        second.start()
        self.assertFalse(second_started.wait(0.1))
        self.assertEqual(len(submitted), 1)
        release.set()
        _join(first)
        _join(second)

        self.assertEqual(results, {"first": "first", "second": "second"})
        self.assertEqual(len(submitted), 2)
        self.assertEqual(maximum_active, 1)

    def test_expired_deadline_on_free_gate_prevents_native_call_and_recovers(self):
        caller_thread = threading.get_ident()
        checks = []
        native_calls = []

        def expired():
            checks.append(threading.get_ident())
            raise DeadlineExpired()

        with self.assertRaises(DeadlineExpired):
            self.lane.run(
                lambda: native_calls.append("called"), check_deadline=expired)

        self.assertEqual(len(checks), 1)
        self.assertNotEqual(checks[0], caller_thread)
        self.assertEqual(native_calls, [])
        self.assertEqual(self.lane.run(lambda: "ready"), "ready")
        self.assertFalse(self.lane._gate.locked())

    def test_deadline_expiring_while_executor_start_is_blocked_prevents_call(self):
        executor_started = threading.Event()
        release_executor = threading.Event()
        self.addCleanup(release_executor.set)

        def block_executor():
            executor_started.set()
            if not release_executor.wait(2):
                raise AssertionError("executor block was not released")

        blocker = self.lane._executor.submit(block_executor)
        self.assertTrue(executor_started.wait(1))
        submitted = []
        scheduled = threading.Event()
        real_submit = self.lane._executor.submit

        def submit(*args, **kwargs):
            future = real_submit(*args, **kwargs)
            submitted.append(future)
            scheduled.set()
            return future

        self.lane._executor.submit = submit
        expired = threading.Event()
        native_calls = []
        errors = []

        def check_deadline():
            if expired.is_set():
                raise DeadlineExpired()

        def call_lane():
            try:
                self.lane.run(
                    lambda: native_calls.append("called"),
                    check_deadline=check_deadline)
            except BaseException as error:
                errors.append(error)

        caller = threading.Thread(target=call_lane)
        caller.start()
        self.assertTrue(scheduled.wait(1))
        expired.set()
        release_executor.set()
        _join(caller)
        blocker.result(timeout=1)

        self.assertEqual(len(submitted), 1)
        self.assertEqual(native_calls, [])
        self.assertIsInstance(errors[0], DeadlineExpired)
        self.assertEqual(self.lane.run(lambda: "ready"), "ready")

    def test_submit_failure_cancels_queued_input_and_closes_lane(self):
        marker = "PRIVATE_SUBMISSION_INPUT"
        submission_failure = KeyboardInterrupt("executor thread start failed")
        executions = []
        submit_count = 0
        shutdown_calls = []
        real_submit = self.lane._executor.submit
        real_shutdown = self.lane._executor.shutdown

        def fail_thread_start():
            raise submission_failure

        def submit(*args, **kwargs):
            nonlocal submit_count
            submit_count += 1
            return real_submit(*args, **kwargs)

        def shutdown(*args, **kwargs):
            shutdown_calls.append(kwargs.copy())
            return real_shutdown(*args, **kwargs)

        self.lane._executor._adjust_thread_count = fail_thread_start
        self.lane._executor.submit = submit
        self.lane._executor.shutdown = shutdown
        log_stream = io.StringIO()
        log_handler = logging.StreamHandler(log_stream)
        root_logger = logging.getLogger()
        root_logger.addHandler(log_handler)
        try:
            with self.assertRaises(KeyboardInterrupt) as raised:
                self.lane.run(lambda value: executions.append(value), marker)
        finally:
            root_logger.removeHandler(log_handler)
            log_handler.close()

        self.assertIs(raised.exception, submission_failure)
        self.assertEqual(executions, [])
        self.assertEqual(shutdown_calls[0], {
            "wait": True, "cancel_futures": True})
        self.assertNotIn(marker, str(raised.exception))
        self.assertNotIn(marker, log_stream.getvalue())

        work_queue = self.lane._executor._work_queue
        queued_items = []
        while True:
            try:
                queued_items.append(work_queue.get_nowait())
            except queue.Empty:
                break
        self.assertLessEqual(len(queued_items), 1)
        self.assertTrue(all(item is None for item in queued_items))

        for _ in range(3):
            with self.assertRaisesRegex(
                    RuntimeError, "^native execution lane is closed$") as closed:
                self.lane.run(lambda value: executions.append(value), marker)
            self.assertNotIn(marker, str(closed.exception))
        self.assertEqual(submit_count, 1)
        self.assertEqual(executions, [])
        self.assertEqual(work_queue.qsize(), 0)

    def test_submit_failure_after_native_start_waits_before_releasing_gate(self):
        marker = "PRIVATE_RUNNING_INPUT"
        started = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        shutdown_started = threading.Event()
        second_entered = threading.Event()
        second_finished = threading.Event()
        submission_failure = KeyboardInterrupt("submission interrupted")
        first_errors = []
        second_errors = []
        submitted = []
        shutdown_calls = []
        real_submit = self.lane._executor.submit
        real_shutdown = self.lane._executor.shutdown
        self.addCleanup(release.set)

        def submit(*args, **kwargs):
            future = real_submit(*args, **kwargs)
            submitted.append(future)
            if len(submitted) == 1:
                if not started.wait(1):
                    raise AssertionError("native work did not start")
                raise submission_failure
            return future

        def shutdown(*args, **kwargs):
            shutdown_calls.append(kwargs.copy())
            shutdown_started.set()
            return real_shutdown(*args, **kwargs)

        self.lane._executor.submit = submit
        self.lane._executor.shutdown = shutdown

        def native_work(value):
            started.set()
            if not release.wait(2):
                raise AssertionError("native work was not released")
            completed.set()
            return value

        def first_call():
            try:
                self.lane.run(native_work, marker)
            except BaseException as error:
                first_errors.append(error)

        def second_call():
            second_entered.set()
            try:
                self.lane.run(lambda value: value, marker)
            except BaseException as error:
                second_errors.append(error)
            finally:
                second_finished.set()

        first = threading.Thread(target=first_call)
        first.start()
        self.assertTrue(started.wait(1))
        self.assertTrue(shutdown_started.wait(1))
        self.assertTrue(first.is_alive())
        self.assertTrue(self.lane._gate.locked())
        self.assertFalse(completed.is_set())

        second = threading.Thread(target=second_call)
        second.start()
        self.assertTrue(second_entered.wait(1))
        self.assertFalse(second_finished.wait(0.1))
        self.assertEqual(len(submitted), 1)

        release.set()
        _join(first)
        _join(second)

        self.assertTrue(completed.is_set())
        self.assertIs(first_errors[0], submission_failure)
        self.assertEqual(len(second_errors), 1)
        self.assertIs(type(second_errors[0]), RuntimeError)
        self.assertEqual(str(second_errors[0]), "native execution lane is closed")
        self.assertEqual(shutdown_calls[0], {
            "wait": True, "cancel_futures": True})
        self.assertEqual(len(submitted), 1)
        self.assertFalse(self.lane._gate.locked())
        self.assertNotIn(marker, str(first_errors[0]))

    def test_interrupted_result_wait_keeps_gate_until_native_work_completes(self):
        started = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        interrupted_result = threading.Event()
        second_entered = threading.Event()
        second_started = threading.Event()
        interruption = KeyboardInterrupt("caller interrupted")
        first_errors = []
        second_errors = []
        events = []
        submitted = []
        self.addCleanup(release.set)
        real_submit = self.lane._executor.submit

        def submit(*args, **kwargs):
            future = real_submit(*args, **kwargs)
            submitted.append(future)
            if len(submitted) == 1:
                def raise_interruption(*_args, **_kwargs):
                    if not started.wait(1):
                        raise AssertionError("native work did not start")
                    interrupted_result.set()
                    raise interruption

                future.result = raise_interruption
            return future

        self.lane._executor.submit = submit

        def first_work():
            started.set()
            if not release.wait(2):
                raise AssertionError("first work was not released")
            completed.set()
            events.append("first-complete")

        def first_call():
            try:
                self.lane.run(first_work)
            except BaseException as error:
                first_errors.append(error)

        def second_call():
            second_entered.set()
            try:
                self.lane.run(lambda: (second_started.set(),
                                       events.append("second-started")))
            except BaseException as error:
                second_errors.append(error)

        first = threading.Thread(target=first_call)
        first.start()
        self.assertTrue(interrupted_result.wait(1))
        self.assertTrue(started.is_set())
        second = threading.Thread(target=second_call)
        second.start()
        self.assertTrue(second_entered.wait(1))
        self.assertFalse(second_started.wait(0.1))
        self.assertEqual(len(submitted), 1)

        release.set()
        _join(first)
        _join(second)

        self.assertIs(first_errors[0], interruption)
        self.assertEqual(second_errors, [])
        self.assertTrue(completed.is_set())
        self.assertEqual(len(submitted), 2)
        self.assertEqual(events, ["first-complete", "second-started"])
        self.assertFalse(self.lane._gate.locked())

    def test_nested_lane_call_runs_inline_on_the_owner_thread(self):
        submitted = []
        real_submit = self.lane._executor.submit

        def submit(*args, **kwargs):
            submitted.append(args)
            return real_submit(*args, **kwargs)

        self.lane._executor.submit = submit
        owner_ids = []

        def outer():
            owner_ids.append(threading.get_ident())
            return self.lane.run(
                lambda: (owner_ids.append(threading.get_ident()), "nested")[1])

        self.assertEqual(self.lane.run(outer), "nested")
        self.assertEqual(len(set(owner_ids)), 1)
        self.assertEqual(len(submitted), 1)

    def test_nested_deadline_checks_and_baseexception_restore_lane_state(self):
        checks = []

        def nested_check():
            checks.append(threading.get_ident())

        self.assertEqual(
            self.lane.run(lambda: self.lane.run(
                lambda: "nested", check_deadline=nested_check),
                check_deadline=nested_check),
            "nested")
        self.assertEqual(len(checks), 4)

        class FatalSignal(BaseException):
            pass

        for failure in (ValueError("expected"), FatalSignal()):
            with self.assertRaises(type(failure)):
                self.lane.run(lambda error=failure: (_ for _ in ()).throw(error))
            self.assertEqual(self.lane.run(lambda: "ready"), "ready")

    def test_deadline_after_wait_is_checked_again_before_submission(self):
        started = threading.Event()
        release = threading.Event()
        first_poll = threading.Event()
        submitted = []
        errors = []
        real_submit = self.lane._executor.submit

        def submit(*args, **kwargs):
            submitted.append(args)
            return real_submit(*args, **kwargs)

        self.lane._executor.submit = submit

        def blocking_work():
            started.set()
            if not release.wait(2):
                raise AssertionError("blocking work was not released")

        def check_deadline():
            if first_poll.is_set():
                raise DeadlineExpired()
            first_poll.set()

        first = threading.Thread(target=lambda: self.lane.run(blocking_work))

        def second_call():
            try:
                self.lane.run(lambda: self.fail("expired work was scheduled"),
                              check_deadline=check_deadline)
            except BaseException as error:
                errors.append(error)

        second = threading.Thread(target=second_call)
        first.start()
        self.assertTrue(started.wait(1))
        second.start()
        self.assertTrue(first_poll.wait(1))
        release.set()
        _join(first)
        _join(second)

        self.assertEqual(len(submitted), 1)
        self.assertIsInstance(errors[0], DeadlineExpired)
        self.assertFalse(self.lane._gate.locked())

    def test_deadline_while_waiting_does_not_add_executor_work(self):
        started = threading.Event()
        release = threading.Event()
        waiting = threading.Event()
        submitted = []
        errors = []
        real_submit = self.lane._executor.submit

        def submit(*args, **kwargs):
            submitted.append(args)
            return real_submit(*args, **kwargs)

        self.lane._executor.submit = submit

        def blocking_work():
            started.set()
            if not release.wait(2):
                raise AssertionError("blocking work was not released")
            return "finished"

        first = threading.Thread(target=lambda: self.lane.run(blocking_work))

        def second_call():
            waiting.set()
            try:
                self.lane.run(lambda: self.fail("waiting work was scheduled"),
                              check_deadline=expired)
            except BaseException as error:
                errors.append(error)

        def expired():
            raise DeadlineExpired()

        second = threading.Thread(target=second_call)
        first.start()
        self.assertTrue(started.wait(1))
        second.start()
        self.assertTrue(waiting.wait(1))
        _join(second)
        self.assertEqual(len(submitted), 1)
        self.assertIsInstance(errors[0], DeadlineExpired)
        release.set()
        _join(first)
        self.assertFalse(self.lane._gate.locked())

    def test_deadline_during_running_work_waits_for_completion_before_release(self):
        started = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        second_started = threading.Event()
        first_errors = []
        events = []

        def check_first_deadline():
            if completed.is_set():
                raise DeadlineExpired()

        def first_work():
            started.set()
            if not release.wait(2):
                raise AssertionError("first work was not released")
            completed.set()
            events.append("first-complete")

        def first_call():
            try:
                self.lane.run(first_work, check_deadline=check_first_deadline)
            except BaseException as error:
                first_errors.append(error)

        first = threading.Thread(target=first_call)
        second = threading.Thread(target=lambda: self.lane.run(
            lambda: (second_started.set(), events.append("second-started"))))
        first.start()
        self.assertTrue(started.wait(1))
        second.start()
        self.assertFalse(second_started.wait(0.1))
        self.assertFalse(completed.is_set())
        release.set()
        _join(first)
        _join(second)

        self.assertIsInstance(first_errors[0], DeadlineExpired)
        self.assertEqual(events, ["first-complete", "second-started"])
        self.assertTrue(second_started.is_set())
        self.assertFalse(self.lane._gate.locked())


class NativeWiringTests(unittest.TestCase):
    APP_SOURCE = APP_DIR / "app.py"
    PDF_EXPORT_SOURCE = APP_DIR / "pdf_export.py"

    def test_source_routes_each_native_entrypoint_to_its_lane(self):
        expected = {
            self.APP_SOURCE: {
                "_silence_native_mupdf_diagnostics": "PDF_LANE",
                "_reset_native_mupdf_warnings": "PDF_LANE",
                "_store_doc": "PDF_LANE",
                "_page_png": "PDF_LANE",
                "_text_from_bytes": "PDF_LANE",
                "_guardrail_extract": "PDF_LANE",
                "detect_model": "MODEL_LANE",
                "_guardrail_detect": "MODEL_LANE",
            },
            self.PDF_EXPORT_SOURCE: {
                "redact_pdf": "PDF_LANE",
                "text_to_pdf": "PDF_LANE",
            },
        }
        for source_path, functions in expected.items():
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            definitions = {node.name: node for node in tree.body
                           if isinstance(node, ast.FunctionDef)}
            for name, lane_name in functions.items():
                with self.subTest(function=name):
                    calls_lane = any(
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "run"
                        and isinstance(node.func.value, ast.Attribute)
                        and node.func.value.attr == lane_name
                        and isinstance(node.func.value.value, ast.Name)
                        and node.func.value.value.id == "runtime_execution"
                        for node in ast.walk(definitions[name]))
                    self.assertTrue(calls_lane)

        app_tree = ast.parse(self.APP_SOURCE.read_text(encoding="utf-8"))
        startup = next(node for node in app_tree.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name)
                               and target.id == "MUPDF_PRIVACY_OK"
                               for target in node.targets))
        self.assertIsInstance(startup.value, ast.Call)
        self.assertEqual(startup.value.func.id, "_silence_native_mupdf_diagnostics")

    @unittest.skipUnless(HAVE_FLASK, "Flask absent")
    def test_model_legacy_and_v1_share_owner_without_request_state_leak(self):
        app = _app_module()
        start = threading.Barrier(3)
        outputs = {}
        owner_ids = []
        model_inputs = []
        lock = threading.Lock()

        def model(inputs):
            marker = inputs[0]
            with lock:
                model_inputs.append(marker)
                owner_ids.append(threading.get_ident())
            return [[{"entity_group": "FULLNAME", "start": 0,
                      "end": len(marker), "score": 0.9}]]

        def legacy_call():
            start.wait(timeout=2)
            outputs["legacy"] = app.detect_model("LEGACYMARKER")

        def v1_call():
            start.wait(timeout=2)
            outputs["v1"] = app._guardrail_detect("V1MARKER", lambda: None)

        with patch.object(app, "nlp", model):
            legacy = threading.Thread(target=legacy_call)
            v1 = threading.Thread(target=v1_call)
            legacy.start()
            v1.start()
            start.wait(timeout=2)
            _join(legacy)
            _join(v1)

        self.assertEqual(set(model_inputs), {"LEGACYMARKER", "V1MARKER"})
        self.assertEqual(len(set(owner_ids)), 1)
        legacy_entities, legacy_chunks = outputs["legacy"]
        self.assertEqual(legacy_chunks, 1)
        self.assertEqual(legacy_entities[0]["end"], len("LEGACYMARKER"))
        self.assertEqual(outputs["v1"][0]["end"], len("V1MARKER"))

    @unittest.skipUnless(HAVE_FLASK, "Flask absent")
    def test_app_native_pdf_paths_keep_objects_on_pdf_owner_and_return_safe_values(self):
        app = _app_module()
        calls = []
        state = {"errors": 1, "warnings": 1}
        sensitive_reset_result = "PRIVATE_MUPDF_WARNING_CONTENT"

        def record(name):
            calls.append((name, threading.get_ident(), threading.current_thread().name))

        class Pixmap:
            def tobytes(self, image_type):
                record("pixmap.tobytes")
                return b"png-bytes" if image_type == "png" else b""

        class Page:
            def get_pixmap(self, dpi):
                record("page.get_pixmap")
                return Pixmap()

        class Document:
            is_pdf = True
            needs_pass = False
            is_encrypted = False
            page_count = 2

            def __enter__(self):
                record("document.enter")
                return self

            def __exit__(self, *_exc):
                record("document.exit")
                return False

            def close(self):
                record("document.close")

            def load_page(self, page_number):
                record("document.load_page")
                return Page()

        def open_document(**_kwargs):
            record("fitz.open")
            return Document()

        def display_error(value=None):
            if value is not None:
                state["errors"] = int(value)
                record("display_errors.set")
                return None
            record("display_errors.get")
            return state["errors"]

        def display_warning(value=None):
            if value is not None:
                state["warnings"] = int(value)
                record("display_warnings.set")
                return None
            record("display_warnings.get")
            return state["warnings"]

        def warnings(reset=False):
            record("warnings.reset")
            return sensitive_reset_result if reset else ""

        fake_fitz = SimpleNamespace(
            TOOLS=SimpleNamespace(
                mupdf_display_errors=display_error,
                mupdf_display_warnings=display_warning,
                mupdf_warnings=warnings),
            open=open_document)
        text_calls = []

        def collect_text(document, **_kwargs):
            self.assertIsInstance(document, Document)
            record("pdf_text.collect")
            text_calls.append(threading.get_ident())
            return "synthetic pdf text"

        with patch.object(app, "fitz", fake_fitz), \
                patch.object(app.pdf_text, "collect_readable_text", collect_text), \
                patch.object(app, "MUPDF_PRIVACY_OK", True):
            self.assertTrue(app._silence_native_mupdf_diagnostics())
            self.assertTrue(app._reset_native_mupdf_warnings())
            stored = app._store_doc(b"pdf", "sample.pdf")
            document_record = {"pdf": b"pdf", "pages": {}, "n_pages": 2}
            rendered = app._page_png(document_record, 0)
            extracted = app._text_from_bytes("sample.pdf", b"%PDF-")
            guarded = app._guardrail_extract(
                "sample.pdf", b"%PDF-", 100, lambda: None)

        owner_ids = {item[1] for item in calls}
        self.assertEqual(len(owner_ids), 1)
        self.assertTrue(all(item[2].startswith("native-pdf") for item in calls))
        self.assertEqual(len(set(text_calls)), 1)
        self.assertEqual(state, {"errors": 0, "warnings": 0})
        self.assertEqual(rendered, b"png-bytes")
        self.assertEqual(extracted, "synthetic pdf text")
        self.assertEqual(guarded, "synthetic pdf text")
        self.assertEqual(stored[1], 2)
        self.assertTrue(_safe_output((stored, rendered, extracted, guarded)))
        self.assertEqual([item[0] for item in calls].count("warnings.reset"), 3)
        self.assertTrue(all(item[0] != sensitive_reset_result for item in calls))
        with app._DOCS_LOCK:
            app._DOCS.pop(stored[0], None)

    @unittest.skipUnless(HAVE_FLASK, "Flask absent")
    def test_startup_mupdf_silencing_runs_on_pdf_owner(self):
        _app_module()
        previous_app = sys.modules.pop("app", None)
        saved = {name: sys.modules.get(name)
                 for name in ("torch", "transformers", "fitz")}
        previous_model = os.environ.get("PII_MODEL_DIR")
        calls = []
        state = {"errors": 1, "warnings": 1}

        def record(name):
            calls.append((name, threading.get_ident(), threading.current_thread().name))

        def display_errors(value=None):
            if value is not None:
                state["errors"] = int(value)
                record("display_errors.set")
                return None
            record("display_errors.get")
            return state["errors"]

        def display_warnings(value=None):
            if value is not None:
                state["warnings"] = int(value)
                record("display_warnings.set")
                return None
            record("display_warnings.get")
            return state["warnings"]

        def reset_warnings(reset=False):
            record("warnings.reset")
            return "PRIVATE_STARTUP_WARNING" if reset else ""

        fake_fitz = MagicMock()
        fake_fitz.TOOLS.mupdf_display_errors = display_errors
        fake_fitz.TOOLS.mupdf_display_warnings = display_warnings
        fake_fitz.TOOLS.mupdf_warnings = reset_warnings
        for name in ("torch", "transformers"):
            sys.modules[name] = MagicMock()
        sys.modules["fitz"] = fake_fitz
        os.environ["PII_MODEL_DIR"] = str(ROOT / "tests")
        fresh = None
        try:
            fresh = importlib.import_module("app")
        finally:
            sys.modules.pop("app", None)
            if previous_app is not None:
                sys.modules["app"] = previous_app
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
            if previous_model is None:
                os.environ.pop("PII_MODEL_DIR", None)
            else:
                os.environ["PII_MODEL_DIR"] = previous_model

        self.assertIsNotNone(fresh)
        self.assertTrue(fresh.MUPDF_PRIVACY_OK)
        self.assertEqual(state, {"errors": 0, "warnings": 0})
        self.assertEqual([call[0] for call in calls], [
            "display_errors.set", "display_warnings.set",
            "display_errors.get", "display_warnings.get", "warnings.reset"])
        self.assertEqual(len({call[1] for call in calls}), 1)
        self.assertTrue(all(call[2].startswith("native-pdf") for call in calls))

    @unittest.skipUnless(HAVE_FITZ, "PyMuPDF absent")
    def test_pdf_export_returns_only_serializable_results_from_owner_thread(self):
        module = importlib.import_module("pdf_export")
        real_fitz = importlib.import_module("fitz")
        owner_calls = []

        class TrackingFitz:
            def __getattr__(self, name):
                return getattr(real_fitz, name)

            def open(self, *args, **kwargs):
                owner_calls.append((threading.get_ident(), threading.current_thread().name))
                return real_fitz.open(*args, **kwargs)

        original_fitz = module.fitz
        module.fitz = TrackingFitz()
        try:
            rendered = module.text_to_pdf("Mario Rossi, test PDF")
            redacted, report = module.redact_pdf(
                rendered, {"[FULLNAME_1]": "Mario Rossi"})
        finally:
            module.fitz = original_fitz

        self.assertTrue(rendered.startswith(b"%PDF-"))
        self.assertTrue(redacted.startswith(b"%PDF-"))
        self.assertGreater(report["occurrences"], 0)
        self.assertTrue(_safe_output((rendered, report, redacted)))
        self.assertEqual(len({item[0] for item in owner_calls}), 1)
        self.assertTrue(all(item[1].startswith("native-pdf") for item in owner_calls))


if __name__ == "__main__":
    unittest.main()
