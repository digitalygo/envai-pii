"""Bounded stdlib transport for the Verda management and inference APIs.

The module holds only fixed URLs for the approved target, a strict credential
reader that keeps values in memory, and a redirect-free TLS sender without
retries. Failures raise closed reason codes and never carry raw exception
text, headers or bodies.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

CLOUD_ROOT = "https://api.verda.com/v1"
TOKEN_URL = CLOUD_ROOT + "/oauth2/token"
DEPLOYMENT_URL = CLOUD_ROOT + "/container-deployments/envai-pii-test"
STATUS_URL = DEPLOYMENT_URL + "/status"
REPLICAS_URL = DEPLOYMENT_URL + "/replicas"
SCALING_URL = DEPLOYMENT_URL + "/scaling"
LOGS_URL = DEPLOYMENT_URL + "/logs"
SYSTEM_LOGS_URL = DEPLOYMENT_URL + "/system-logs"
INFERENCE_URL = "https://containers.datacrunch.io/envai-pii-test/api/v1/analyses"
DEPLOYMENT_ACTIONS = frozenset({"pause", "resume"})

OAUTH_TIMEOUT_SECONDS = 30.0
MANAGEMENT_TIMEOUT_SECONDS = 30.0
MANAGEMENT_CAP_BYTES = 8 * 1024 * 1024
INFERENCE_CAP_BYTES = 2 * 1024 * 1024
CREDENTIAL_FILE_MAX_BYTES = 16 * 1024
LOG_LIMIT_MAX = 1000
MAX_LOG_WINDOW_SECONDS = 55.0
MAX_LOG_POD_LENGTH = 253
MAX_LOG_CONTAINER_LENGTH = 63

CREDENTIAL_FIELDS = ("client_id", "client_secret", "inference_api_key")
MANAGEMENT_OK_STATUSES = frozenset({200})
ACTION_OK_STATUSES = frozenset({200, 201})
SYSTEM_LOG_METADATA_FIELDS = (
    "timestamp",
    "first_timestamp",
    "last_timestamp",
    "level",
    "reason",
    "involved_object",
    "count",
)

KNOWN_DEPLOYMENT_STATUSES = frozenset({
    "degraded",
    "healthy",
    "image_pulling",
    "initializing",
    "paused",
    "quota_reached",
    "terminating",
    "unhealthy",
    "updating",
})

_LOG_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class TransportError(Exception):
    def __init__(self, reason: str, status: int | None = None):
        message = reason if status is None else f"{reason} ({status})"
        super().__init__(message)
        self.reason = reason
        self.status = status


@dataclass(frozen=True)
class Credentials:
    client_id: str
    client_secret: str
    inference_api_key: str

    def __repr__(self) -> str:
        return "Credentials(<redacted>)"

    @classmethod
    def from_file(cls, path: str) -> "Credentials":
        try:
            payload = json.loads(
                _read_credential_file(path).decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise TransportError("credential_file_invalid") from None
        if not isinstance(payload, dict) or set(payload) != set(CREDENTIAL_FIELDS):
            raise TransportError("credential_file_invalid")
        values = [payload[field] for field in CREDENTIAL_FIELDS]
        if any(not isinstance(value, str) or not value for value in values):
            raise TransportError("credential_file_invalid")
        return cls(*values)


def _read_credential_file(path: str) -> bytes:
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        descriptor = os.open(path, flags)
    except Exception:
        raise TransportError("credential_file_invalid") from None
    try:
        try:
            info = os.fstat(descriptor)
        except Exception:
            raise TransportError("credential_file_invalid") from None
        if (not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size > CREDENTIAL_FILE_MAX_BYTES):
            raise TransportError("credential_file_invalid")
        chunks = []
        remaining = CREDENTIAL_FILE_MAX_BYTES + 1
        while remaining > 0:
            try:
                chunk = os.read(descriptor, remaining)
            except Exception:
                raise TransportError("credential_file_invalid") from None
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
    finally:
        try:
            os.close(descriptor)
        except Exception:
            pass
    if len(payload) > CREDENTIAL_FILE_MAX_BYTES:
        raise TransportError("credential_file_invalid")
    return payload


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _close_quietly(handle: Any) -> None:
    close = getattr(handle, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _read_payload(handle: Any, status: int, cap: int) -> tuple[int, bytes]:
    try:
        body = handle.read(cap + 1)
    except Exception:
        raise TransportError("response_read_failed", status) from None
    finally:
        _close_quietly(handle)
    if not isinstance(body, (bytes, bytearray)):
        raise TransportError("response_read_failed", status)
    if len(body) > cap:
        raise TransportError("response_cap_exceeded", status)
    return status, bytes(body)


def _secure_url(url: str) -> bool:
    if not isinstance(url, str) or not url.startswith("https://"):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
    except (TypeError, ValueError):
        return False
    return (
        parts.scheme == "https"
        and bool(parts.netloc)
        and parts.username is None
        and parts.password is None
    )


def _urllib_send(method: str, url: str, headers: dict[str, str],
                 payload: bytes | None, timeout: float, cap: int,
                 ) -> tuple[int, bytes]:
    if not _secure_url(url):
        raise TransportError("transport_error")
    try:
        request = urllib.request.Request(
            url, data=payload, headers=headers, method=method)
    except (TypeError, ValueError, OSError):
        raise TransportError("transport_error") from None
    try:
        response = _OPENER.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        try:
            status = int(error.code)
        except (TypeError, ValueError):
            _close_quietly(error)
            raise TransportError("transport_error") from None
        try:
            return _read_payload(error, status, cap)
        finally:
            _close_quietly(error)
    except Exception:
        raise TransportError("transport_error") from None
    try:
        status = int(response.status)
    except (AttributeError, TypeError, ValueError):
        _close_quietly(response)
        raise TransportError("response_read_failed") from None
    return _read_payload(response, status, cap)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _parse_json(body: bytes, reason: str) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise TransportError(reason) from None


def _parse_json_object(body: bytes, reason: str) -> dict[str, Any]:
    parsed = _parse_json(body, reason)
    if not isinstance(parsed, dict):
        raise TransportError(reason)
    return parsed


def _format_utc(moment: datetime) -> str:
    text = moment.isoformat(timespec="auto")
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text


def _log_time(value: Any) -> tuple[str, datetime]:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        if not value or value.strip() != value:
            raise TransportError("log_query_invalid")
        candidate = (
            value[:-1] + "+00:00"
            if value.endswith(("Z", "z")) else value)
        try:
            moment = datetime.fromisoformat(candidate)
        except ValueError:
            raise TransportError("log_query_invalid") from None
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if not math.isfinite(seconds):
            raise TransportError("log_query_invalid")
        try:
            moment = datetime.fromtimestamp(seconds, timezone.utc)
        except (OverflowError, OSError, ValueError):
            raise TransportError("log_query_invalid") from None
    else:
        raise TransportError("log_query_invalid")
    try:
        offset = moment.utcoffset()
    except (OverflowError, ValueError):
        raise TransportError("log_query_invalid") from None
    if moment.tzinfo is None or offset != timedelta(0):
        raise TransportError("log_query_invalid")
    return _format_utc(moment.astimezone(timezone.utc)), moment.astimezone(
        timezone.utc)


def _log_window(start: Any, end: Any | None) -> tuple[str, str | None]:
    start_text, start_moment = _log_time(start)
    if end is None:
        return start_text, None
    end_text, end_moment = _log_time(end)
    window = (end_moment - start_moment).total_seconds()
    if window < 0 or window > MAX_LOG_WINDOW_SECONDS:
        raise TransportError("log_query_invalid")
    return start_text, end_text


def _validate_log_name(value: Any, maximum: int) -> str:
    if (not isinstance(value, str)
            or not 1 <= len(value) <= maximum
            or _LOG_NAME_PATTERN.fullmatch(value) is None):
        raise TransportError("log_query_invalid")
    return value


def _log_pods(pod: str | Sequence[str] | None,
              pods: Sequence[str]) -> tuple[str, ...]:
    candidates: list[Any] = []
    if pod is not None:
        if isinstance(pod, str):
            candidates.append(pod)
        elif isinstance(pod, Sequence) and not isinstance(
                pod, (bytes, bytearray)):
            candidates.extend(pod)
        else:
            raise TransportError("log_query_invalid")
    if not isinstance(pods, Sequence) or isinstance(
            pods, (str, bytes, bytearray)):
        raise TransportError("log_query_invalid")
    candidates.extend(pods)
    return tuple(
        _validate_log_name(value, MAX_LOG_POD_LENGTH) for value in candidates)


def _log_query(*, start: Any, end: Any | None, pods: Sequence[str],
               container_name: str | None, order: str, limit: int,
               ) -> str:
    if order not in ("asc", "desc"):
        raise TransportError("log_query_invalid")
    if type(limit) is not int or not 1 <= limit <= LOG_LIMIT_MAX:
        raise TransportError("log_query_invalid")
    start_text, end_text = _log_window(start, end)
    params = [("pod", value) for value in pods]
    if container_name is not None:
        params.append((
            "container_name",
            _validate_log_name(container_name, MAX_LOG_CONTAINER_LENGTH),
        ))
    params.append(("start", start_text))
    if end_text is not None:
        params.append(("end", end_text))
    params.append(("order", order))
    params.append(("limit", str(limit)))
    return urllib.parse.urlencode(params)


def _system_log_metadata(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {}
    return {
        key: entry[key]
        for key in SYSTEM_LOG_METADATA_FIELDS
        if key in entry
        and isinstance(entry[key], (str, int, float, bool))
    }


class VerdaTransport:
    def __init__(self, credentials: Credentials, *,
                 sender: Any = None) -> None:
        self._credentials = credentials
        self._send = sender if sender is not None else _urllib_send
        self._token: str | None = None

    def fetch_token(self) -> None:
        payload = _json_bytes({
            "grant_type": "client_credentials",
            "client_id": self._credentials.client_id,
            "client_secret": self._credentials.client_secret,
        })
        status, body = self._send(
            "POST", TOKEN_URL, {"Content-Type": "application/json"},
            payload, OAUTH_TIMEOUT_SECONDS, MANAGEMENT_CAP_BYTES)
        if status != 200:
            raise TransportError("oauth_failed", status)
        parsed = _parse_json_object(body, "oauth_response_invalid")
        token = parsed.get("access_token")
        if not isinstance(token, str) or not token:
            raise TransportError("oauth_response_invalid")
        self._token = token

    def _management_body(
            self, method: str, url: str, *,
            payload: bytes | None = None,
            accepted_statuses: frozenset[int] = MANAGEMENT_OK_STATUSES,
    ) -> bytes:
        if not self._token:
            raise TransportError("token_missing")
        headers = {
            "Authorization": "Bearer " + self._token,
            "Accept": "application/json",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        status, body = self._send(
            method, url, headers, payload, MANAGEMENT_TIMEOUT_SECONDS,
            MANAGEMENT_CAP_BYTES)
        if status not in accepted_statuses:
            raise TransportError("management_http", status)
        return body

    def _management_json(self, method: str, url: str, *,
                         payload: bytes | None = None) -> dict[str, Any]:
        body = self._management_body(method, url, payload=payload)
        return _parse_json_object(body, "management_json_invalid")

    def get_deployment(self) -> dict[str, Any]:
        return self._management_json("GET", DEPLOYMENT_URL)

    def get_scaling(self) -> dict[str, Any]:
        return self._management_json("GET", SCALING_URL)

    def patch_scaling(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._management_json(
            "PATCH", SCALING_URL, payload=_json_bytes(body))

    def patch_deployment(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._management_json(
            "PATCH", DEPLOYMENT_URL, payload=_json_bytes(body))

    def get_status(self) -> str:
        parsed = self._management_json("GET", STATUS_URL)
        if set(parsed) != {"status"} or not isinstance(parsed["status"], str):
            raise TransportError("status_shape_invalid")
        return parsed["status"]

    def get_replicas(self) -> dict[str, Any]:
        parsed = self._management_json("GET", REPLICAS_URL)
        if not isinstance(parsed.get("list"), list):
            raise TransportError("replicas_shape_invalid")
        return parsed

    def post_action(self, action: str) -> None:
        if action not in DEPLOYMENT_ACTIONS:
            raise TransportError("action_invalid")
        self._management_body(
            "POST", DEPLOYMENT_URL + "/" + action,
            accepted_statuses=ACTION_OK_STATUSES)

    def get_logs(self, *, start: Any, end: Any | None = None,
                 pod: str | Sequence[str] | None = None,
                 pods: Sequence[str] = (),
                 container_name: str | None = None,
                 order: str = "asc", limit: int = LOG_LIMIT_MAX) -> list[Any]:
        pod_values = _log_pods(pod, pods)
        query = _log_query(
            start=start, end=end, pods=pod_values,
            container_name=container_name, order=order, limit=limit)
        body = self._management_body("GET", LOGS_URL + "?" + query)
        parsed = _parse_json(body, "logs_shape_invalid")
        if not isinstance(parsed, list):
            raise TransportError("logs_shape_invalid")
        return parsed

    def get_system_logs(self, *, start: Any, end: Any | None = None,
                        order: str = "desc", limit: int = LOG_LIMIT_MAX,
                        ) -> list[dict[str, Any]]:
        query = _log_query(
            start=start, end=end, pods=(), container_name=None,
            order=order, limit=limit)
        body = self._management_body("GET", SYSTEM_LOGS_URL + "?" + query)
        parsed = _parse_json(body, "system_logs_shape_invalid")
        if not isinstance(parsed, list):
            raise TransportError("system_logs_shape_invalid")
        return [
            metadata for metadata in (
                _system_log_metadata(entry) for entry in parsed)
            if metadata
        ]

    def post_inference(self, body: bytes, timeout: float) -> tuple[int, bytes]:
        headers = {
            "Authorization": "Bearer " + self._credentials.inference_api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        return self._send(
            "POST", INFERENCE_URL, headers, body, timeout, INFERENCE_CAP_BYTES)
