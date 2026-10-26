# -*- coding: utf-8 -*-
"""Cloud service boundary for the existing Flask API (additive, WSGI-only).

Gunicorn entry point: ``cloud_service:create_app()``. Local Bearer
authentication is the default: the factory requires a non-blank
``PII_API_TOKEN`` and the middleware checks it before Flask sees a request.
Only the exact server environment value ``PII_AUTH_MODE=upstream`` removes that
local token prerequisite and check, for deployments whose upstream provider
authenticates callers. Absent, blank, or any other value keeps the local token
semantics. The mode is read only from the server environment, never from
request headers, query, or body.

In every mode the factory requires a working CUDA device, imports ``app`` only
after those checks, verifies the model is loaded on GPU, sanitizes the Flask
error logger, and returns a tiny WSGI middleware around ``app.app``.

The middleware authenticates every protected request before Flask sees it,
except exact ``GET``/``HEAD`` probes on ``/health`` and ``/healthz``, and except
when the exact upstream mode is selected. It never reads the request body,
never redirects before authentication, serves a minimal health payload itself,
and forces ``Cache-Control: no-store`` on every response while leaving
authorized response bodies untouched.

No torch, Flask, transformers or ``app`` import happens at module import time.
"""

import importlib
import json
import logging
import os
import secrets
from collections.abc import Callable, Iterable
from http import HTTPStatus

TOKEN_ENV = "PII_API_TOKEN"
AUTH_MODE_ENV = "PII_AUTH_MODE"
UPSTREAM_AUTH_MODE = "upstream"
HEALTH_PATHS = frozenset({"/health", "/healthz"})

_MISSING_TOKEN = "PII_API_TOKEN is required."
_CUDA_ERROR = "CUDA is unavailable."
_MODEL_ERROR = "The model is not loaded on CUDA."
_INTERNAL_ERROR = "Internal error."
_LOG_ERROR = "Application error."

_UNAVAILABLE = (503, "unavailable", "Service unavailable.")
_UNAUTHORIZED = (401, "unauthorized", "Unauthorized.")
_INTERNAL = (500, "internal_error", _INTERNAL_ERROR)


def _token_configured(token: str | None) -> bool:
    return token is not None and bool(str(token).strip())


def _upstream_auth_mode() -> bool:
    """True only for the exact server environment value ``PII_AUTH_MODE=upstream``."""
    return os.environ.get(AUTH_MODE_ENV) == UPSTREAM_AUTH_MODE


def _authorized(environ: dict, token: str | None) -> bool:
    """Bearer check with the same bytes/Unicode semantics as the guardrail."""
    header = environ.get("HTTP_AUTHORIZATION")
    if not isinstance(header, str):
        return False
    parts = header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    try:
        expected = str(token).encode("utf-8", "surrogatepass")
        presented = parts[1].encode("utf-8", "surrogatepass")
    except (UnicodeError, AttributeError):
        return False
    return secrets.compare_digest(expected, presented)


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=True,
                      separators=(",", ":")).encode("ascii")


def _respond(environ: dict, start_response: Callable, status: int, body: bytes,
             content_type: str = "application/json") -> list[bytes]:
    """Small stdlib response: accurate length, no-store, correct HEAD."""
    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ]
    start_response(f"{status} {HTTPStatus(status).phrase}", headers)
    if str(environ.get("REQUEST_METHOD", "GET")).upper() == "HEAD":
        return []
    return [body]


def _error_response(environ, start_response, error):
    status, code, message = error
    return _respond(environ, start_response, status,
                    _json_bytes({"error": message, "code": code}))


def _internal_response(environ, start_response) -> list[bytes]:
    """Generic 500; a failing error response must not expose its cause."""
    try:
        return _error_response(environ, start_response, _INTERNAL)
    except Exception:
        raise RuntimeError(_INTERNAL_ERROR) from None


def _with_no_store(headers: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    kept = [(name, value) for name, value in headers
            if name.lower() != "cache-control"]
    kept.append(("Cache-Control", "no-store"))
    return kept


class _Stream:
    """Pass an app body through without buffering or leaking late errors."""

    def __init__(self, body, started, environ, start_response):
        self._body = body
        self._started = started
        self._environ = environ
        self._start_response = start_response
        self._iterator = None
        self._pending = None
        self._closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._pending is not None:
            return next(self._pending)
        if self._iterator is None:
            try:
                self._iterator = iter(self._body)
            except Exception:
                return self._fail()
        try:
            return next(self._iterator)
        except StopIteration:
            if not self._started():
                return self._fail()
            raise
        except Exception:
            return self._fail()

    def _fail(self):
        if self._started():
            raise RuntimeError(_INTERNAL_ERROR) from None
        self._pending = iter(_internal_response(
            self._environ, self._start_response))
        return next(self._pending)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            close = getattr(self._body, "close", None)
            if callable(close):
                close()
        except Exception:
            raise RuntimeError(_INTERNAL_ERROR) from None


class CloudService:
    """WSGI middleware: conditional local token, health, no-store, generic errors."""

    def __init__(self, application, module):
        self.application = application
        self.module = module

    def health(self, environ: dict, start_response: Callable) -> list[bytes]:
        """Minimal readiness probe; the local token prerequisite is conditional."""
        configured = False
        loaded = False
        gpu = False
        try:
            configured = _upstream_auth_mode() or _token_configured(
                os.environ.get(TOKEN_ENV))
            loaded = getattr(self.module, "nlp", None) is not None
            gpu = getattr(self.module, "device", None) == 0
        except Exception:
            # A readiness probe must stay a probe: never leak or raise.
            pass
        ready = configured and loaded and gpu
        body = {
            "status": "ok" if ready else "loading",
            "model_loaded": loaded,
            "device": "cuda" if gpu else "cpu",
        }
        return _respond(environ, start_response, 200 if ready else 503,
                        _json_bytes(body))

    def delegate(self, environ: dict, start_response: Callable) -> Iterable[bytes]:
        started = False
        head = str(environ.get("REQUEST_METHOD", "GET")).upper() == "HEAD"

        def send(status, headers, exc_info=None):
            nonlocal started
            result = start_response(status, _with_no_store(headers), exc_info)
            started = True
            if head and callable(result):
                # Legacy write callable: HEAD must not emit bytes either way.
                return lambda _data: None
            return result

        def is_started():
            return started

        try:
            body = self.application(environ, send)
        except Exception:
            if started:
                raise RuntimeError(_INTERNAL_ERROR) from None
            return _internal_response(environ, start_response)

        if head:
            return self._head(body, is_started, environ, start_response)
        return _Stream(body, is_started, environ, start_response)

    @staticmethod
    def _head(body, started, environ, start_response) -> list[bytes]:
        """Keep the app's status and headers, discard its body, close it.

        ``close`` runs in ``finally`` on every path, so a body that fails from
        ``__iter__`` or ``__next__`` cannot leak. Ordinary failures are
        sanitized, and a raw close exception never replaces a primary ordinary
        failure. ``BaseException`` keeps its identity after cleanup instead of
        being converted.
        """
        failure = None
        close_failure = None
        try:
            if not started():
                # A lazy app declares its status on the first iteration.
                iterator = iter(body)
                try:
                    next(iterator)
                except StopIteration:
                    pass
        except BaseException as error:
            failure = error
        finally:
            try:
                close = getattr(body, "close", None)
                if callable(close):
                    close()
            except BaseException as error:
                close_failure = error

        if failure is not None and not isinstance(failure, Exception):
            raise failure
        if close_failure is not None \
                and not isinstance(close_failure, Exception):
            raise close_failure
        error = failure if failure is not None else close_failure
        if error is not None:
            if started():
                raise RuntimeError(_INTERNAL_ERROR) from None
            return _internal_response(environ, start_response)
        if not started():
            return _internal_response(environ, start_response)
        return []

    def __call__(self, environ: dict, start_response: Callable) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = environ.get("PATH_INFO", "")
        if method in ("GET", "HEAD") and isinstance(path, str) \
                and path in HEALTH_PATHS:
            return self.health(environ, start_response)
        if not _upstream_auth_mode():
            try:
                token = os.environ.get(TOKEN_ENV)
            except Exception:
                token = None
            if not _token_configured(token):
                return _error_response(environ, start_response, _UNAVAILABLE)
            if not _authorized(environ, token):
                return _error_response(environ, start_response, _UNAUTHORIZED)
        return self.delegate(environ, start_response)


def _require_token() -> None:
    """Require the local token unless the exact upstream auth mode is selected."""
    if _upstream_auth_mode():
        return
    if not _token_configured(os.environ.get(TOKEN_ENV)):
        raise RuntimeError(_MISSING_TOKEN) from None


def _require_cuda() -> None:
    """Prove that CUDA really executes work, not only that a wheel imported."""
    try:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError
        probe = torch.ones(1, device="cuda")
        probe = probe + probe
        torch.cuda.synchronize()
        if float(probe.item()) != 2.0:
            raise RuntimeError
    except Exception:
        raise RuntimeError(_CUDA_ERROR) from None


def _model_ready(module) -> bool:
    try:
        return (getattr(module, "nlp", None) is not None
                and getattr(module, "device", None) == 0)
    except Exception:
        return False


def _import_application():
    return importlib.import_module("app")


class _SanitizeErrors(logging.Filter):
    """Replace error records (paths, tracebacks, request values) with a generic."""

    def filter(self, record):
        if record.exc_info or record.exc_text or record.levelno >= logging.ERROR:
            record.msg = _LOG_ERROR
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


def _sanitize_logging(module) -> None:
    flask_app = getattr(module, "app", None)
    logger = getattr(flask_app, "logger", None)
    if logger is None or getattr(logger, "__dict__", {}).get(
            "_cloud_service_sanitized", False):
        return
    logger.addFilter(_SanitizeErrors())
    setattr(logger, "_cloud_service_sanitized", True)


def create_app() -> "CloudService":
    """Gunicorn factory: local token unless upstream mode, CUDA, then Flask."""
    _require_token()
    _require_cuda()
    module = _import_application()
    if not _model_ready(module):
        raise RuntimeError(_MODEL_ERROR) from None
    _sanitize_logging(module)
    return CloudService(module.app, module)
