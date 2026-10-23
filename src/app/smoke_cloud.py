# -*- coding: utf-8 -*-
"""Smoke test remoto e sintetico per il servizio cloud su GPU.

Il servizio e' `cloud_service:create_app()` su un host RunPod gia' avviato: qui
non si carica il modello, non si addestra nulla e non si aprono documenti. Gli
input sono costanti sintetiche nel file; il segreto arriva solo da
`PII_API_TOKEN`, mai dagli argomenti e mai dalla URL.

La sequenza verifica:
  - `/health` pubblico, 200, `model_loaded` true e `device` "cuda";
  - `/api/v1/analyses` e `/settings` senza Bearer rispondono 401;
  - analisi JSON con `categories=["EMAIL"]` e placeholder/delta esatti;
  - riuso del seed JSON, con delta vuoto e `[EMAIL_1]` conservato;
  - multipart con un `.txt` sintetico piu' `text`, stesso delta aggregato.

Nessun retry: un 429 o un errore restano visibili e non raddoppiano il carico.
L'output contiene solo etichette PASS/FAIL fisse: mai token, corpi, delta,
frammenti di URL, nomi di file o testo delle eccezioni di rete. HTTPS e'
obbligatorio per un host remoto; HTTP e' ammesso solo per loopback letterale
(`localhost`, `127.0.0.1`, `[::1]`) durante i test su tunnel.

Uso::

    PII_API_TOKEN=... python src/app/smoke_cloud.py --url https://host:port

Il client usa solo la libreria standard, non segue redirect e limita la
risposta letta a 1 MiB. L'opener e' iniettabile dai test unitari.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

TOKEN_ENV = "PII_API_TOKEN"
DEFAULT_TIMEOUT = 60.0
MAX_RESPONSE_BYTES = 1024 * 1024
USER_AGENT = "envai-pii-cloud-smoke/1"

EMAIL = "runpod-smoke@example.com"
EMAIL_PLACEHOLDER = "[EMAIL_1]"
CATEGORIES = ("EMAIL",)
JSON_TEXT = f"Contact: {EMAIL}"
MULTIPART_FILE_TEXT = f"Contact: {EMAIL}\n"
MULTIPART_TEXT = f"Backup contact: {EMAIL}"
SEED = {EMAIL_PLACEHOLDER: EMAIL}

HEALTH_PATH = "/health"
ANALYSES_PATH = "/api/v1/analyses"
SETTINGS_PATH = "/settings"

PASS_HEALTH = "PASS health"
PASS_ANALYSES_AUTH = "PASS unauthenticated analyses"
PASS_SETTINGS_AUTH = "PASS unauthenticated settings"
PASS_JSON = "PASS json email"
PASS_SEED = "PASS json seed reuse"
PASS_MULTIPART = "PASS multipart aggregate"
PASS_FINAL = "PASS remote synthetic smoke"

LABEL_CONFIG = "configuration"
LABEL_HEALTH = "health"
LABEL_ANALYSES_AUTH = "unauthenticated analyses"
LABEL_SETTINGS_AUTH = "unauthenticated settings"
LABEL_JSON = "json email"
LABEL_SEED = "json seed reuse"
LABEL_MULTIPART = "multipart aggregate"
LABEL_INTERNAL = "internal"

MESSAGE_URL = "invalid --url"
MESSAGE_TOKEN_MISSING = "PII_API_TOKEN is not set"
MESSAGE_TOKEN_HEADER = "PII_API_TOKEN is not valid for an HTTP header"
MESSAGE_TIMEOUT = "timeout must be a finite positive number"
MESSAGE_REQUEST = "HTTP request failed"
MESSAGE_TOO_LARGE = "HTTP response is too large"
MESSAGE_RESPONSE = "HTTP response is invalid"
MESSAGE_CHECK = "check failed"
MESSAGE_INTERNAL = "unexpected smoke error"

BOUNDARY = "----envai-pii-cloud-smoke-7f3a"
MULTIPART_FILENAME = "runpod-smoke.txt"
PLACEHOLDER_RE = re.compile(r"\[[A-Z][A-Z0-9_]*_[1-9][0-9]*\]")
HOST_RE = re.compile(r"[A-Za-z0-9.-]+")
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class SmokeFailure(Exception):
    """Errore gia' sanificato: etichetta e messaggio sono costanti, mai dati."""

    def __init__(self, label: str, message: str):
        super().__init__(message)
        self.label = label
        self.message = message


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Non costruisce mai la richiesta successiva: nessun token verso un redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes


def build_opener():
    """Opener urllib con TLS standard e senza follow dei redirect."""
    return urllib.request.build_opener(_NoRedirectHandler())


# --------------------------------------------------------------------------- #
# Validazione della configurazione
# --------------------------------------------------------------------------- #
def _invalid_url() -> SmokeFailure:
    return SmokeFailure(LABEL_CONFIG, MESSAGE_URL)


def validate_base_url(value: Any) -> str:
    """URL base normalizzata, oppure SmokeFailure con messaggio fisso.

    Rifiuta schemi diversi da http/https, userinfo, query, fragment, porte non
    valide, caratteri di controllo, host non ASCII e HTTP verso un host che non
    sia loopback letterale. HTTPS resta obbligatorio per qualunque host remoto.
    """
    if not isinstance(value, str) or not value or not value.isascii():
        raise _invalid_url()
    if value != value.strip():
        raise _invalid_url()
    if any(ord(char) < 0x21 or ord(char) == 0x7F for char in value):
        raise _invalid_url()
    if "#" in value or "?" in value or "\\" in value:
        raise _invalid_url()

    try:
        parts = urllib.parse.urlsplit(value)
        hostname = parts.hostname
    except ValueError:
        raise _invalid_url() from None

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.netloc:
        raise _invalid_url()
    if "@" in parts.netloc:
        raise _invalid_url()
    if not hostname:
        raise _invalid_url()

    netloc = parts.netloc
    port_text: str | None
    if netloc.startswith("["):
        end = netloc.find("]")
        if end < 0:
            raise _invalid_url()
        literal = netloc[1:end]
        suffix = netloc[end + 1:]
        if suffix and not suffix.startswith(":"):
            raise _invalid_url()
        port_text = suffix[1:] if suffix else None
        try:
            ipaddress.IPv6Address(literal)
        except ValueError:
            raise _invalid_url() from None
    else:
        if ":" in netloc:
            host_text, port_text = netloc.rsplit(":", 1)
            if ":" in host_text:
                raise _invalid_url()
        else:
            host_text, port_text = netloc, None
        if not HOST_RE.fullmatch(host_text):
            raise _invalid_url()

    if port_text is not None:
        if not port_text.isdigit() or len(port_text) > 5:
            raise _invalid_url()
        port = int(port_text)
        if not 1 <= port <= 65535:
            raise _invalid_url()

    if scheme == "http" and hostname not in LOOPBACK_HOSTS:
        raise _invalid_url()

    path = parts.path.rstrip("/")
    return f"{scheme}://{netloc}{path}"


def validate_token(token: Any) -> str:
    """Token sicuro per un header: visibile ASCII, senza spazi o caratteri di controllo."""
    if not isinstance(token, str) or not token:
        raise SmokeFailure(LABEL_CONFIG, MESSAGE_TOKEN_HEADER)
    if any(not 0x21 <= ord(char) <= 0x7E for char in token):
        raise SmokeFailure(LABEL_CONFIG, MESSAGE_TOKEN_HEADER)
    return token


def load_token(environ: Mapping[str, str] | None = None) -> str:
    """Legge il segreto solo dall'ambiente e lo valida prima di usarlo."""
    env = os.environ if environ is None else environ
    token = env.get(TOKEN_ENV)
    if token is None or token == "":
        raise SmokeFailure(LABEL_CONFIG, MESSAGE_TOKEN_MISSING)
    return validate_token(token)


def validate_timeout(value: Any) -> float:
    """Timeout finito e positivo, in secondi."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise SmokeFailure(LABEL_CONFIG, MESSAGE_TIMEOUT) from None
    if not math.isfinite(seconds) or seconds <= 0.0:
        raise SmokeFailure(LABEL_CONFIG, MESSAGE_TIMEOUT)
    return seconds


# --------------------------------------------------------------------------- #
# Trasporto HTTP bounded
# --------------------------------------------------------------------------- #
def _close_quietly(response: Any) -> None:
    try:
        close = getattr(response, "close", None)
        if close is not None:
            close()
    except Exception:
        pass


def _response_status(response: Any, label: str) -> int:
    status = getattr(response, "status", None)
    if status is None:
        getcode = getattr(response, "getcode", None)
        if getcode is None:
            raise SmokeFailure(label, MESSAGE_RESPONSE)
        try:
            status = getcode()
        except Exception:
            raise SmokeFailure(label, MESSAGE_RESPONSE) from None
    if type(status) is not int:
        raise SmokeFailure(label, MESSAGE_RESPONSE)
    return status


def _read_bounded(response: Any, label: str) -> bytes:
    """Legge al massimo MAX_RESPONSE_BYTES + 1 byte, poi rifiuta l'eccesso."""
    chunks: list[bytes] = []
    remaining = MAX_RESPONSE_BYTES + 1
    try:
        while remaining > 0:
            chunk = response.read(remaining)
            if not chunk:
                break
            if not isinstance(chunk, (bytes, bytearray)):
                raise SmokeFailure(label, MESSAGE_RESPONSE)
            data = bytes(chunk)
            chunks.append(data)
            remaining -= len(data)
    except SmokeFailure:
        raise
    except Exception:
        raise SmokeFailure(label, MESSAGE_REQUEST) from None

    body = b"".join(chunks)
    if len(body) > MAX_RESPONSE_BYTES:
        raise SmokeFailure(label, MESSAGE_TOO_LARGE)
    return body


def _http_request(opener: Any, method: str, url: str, *, token: str | None,
                  timeout: float, body: bytes | None = None,
                  content_type: str | None = None, label: str) -> HttpResponse:
    """Una sola richiesta, senza retry, con corpo limitato e chiusura garantita."""
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": USER_AGENT,
    }
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    if content_type is not None:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(
        url, data=body, headers=headers, method=method)

    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        try:
            status = exc.code
            if type(status) is not int:
                raise ValueError
            return HttpResponse(status, b"")
        except Exception:
            raise SmokeFailure(label, MESSAGE_REQUEST) from None
        finally:
            _close_quietly(exc)
    except SmokeFailure:
        raise
    except Exception:
        raise SmokeFailure(label, MESSAGE_REQUEST) from None

    try:
        status = _response_status(response, label)
        response_body = _read_bounded(response, label)
    except SmokeFailure:
        raise
    except Exception:
        raise SmokeFailure(label, MESSAGE_REQUEST) from None
    finally:
        _close_quietly(response)
    return HttpResponse(status, response_body)


def _reject_json_constant(_value: str) -> None:
    """NaN e Infinity non fanno parte del JSON standard."""
    raise ValueError


def _decode_json(body: bytes, label: str) -> Any:
    try:
        return json.loads(
            body.decode("utf-8"), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, ValueError, TypeError):
        raise SmokeFailure(label, MESSAGE_RESPONSE) from None


def _require_status(response: HttpResponse, expected: int, label: str) -> None:
    if response.status != expected:
        raise SmokeFailure(label, MESSAGE_CHECK)


# --------------------------------------------------------------------------- #
# Validazione di risposte e checks
# --------------------------------------------------------------------------- #
def _validate_health(payload: Any, label: str = LABEL_HEALTH) -> None:
    """Campi minimi di /health; i campi extra del servizio reale sono ammessi."""
    if not isinstance(payload, dict):
        raise SmokeFailure(label, MESSAGE_RESPONSE)
    if (payload.get("status") != "ok"
            or payload.get("model_loaded") is not True
            or payload.get("device") != "cuda"):
        raise SmokeFailure(label, MESSAGE_CHECK)


def _validate_analysis(payload: Any, expected_ids: Sequence[str],
                       expected_delta: Mapping[str, str],
                       label: str) -> None:
    """Forma esatta della risposta guardrail, placeholder EMAIL e delta attesi."""
    if not isinstance(payload, dict) or set(payload) != {"results", "dictionary_delta"}:
        raise SmokeFailure(label, MESSAGE_RESPONSE)
    results = payload["results"]
    delta = payload["dictionary_delta"]
    if not isinstance(results, list) or len(results) != len(expected_ids):
        raise SmokeFailure(label, MESSAGE_RESPONSE)
    if not isinstance(delta, dict) or delta != expected_delta:
        raise SmokeFailure(label, MESSAGE_CHECK)

    for result, expected_id in zip(results, expected_ids):
        if not isinstance(result, dict) or set(result) != {
                "input_id", "anonymized_text", "statistics"}:
            raise SmokeFailure(label, MESSAGE_RESPONSE)
        if result["input_id"] != expected_id:
            raise SmokeFailure(label, MESSAGE_CHECK)

        anonymous = result["anonymized_text"]
        statistics = result["statistics"]
        if not isinstance(anonymous, str):
            raise SmokeFailure(label, MESSAGE_RESPONSE)
        if not isinstance(statistics, dict) or set(statistics) != {"placeholder_count"}:
            raise SmokeFailure(label, MESSAGE_RESPONSE)
        count = statistics["placeholder_count"]
        if type(count) is not int or count != 1:
            raise SmokeFailure(label, MESSAGE_CHECK)

        placeholders = PLACEHOLDER_RE.findall(anonymous)
        if (placeholders != [EMAIL_PLACEHOLDER]
                or anonymous.count(EMAIL_PLACEHOLDER) != 1
                or EMAIL in anonymous):
            raise SmokeFailure(label, MESSAGE_CHECK)


def _check_health(base: str, opener: Any, timeout: float) -> None:
    response = _http_request(
        opener, "GET", base + HEALTH_PATH, token=None, timeout=timeout,
        label=LABEL_HEALTH)
    _require_status(response, 200, LABEL_HEALTH)
    _validate_health(_decode_json(response.body, LABEL_HEALTH), LABEL_HEALTH)


def _check_unauthenticated(base: str, opener: Any, timeout: float) -> None:
    analyses = _http_request(
        opener, "POST", base + ANALYSES_PATH, token=None, timeout=timeout,
        label=LABEL_ANALYSES_AUTH)
    _require_status(analyses, 401, LABEL_ANALYSES_AUTH)

    settings = _http_request(
        opener, "GET", base + SETTINGS_PATH, token=None, timeout=timeout,
        label=LABEL_SETTINGS_AUTH)
    _require_status(settings, 401, LABEL_SETTINGS_AUTH)


def _post_json(base: str, opener: Any, token: str, timeout: float,
               payload: Mapping[str, Any], expected_ids: Sequence[str],
               expected_delta: Mapping[str, str], label: str) -> None:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    response = _http_request(
        opener, "POST", base + ANALYSES_PATH, token=token, timeout=timeout,
        body=body, content_type="application/json", label=label)
    _require_status(response, 200, label)
    _validate_analysis(
        _decode_json(response.body, label), expected_ids, expected_delta, label)


def _multipart_body(parts: Sequence[tuple[str, str | None, str | None, bytes]]) -> bytes:
    chunks: list[bytes] = []
    for name, filename, content_type, data in parts:
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        head = [f"--{BOUNDARY}\r\n", disposition, "\r\n"]
        if content_type is not None:
            head.append(f"Content-Type: {content_type}\r\n")
        head.append("\r\n")
        chunks.append("".join(head).encode("ascii"))
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{BOUNDARY}--\r\n".encode("ascii"))
    return b"".join(chunks)


def _check_multipart(base: str, opener: Any, token: str, timeout: float) -> None:
    body = _multipart_body((
        ("files", MULTIPART_FILENAME, "text/plain", MULTIPART_FILE_TEXT.encode("ascii")),
        ("text", None, None, MULTIPART_TEXT.encode("ascii")),
        ("categories", None, None, json.dumps(list(CATEGORIES)).encode("ascii")),
    ))
    content_type = f"multipart/form-data; boundary={BOUNDARY}"
    response = _http_request(
        opener, "POST", base + ANALYSES_PATH, token=token, timeout=timeout,
        body=body, content_type=content_type, label=LABEL_MULTIPART)
    _require_status(response, 200, LABEL_MULTIPART)
    _validate_analysis(
        _decode_json(response.body, LABEL_MULTIPART),
        ("file_1", "text"), {EMAIL_PLACEHOLDER: EMAIL}, LABEL_MULTIPART)


def run_smoke(base_url: str, token: str, *, opener: Any = None,
              timeout: float = DEFAULT_TIMEOUT,
              on_pass: Callable[[str], None] | None = None) -> None:
    """Esegue i checks in ordine; nessun retry e nessuna scrittura su disco."""
    base = validate_base_url(base_url)
    validate_token(token)
    seconds = validate_timeout(timeout)
    if opener is None:
        opener = build_opener()

    def passed(label: str) -> None:
        if on_pass is not None:
            on_pass(label)

    _check_health(base, opener, seconds)
    passed(PASS_HEALTH)
    _check_unauthenticated(base, opener, seconds)
    passed(PASS_ANALYSES_AUTH)
    passed(PASS_SETTINGS_AUTH)

    _post_json(base, opener, token, seconds,
               {"text": JSON_TEXT, "categories": list(CATEGORIES)},
               ("text",), {EMAIL_PLACEHOLDER: EMAIL}, LABEL_JSON)
    passed(PASS_JSON)

    _post_json(base, opener, token, seconds,
               {"text": JSON_TEXT, "dictionary": SEED,
                "categories": list(CATEGORIES)},
               ("text",), {}, LABEL_SEED)
    passed(PASS_SEED)

    _check_multipart(base, opener, token, seconds)
    passed(PASS_MULTIPART)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
class _Parser(argparse.ArgumentParser):
    """Parser che non ripete mai gli argomenti grezzi nei messaggi di errore."""

    def error(self, message):  # noqa: D401
        self.exit(2, "configuration error\n")


def _timeout_argument(raw: str) -> float:
    try:
        return validate_timeout(raw)
    except SmokeFailure:
        raise argparse.ArgumentTypeError(MESSAGE_TIMEOUT) from None


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        description="Synthetic remote smoke test for the GPU cloud service.",
        allow_abbrev=False)
    parser.add_argument("--url", required=True,
                        help="base URL (HTTPS; HTTP only for literal loopback)")
    parser.add_argument("--timeout", type=_timeout_argument, default=DEFAULT_TIMEOUT,
                        help=f"per-request timeout in seconds (default {DEFAULT_TIMEOUT:g})")
    return parser


def main(argv: Sequence[str] | None = None, *, opener: Any = None,
         environ: Mapping[str, str] | None = None,
         stdout: Any = None, stderr: Any = None) -> int:
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    args = build_parser().parse_args(argv)

    try:
        token = load_token(environ)
        run_smoke(
            args.url, token, opener=opener, timeout=args.timeout,
            on_pass=lambda label: print(label, file=out, flush=True))
    except SmokeFailure as exc:
        print(f"FAIL {exc.label}: {exc.message}", file=err, flush=True)
        return 1
    except Exception:
        print(f"FAIL {LABEL_INTERNAL}: {MESSAGE_INTERNAL}", file=err, flush=True)
        return 1

    print(PASS_FINAL, file=out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
