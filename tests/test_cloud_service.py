# -*- coding: utf-8 -*-
"""Cloud WSGI boundary (`src/app/cloud_service.py`).

The pure tests use a fake application and a fake legacy module, so they need
no torch, Flask, fitz or the real `app`. Optional Flask integration only runs
when Flask and the mocked-torch real application are importable.

All values are synthetic. Tests restore sys.modules, environment and shared
application globals they touch.
"""

import contextlib
import io
import itertools
import json
import logging
import os
import subprocess
import sys
import traceback
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "app"))

import cloud_service as cs  # noqa: E402

try:
    from flask import Flask                                  # noqa: F401
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    HAVE_FLASK = True
except ImportError:                                          # CI stdlib
    Flask = None
    Client = None
    Response = None
    HAVE_FLASK = False

TOKEN = "cloud-service-test-token"
AUTH = "Bearer " + TOKEN
_MISSING = object()


def _token_env(value):
    """Configure (or remove) PII_API_TOKEN for one test."""
    @contextlib.contextmanager
    def manager():
        with patch.dict(os.environ, {}, clear=False):
            if value is _MISSING:
                os.environ.pop(cs.TOKEN_ENV, None)
            else:
                os.environ[cs.TOKEN_ENV] = value
            yield
    return manager()


class _BombInput:
    """Reading it at any point would fail the test."""

    def __init__(self):
        self.read_called = False

    def read(self, *_args):
        self.read_called = True
        raise AssertionError("the request body must not be read")

    readline = read
    readinto = read


class _Capture:
    def __init__(self):
        self.status = None
        self.headers = None
        self.exc_info = None
        self.written = []

    def __call__(self, status, headers, exc_info=None):
        self.status = status
        self.headers = list(headers)
        self.exc_info = exc_info

        def write(data):
            self.written.append(bytes(data))

        return write

    def header(self, name):
        for key, value in self.headers or []:
            if key.lower() == name.lower():
                return value
        return None


def _environ(path="/", method="GET", authorization=None, stream=None):
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "test",
        "SERVER_PORT": "80",
        "HTTP_HOST": "test",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": stream if stream is not None else io.BytesIO(b""),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    if authorization is not None:
        environ["HTTP_AUTHORIZATION"] = authorization
    return environ


def _call(service, path="/", method="GET", authorization=None, stream=None,
          environ=None):
    capture = _Capture()
    env = environ if environ is not None else _environ(
        path, method, authorization, stream)
    body = b"".join(service(env, capture))
    return capture, body


def _assert_sanitized(testcase, error):
    testcase.assertIsInstance(error, RuntimeError)
    testcase.assertEqual(str(error), cs._INTERNAL_ERROR)
    testcase.assertIsNone(error.__cause__)
    testcase.assertTrue(error.__suppress_context__)
    rendered = "".join(traceback.format_exception(
        type(error), error, error.__traceback__))
    testcase.assertNotIn("SECRET", rendered)


class _FakeApplication:
    def __init__(self, status="200 OK", headers=None, body=(b"ok",),
                 error=None, after_start=False):
        self.status = status
        self.headers = headers or [("Content-Type", "text/plain")]
        self.body = body
        self.error = error
        self.after_start = after_start
        self.calls = []

    def __call__(self, environ, start_response):
        self.calls.append(environ)
        if self.error is not None and not self.after_start:
            raise self.error
        start_response(self.status, self.headers)
        if self.error is not None and self.after_start:
            raise self.error
        return self.body


_logger_ids = itertools.count()


class _FakeFlask:
    def __init__(self):
        self.logger = logging.getLogger(
            f"cloud_service_test_{next(_logger_ids)}")
        self.logger.handlers = []
        self.logger.filters = []
        self.logger.propagate = False


class _FakeModule:
    def __init__(self, nlp=True, device=0, app=None):
        self.nlp = object() if nlp else None
        self.device = device
        self.app = app if app is not None else _FakeFlask()


class _FakeTensor:
    def __init__(self, value):
        self.value = value

    def __add__(self, other):
        return _FakeTensor(self.value + other.value)

    def item(self):
        return self.value


class _FakeCuda:
    def __init__(self, available=True, sync_error=None):
        self.available = available
        self.sync_error = sync_error
        self.available_calls = 0
        self.sync_calls = 0

    def is_available(self):
        self.available_calls += 1
        return self.available

    def synchronize(self):
        self.sync_calls += 1
        if self.sync_error is not None:
            raise self.sync_error


class _FakeTorch:
    def __init__(self, available=True, value=1.0, op_error=None,
                 sync_error=None):
        self.cuda = _FakeCuda(available, sync_error)
        self.value = value
        self.op_error = op_error
        self.ones_calls = 0

    def ones(self, *_args, **_kwargs):
        self.ones_calls += 1
        if self.op_error is not None:
            raise self.op_error
        return _FakeTensor(self.value)


def _service(module=None, application=None):
    module = module or _FakeModule()
    application = application or _FakeApplication()
    return cs.CloudService(application, module), module, application


class ImportIsolation(unittest.TestCase):
    def test_import_does_not_load_torch_flask_or_app(self):
        code = (
            "import sys; sys.path.insert(0, %r); "
            "import cloud_service; "
            "assert 'torch' not in sys.modules, 'torch'; "
            "assert 'transformers' not in sys.modules, 'transformers'; "
            "assert 'flask' not in sys.modules, 'flask'; "
            "assert 'app' not in sys.modules, 'app'; "
            "print('ok')" % str(ROOT / "src" / "app")
        )
        result = subprocess.run([sys.executable, "-c", code],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


class Health(unittest.TestCase):
    def setUp(self):
        self.service, self.module, self.application = _service()

    def test_get_health_is_minimal_and_does_not_touch_app(self):
        for path in ("/health", "/healthz"):
            with self.subTest(path=path), _token_env(TOKEN):
                capture, body = _call(self.service, path)
            self.assertEqual(capture.status, "200 OK")
            payload = json.loads(body)
            self.assertEqual(set(payload), {"status", "model_loaded", "device"})
            self.assertEqual(payload, {"status": "ok", "model_loaded": True,
                                       "device": "cuda"})
            self.assertNotIn(TOKEN, body.decode())
            self.assertEqual(capture.header("Cache-Control"), "no-store")
            self.assertEqual(capture.header("Content-Length"), str(len(body)))
            self.assertEqual(self.application.calls, [])

    def test_health_ignores_bad_authorization(self):
        with _token_env(TOKEN):
            capture, body = _call(self.service, "/health",
                                  authorization="Bearer wrong")
        self.assertEqual(capture.status, "200 OK")
        self.assertEqual(json.loads(body)["status"], "ok")

    def test_head_health_matches_get_length_without_body(self):
        with _token_env(TOKEN):
            _, get_body = _call(self.service, "/health", "GET")
            capture, head_body = _call(self.service, "/health", "HEAD")
        self.assertEqual(capture.status, "200 OK")
        self.assertEqual(head_body, b"")
        self.assertEqual(capture.header("Content-Length"), str(len(get_body)))
        self.assertEqual(capture.header("Cache-Control"), "no-store")
        self.assertEqual(self.application.calls, [])

    def test_health_requires_configured_token(self):
        with _token_env(_MISSING):
            capture, body = _call(self.service, "/health")
        self.assertEqual(capture.status, "503 Service Unavailable")
        payload = json.loads(body)
        self.assertEqual(payload["status"], "loading")
        self.assertTrue(payload["model_loaded"])
        self.assertEqual(payload["device"], "cuda")
        with _token_env("   \t"):
            capture, _ = _call(self.service, "/health")
        self.assertEqual(capture.status, "503 Service Unavailable")

    def test_health_reports_model_and_device_failures(self):
        cases = [
            (_FakeModule(nlp=False), False, "cuda"),
            (_FakeModule(device=-1), True, "cpu"),
        ]
        for module, loaded, device in cases:
            service = cs.CloudService(_FakeApplication(), module)
            with self.subTest(module=module), _token_env(TOKEN):
                capture, body = _call(service, "/health")
            payload = json.loads(body)
            self.assertEqual(capture.status, "503 Service Unavailable")
            self.assertEqual(payload["status"], "loading")
            self.assertEqual(payload["model_loaded"], loaded)
            self.assertEqual(payload["device"], device)

    def test_health_survives_broken_readiness_attributes(self):
        class Broken:
            @property
            def nlp(self):
                raise RuntimeError("SECRET-health-marker")

            @property
            def device(self):
                raise RuntimeError("SECRET-device-marker")

        service = cs.CloudService(_FakeApplication(), Broken())
        with _token_env(TOKEN):
            capture, body = _call(service, "/health")
        self.assertEqual(capture.status, "503 Service Unavailable")
        self.assertNotIn(b"SECRET", body)
        self.assertEqual(json.loads(body), {"status": "loading",
                                            "model_loaded": False,
                                            "device": "cpu"})

    def test_non_get_head_methods_on_health_require_auth(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.subTest(method=method), _token_env(TOKEN):
                capture, body = _call(self.service, "/health", method)
            self.assertEqual(capture.status, "401 Unauthorized")
            self.assertEqual(json.loads(body)["code"], "unauthorized")
            self.assertEqual(self.application.calls, [])
        with _token_env(TOKEN):
            capture, _ = _call(self.service, "/health", "POST",
                               authorization=AUTH)
        self.assertEqual(capture.status, "200 OK")
        self.assertEqual(len(self.application.calls), 1)

    def test_slash_and_case_variants_are_not_health(self):
        for path in ("/health/", "//health", "/HEALTH", "/healthz/",
                     "/health%2F", "/foo/health"):
            with self.subTest(path=path), _token_env(TOKEN):
                capture, body = _call(self.service, path)
            self.assertEqual(capture.status, "401 Unauthorized")
            self.assertEqual(json.loads(body)["code"], "unauthorized")
            self.assertEqual(self.application.calls, [])


class Authentication(unittest.TestCase):
    def setUp(self):
        self.service, self.module, self.application = _service()

    def test_every_protected_path_and_method_is_401_before_app(self):
        cases = [
            ("/", "GET"), ("/nope/mario.rossi@example.com", "GET"),
            ("/analyze", "POST"), ("/pdf", "POST"),
            ("/pdf/preview", "POST"), ("/preview", "POST"),
            ("/settings", "GET"), ("/settings", "POST"),
            ("/tags", "GET"), ("/tags", "POST"),
            ("/config", "GET"), ("/config", "POST"),
            ("/port-check", "GET"), ("/doc/x/page/0.png", "GET"),
            ("/doc/x/file.pdf", "GET"), ("/static/app.js", "GET"),
            ("/api/v1/analyses", "POST"), ("/api/v1/analyses", "OPTIONS"),
            ("/api/v1/analyses/", "GET"), ("/health", "POST"),
            ("/health/", "GET"), ("/healthz/", "HEAD"),
        ]
        for path, method in cases:
            with self.subTest(path=path, method=method), _token_env(TOKEN):
                capture, body = _call(self.service, path, method)
            self.assertEqual(capture.status, "401 Unauthorized")
            if method != "HEAD":
                self.assertEqual(json.loads(body), {"error": "Unauthorized.",
                                                    "code": "unauthorized"})
            self.assertEqual(capture.header("Cache-Control"), "no-store")
            if method != "HEAD":
                self.assertEqual(capture.header("Content-Length"), str(len(body)))
            self.assertEqual(self.application.calls, [])

    def test_authorized_requests_reach_the_application(self):
        for path, method in (("/analyze", "POST"), ("/settings", "GET"),
                             ("/api/v1/analyses", "POST"),
                             ("/doc/x/file.pdf", "GET"),
                             ("/nope", "OPTIONS")):
            self.application.calls = []
            with self.subTest(path=path, method=method), _token_env(TOKEN):
                capture, body = _call(self.service, path, method,
                                      authorization=AUTH)
            self.assertEqual(capture.status, "200 OK")
            self.assertEqual(body, b"ok")
            self.assertEqual(len(self.application.calls), 1)

    def test_missing_or_blank_token_is_503_even_with_credentials(self):
        for value in (_MISSING, "", "   ", "\t\n"):
            with self.subTest(value=value), _token_env(value):
                capture, body = _call(self.service, "/analyze", "POST",
                                      authorization=AUTH)
            self.assertEqual(capture.status, "503 Service Unavailable")
            self.assertEqual(json.loads(body), {"error": "Service unavailable.",
                                                "code": "unavailable"})
            self.assertEqual(self.application.calls, [])
            self.assertEqual(capture.header("Cache-Control"), "no-store")

    def test_token_is_read_per_request_and_rotates(self):
        with _token_env("first-token"):
            first, _ = _call(self.service, "/settings", authorization="Bearer first-token")
        self.assertEqual(first.status, "200 OK")
        self.assertEqual(len(self.application.calls), 1)

        with _token_env("second-token"):
            stale, _ = _call(self.service, "/settings", authorization="Bearer first-token")
            fresh, _ = _call(self.service, "/settings", authorization="Bearer second-token")
        self.assertEqual(stale.status, "401 Unauthorized")
        self.assertEqual(fresh.status, "200 OK")
        self.assertEqual(len(self.application.calls), 2)

        with _token_env(_MISSING):
            unset, _ = _call(self.service, "/settings", authorization="Bearer second-token")
        self.assertEqual(unset.status, "503 Service Unavailable")

    def test_unicode_token_and_scheme_case(self):
        token = "tökén-日本語-🔐"
        with _token_env(token):
            for scheme in ("Bearer", "bearer", "BEARER", "BeArEr"):
                capture, _ = _call(self.service, "/settings",
                                   authorization=f"{scheme} {token}")
                self.assertEqual(capture.status, "200 OK", scheme)
            capture, _ = _call(self.service, "/settings",
                               authorization="Bearer " + token + "x")
        self.assertEqual(capture.status, "401 Unauthorized")

    def test_token_comparison_is_case_sensitive(self):
        with _token_env("CaseSensitive"):
            capture, _ = _call(self.service, "/settings",
                               authorization="Bearer casesensitive")
        self.assertEqual(capture.status, "401 Unauthorized")

    def test_malformed_authorization_headers_are_401(self):
        headers = [
            "Bearer", "Bearer ", "Bearer  " + TOKEN, "Basic " + TOKEN,
            " " + TOKEN, "Bearer\t" + TOKEN, "Bearer " + TOKEN + " ",
            "Bearer " + TOKEN + " extra", "", "bearer",
        ]
        with _token_env(TOKEN):
            for header in headers:
                with self.subTest(header=header):
                    capture, _ = _call(self.service, "/settings",
                                       authorization=header)
                self.assertEqual(capture.status, "401 Unauthorized")
        self.assertEqual(self.application.calls, [])

    def test_non_string_authorization_header_is_rejected(self):
        env = _environ("/settings")
        env["HTTP_AUTHORIZATION"] = 1234
        with _token_env(TOKEN):
            capture, _ = _call(self.service, environ=env)
        self.assertEqual(capture.status, "401 Unauthorized")

    def test_authorization_helper_survives_bad_token_string(self):
        class Bad:
            def __str__(self):
                raise AttributeError("no string")

        self.assertFalse(cs._authorized({"HTTP_AUTHORIZATION": "Bearer x"},
                                        Bad()))

    def test_authentication_never_reads_the_body(self):
        bomb = _BombInput()
        with _token_env(TOKEN):
            _call(self.service, "/analyze", "POST", stream=bomb)
        self.assertFalse(bomb.read_called)
        self.assertEqual(self.application.calls, [])

        missing = _BombInput()
        with _token_env(_MISSING):
            _call(self.service, "/analyze", "POST", authorization=AUTH,
                  stream=missing)
        self.assertFalse(missing.read_called)

        health = _BombInput()
        with _token_env(TOKEN):
            _call(self.service, "/health", stream=health)
        self.assertFalse(health.read_called)

        authorized = _BombInput()
        with _token_env(TOKEN):
            _call(self.service, "/analyze", "POST", authorization=AUTH,
                  stream=authorized)
        self.assertFalse(authorized.read_called)
        self.assertEqual(len(self.application.calls), 1)

    def test_head_error_has_length_without_body(self):
        with _token_env(TOKEN):
            _, body = _call(self.service, "/settings", "GET")
            capture, head_body = _call(self.service, "/settings", "HEAD")
        self.assertEqual(capture.status, "401 Unauthorized")
        self.assertEqual(head_body, b"")
        self.assertEqual(capture.header("Content-Length"), str(len(body)))

    def test_unknown_path_is_401_not_404_when_unauthorized(self):
        with _token_env(TOKEN):
            capture, body = _call(self.service, "/unknown/path")
        self.assertEqual(capture.status, "401 Unauthorized")
        self.assertEqual(json.loads(body)["code"], "unauthorized")
        self.assertEqual(self.application.calls, [])


class Delegation(unittest.TestCase):
    def setUp(self):
        self.application = _FakeApplication(
            status="201 Created",
            headers=[("Content-Type", "text/plain"),
                     ("Cache-Control", "private, max-age=600"),
                     ("X-Test", "kept"), ("Content-Length", "4")],
            body=[b"body"])
        self.service = cs.CloudService(self.application, _FakeModule())

    def test_authorized_response_is_not_rewritten(self):
        with _token_env(TOKEN):
            capture, body = _call(self.service, "/settings",
                                  authorization=AUTH)
        self.assertEqual(capture.status, "201 Created")
        self.assertEqual(body, b"body")
        self.assertEqual(capture.header("X-Test"), "kept")
        self.assertEqual(capture.header("Content-Length"), "4")
        self.assertEqual(capture.header("Cache-Control"), "no-store")
        self.assertEqual(len([value for name, value in capture.headers
                              if name.lower() == "cache-control"]), 1)

    def test_generator_body_is_not_materialized_by_the_wrapper(self):
        seen = []

        def body():
            seen.append("start")
            yield b"a"
            seen.append("end")
            yield b"b"

        application = _FakeApplication(body=body())
        service = cs.CloudService(application, _FakeModule())
        with _token_env(TOKEN):
            capture = _Capture()
            stream = service(_environ("/settings", authorization=AUTH), capture)
            self.assertEqual(seen, [])
            self.assertEqual(b"".join(stream), b"ab")
        self.assertEqual(seen, ["start", "end"])
        self.assertEqual(capture.header("Cache-Control"), "no-store")

    def test_authorized_errors_keep_their_body(self):
        payload = b'{"error":"Invalid request.","code":"invalid_request"}'
        application = _FakeApplication(
            status="400 Bad Request",
            headers=[("Content-Type", "application/json"),
                     ("Cache-Control", "no-cache")],
            body=[payload])
        service = cs.CloudService(application, _FakeModule())
        with _token_env(TOKEN):
            capture, body = _call(service, "/api/v1/analyses", "POST",
                                  authorization=AUTH)
        self.assertEqual(capture.status, "400 Bad Request")
        self.assertEqual(body, payload)
        self.assertEqual(capture.header("Cache-Control"), "no-store")

    def test_authorized_v1_contract_is_byte_identical(self):
        payload = (
            b'{"results":[{"input_id":"text","anonymized_text":"[FULLNAME_1]",'
            b'"statistics":{"placeholder_count":1}}],"dictionary_delta":{}}'
        )
        application = _FakeApplication(
            headers=[("Content-Type", "application/json"),
                     ("Cache-Control", "no-store")],
            body=[payload])
        service = cs.CloudService(application, _FakeModule())
        with _token_env(TOKEN):
            capture, body = _call(service, "/api/v1/analyses", "POST",
                                  authorization=AUTH)
        self.assertEqual(capture.status, "200 OK")
        self.assertEqual(body, payload)
        self.assertEqual(capture.header("Cache-Control"), "no-store")

    def test_binary_pdf_and_png_keep_bytes_but_lose_legacy_cache(self):
        cases = [
            ("/doc/x/file.pdf", b"%PDF-1.7\x00binary", "application/pdf",
             "attachment; filename=atto.pdf"),
            ("/doc/x/page/0.png", b"\x89PNG\r\n\x1a\nbinary", "image/png",
             None),
        ]
        for path, payload, content_type, disposition in cases:
            headers = [("Content-Type", content_type),
                       ("Content-Length", str(len(payload))),
                       ("Cache-Control", "private, max-age=600")]
            if disposition:
                headers.append(("Content-Disposition", disposition))
            application = _FakeApplication(headers=headers, body=[payload])
            service = cs.CloudService(application, _FakeModule())
            with self.subTest(path=path), _token_env(TOKEN):
                capture, body = _call(service, path, authorization=AUTH)
            self.assertEqual(body, payload)
            self.assertEqual(capture.status, "200 OK")
            self.assertEqual(capture.header("Cache-Control"), "no-store")
            self.assertEqual(capture.header("Content-Length"), str(len(payload)))
            if disposition:
                self.assertEqual(capture.header("Content-Disposition"),
                                 disposition)

    def test_head_binary_response_keeps_accurate_length(self):
        application = _FakeApplication(
            headers=[("Content-Type", "image/png"),
                     ("Content-Length", "7"),
                     ("Cache-Control", "private, max-age=600")],
            body=[])
        service = cs.CloudService(application, _FakeModule())
        with _token_env(TOKEN):
            capture, body = _call(service, "/doc/x/page/0.png", "HEAD",
                                  authorization=AUTH)
        self.assertEqual(body, b"")
        self.assertEqual(capture.header("Content-Length"), "7")
        self.assertEqual(capture.header("Cache-Control"), "no-store")

    def test_head_discards_an_authorized_app_body(self):
        application = _FakeApplication(
            headers=[("Content-Type", "image/png"),
                     ("Content-Length", "6")],
            body=[b"hidden"])
        service = cs.CloudService(application, _FakeModule())
        with _token_env(TOKEN):
            capture, body = _call(service, "/doc/x/page/0.png", "HEAD",
                                  authorization=AUTH)
        self.assertEqual(body, b"")
        self.assertEqual(capture.header("Content-Length"), "6")
        self.assertEqual(capture.header("Cache-Control"), "no-store")

    def test_unexpected_application_error_is_generic(self):
        application = _FakeApplication(error=RuntimeError("SECRET-document"))
        service = cs.CloudService(application, _FakeModule())
        with _token_env(TOKEN):
            capture, body = _call(service, "/analyze", "POST",
                                  authorization=AUTH)
        self.assertEqual(capture.status, "500 Internal Server Error")
        self.assertEqual(json.loads(body), {"error": "Internal error.",
                                            "code": "internal_error"})
        self.assertNotIn(b"SECRET", body)
        self.assertEqual(capture.header("Cache-Control"), "no-store")
        self.assertEqual(capture.header("Content-Length"), str(len(body)))

    def test_error_after_start_response_is_sanitized(self):
        application = _FakeApplication(
            error=RuntimeError("SECRET-late"), after_start=True)
        service = cs.CloudService(application, _FakeModule())
        with _token_env(TOKEN), self.assertRaises(RuntimeError) as caught:
            _call(service, "/analyze", "POST", authorization=AUTH)
        _assert_sanitized(self, caught.exception)

    def test_generator_error_before_start_returns_generic_500(self):
        class Application:
            def __call__(self, environ, start_response):
                def body():
                    raise RuntimeError("SECRET-early")
                    yield b"unreachable"

                return body()

        service = cs.CloudService(Application(), _FakeModule())
        with _token_env(TOKEN):
            capture, payload = _call(service, "/analyze", "POST",
                                     authorization=AUTH)
        self.assertEqual(capture.status, "500 Internal Server Error")
        self.assertEqual(json.loads(payload), {"error": "Internal error.",
                                                "code": "internal_error"})
        self.assertNotIn(b"SECRET", payload)
        self.assertEqual(capture.header("Cache-Control"), "no-store")

    def test_generator_error_after_first_chunk_is_sanitized(self):
        class Application:
            def __call__(self, environ, start_response):
                def body():
                    start_response("200 OK", [("Content-Type", "text/plain")])
                    yield b"first"
                    raise RuntimeError("SECRET-mid")

                return body()

        service = cs.CloudService(Application(), _FakeModule())
        with _token_env(TOKEN):
            capture = _Capture()
            stream = service(_environ("/analyze", "POST", AUTH), capture)
            self.assertEqual(next(stream), b"first")
            self.assertEqual(capture.status, "200 OK")
            self.assertEqual(capture.header("Cache-Control"), "no-store")
            with self.assertRaises(RuntimeError) as caught:
                next(stream)
        _assert_sanitized(self, caught.exception)

    def test_body_close_error_is_sanitized(self):
        class Body:
            def __iter__(self):
                return iter([b"ok"])

            def close(self):
                raise RuntimeError("SECRET-close")

        application = _FakeApplication(body=Body())
        service = cs.CloudService(application, _FakeModule())
        with _token_env(TOKEN):
            capture, body = _call(service, "/settings", authorization=AUTH)
            self.assertEqual(body, b"ok")
            stream = service(_environ("/settings", authorization=AUTH), capture)
            self.assertEqual(list(stream), [b"ok"])
            with self.assertRaises(RuntimeError) as caught:
                stream.close()
        _assert_sanitized(self, caught.exception)

    def test_body_close_is_forwarded(self):
        closed = []

        class Body:
            def __iter__(self):
                return iter([b"ok"])

            def close(self):
                closed.append(True)

        application = _FakeApplication(body=Body())
        service = cs.CloudService(application, _FakeModule())
        with _token_env(TOKEN):
            capture = _Capture()
            stream = service(_environ("/settings", authorization=AUTH), capture)
            self.assertEqual(b"".join(stream), b"ok")
            stream.close()
        self.assertEqual(closed, [True])

    def test_head_lazy_generator_keeps_status_without_body(self):
        closed = []

        class Application:
            def __call__(self, environ, start_response):
                def body():
                    try:
                        start_response("204 No Content", [("X-Lazy", "1")])
                        yield b"SECRET-hidden"
                    finally:
                        closed.append(True)

                return body()

        service = cs.CloudService(Application(), _FakeModule())
        with _token_env(TOKEN):
            capture, body = _call(service, "/doc/x/page/0.png", "HEAD",
                                  authorization=AUTH)
        self.assertEqual(capture.status, "204 No Content")
        self.assertEqual(body, b"")
        self.assertEqual(capture.header("X-Lazy"), "1")
        self.assertEqual(capture.header("Cache-Control"), "no-store")
        self.assertEqual(closed, [True])

    def test_head_close_failure_is_sanitized(self):
        class Body:
            def __iter__(self):
                return iter([b"hidden"])

            def close(self):
                raise RuntimeError("SECRET-close")

        application = _FakeApplication(
            headers=[("Content-Type", "image/png"),
                     ("Content-Length", "6")],
            body=Body())
        service = cs.CloudService(application, _FakeModule())
        with _token_env(TOKEN), self.assertRaises(RuntimeError) as caught:
            _call(service, "/doc/x/page/0.png", "HEAD", authorization=AUTH)
        _assert_sanitized(self, caught.exception)

    def test_head_iter_error_before_start_is_generic_and_closed(self):
        class Body:
            def __init__(self):
                self.close_calls = 0

            def __iter__(self):
                raise RuntimeError("SECRET-iter")

            def close(self):
                self.close_calls += 1

        class Application:
            def __call__(self, environ, start_response):
                return body

        body = Body()
        service = cs.CloudService(Application(), _FakeModule())
        with _token_env(TOKEN):
            capture, payload = _call(service, "/doc/x/page/0.png", "HEAD",
                                     authorization=AUTH)
        self.assertEqual(capture.status, "500 Internal Server Error")
        expected = cs._json_bytes({"error": "Internal error.",
                                   "code": "internal_error"})
        self.assertEqual(payload, b"")
        self.assertEqual(capture.header("Content-Length"), str(len(expected)))
        self.assertNotIn(b"SECRET", payload + b"".join(capture.written))
        self.assertEqual(capture.header("Cache-Control"), "no-store")
        self.assertEqual(body.close_calls, 1)

    def test_head_next_error_before_start_is_generic_and_closed(self):
        class Body:
            def __init__(self):
                self.close_calls = 0

            def __iter__(self):
                return self

            def __next__(self):
                raise RuntimeError("SECRET-next")

            def close(self):
                self.close_calls += 1

        class Application:
            def __call__(self, environ, start_response):
                return body

        body = Body()
        service = cs.CloudService(Application(), _FakeModule())
        with _token_env(TOKEN):
            capture, payload = _call(service, "/doc/x/page/0.png", "HEAD",
                                     authorization=AUTH)
        self.assertEqual(capture.status, "500 Internal Server Error")
        expected = cs._json_bytes({"error": "Internal error.",
                                   "code": "internal_error"})
        self.assertEqual(payload, b"")
        self.assertEqual(capture.header("Content-Length"), str(len(expected)))
        self.assertNotIn(b"SECRET", payload + b"".join(capture.written))
        self.assertEqual(capture.header("Cache-Control"), "no-store")
        self.assertEqual(body.close_calls, 1)

    def test_head_next_error_after_start_is_sanitized_and_closed(self):
        class Body:
            def __init__(self):
                self.close_calls = 0
                self.start = None

            def __iter__(self):
                return self

            def __next__(self):
                self.start("200 OK", [("Content-Type", "text/plain")])
                raise RuntimeError("SECRET-next-after")

            def close(self):
                self.close_calls += 1

        class Application:
            def __call__(self, environ, start_response):
                body.start = start_response
                return body

        body = Body()
        service = cs.CloudService(Application(), _FakeModule())
        capture = _Capture()
        with _token_env(TOKEN):
            env = _environ("/doc/x/page/0.png", "HEAD", AUTH)
            with self.assertRaises(RuntimeError) as caught:
                list(service(env, capture))
        _assert_sanitized(self, caught.exception)
        self.assertEqual(capture.status, "200 OK")
        self.assertEqual(capture.header("Cache-Control"), "no-store")
        self.assertEqual(body.close_calls, 1)

    def test_head_close_error_does_not_mask_iter_error(self):
        class Body:
            def __init__(self):
                self.close_calls = 0

            def __iter__(self):
                raise RuntimeError("SECRET-iter-primary")

            def close(self):
                self.close_calls += 1
                raise RuntimeError("SECRET-close-secondary")

        class Application:
            def __call__(self, environ, start_response):
                return body

        body = Body()
        service = cs.CloudService(Application(), _FakeModule())
        with _token_env(TOKEN):
            capture, payload = _call(service, "/doc/x/page/0.png", "HEAD",
                                     authorization=AUTH)
        self.assertEqual(capture.status, "500 Internal Server Error")
        expected = cs._json_bytes({"error": "Internal error.",
                                   "code": "internal_error"})
        self.assertEqual(payload, b"")
        self.assertEqual(capture.header("Content-Length"), str(len(expected)))
        self.assertNotIn(b"SECRET", payload + b"".join(capture.written))
        self.assertEqual(body.close_calls, 1)

    def test_head_close_error_does_not_mask_error_after_start(self):
        class Body:
            def __init__(self):
                self.close_calls = 0
                self.start = None

            def __iter__(self):
                return self

            def __next__(self):
                self.start("200 OK", [("Content-Type", "text/plain")])
                raise RuntimeError("SECRET-next-primary")

            def close(self):
                self.close_calls += 1
                raise RuntimeError("SECRET-close-secondary")

        class Application:
            def __call__(self, environ, start_response):
                body.start = start_response
                return body

        body = Body()
        service = cs.CloudService(Application(), _FakeModule())
        capture = _Capture()
        with _token_env(TOKEN):
            env = _environ("/doc/x/page/0.png", "HEAD", AUTH)
            with self.assertRaises(RuntimeError) as caught:
                list(service(env, capture))
        _assert_sanitized(self, caught.exception)
        self.assertEqual(capture.status, "200 OK")
        self.assertEqual(capture.header("Cache-Control"), "no-store")
        self.assertEqual(body.close_calls, 1)

    def test_head_close_error_before_start_is_generic(self):
        class Body:
            def __init__(self):
                self.close_calls = 0

            def __iter__(self):
                return iter(())

            def close(self):
                self.close_calls += 1
                raise RuntimeError("SECRET-close")

        class Application:
            def __call__(self, environ, start_response):
                return body

        body = Body()
        service = cs.CloudService(Application(), _FakeModule())
        with _token_env(TOKEN):
            capture, payload = _call(service, "/doc/x/page/0.png", "HEAD",
                                     authorization=AUTH)
        self.assertEqual(capture.status, "500 Internal Server Error")
        expected = cs._json_bytes({"error": "Internal error.",
                                   "code": "internal_error"})
        self.assertEqual(payload, b"")
        self.assertEqual(capture.header("Content-Length"), str(len(expected)))
        self.assertNotIn(b"SECRET", payload + b"".join(capture.written))
        self.assertEqual(body.close_calls, 1)

    def test_head_close_error_after_start_is_sanitized(self):
        class Body:
            def __init__(self):
                self.close_calls = 0
                self.start = None

            def __iter__(self):
                return self

            def __next__(self):
                self.start("204 No Content", [("X-Lazy", "1")])
                return b"hidden"

            def close(self):
                self.close_calls += 1
                raise RuntimeError("SECRET-close")

        class Application:
            def __call__(self, environ, start_response):
                body.start = start_response
                return body

        body = Body()
        service = cs.CloudService(Application(), _FakeModule())
        capture = _Capture()
        with _token_env(TOKEN):
            env = _environ("/doc/x/page/0.png", "HEAD", AUTH)
            with self.assertRaises(RuntimeError) as caught:
                list(service(env, capture))
        _assert_sanitized(self, caught.exception)
        self.assertEqual(capture.status, "204 No Content")
        self.assertEqual(capture.header("Cache-Control"), "no-store")
        self.assertEqual(body.close_calls, 1)

    def test_head_base_exception_passes_through_after_cleanup(self):
        for error in (SystemExit("SECRET-exit"),
                      KeyboardInterrupt("SECRET-interrupt")):
            with self.subTest(error=type(error).__name__):
                class Body:
                    def __init__(self):
                        self.close_calls = 0

                    def __iter__(self):
                        raise error

                    def close(self):
                        self.close_calls += 1

                class Application:
                    def __call__(self, environ, start_response):
                        return body

                body = Body()
                service = cs.CloudService(Application(), _FakeModule())
                with _token_env(TOKEN), \
                        self.assertRaises(type(error)) as caught:
                    _call(service, "/doc/x/page/0.png", "HEAD",
                          authorization=AUTH)
                self.assertIs(caught.exception, error)
                self.assertIn("SECRET", str(caught.exception))
                self.assertEqual(body.close_calls, 1)

    def test_head_close_base_exception_passes_through(self):
        class Body:
            def __init__(self):
                self.close_calls = 0
                self.start = None

            def __iter__(self):
                return self

            def __next__(self):
                self.start("204 No Content", [])
                return b"hidden"

            def close(self):
                self.close_calls += 1
                raise SystemExit("SECRET-close-exit")

        class Application:
            def __call__(self, environ, start_response):
                body.start = start_response
                return body

        body = Body()
        service = cs.CloudService(Application(), _FakeModule())
        with _token_env(TOKEN), self.assertRaises(SystemExit) as caught:
            _call(service, "/doc/x/page/0.png", "HEAD", authorization=AUTH)
        self.assertEqual(str(caught.exception), "SECRET-close-exit")
        self.assertEqual(body.close_calls, 1)

    def test_legacy_start_response_write_is_preserved(self):
        class Application:
            def __call__(self, environ, start_response):
                write = start_response("200 OK", [("Content-Type", "text/plain")])
                write(b"legacy")
                return []

        service = cs.CloudService(Application(), _FakeModule())
        with _token_env(TOKEN):
            capture, body = _call(service, "/settings", authorization=AUTH)
            head_capture, head_body = _call(service, "/settings", "HEAD",
                                            authorization=AUTH)
        self.assertEqual(body, b"")
        self.assertEqual(capture.written, [b"legacy"])
        self.assertEqual(capture.status, "200 OK")
        self.assertEqual(capture.header("Cache-Control"), "no-store")
        self.assertEqual(head_body, b"")
        self.assertEqual(head_capture.written, [])

    def test_base_exceptions_are_not_sanitized(self):
        for error in (SystemExit("SECRET-exit"),
                      KeyboardInterrupt("SECRET-interrupt")):
            with self.subTest(error=type(error).__name__):
                class Application:
                    def __call__(self, environ, start_response):
                        def body():
                            start_response("200 OK", [])
                            raise error
                            yield b"unreachable"

                        return body()

                service = cs.CloudService(Application(), _FakeModule())
                with _token_env(TOKEN):
                    capture = _Capture()
                    stream = service(_environ("/settings", authorization=AUTH),
                                     capture)
                    with self.assertRaises(type(error)) as caught:
                        next(stream)
                self.assertIn("SECRET", str(caught.exception))

    def test_requests_emit_no_secret_logs_or_output(self):
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        handler = Capture()
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        out, err = io.StringIO(), io.StringIO()
        try:
            with _token_env(TOKEN), contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(err):
                _call(self.service, "/path-with-SECRET?token=SECRET",
                      authorization="Bearer wrong-SECRET")
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)
        self.assertFalse(any("SECRET" in record.getMessage()
                             for record in records))
        self.assertNotIn("SECRET", out.getvalue())
        self.assertNotIn("SECRET", err.getvalue())


class Startup(unittest.TestCase):
    def test_missing_token_is_rejected_before_cuda_or_app(self):
        for value in (_MISSING, "", "   "):
            with self.subTest(value=value), _token_env(value), \
                    patch.object(cs, "_require_cuda") as cuda, \
                    patch.object(cs, "_import_application") as load:
                with self.assertRaises(RuntimeError) as caught:
                    cs.create_app()
            self.assertEqual(str(caught.exception), cs._MISSING_TOKEN)
            self.assertIsNone(caught.exception.__cause__)
            cuda.assert_not_called()
            load.assert_not_called()

    def test_missing_token_prints_nothing(self):
        out, err = io.StringIO(), io.StringIO()
        with _token_env("  "), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            with self.assertRaises(RuntimeError):
                cs.create_app()
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), "")

    def test_cpu_only_runtime_is_rejected_before_app_import(self):
        fake = _FakeTorch(available=False)
        with _token_env(TOKEN), patch.dict(sys.modules, {"torch": fake}), \
                patch.object(cs, "_import_application") as load:
            with self.assertRaises(RuntimeError) as caught:
                cs.create_app()
        self.assertEqual(str(caught.exception), cs._CUDA_ERROR)
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        load.assert_not_called()
        self.assertEqual(fake.cuda.available_calls, 1)
        self.assertEqual(fake.ones_calls, 0)

    def test_cuda_tensor_failure_is_generic_and_from_none(self):
        fake = _FakeTorch(op_error=RuntimeError("SECRET-driver-mismatch"))
        with _token_env(TOKEN), patch.dict(sys.modules, {"torch": fake}), \
                patch.object(cs, "_import_application") as load:
            with self.assertRaises(RuntimeError) as caught:
                cs.create_app()
        self.assertEqual(str(caught.exception), cs._CUDA_ERROR)
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        load.assert_not_called()

    def test_cuda_synchronize_failure_is_rejected(self):
        fake = _FakeTorch(sync_error=RuntimeError("SECRET-sync"))
        with _token_env(TOKEN), patch.dict(sys.modules, {"torch": fake}), \
                patch.object(cs, "_import_application") as load:
            with self.assertRaises(RuntimeError) as caught:
                cs.create_app()
        self.assertEqual(str(caught.exception), cs._CUDA_ERROR)
        self.assertEqual(fake.cuda.sync_calls, 1)
        load.assert_not_called()

    def test_wrong_cuda_arithmetic_result_is_rejected(self):
        fake = _FakeTorch(value=3.0)
        with _token_env(TOKEN), patch.dict(sys.modules, {"torch": fake}):
            with self.assertRaises(RuntimeError) as caught:
                cs.create_app()
        self.assertEqual(str(caught.exception), cs._CUDA_ERROR)

    def test_model_not_loaded_or_not_on_gpu_is_rejected(self):
        for module in (_FakeModule(nlp=False), _FakeModule(device=-1),
                       _FakeModule(device="0")):
            with self.subTest(module=module), _token_env(TOKEN), \
                    patch.dict(sys.modules, {"torch": _FakeTorch(),
                                             "app": module}):
                with self.assertRaises(RuntimeError) as caught:
                    cs.create_app()
            self.assertEqual(str(caught.exception), cs._MODEL_ERROR)
            self.assertIsNone(caught.exception.__cause__)
            self.assertEqual(module.app.logger.filters, [])

    def test_broken_model_attributes_are_rejected(self):
        class Broken:
            app = _FakeFlask()

            @property
            def nlp(self):
                raise RuntimeError("SECRET-nlp")

            @property
            def device(self):
                raise RuntimeError("SECRET-device")

        with _token_env(TOKEN), patch.dict(
                sys.modules, {"torch": _FakeTorch(), "app": Broken()}):
            with self.assertRaises(RuntimeError) as caught:
                cs.create_app()
        self.assertEqual(str(caught.exception), cs._MODEL_ERROR)
        self.assertNotIn("SECRET", str(caught.exception))

    def test_successful_factory_returns_wrapper_and_sanitizes_logger_once(self):
        module = _FakeModule()
        with _token_env(TOKEN), patch.dict(
                sys.modules, {"torch": _FakeTorch(), "app": module}):
            first = cs.create_app()
            second = cs.create_app()
        self.assertIsInstance(first, cs.CloudService)
        self.assertIs(first.application, module.app)
        self.assertIs(first.module, module)
        self.assertIs(second.application, module.app)
        self.assertEqual(len(module.app.logger.filters), 1)
        self.assertIsInstance(module.app.logger.filters[0],
                              cs._SanitizeErrors)

    def test_cloud_service_module_has_no_routes_or_legacy_imports(self):
        source = (ROOT / "src" / "app" / "cloud_service.py").read_text(
            encoding="utf-8")
        self.assertNotIn("@app.route", source)
        self.assertNotIn("register_blueprint", source)
        self.assertNotIn("before_request", source)

    def test_sanitizing_filter_keeps_info_and_scrubs_errors(self):
        sanitizer = cs._SanitizeErrors()
        info = logging.LogRecord("app", logging.INFO, __file__, 1,
                                 "startup ok", (), None)
        self.assertTrue(sanitizer.filter(info))
        self.assertEqual(info.msg, "startup ok")

        error = logging.LogRecord(
            "app", logging.ERROR, __file__, 1,
            "Exception on /secret?token=SECRET", ("SECRET",),
            (RuntimeError, RuntimeError("SECRET"), None))
        error.exc_text = "SECRET-traceback"
        error.stack_info = "SECRET-stack"
        self.assertTrue(sanitizer.filter(error))
        self.assertEqual(error.msg, cs._LOG_ERROR)
        self.assertEqual(error.args, ())
        self.assertIsNone(error.exc_info)
        self.assertIsNone(error.exc_text)
        self.assertIsNone(error.stack_info)
        self.assertNotIn("SECRET", error.getMessage())

    def test_sanitize_logging_is_a_noop_without_a_logger(self):
        module = SimpleNamespace(app=SimpleNamespace(logger=None))
        cs._sanitize_logging(module)

    def test_startup_failure_output_has_no_secret_or_traceback(self):
        fake = _FakeTorch(op_error=RuntimeError("SECRET-driver"))
        out, err = io.StringIO(), io.StringIO()
        with _token_env("UPPER-SECRET-TOKEN"), \
                patch.dict(sys.modules, {"torch": fake}), \
                contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            with self.assertRaises(RuntimeError):
                cs.create_app()
        output = out.getvalue() + err.getvalue()
        self.assertNotIn("SECRET", output)
        self.assertNotIn("Traceback", output)


@unittest.skipUnless(HAVE_FLASK, "Flask assente")
class FlaskIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_module = _load_real_app()
        if cls.app_module is None:
            raise unittest.SkipTest("app.py non importabile (torch/fitz assenti)")

    def setUp(self):
        self.patch = patch.object(self.app_module, "nlp", _nlp_fullname())
        self.patch.start()
        self.addCleanup(self.patch.stop)
        device = patch.object(self.app_module, "device", 0)
        device.start()
        self.addCleanup(device.stop)
        prefs = patch.object(self.app_module, "_get_prefs", lambda: ([], True))
        prefs.start()
        self.addCleanup(prefs.stop)
        self.addCleanup(_clear_docs, self.app_module)

    def test_route_table_and_legacy_app_are_untouched(self):
        before = _routes(self.app_module.app)
        service = cs.CloudService(self.app_module.app, self.app_module)
        self.assertEqual(_routes(self.app_module.app), before)
        with _token_env(TOKEN):
            wrapped = Client(service, Response)
            self.assertEqual(wrapped.get("/settings").status_code, 401)
            legacy = self.app_module.app.test_client()
            self.assertEqual(legacy.get("/health").status_code, 200)
        self.assertEqual(_routes(self.app_module.app), before)

    def test_factory_sanitizes_real_flask_log_but_not_500_response(self):
        logger = self.app_module.app.logger
        original_filters = list(logger.filters)
        had_flag = "_cloud_service_sanitized" in logger.__dict__
        original_flag = logger.__dict__.get("_cloud_service_sanitized")

        def restore_logger():
            logger.filters[:] = original_filters
            if had_flag:
                setattr(logger, "_cloud_service_sanitized", original_flag)
            else:
                logger.__dict__.pop("_cloud_service_sanitized", None)

        self.addCleanup(restore_logger)

        marker = "SECRET-token /health?token=SECRET-query"

        def boom(*_args, **_kwargs):
            raise RuntimeError(marker)

        with _token_env(TOKEN), patch.dict(
                sys.modules, {"torch": _FakeTorch()}), \
                patch.dict(self.app_module.app.view_functions,
                           {"health": boom}):
            service = cs.create_app()
            self.assertIsInstance(service, cs.CloudService)
            self.assertIs(service.application, self.app_module.app)
            self.assertEqual(len(logger.filters), len(original_filters) + 1)
            self.assertIsInstance(logger.filters[-1], cs._SanitizeErrors)
            with self.assertLogs(logger, level="ERROR") as captured:
                response = self.app_module.app.test_client().get(
                    "/health?token=SECRET-query")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {
            "error": "Internal Server Error.",
            "code": "internal_server_error"})
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertEqual(record.msg, cs._LOG_ERROR)
        self.assertEqual(record.args, ())
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.exc_text)
        self.assertIsNone(record.stack_info)
        rendered = "\n".join(captured.output).lower()
        self.assertIn(cs._LOG_ERROR.lower(), rendered)
        for forbidden in ("secret", "token", "query"):
            self.assertNotIn(forbidden, rendered)

    def test_health_and_slash_variants(self):
        service = cs.CloudService(self.app_module.app, self.app_module)
        with _token_env(TOKEN):
            client = Client(service, Response)
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set(response.get_json()),
                             {"status", "model_loaded", "device"})
            self.assertEqual(client.get("/health/").status_code, 401)
            self.assertEqual(client.options("/health").status_code, 401)
            self.assertEqual(client.head("/health").get_data(), b"")

            get_length = int(response.headers["Content-Length"])
            head = client.head("/health")
            self.assertEqual(int(head.headers["Content-Length"]), get_length)

    def test_guardrail_response_is_unchanged(self):
        payload = {"text": "Mario Rossi scrive a mario.rossi@example.com"}
        service = cs.CloudService(self.app_module.app, self.app_module)
        with _token_env(TOKEN):
            wrapped = Client(service, Response).post(
                "/api/v1/analyses", json=payload,
                headers={"Authorization": AUTH})
            direct = self.app_module.app.test_client().post(
                "/api/v1/analyses", json=payload,
                headers={"Authorization": AUTH})
        self.assertEqual(wrapped.status_code, direct.status_code)
        self.assertEqual(wrapped.get_data(), direct.get_data())
        self.assertEqual(wrapped.headers.get("Cache-Control"), "no-store")
        self.assertEqual(wrapped.get_json()["results"][0]["anonymized_text"],
                         "[FULLNAME_1] scrive a [EMAIL_1]")

    def test_authorized_legacy_response_gets_no_store(self):
        service = cs.CloudService(self.app_module.app, self.app_module)
        with _token_env(TOKEN):
            response = Client(service, Response).post(
                "/analyze", json={"text": "Mario Rossi"},
                headers={"Authorization": AUTH})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertIn("Mario Rossi", response.get_json()["mapping"].values())


def _nlp_fullname(value="Mario Rossi"):
    def nlp(chunks):
        out = []
        for chunk in chunks:
            index = chunk.find(value)
            if index < 0:
                out.append([])
            else:
                out.append([{"entity_group": "FULLNAME", "start": index,
                             "end": index + len(value), "score": 0.9,
                             "word": value}])
        return out
    return nlp


def _routes(flask_app):
    return sorted((str(rule.rule), tuple(sorted(rule.methods or ())))
                  for rule in flask_app.url_map.iter_rules())


def _clear_docs(app_module):
    lock = getattr(app_module, "_DOCS_LOCK", None)
    docs = getattr(app_module, "_DOCS", None)
    if lock is None or docs is None:
        return
    with lock:
        docs.clear()


def _load_real_app():
    if "app" in sys.modules:
        return sys.modules["app"]
    fake_transformers = MagicMock()
    fake_transformers.pipeline.return_value = MagicMock(return_value=[])
    saved = {name: sys.modules.get(name) for name in ("torch", "transformers")}
    previous = os.environ.get("PII_MODEL_DIR")
    for name in saved:
        sys.modules[name] = MagicMock()
    sys.modules["transformers"] = fake_transformers
    os.environ["PII_MODEL_DIR"] = str(ROOT / "tests")
    try:
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            import app as app_module
        return app_module
    except Exception:
        return None
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        if previous is None:
            os.environ.pop("PII_MODEL_DIR", None)
        else:
            os.environ["PII_MODEL_DIR"] = previous


if __name__ == "__main__":
    unittest.main()
