# -*- coding: utf-8 -*-
"""Upstream authentication mode across both HTTP layers.

Only the exact server environment value ``PII_AUTH_MODE=upstream`` removes the
local Bearer prerequisite and check. Every other value keeps the default
fail-closed behavior. These tests exercise the predicates in
``cloud_service`` and ``guardrail_api``, the WSGI middleware, the Flask shell,
and the real two-layer application with a mocked model. No test loads Torch,
model weights, or PyMuPDF documents, and every environment change is restored.
"""

import contextlib
import inspect
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / "src" / "app", ROOT / "tests"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import cloud_service as cs  # noqa: E402
import guardrail_api as ga  # noqa: E402
import test_cloud_service as cloud_helpers  # noqa: E402

try:
    from flask import Flask
    HAVE_FLASK = True
except ImportError:
    Flask = None
    HAVE_FLASK = False

TOKEN = "upstream-mode-test-token"
AUTH = "Bearer " + TOKEN
TAGS = ("EMAIL", "FULLNAME")
JSON_CT = {"Content-Type": "application/json"}
PATH = "/api/v1/analyses"
_MISSING = object()

_INVALID_MODES = (
    _MISSING,
    "",
    " ",
    "\t",
    "upstream ",
    " upstream",
    "upstream\n",
    "Upstream",
    "UPSTREAM",
    "upstream-mode",
    "upstream,local",
    "1",
    "true",
    "local",
    "disabled",
)


@contextlib.contextmanager
def _auth_env(token=_MISSING, mode=_MISSING):
    with patch.dict(os.environ, {}, clear=False):
        for name, value in ((cs.TOKEN_ENV, token), (cs.AUTH_MODE_ENV, mode)):
            if value is _MISSING:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield


@contextlib.contextmanager
def _analysis_env():
    with patch.dict(os.environ, {
        "PII_ANALYSIS_TIMEOUT_SECONDS": "",
        "PII_MAX_SEED_ENTRIES": "",
        "PII_MAX_ORIGINAL_CHARS": "",
        "PII_MAX_AGGREGATE_CHARS": "",
        "PII_MAX_JSON_BODY_BYTES": "",
    }, clear=False):
        yield


class _BombReader:
    def __init__(self):
        self.calls = []

    def __call__(self, cap):
        self.calls.append(cap)
        raise AssertionError("the request body must not be read")


class _Reader:
    def __init__(self, payload=b'{"text":"x"}'):
        self.payload = payload
        self.calls = []

    def __call__(self, cap):
        self.calls.append(cap)
        return self.payload


class _NoLeaseAdmission:
    def __init__(self):
        self.calls = 0

    def acquire(self):
        self.calls += 1
        return None


def _no_entities(_text, _check):
    return []


def _secret_detector(_text, _check):
    raise RuntimeError("SECRET-document-value")


class CrossLayerAuthMode(unittest.TestCase):
    def test_constants_are_shared_and_exact(self):
        self.assertEqual(cs.AUTH_MODE_ENV, "PII_AUTH_MODE")
        self.assertEqual(ga.AUTH_MODE_ENV, "PII_AUTH_MODE")
        self.assertEqual(cs.UPSTREAM_AUTH_MODE, "upstream")
        self.assertEqual(ga.UPSTREAM_AUTH_MODE, "upstream")

    def test_exact_mode_is_true_in_both_layers_regardless_of_token(self):
        for token in (_MISSING, TOKEN):
            with self.subTest(token=token), _auth_env(token=token,
                                                      mode="upstream"):
                self.assertTrue(cs._upstream_auth_mode())
                self.assertTrue(ga._upstream_auth_mode())

    def test_every_other_mode_is_false_in_both_layers(self):
        for mode in _INVALID_MODES:
            with self.subTest(mode=repr(mode)), _auth_env(
                    token=TOKEN, mode=mode):
                self.assertIs(cs._upstream_auth_mode(), False)
                self.assertIs(ga._upstream_auth_mode(), False)


class DefaultCloudMode(unittest.TestCase):
    def setUp(self):
        self.service, self.module, self.application = cloud_helpers._service()

    def test_missing_token_is_503_for_absent_and_invalid_modes(self):
        for mode in _INVALID_MODES:
            with self.subTest(mode=repr(mode)), _auth_env(
                    token=_MISSING, mode=mode):
                capture, body = cloud_helpers._call(self.service, "/settings")
            self.assertEqual(capture.status, "503 Service Unavailable")
            self.assertEqual(json.loads(body), {
                "error": "Service unavailable.", "code": "unavailable"})
            self.assertEqual(capture.header("Cache-Control"), "no-store")
            self.assertEqual(self.application.calls, [])

    def test_invalid_modes_keep_the_bearer_requirement(self):
        for mode in _INVALID_MODES:
            with self.subTest(mode=repr(mode)), _auth_env(
                    token=TOKEN, mode=mode):
                missing, _ = cloud_helpers._call(self.service, "/settings")
                wrong, _ = cloud_helpers._call(
                    self.service, "/settings", authorization="Bearer wrong")
            self.assertEqual(missing.status, "401 Unauthorized")
            self.assertEqual(wrong.status, "401 Unauthorized")
            self.assertEqual(self.application.calls, [])

    def test_valid_bearer_still_reaches_the_application(self):
        with _auth_env(token=TOKEN, mode="local"):
            capture, body = cloud_helpers._call(
                self.service, "/settings", authorization=AUTH)
        self.assertEqual(capture.status, "200 OK")
        self.assertEqual(body, b"ok")
        self.assertEqual(len(self.application.calls), 1)

    def test_health_token_prerequisite_survives_invalid_modes(self):
        for mode in ("local", "upstream ", "Upstream", "1"):
            with self.subTest(mode=mode), _auth_env(token=_MISSING, mode=mode):
                capture, body = cloud_helpers._call(self.service, "/health")
            self.assertEqual(capture.status, "503 Service Unavailable")
            self.assertEqual(json.loads(body)["status"], "loading")

    def test_headers_query_and_body_cannot_select_upstream(self):
        bomb = cloud_helpers._BombInput()
        environ = cloud_helpers._environ("/settings")
        environ["QUERY_STRING"] = (
            "PII_AUTH_MODE=upstream&auth_mode=upstream&require_token=false")
        environ["HTTP_X_PII_AUTH_MODE"] = "upstream"
        environ["HTTP_X_AUTH_MODE"] = "upstream"
        environ["HTTP_X_FORWARDED_AUTH_MODE"] = "upstream"
        environ["HTTP_PII_AUTH_MODE"] = "upstream"
        environ["wsgi.input"] = bomb
        with _auth_env(token=TOKEN, mode="local"):
            capture, body = cloud_helpers._call(
                self.service, environ=environ)
        self.assertEqual(capture.status, "401 Unauthorized")
        self.assertEqual(json.loads(body)["code"], "unauthorized")
        self.assertFalse(bomb.read_called)
        self.assertEqual(self.application.calls, [])

    def test_missing_token_rejects_before_body_and_client_overrides(self):
        bomb = cloud_helpers._BombInput()
        environ = cloud_helpers._environ("/settings")
        environ["QUERY_STRING"] = "PII_AUTH_MODE=upstream"
        environ["HTTP_X_PII_AUTH_MODE"] = "upstream"
        environ["wsgi.input"] = bomb
        with _auth_env(token=_MISSING, mode="local"):
            capture, _ = cloud_helpers._call(self.service, environ=environ)
        self.assertEqual(capture.status, "503 Service Unavailable")
        self.assertFalse(bomb.read_called)
        self.assertEqual(self.application.calls, [])


class UpstreamCloudService(unittest.TestCase):
    def setUp(self):
        self.service, self.module, self.application = cloud_helpers._service()

    def test_health_get_is_ready_without_a_token_and_no_store(self):
        with _auth_env(token=_MISSING, mode="upstream"):
            capture, body = cloud_helpers._call(self.service, "/health")
        self.assertEqual(capture.status, "200 OK")
        self.assertEqual(json.loads(body), {
            "status": "ok", "model_loaded": True, "device": "cuda"})
        self.assertEqual(capture.header("Cache-Control"), "no-store")
        self.assertEqual(capture.header("Content-Length"), str(len(body)))
        self.assertEqual(self.application.calls, [])

    def test_health_head_matches_get_without_a_body(self):
        with _auth_env(token=_MISSING, mode="upstream"):
            _, get_body = cloud_helpers._call(self.service, "/health")
            capture, head_body = cloud_helpers._call(
                self.service, "/health", "HEAD")
        self.assertEqual(capture.status, "200 OK")
        self.assertEqual(head_body, b"")
        self.assertEqual(capture.header("Content-Length"), str(len(get_body)))
        self.assertEqual(capture.header("Cache-Control"), "no-store")
        self.assertEqual(self.application.calls, [])

    def test_health_still_requires_model_and_cuda(self):
        cases = (
            (cloud_helpers._FakeModule(nlp=False), "503 Service Unavailable"),
            (cloud_helpers._FakeModule(device=-1), "503 Service Unavailable"),
        )
        for module, expected in cases:
            service = cs.CloudService(cloud_helpers._FakeApplication(), module)
            with self.subTest(module=module), _auth_env(
                    token=_MISSING, mode="upstream"):
                capture, body = cloud_helpers._call(service, "/health")
            self.assertEqual(capture.status, expected)
            self.assertEqual(json.loads(body)["status"], "loading")

    def test_health_head_loading_has_no_body_and_no_store(self):
        service = cs.CloudService(
            cloud_helpers._FakeApplication(),
            cloud_helpers._FakeModule(nlp=False))
        with _auth_env(token=_MISSING, mode="upstream"):
            capture, body = cloud_helpers._call(service, "/health", "HEAD")
        self.assertEqual(capture.status, "503 Service Unavailable")
        self.assertEqual(body, b"")
        self.assertEqual(capture.header("Cache-Control"), "no-store")

    def test_absent_and_invalid_authorization_are_ignored(self):
        cases = (
            None,
            "",
            "Bearer",
            "Bearer wrong",
            "Basic " + TOKEN,
            "Bearer " + TOKEN + " extra",
            1234,
        )
        for authorization in cases:
            environ = cloud_helpers._environ("/settings")
            if authorization is not None:
                environ["HTTP_AUTHORIZATION"] = authorization
            with self.subTest(authorization=authorization), _auth_env(
                    token=_MISSING, mode="upstream"):
                capture, body = cloud_helpers._call(
                    self.service, environ=environ)
            self.assertEqual(capture.status, "200 OK")
            self.assertEqual(body, b"ok")
            self.assertEqual(capture.header("Cache-Control"), "no-store")
            self.assertEqual(len(self.application.calls), 1)
            self.application.calls.clear()

    def test_analyses_and_legacy_paths_reach_the_application_without_a_token(self):
        for path, method in (("/api/v1/analyses", "POST"),
                             ("/analyze", "POST"),
                             ("/settings", "GET")):
            with self.subTest(path=path), _auth_env(
                    token=_MISSING, mode="upstream"):
                capture, body = cloud_helpers._call(self.service, path, method)
            self.assertEqual(capture.status, "200 OK")
            self.assertEqual(body, b"ok")
            self.assertEqual(len(self.application.calls), 1)
            self.application.calls.clear()

    def test_upstream_mode_does_not_read_the_body_in_the_middleware(self):
        bomb = cloud_helpers._BombInput()
        with _auth_env(token=_MISSING, mode="upstream"):
            capture, _ = cloud_helpers._call(
                self.service, "/api/v1/analyses", "POST", stream=bomb)
        self.assertEqual(capture.status, "200 OK")
        self.assertFalse(bomb.read_called)
        self.assertEqual(len(self.application.calls), 1)

    def test_upstream_application_errors_remain_sanitized(self):
        application = cloud_helpers._FakeApplication(
            error=RuntimeError("SECRET-upstream"))
        service = cs.CloudService(application, cloud_helpers._FakeModule())
        with _auth_env(token=_MISSING, mode="upstream"):
            capture, body = cloud_helpers._call(
                service, "/api/v1/analyses", "POST")
        self.assertEqual(capture.status, "500 Internal Server Error")
        self.assertEqual(json.loads(body), {
            "error": "Internal error.", "code": "internal_error"})
        self.assertNotIn(b"SECRET", body)
        self.assertEqual(capture.header("Cache-Control"), "no-store")


class UpstreamFactory(unittest.TestCase):
    def test_exact_upstream_mode_allows_a_missing_token(self):
        module = cloud_helpers._FakeModule()
        with _auth_env(token=_MISSING, mode="upstream"), patch.dict(
                sys.modules, {"torch": cloud_helpers._FakeTorch(),
                              "app": module}):
            service = cs.create_app()
        self.assertIsInstance(service, cs.CloudService)
        self.assertIs(service.application, module.app)
        self.assertIs(service.module, module)
        self.assertEqual(len(module.app.logger.filters), 1)

    def test_upstream_mode_still_rejects_missing_cuda(self):
        fake = cloud_helpers._FakeTorch(available=False)
        with _auth_env(token=_MISSING, mode="upstream"), patch.dict(
                sys.modules, {"torch": fake}), patch.object(
                cs, "_import_application") as load:
            with self.assertRaises(RuntimeError) as caught:
                cs.create_app()
        self.assertEqual(str(caught.exception), cs._CUDA_ERROR)
        load.assert_not_called()

    def test_upstream_mode_still_rejects_a_model_not_ready_on_gpu(self):
        for module in (cloud_helpers._FakeModule(nlp=False),
                       cloud_helpers._FakeModule(device=-1)):
            with self.subTest(module=module), _auth_env(
                    token=_MISSING, mode="upstream"), patch.dict(
                    sys.modules, {"torch": cloud_helpers._FakeTorch(),
                                  "app": module}):
                with self.assertRaises(RuntimeError) as caught:
                    cs.create_app()
            self.assertEqual(str(caught.exception), cs._MODEL_ERROR)

    def test_invalid_modes_without_a_token_fail_before_cuda_or_app(self):
        for mode in _INVALID_MODES:
            with self.subTest(mode=repr(mode)), _auth_env(
                    token=_MISSING, mode=mode), patch.object(
                    cs, "_require_cuda") as cuda, patch.object(
                    cs, "_import_application") as load:
                with self.assertRaises(RuntimeError) as caught:
                    cs.create_app()
                self.assertEqual(str(caught.exception), cs._MISSING_TOKEN)
                cuda.assert_not_called()
                load.assert_not_called()


class GuardrailTokenDefault(unittest.TestCase):
    def test_require_token_is_keyword_only_and_defaults_true(self):
        parameter = inspect.signature(
            ga.process_request).parameters["require_token"]
        self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(parameter.default, True)

    def test_missing_or_blank_token_is_503_before_body(self):
        for token in (None, "", "   ", "\t"):
            reader = _BombReader()
            lock = threading.Lock()
            with self.subTest(token=token), _analysis_env():
                status, body = ga.process_request(
                    dict(JSON_CT), reader, token=token, tags=TAGS,
                    detect=_no_entities, lock=lock)
            self.assertEqual(status, 503)
            self.assertEqual(body["code"], "unavailable")
            self.assertEqual(reader.calls, [])
            self.assertFalse(lock.locked())

    def test_missing_or_wrong_authorization_is_401_before_body(self):
        cases = (
            {},
            {"Authorization": ""},
            {"Authorization": "Basic " + TOKEN},
            {"Authorization": "Bearer"},
            {"Authorization": "Bearer wrong"},
            {"Authorization": "Bearer " + TOKEN + "x"},
        )
        for headers in cases:
            reader = _BombReader()
            lock = threading.Lock()
            with self.subTest(headers=headers), _analysis_env():
                status, body = ga.process_request(
                    dict(headers), reader, token=TOKEN, tags=TAGS,
                    detect=_no_entities, lock=lock)
            self.assertEqual(status, 401)
            self.assertEqual(body["code"], "unauthorized")
            self.assertEqual(reader.calls, [])
            self.assertFalse(lock.locked())

    def test_authorization_precedes_readiness_and_body(self):
        reader = _BombReader()
        readiness_calls = []

        def readiness():
            readiness_calls.append(True)
            return True

        with _analysis_env():
            status, body = ga.process_request(
                {}, reader, token=TOKEN, tags=TAGS, detect=_no_entities,
                lock=threading.Lock(), readiness=readiness)
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "unauthorized")
        self.assertEqual(readiness_calls, [])
        self.assertEqual(reader.calls, [])

    def test_valid_authorization_still_enforces_readiness_before_body(self):
        reader = _BombReader()
        with _analysis_env():
            status, body = ga.process_request(
                {"Authorization": AUTH}, reader, token=TOKEN, tags=TAGS,
                detect=_no_entities, lock=threading.Lock(),
                readiness=lambda: False)
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "unavailable")
        self.assertEqual(reader.calls, [])


class GuardrailUpstreamBypass(unittest.TestCase):
    def bypass(self, *, raw_body=b'{"text":"x"}', headers=None, token=None,
               detect=_no_entities, **kwargs):
        all_headers = dict(JSON_CT)
        if headers:
            all_headers.update(headers)
        if "lock" not in kwargs and "admission" not in kwargs:
            kwargs["lock"] = threading.Lock()
        return ga.process_request(
            all_headers, raw_body, token=token, require_token=False,
            tags=TAGS, detect=detect, **kwargs)

    def test_absent_and_invalid_authorization_are_ignored(self):
        cases = (
            None,
            {},
            {"Authorization": ""},
            {"Authorization": "Basic " + TOKEN},
            {"Authorization": "Bearer"},
            {"Authorization": "Bearer wrong"},
            {"Authorization": "Bearer " + TOKEN + " extra"},
            {"X-PII-Auth-Mode": "upstream"},
            {"X-Forwarded-User": "provider-authenticated"},
        )
        for headers in cases:
            with self.subTest(headers=headers), _analysis_env():
                status, body = self.bypass(headers=headers)
            self.assertEqual(status, 200)
            self.assertEqual(
                body["results"][0]["anonymized_text"], "x")
            self.assertEqual(body["dictionary_delta"], {})

    def test_readiness_precedes_body_in_bypass(self):
        reader = _BombReader()
        lock = threading.Lock()
        with _analysis_env():
            status, body = self.bypass(
                raw_body=reader, readiness=lambda: False, lock=lock)
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "unavailable")
        self.assertEqual(reader.calls, [])
        self.assertFalse(lock.locked())

    def test_model_check_precedes_admission_and_body_in_bypass(self):
        reader = _BombReader()
        lock = threading.Lock()
        with _analysis_env():
            status, body = self.bypass(
                raw_body=reader, detect=None, lock=lock)
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "unavailable")
        self.assertEqual(reader.calls, [])
        self.assertFalse(lock.locked())

    def test_admission_precedes_body_in_bypass(self):
        reader = _BombReader()
        admission = _NoLeaseAdmission()
        with _analysis_env():
            status, body = self.bypass(
                raw_body=reader, admission=admission)
        self.assertEqual(status, 429)
        self.assertEqual(body["code"], "busy")
        self.assertEqual(admission.calls, 1)
        self.assertEqual(reader.calls, [])

    def test_legacy_lock_precedes_body_in_bypass(self):
        reader = _BombReader()
        lock = threading.Lock()
        lock.acquire()
        try:
            with _analysis_env():
                status, body = self.bypass(raw_body=reader, lock=lock)
        finally:
            lock.release()
        self.assertEqual(status, 429)
        self.assertEqual(body["code"], "busy")
        self.assertEqual(reader.calls, [])

    def test_readiness_failures_are_sanitized_before_body(self):
        def unavailable():
            raise ga.ModelUnavailable()

        def broken():
            raise RuntimeError("SECRET-readiness-value")

        for callback, expected_status, expected_code in (
                (unavailable, 503, "unavailable"),
                (broken, 500, "internal_error")):
            reader = _BombReader()
            with self.subTest(code=expected_code), _analysis_env():
                status, body = self.bypass(
                    raw_body=reader, readiness=callback)
            self.assertEqual(status, expected_status)
            self.assertEqual(body["code"], expected_code)
            self.assertNotIn("SECRET", json.dumps(body))
            self.assertEqual(reader.calls, [])

    def test_detector_failure_is_sanitized_and_releases_the_lock(self):
        lock = threading.Lock()
        with _analysis_env():
            status, body = self.bypass(detect=_secret_detector, lock=lock)
        self.assertEqual(status, 500)
        self.assertEqual(body["code"], "internal_error")
        self.assertNotIn("SECRET", json.dumps(body))
        self.assertFalse(lock.locked())

    def test_reader_failure_is_sanitized(self):
        class FailingReader:
            def __call__(self, _cap):
                raise RuntimeError("SECRET-reader-value")

        with _analysis_env():
            status, body = self.bypass(raw_body=FailingReader())
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")
        self.assertNotIn("SECRET", json.dumps(body))

    def test_body_is_read_after_admission_and_limits_still_apply(self):
        reader = _Reader()
        lock = threading.Lock()
        with _analysis_env():
            status, body = self.bypass(raw_body=reader, lock=lock)
        self.assertEqual(status, 200)
        self.assertEqual(len(reader.calls), 1)
        self.assertFalse(lock.locked())
        with _analysis_env():
            status, body = self.bypass(
                raw_body=b" " * (ga.MAX_BODY_BYTES + 1))
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "payload_too_large")


@unittest.skipUnless(HAVE_FLASK, "Flask assente")
class GuardrailFlaskShell(unittest.TestCase):
    def setUp(self):
        self.application = Flask("upstream-auth-shell")
        self.application.config["TESTING"] = True
        self.application.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
        self.lock = threading.Lock()
        blueprint = ga.create_blueprint(TAGS, _no_entities, lock=self.lock)
        self.application.register_blueprint(blueprint)
        self.client = self.application.test_client()

    def test_exact_mode_skips_http_auth_for_missing_and_invalid_headers(self):
        cases = (
            None,
            {"Authorization": ""},
            {"Authorization": "Basic " + TOKEN},
            {"Authorization": "Bearer"},
            {"Authorization": "Bearer wrong"},
            {"X-PII-Auth-Mode": "upstream"},
        )
        with _auth_env(token=_MISSING, mode="upstream"), _analysis_env():
            for headers in cases:
                with self.subTest(headers=headers):
                    response = self.client.post(
                        PATH, json={"text": "x"}, headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.get_json()["results"][0]["anonymized_text"], "x")
                self.assertEqual(
                    response.headers.get("Cache-Control"), "no-store")

    def test_invalid_modes_and_client_overrides_keep_default_auth(self):
        modes = _INVALID_MODES
        overrides = (
            ({"X-PII-Auth-Mode": "upstream"}, ""),
            ({"X-Auth-Mode": "upstream"}, ""),
            ({"X-Forwarded-Auth-Mode": "upstream"}, ""),
            ({}, "?PII_AUTH_MODE=upstream&auth_mode=upstream"),
        )
        for mode in modes:
            with self.subTest(mode=repr(mode)), _auth_env(
                    token=TOKEN, mode=mode), _analysis_env():
                for headers, query in overrides:
                    with self.subTest(mode=repr(mode), headers=headers,
                                      query=query):
                        response = self.client.post(
                            PATH + query, json={"text": "x"},
                            headers=headers or None)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(
                        response.get_json()["code"], "unauthorized")
                    self.assertEqual(
                        response.headers.get("Cache-Control"), "no-store")
                response = self.client.post(
                    PATH,
                    json={"text": "x", "PII_AUTH_MODE": "upstream",
                          "auth_mode": "upstream", "require_token": False})
                self.assertEqual(response.status_code, 401)

    def test_missing_token_is_503_despite_client_overrides(self):
        with _auth_env(token=_MISSING, mode="local"), _analysis_env():
            response = self.client.post(
                PATH + "?PII_AUTH_MODE=upstream", json={"text": "x"},
                headers={"X-PII-Auth-Mode": "upstream"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "unavailable")
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_valid_token_still_reaches_the_endpoint_in_default_mode(self):
        with _auth_env(token=TOKEN, mode="local"), _analysis_env():
            response = self.client.post(
                PATH, json={"text": "x"},
                headers={"Authorization": AUTH})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["results"][0]["anonymized_text"], "x")


@unittest.skipUnless(HAVE_FLASK, "Flask assente")
class RealTwoLayerIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_module = cloud_helpers._load_real_app()
        if cls.app_module is None:
            raise unittest.SkipTest(
                "app.py non importabile (torch/fitz assenti)")

    def setUp(self):
        self.patch = patch.object(
            self.app_module, "nlp", cloud_helpers._nlp_fullname())
        self.patch.start()
        self.addCleanup(self.patch.stop)
        device = patch.object(self.app_module, "device", 0)
        device.start()
        self.addCleanup(device.stop)
        prefs = patch.object(self.app_module, "_get_prefs", lambda: ([], True))
        prefs.start()
        self.addCleanup(prefs.stop)
        self.addCleanup(cloud_helpers._clear_docs, self.app_module)

    def client(self):
        service = cs.CloudService(self.app_module.app, self.app_module)
        return cloud_helpers.Client(service, cloud_helpers.Response)

    def test_upstream_mode_reaches_legacy_and_analyses_without_a_token(self):
        client = self.client()
        with _auth_env(token=_MISSING, mode="upstream"), _analysis_env():
            legacy = client.get("/settings")
            self.assertEqual(legacy.status_code, 200)
            self.assertEqual(
                legacy.headers.get("Cache-Control"), "no-store")

            for headers in (None, {"Authorization": "Bearer wrong"}):
                with self.subTest(headers=headers):
                    response = client.post(
                        PATH, json={"text": "Mario Rossi"}, headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.get_json()["results"][0]["anonymized_text"],
                    "[FULLNAME_1]")
                self.assertEqual(
                    response.headers.get("Cache-Control"), "no-store")

    def test_default_and_invalid_modes_keep_two_layer_fail_closed(self):
        with _auth_env(token=_MISSING, mode="local"), _analysis_env():
            client = self.client()
            self.assertEqual(client.get("/settings").status_code, 503)
            self.assertEqual(
                client.post(PATH, json={"text": "Mario Rossi"}).status_code,
                503)
        with _auth_env(token=TOKEN, mode="upstream "), _analysis_env():
            client = self.client()
            self.assertEqual(client.get("/settings").status_code, 401)
            self.assertEqual(
                client.post(PATH, json={"text": "Mario Rossi"}).status_code,
                401)
        with _auth_env(token=TOKEN, mode="local"), _analysis_env():
            client = self.client()
            self.assertEqual(client.get("/settings").status_code, 401)
            self.assertEqual(
                client.post(PATH, json={"text": "Mario Rossi"}).status_code,
                401)
            response = client.post(
                PATH, json={"text": "Mario Rossi"},
                headers={"Authorization": AUTH})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.get_json()["results"][0]["anonymized_text"],
                "[FULLNAME_1]")


if __name__ == "__main__":
    unittest.main()
