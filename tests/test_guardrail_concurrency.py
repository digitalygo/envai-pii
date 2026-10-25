import contextlib
import io
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "src" / "app"
sys.path.insert(0, str(APP_DIR))

import guardrail_api
import request_admission

try:
    from flask import Flask, request
    HAVE_FLASK = True
except ImportError:
    Flask = None
    request = None
    HAVE_FLASK = False

try:
    import fitz
    HAVE_FITZ = True
except ImportError:
    fitz = None
    HAVE_FITZ = False

HAVE_NATIVE_MULTIPART = guardrail_api.guardrail_inputs.native_multipart_available()

TOKEN = "admission-test-token"
AUTH = {"Authorization": "Bearer " + TOKEN}
PATH = "/api/v1/analyses"
TAGS = ("EMAIL", "ORG")


def _detect_none(_text, _check):
    return []


@unittest.skipUnless(HAVE_FLASK, "Flask is unavailable")
class DefaultBlueprintAdmissionTests(unittest.TestCase):
    def test_default_blueprint_limits_fifo_auth_and_request_local_results(self):
        environment = {
            "PII_API_TOKEN": TOKEN,
            "PII_MAX_CONCURRENT_ANALYSES": "4",
            "PII_MAX_QUEUED_ANALYSES": "4",
            "PII_QUEUE_TIMEOUT_SECONDS": "5",
        }
        with patch.dict(os.environ, environment):
            readiness_state = {"ready": True}
            ready_calls = []
            blocked_cases = ["a1", "a2", "a3", "a4"]
            entered = {case: threading.Event() for case in blocked_cases}
            release = {case: threading.Event() for case in blocked_cases}
            reader_events = {}
            reader_cases = []
            detected_cases = []
            state_lock = threading.Lock()

            def readiness():
                ready_calls.append(readiness_state["ready"])
                return readiness_state["ready"]

            def detect(text, _check):
                with state_lock:
                    detected_cases.append(text)
                if text.startswith("blocked-"):
                    case = text.split()[0].removeprefix("blocked-")
                    entered[case].set()
                    if not release[case].wait(4.0):
                        raise TimeoutError("blocked detector timed out")
                return []

            application = Flask("default-admission-test")
            application.config["TESTING"] = True
            blueprint = guardrail_api.create_blueprint(
                TAGS, detect, readiness=readiness
            )
            application.register_blueprint(blueprint)
            admission = blueprint.request_admission
            self.assertIsInstance(admission, request_admission.RequestAdmission)
            self.assertEqual(admission.config, request_admission.AdmissionConfig(4, 4, 5.0))
            with self.assertRaises(ValueError):
                guardrail_api.create_blueprint(
                    TAGS, _detect_none, lock=threading.Lock(), admission=admission
                )
            with patch.dict(os.environ, {
                "PII_MAX_CONCURRENT_ANALYSES": "1",
                "PII_MAX_QUEUED_ANALYSES": "0",
                "PII_QUEUE_TIMEOUT_SECONDS": "0.1",
            }):
                self.assertEqual(
                    admission.config,
                    request_admission.AdmissionConfig(4, 4, 5.0),
                )

            original_reader = guardrail_api._read_body

            def tracked_reader(cap):
                case = request.headers.get("X-Test-Case")
                with state_lock:
                    reader_cases.append(case)
                    reader_events.setdefault(case, threading.Event()).set()
                return original_reader(cap)

            def payload(case, blocked=False, category="ORG"):
                prefix = "blocked-" if blocked else "queued-"
                return {
                    "text": f"{prefix}{case} org-{case} email-{case}",
                    "dictionary": {
                        "[ORG_1]": f"org-{case}",
                        "[EMAIL_1]": f"email-{case}",
                    },
                    "categories": [category],
                }

            def expected_response(case, blocked=False, category="ORG"):
                prefix = "blocked-" if blocked else "queued-"
                text = f"{prefix}{case} "
                if category == "ORG":
                    text += f"[ORG_1] email-{case}"
                else:
                    text += f"org-{case} [EMAIL_1]"
                return {
                    "results": [{
                        "input_id": "text",
                        "anonymized_text": text,
                        "statistics": {"placeholder_count": 1},
                    }],
                    "dictionary_delta": {},
                }

            responses = {}
            failures = {}
            workers = []

            def send(case, body, auth=AUTH):
                headers = {"X-Test-Case": case}
                headers.update(auth)
                with application.test_client() as client:
                    response = client.post(PATH, json=body, headers=headers)
                    return response.status_code, response.get_json()

            def start_request(case, body, auth=AUTH):
                finished = threading.Event()

                def run():
                    try:
                        responses[case] = send(case, body, auth)
                    except BaseException as exc:
                        failures[case] = exc
                    finally:
                        finished.set()

                worker = threading.Thread(target=run)
                worker.start()
                workers.append(worker)
                return finished

            reader_patcher = patch.object(
                guardrail_api, "_read_body", tracked_reader
            )
            reader_patcher.start()
            try:
                for index, case in enumerate(blocked_cases):
                    category = "ORG" if index % 2 == 0 else "EMAIL"
                    start_request(case, payload(case, blocked=True, category=category))
                for case in blocked_cases:
                    self.assertTrue(entered[case].wait(2.0), case)
                self.assertEqual(admission.active_count, 4)

                queue_cases = ["q1", "q2", "q3", "q4"]
                queue_finished = {}
                for index, case in enumerate(queue_cases):
                    category = "ORG" if index % 2 == 0 else "EMAIL"
                    queue_finished[case] = start_request(
                        case, payload(case, category=category)
                    )
                    self.assertTrue(admission.wait_for_queue_size(index + 1, 1.0))
                self.assertEqual(admission.queued_count, 4)
                self.assertFalse(any(case in reader_cases for case in queue_cases))

                rejected = send("rejected", payload("rejected"))
                self.assertEqual(rejected, (429, {
                    "error": "Another analysis is in progress.",
                    "code": "busy",
                }))
                self.assertNotIn("rejected", reader_cases)

                unauthorized = send(
                    "unauthorized", payload("unauthorized"),
                    {"Authorization": "Bearer wrong-token"},
                )
                self.assertEqual(unauthorized, (401, {
                    "error": "Unauthorized.", "code": "unauthorized",
                }))
                self.assertNotIn("unauthorized", reader_cases)

                with patch.dict(os.environ, {"PII_API_TOKEN": ""}):
                    unconfigured = send("unconfigured", payload("unconfigured"))
                self.assertEqual(unconfigured, (503, {
                    "error": "Service unavailable.", "code": "unavailable",
                }))
                self.assertNotIn("unconfigured", reader_cases)

                readiness_state["ready"] = False
                not_ready = send("not-ready", payload("not-ready"))
                self.assertEqual(not_ready, (503, {
                    "error": "Service unavailable.", "code": "unavailable",
                }))
                self.assertNotIn("not-ready", reader_cases)
                readiness_state["ready"] = True

                release["a1"].set()
                for case in queue_cases:
                    self.assertTrue(reader_events.setdefault(case, threading.Event()).wait(2.0))
                    self.assertTrue(queue_finished[case].wait(2.0))
                    self.assertNotIn(case, failures)
                queued_read_order = [case for case in reader_cases if case.startswith("q")]
                self.assertEqual(queued_read_order, queue_cases)

                for case in blocked_cases:
                    release[case].set()
                for worker in workers:
                    worker.join(2.0)
                    self.assertFalse(worker.is_alive())
                self.assertEqual(failures, {})

                for index, case in enumerate(blocked_cases):
                    category = "ORG" if index % 2 == 0 else "EMAIL"
                    self.assertEqual(
                        responses[case],
                        (200, expected_response(case, blocked=True, category=category)),
                    )
                for index, case in enumerate(queue_cases):
                    category = "ORG" if index % 2 == 0 else "EMAIL"
                    self.assertEqual(
                        responses[case],
                        (200, expected_response(case, category=category)),
                    )
                self.assertEqual(admission.active_count, 0)
                self.assertEqual(admission.queued_count, 0)
                self.assertFalse(any(case in detected_cases for case in (
                    "queued-rejected", "queued-unauthorized", "queued-unconfigured",
                    "queued-not-ready",
                )))
            finally:
                for event in release.values():
                    event.set()
                for worker in workers:
                    worker.join(2.0)
                reader_patcher.stop()

    def test_queue_timeout_returns_busy_without_reading_body_and_recovers(self):
        environment = {
            "PII_API_TOKEN": TOKEN,
            "PII_MAX_CONCURRENT_ANALYSES": "1",
            "PII_MAX_QUEUED_ANALYSES": "1",
            "PII_QUEUE_TIMEOUT_SECONDS": "0.05",
        }
        with patch.dict(os.environ, environment):
            entered = threading.Event()
            release = threading.Event()
            reader_cases = []
            reader_events = {}
            application = Flask("admission-timeout-test")
            application.config["TESTING"] = True

            def detect(text, _check):
                if text == "blocked":
                    entered.set()
                    if not release.wait(3.0):
                        raise TimeoutError("blocked detector timed out")
                return []

            blueprint = guardrail_api.create_blueprint(
                TAGS, detect, clock=lambda: 0.0
            )
            application.register_blueprint(blueprint)
            admission = blueprint.request_admission
            original_reader = guardrail_api._read_body

            def tracked_reader(cap):
                case = request.headers.get("X-Test-Case")
                reader_cases.append(case)
                reader_events.setdefault(case, threading.Event()).set()
                return original_reader(cap)

            def send(case, text):
                with application.test_client() as client:
                    response = client.post(
                        PATH,
                        json={"text": text},
                        headers={**AUTH, "X-Test-Case": case},
                    )
                    return response.status_code, response.get_json()

            first_result = []
            first_done = threading.Event()

            def first_request():
                try:
                    first_result.append(send("active", "blocked"))
                finally:
                    first_done.set()

            first_worker = threading.Thread(target=first_request)
            with patch.object(guardrail_api, "_read_body", tracked_reader):
                first_worker.start()
                try:
                    self.assertTrue(entered.wait(2.0))
                    self.assertEqual(admission.active_count, 1)
                    queued_result = []
                    queued_done = threading.Event()

                    def queued_request():
                        queued_result.append(send("timed-out", "not-read"))
                        queued_done.set()

                    queued_worker = threading.Thread(target=queued_request)
                    queued_worker.start()
                    self.assertTrue(admission.wait_for_queue_size(1, 1.0))
                    self.assertTrue(queued_done.wait(1.0))
                    queued_worker.join(1.0)
                    self.assertFalse(queued_worker.is_alive())
                    self.assertEqual(queued_result, [(429, {
                        "error": "Another analysis is in progress.",
                        "code": "busy",
                    })])
                    self.assertNotIn("timed-out", reader_cases)
                    self.assertEqual(admission.queued_count, 0)

                    release.set()
                    self.assertTrue(first_done.wait(2.0))
                    first_worker.join(1.0)
                    self.assertEqual(first_result[0][0], 200)
                    recovered = send("recovered", "valid")
                    self.assertEqual(recovered[0], 200)
                    self.assertEqual(admission.active_count, 0)
                    self.assertEqual(admission.queued_count, 0)
                finally:
                    release.set()
                    first_worker.join(2.0)

    def test_process_request_releases_admission_after_validation_model_read_and_deadline_errors(self):
        admission = request_admission.RequestAdmission(
            request_admission.AdmissionConfig(1, 0, 1.0)
        )
        headers = {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}

        def process(raw_body, detect=_detect_none, clock=lambda: 0.0):
            return guardrail_api.process_request(
                headers,
                raw_body,
                token=TOKEN,
                tags=TAGS,
                detect=detect,
                clock=clock,
                admission=admission,
            )

        with self.assertRaises(TypeError):
            guardrail_api.process_request(
                headers,
                b'{"text":"x"}',
                token=TOKEN,
                tags=TAGS,
                detect=_detect_none,
            )

        cases = [
            (process(b"{"), 400, "invalid_request"),
            (process(lambda _cap: (_ for _ in ()).throw(OSError("private"))),
             400, "invalid_request"),
            (process(b'{"text":"x"}',
                     detect=lambda _text, _check: (_ for _ in ()).throw(
                         guardrail_api.ModelUnavailable())),
             503, "unavailable"),
            (process(b'{"text":"x"}', clock=iter((0.0, 61.0)).__next__),
             504, "deadline_exceeded"),
        ]
        for result, status, code in cases:
            with self.subTest(status=status, code=code):
                self.assertEqual((result[0], result[1]["code"]), (status, code))
                self.assertEqual(admission.active_count, 0)
                recovered = admission.acquire()
                self.assertIsNotNone(recovered)
                recovered.release()

        success = process(b'{"text":"valid"}')
        self.assertEqual(success[0], 200)
        self.assertEqual(admission.active_count, 0)

    def test_process_request_releases_admission_when_reader_or_detector_raises_base_exception(self):
        class RequestInterrupted(BaseException):
            pass

        admission = request_admission.RequestAdmission(
            request_admission.AdmissionConfig(1, 0, 1.0)
        )
        headers = {"Authorization": "Bearer " + TOKEN,
                   "Content-Type": "application/json"}

        def interrupt(*_args):
            raise RequestInterrupted()

        calls = (
            lambda: guardrail_api.process_request(
                headers, interrupt, token=TOKEN, tags=TAGS,
                detect=_detect_none, admission=admission),
            lambda: guardrail_api.process_request(
                headers, b'{"text":"private"}', token=TOKEN, tags=TAGS,
                detect=interrupt, admission=admission),
        )
        for call in calls:
            with self.assertRaises(RequestInterrupted):
                call()
            self.assertEqual(admission.active_count, 0)
            self.assertEqual(admission.queued_count, 0)
            recovered = admission.acquire()
            self.assertIsNotNone(recovered)
            recovered.release()


def _import_real_app():
    module = sys.modules.get("app")
    if module is not None and not isinstance(module, MagicMock):
        return module
    sys.modules.pop("app", None)
    saved = {name: sys.modules.get(name)
             for name in ("torch", "transformers", "fitz")}
    for name in saved:
        sys.modules[name] = MagicMock()
    fake_fitz = sys.modules["fitz"]
    fake_fitz.TOOLS.mupdf_display_errors.return_value = 0
    fake_fitz.TOOLS.mupdf_display_warnings.return_value = 0
    fake_fitz.TOOLS.mupdf_warnings.return_value = ""
    previous = os.environ.get("PII_MODEL_DIR")
    os.environ["PII_MODEL_DIR"] = str(ROOT / "tests")
    try:
        import app as app_module
    finally:
        if previous is None:
            os.environ.pop("PII_MODEL_DIR", None)
        else:
            os.environ["PII_MODEL_DIR"] = previous
        for name, dependency in saved.items():
            if dependency is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = dependency
        sys.modules.pop("pdf_export", None)
        sys.modules.pop("pdf_text", None)
    return app_module


def _real_module(name):
    module = sys.modules.get(name)
    if module is None or isinstance(module, MagicMock):
        sys.modules.pop(name, None)
        return __import__(name)
    return module


def _pdf_bytes(text):
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


@unittest.skipUnless(HAVE_FLASK and HAVE_FITZ and HAVE_NATIVE_MULTIPART,
                     "Flask, PyMuPDF, or native multipart support is unavailable")
class RealAppMixedAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            "PII_MAX_CONCURRENT_ANALYSES": "4",
            "PII_MAX_QUEUED_ANALYSES": "4",
            "PII_QUEUE_TIMEOUT_SECONDS": "5",
        }):
            cls.APP = _import_real_app()

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "PII_API_TOKEN": TOKEN,
            "PII_ANALYSIS_TIMEOUT_SECONDS": "60",
        }))
        self.stack.enter_context(patch.object(self.APP, "fitz", fitz))
        self.stack.enter_context(patch.object(
            self.APP, "pdf_text", _real_module("pdf_text")))
        self.stack.enter_context(patch.dict(self.APP.app.config, {"TESTING": True}))
        self.application = self.APP.app
        self.admission = self.application.blueprints[
            "guardrail_api"].request_admission
        self.assertEqual(
            self.admission.config,
            request_admission.AdmissionConfig(4, 4, 5.0),
        )
        self.assertEqual(self.admission.active_count, 0)
        self.assertEqual(self.admission.queued_count, 0)

    def test_four_active_mixed_json_and_pdf_requests_have_local_deltas(self):
        requests_to_send = (
            ("json-a", "json", "Ari Alpha"),
            ("pdf-b", "pdf", "Bela Bravo"),
            ("json-c", "json", "Ciro Charlie"),
            ("pdf-d", "pdf", "Dina Delta"),
        )
        names = tuple(name for _case, _kind, name in requests_to_send)
        model_calls = []
        model_lock = threading.Lock()

        def mock_model(chunks):
            results = []
            with model_lock:
                model_calls.extend(chunks)
            for chunk in chunks:
                entities = []
                for name in names:
                    start = chunk.find(name)
                    if start >= 0:
                        entities.append({
                            "entity_group": "FULLNAME",
                            "start": start,
                            "end": start + len(name),
                            "score": 0.99,
                            "word": name,
                        })
                results.append(entities)
            return results

        self.stack.enter_context(patch.object(self.APP, "nlp", mock_model))
        self.assertTrue(self.APP.MUPDF_PRIVACY_OK)
        original_reader = guardrail_api._read_body
        reader_lock = threading.Lock()
        reader_count = 0
        all_readers_waiting = threading.Event()
        release_readers = threading.Event()

        def synchronized_reader(cap):
            body = original_reader(cap)
            nonlocal reader_count
            with reader_lock:
                reader_count += 1
                if reader_count == len(requests_to_send):
                    all_readers_waiting.set()
            if not release_readers.wait(8.0):
                raise TimeoutError("concurrent request reader timed out")
            return body

        responses = {}
        failures = {}
        response_lock = threading.Lock()

        def send(case, kind, name):
            with self.application.test_client() as client:
                headers = dict(AUTH)
                if kind == "json":
                    response = client.post(
                        PATH, json={"text": f"JSON {name}"}, headers=headers)
                else:
                    response = client.post(
                        PATH,
                        data={"files": (io.BytesIO(_pdf_bytes(f"PDF {name}")),
                                         f"{case}.pdf")},
                        headers=headers,
                    )
                result = response.status_code, response.get_json()
            with response_lock:
                responses[case] = result

        workers = []
        with patch.object(guardrail_api, "_read_body", synchronized_reader):
            try:
                for case, kind, name in requests_to_send:
                    def run(case=case, kind=kind, name=name):
                        try:
                            send(case, kind, name)
                        except BaseException as exc:
                            with response_lock:
                                failures[case] = exc

                    worker = threading.Thread(target=run)
                    worker.start()
                    workers.append(worker)
                self.assertTrue(all_readers_waiting.wait(4.0))
                self.assertEqual(reader_count, 4)
                self.assertEqual(self.admission.active_count, 4)
            finally:
                release_readers.set()
                for worker in workers:
                    worker.join(8.0)
                    self.assertFalse(worker.is_alive())

        self.assertEqual(failures, {})
        self.assertEqual(set(responses), {case for case, _kind, _name in requests_to_send})
        for case, _kind, name in requests_to_send:
            with self.subTest(case=case):
                status, body = responses[case]
                self.assertEqual(status, 200)
                self.assertEqual(body["dictionary_delta"], {"[FULLNAME_1]": name})
                self.assertEqual(len(body["results"]), 1)
                anonymized = body["results"][0]["anonymized_text"]
                self.assertIn("[FULLNAME_1]", anonymized)
                self.assertNotIn(name, anonymized)
        self.assertEqual(len(model_calls), 4)
        self.assertEqual(self.admission.active_count, 0)
        self.assertEqual(self.admission.queued_count, 0)


if __name__ == "__main__":
    unittest.main()
