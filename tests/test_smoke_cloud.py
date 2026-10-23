# -*- coding: utf-8 -*-
"""Test unitari di `src/app/smoke_cloud.py` (solo libreria standard).

Nessun modello, nessun container e nessun host esterno: l'opener HTTP e'
iniettato con risposte finte, tranne un fixture locale su 127.0.0.1 che verifica
il mancato follow dei redirect e viene sempre chiuso. Tutti i valori sono
sintetici.
"""

import contextlib
import http.server
import io
import json
import os
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "app"))

import smoke_cloud as smoke  # noqa: E402

SCRIPT = ROOT / "src" / "app" / "smoke_cloud.py"
TOKEN = "smoke-test-token-123"
BASE = "https://cloud.example.test"
TIMEOUT = 7.5
HEALTH_OK = {
    "status": "ok",
    "model_loaded": True,
    "device": "cuda",
    "model": "must-not-be-printed",
    "tags": 24,
}
JSON_OK = {
    "results": [{
        "input_id": "text",
        "anonymized_text": "Contact: [EMAIL_1]",
        "statistics": {"placeholder_count": 1},
    }],
    "dictionary_delta": {"[EMAIL_1]": smoke.EMAIL},
}
SEED_OK = {
    "results": [{
        "input_id": "text",
        "anonymized_text": "Contact: [EMAIL_1]",
        "statistics": {"placeholder_count": 1},
    }],
    "dictionary_delta": {},
}
MULTIPART_OK = {
    "results": [
        {
            "input_id": "file_1",
            "anonymized_text": "Contact: [EMAIL_1]\n",
            "statistics": {"placeholder_count": 1},
        },
        {
            "input_id": "text",
            "anonymized_text": "Backup contact: [EMAIL_1]",
            "statistics": {"placeholder_count": 1},
        },
    ],
    "dictionary_delta": {"[EMAIL_1]": smoke.EMAIL},
}


class FakeResponse:
    """Risposta file-like con status, corpo e chiusura osservabile."""

    def __init__(self, status=200, body=b"", status_attr=True):
        self._status = status
        self._body = body
        self.closed = False
        self.status = status if status_attr else None

    def getcode(self):
        return self._status

    def read(self, size=-1):
        if size is None or size < 0:
            chunk, self._body = self._body, b""
            return chunk
        chunk, self._body = self._body[:size], self._body[size:]
        return chunk

    def close(self):
        self.closed = True


class ScriptedOpener:
    """Opener finto: registra richieste e timeout, risponde con una funzione."""

    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append((request, timeout))
        result = self.responder(request)
        if isinstance(result, BaseException):
            raise result
        return result


class FailOpener:
    """Opener che fallisce se viene usato: serve per i test di sola configurazione."""

    def __init__(self):
        self.calls = 0

    def open(self, request, timeout=None):
        self.calls += 1
        raise AssertionError("network must not be used")


def header(request, name):
    """Header case-insensitive: urllib normalizza le chiavi in `Xxx-yyy`."""
    lowered = name.lower()
    for key, value in request.headers.items():
        if key.lower() == lowered:
            return value
    return None


def success_responder(request):
    path = urllib.parse.urlsplit(request.full_url).path
    auth = header(request, "Authorization")
    if path == "/health":
        return FakeResponse(200, json.dumps(HEALTH_OK).encode("utf-8"))
    if path == "/settings":
        return FakeResponse(401)
    if path == "/api/v1/analyses" and request.get_method() == "POST":
        if auth is None:
            return FakeResponse(401)
        if auth != "Bearer " + TOKEN:
            return FakeResponse(401)
        content_type = header(request, "Content-Type") or ""
        if content_type.startswith("multipart/form-data"):
            return FakeResponse(200, json.dumps(MULTIPART_OK).encode("utf-8"))
        payload = json.loads(request.data.decode("utf-8"))
        body = SEED_OK if "dictionary" in payload else JSON_OK
        return FakeResponse(200, json.dumps(body).encode("utf-8"))
    return FakeResponse(404)


def analysis_payload(ids=("text",), delta=None):
    if delta is None:
        delta = {"[EMAIL_1]": smoke.EMAIL}
    return {
        "results": [{
            "input_id": input_id,
            "anonymized_text": "Contact: [EMAIL_1]",
            "statistics": {"placeholder_count": 1},
        } for input_id in ids],
        "dictionary_delta": dict(delta),
    }


class UrlValidation(unittest.TestCase):
    def test_https_remoto_e_path_normalizzato(self):
        self.assertEqual(
            smoke.validate_base_url("HTTPS://Cloud.Example:8443/prefix/"),
            "https://Cloud.Example:8443/prefix")
        self.assertEqual(
            smoke.validate_base_url("https://example.test/"),
            "https://example.test")
        self.assertEqual(
            smoke.validate_base_url("https://[2001:db8::1]:443/root"),
            "https://[2001:db8::1]:443/root")
        self.assertEqual(
            smoke.validate_base_url("https://example.test:65535"),
            "https://example.test:65535")

    def test_http_solo_loopback_letterale(self):
        for url in ("http://localhost", "http://LOCALHOST:5005",
                    "http://127.0.0.1", "http://127.0.0.1:8080",
                    "http://[::1]", "http://[::1]:5005"):
            with self.subTest(url=url):
                self.assertTrue(smoke.validate_base_url(url).startswith("http://"))
        self.assertEqual(smoke.validate_base_url("http://[::1]:5005"),
                         "http://[::1]:5005")

    def test_url_rifiutate(self):
        urls = (
            "", "ftp://example.test", "file:///tmp/x", "//example.test",
            "https://", "https:///path", "https://user@example.test",
            "https://user:pass@example.test", "https://@example.test",
            "https://example.test/path?x=1", "https://example.test/path?",
            "https://example.test/path#frag", "https://example.test/path#",
            "https://example.test:abc", "https://example.test:0",
            "https://example.test:65536", "https://example.test:",
            "https://example.test:80:90", "https://example.test\\@127.0.0.1",
            "https://exa mple.test", "https://exämple.test",
            "https://example.test\n", " https://example.test",
            "https://example.test\\path", "http://example.test",
            "http://localhost.", "http://127.0.0.2",
            "http://[0:0:0:0:0:0:0:1]", "http://[::1", "https://[not-ipv6]",
            "https://example.test: 80", 123, None,
        )
        for url in urls:
            with self.subTest(url=url):
                with self.assertRaises(smoke.SmokeFailure) as raised:
                    smoke.validate_base_url(url)
                self.assertEqual(raised.exception.label, smoke.LABEL_CONFIG)
                self.assertEqual(raised.exception.message, smoke.MESSAGE_URL)

    def test_url_con_segreto_non_finisce_nel_messaggio(self):
        with self.assertRaises(smoke.SmokeFailure) as raised:
            smoke.validate_base_url(f"https://user:{TOKEN}@example.test")
        self.assertNotIn(TOKEN, str(raised.exception))
        self.assertNotIn("example.test", str(raised.exception))


class TokenAndTimeout(unittest.TestCase):
    def test_token_valido_e_ambiente(self):
        self.assertEqual(smoke.validate_token("abc.DEF_123-+="), "abc.DEF_123-+=")
        self.assertEqual(smoke.load_token({smoke.TOKEN_ENV: TOKEN}), TOKEN)

    def test_token_mancante_o_non_header(self):
        for env in ({}, {smoke.TOKEN_ENV: ""}):
            with self.subTest(env=env):
                with self.assertRaises(smoke.SmokeFailure) as raised:
                    smoke.load_token(env)
                self.assertEqual(raised.exception.message, smoke.MESSAGE_TOKEN_MISSING)

        secrets = ("abc\nInjected: yes", "abc\rX", "abc\tdef", "abc def",
                   "abc\x7f", "café", " abc", "abc ", 123)
        for token in secrets:
            with self.subTest(token=token):
                with self.assertRaises(smoke.SmokeFailure) as raised:
                    smoke.validate_token(token)
                self.assertEqual(raised.exception.message, smoke.MESSAGE_TOKEN_HEADER)
                self.assertNotIn("Injected", str(raised.exception))

    def test_timeout_finito_e_positivo(self):
        for value, expected in ((5, 5.0), ("2.5", 2.5), (0.125, 0.125)):
            with self.subTest(value=value):
                self.assertEqual(smoke.validate_timeout(value), expected)
        for value in (0, -1, "nan", "inf", "-inf", "1e999", "x", None):
            with self.subTest(value=value):
                with self.assertRaises(smoke.SmokeFailure) as raised:
                    smoke.validate_timeout(value)
                self.assertEqual(raised.exception.message, smoke.MESSAGE_TIMEOUT)


class ResponseTransport(unittest.TestCase):
    def opener(self, response):
        return ScriptedOpener(lambda _request: response)

    def test_corpo_esattamente_al_limite_e_oltre(self):
        exact = smoke._read_bounded(
            FakeResponse(body=b"x" * smoke.MAX_RESPONSE_BYTES), "health")
        self.assertEqual(len(exact), smoke.MAX_RESPONSE_BYTES)
        with self.assertRaises(smoke.SmokeFailure) as raised:
            smoke._read_bounded(
                FakeResponse(body=b"x" * (smoke.MAX_RESPONSE_BYTES + 1)), "health")
        self.assertEqual(raised.exception.message, smoke.MESSAGE_TOO_LARGE)

    def test_lettura_non_bytes_o_eccezione_sanificata(self):
        class TextResponse(FakeResponse):
            def read(self, _size=-1):
                return "SECRET body"

        class BrokenResponse(FakeResponse):
            def read(self, _size=-1):
                raise TimeoutError("SECRET timeout")

        for response in (TextResponse(), BrokenResponse()):
            with self.subTest(response=type(response).__name__):
                with self.assertRaises(smoke.SmokeFailure) as raised:
                    smoke._read_bounded(response, "health")
                self.assertNotIn("SECRET", str(raised.exception))

    def test_status_fallback_e_status_invalido(self):
        request = urllib.request.Request(BASE)
        opener = ScriptedOpener(lambda _request: FakeResponse(200, b"{}", status_attr=False))
        result = smoke._http_request(
            opener, "GET", BASE, token=None, timeout=1, label="health")
        self.assertEqual(result.status, 200)

        for response in (FakeResponse("200"), type("NoStatus", (), {})()):
            with self.subTest(response=type(response).__name__):
                with self.assertRaises(smoke.SmokeFailure) as raised:
                    smoke._http_request(
                        ScriptedOpener(lambda _request: response), "GET", BASE,
                        token=None, timeout=1, label="health")
                self.assertEqual(raised.exception.message, smoke.MESSAGE_RESPONSE)
        self.assertIsNotNone(request)

    def test_httperror_diventa_status_senza_corpo(self):
        error = urllib.error.HTTPError(
            BASE, 401, "SECRET reason", {}, io.BytesIO(b"SECRET body"))
        opener = ScriptedOpener(lambda _request: error)
        result = smoke._http_request(
            opener, "GET", BASE, token=None, timeout=1, label="health")
        self.assertEqual((result.status, result.body), (401, b""))

    def test_httperror_status_malformato_viene_comunque_chiuso(self):
        body = io.BytesIO(b"SECRET body")
        error = urllib.error.HTTPError(BASE, "invalid", "SECRET reason", {}, body)
        opener = ScriptedOpener(lambda _request: error)

        with self.assertRaises(smoke.SmokeFailure) as raised:
            smoke._http_request(
                opener, "GET", BASE, token=None, timeout=1, label="health")

        self.assertEqual(raised.exception.message, smoke.MESSAGE_REQUEST)
        self.assertTrue(body.closed)
        self.assertNotIn("SECRET", str(raised.exception))

    def test_timeout_connessione_e_url_error_sanificati(self):
        errors = (TimeoutError("SECRET timeout"),
                  ConnectionRefusedError("SECRET refused"),
                  urllib.error.URLError("SECRET dns"))
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(smoke.SmokeFailure) as raised:
                    smoke._http_request(
                        ScriptedOpener(lambda _request: error), "GET", BASE,
                        token=None, timeout=1, label="health")
                self.assertEqual(raised.exception.message, smoke.MESSAGE_REQUEST)
                self.assertNotIn("SECRET", str(raised.exception))

    def test_require_status_e_json_invalido(self):
        with self.assertRaises(smoke.SmokeFailure):
            smoke._require_status(smoke.HttpResponse(302, b""), 200, "health")
        valid = smoke._decode_json(b'{"ok": true}', "health")
        self.assertEqual(valid, {"ok": True})
        for body in (b"not-json", b"\xff", b'{"x": NaN}'):
            with self.subTest(body=body):
                with self.assertRaises(smoke.SmokeFailure) as raised:
                    smoke._decode_json(body, "health")
                self.assertEqual(raised.exception.message, smoke.MESSAGE_RESPONSE)

    def test_chiusura_sempre_e_chiusura_che_fallisce_non_propaga(self):
        response = FakeResponse(200, b"{}")
        smoke._http_request(
            self.opener(response), "GET", BASE, token=None, timeout=1, label="health")
        self.assertTrue(response.closed)

        class BadClose(FakeResponse):
            def close(self):
                raise OSError("SECRET close")

        response = BadClose(200, b"{}")
        smoke._http_request(
            self.opener(response), "GET", BASE, token=None, timeout=1, label="health")


class HealthAndUnauthenticated(unittest.TestCase):
    def test_health_valido_ammette_campi_extra(self):
        smoke._validate_health(dict(HEALTH_OK))

    def test_health_campi_non_validi(self):
        cases = (
            [],
            {},
            {"status": "loading", "model_loaded": True, "device": "cuda"},
            {"status": "ok", "model_loaded": False, "device": "cuda"},
            {"status": "ok", "model_loaded": 1, "device": "cuda"},
            {"status": "ok", "model_loaded": True, "device": "cpu"},
        )
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(smoke.SmokeFailure) as raised:
                    smoke._validate_health(payload)
                self.assertEqual(raised.exception.label, smoke.LABEL_HEALTH)

    def test_check_health_status_corpo_e_json(self):
        cases = (
            FakeResponse(503, b"{}"),
            FakeResponse(200, b"SECRET not-json"),
            FakeResponse(200, b"[]"),
        )
        for response in cases:
            with self.subTest(body=response._body):
                with self.assertRaises(smoke.SmokeFailure) as raised:
                    smoke._check_health(
                        BASE, ScriptedOpener(lambda _request: response), TIMEOUT)
                self.assertEqual(raised.exception.label, smoke.LABEL_HEALTH)
                self.assertNotIn("SECRET", str(raised.exception))
                self.assertTrue(response.closed)

    def test_gate_senza_token(self):
        opener = ScriptedOpener(success_responder)
        smoke._check_unauthenticated(BASE, opener, TIMEOUT)
        self.assertEqual(
            [urllib.parse.urlsplit(request.full_url).path for request, _ in opener.calls],
            ["/api/v1/analyses", "/settings"])
        self.assertTrue(all(header(request, "Authorization") is None
                            for request, _ in opener.calls))
        self.assertEqual([timeout for _, timeout in opener.calls], [TIMEOUT, TIMEOUT])

    def test_gate_analyses_non_401(self):
        opener = ScriptedOpener(lambda _request: FakeResponse(200))
        with self.assertRaises(smoke.SmokeFailure) as raised:
            smoke._check_unauthenticated(BASE, opener, TIMEOUT)
        self.assertEqual(raised.exception.label, smoke.LABEL_ANALYSES_AUTH)
        self.assertEqual(len(opener.calls), 1)

    def test_gate_settings_non_401(self):
        def responder(request):
            path = urllib.parse.urlsplit(request.full_url).path
            return FakeResponse(401 if path == "/api/v1/analyses" else 200)

        with self.assertRaises(smoke.SmokeFailure) as raised:
            smoke._check_unauthenticated(BASE, ScriptedOpener(responder), TIMEOUT)
        self.assertEqual(raised.exception.label, smoke.LABEL_SETTINGS_AUTH)


class AnalysisValidation(unittest.TestCase):
    def test_risposta_valida_json_e_seed(self):
        smoke._validate_analysis(
            analysis_payload(), ("text",), {"[EMAIL_1]": smoke.EMAIL}, "json email")
        seed = analysis_payload(delta={})
        smoke._validate_analysis(seed, ("text",), {}, "json seed reuse")

    def test_risposta_valida_multipart_con_delta_aggregato(self):
        smoke._validate_analysis(
            analysis_payload(("file_1", "text")),
            ("file_1", "text"), {"[EMAIL_1]": smoke.EMAIL}, "multipart aggregate")

    def test_mutazioni_rifiutate_senza_esporre_valori(self):
        def extra_top(payload):
            payload["extra"] = 1

        def wrong_delta_type(payload):
            payload["dictionary_delta"] = []

        def empty_delta(payload):
            payload["dictionary_delta"] = {}

        def wrong_delta_value(payload):
            payload["dictionary_delta"]["[EMAIL_1]"] = "other-secret@example.com"

        def extra_delta(payload):
            payload["dictionary_delta"]["[ORG_1]"] = "other-secret"

        def results_dict(payload):
            payload["results"] = {}

        def no_results(payload):
            payload["results"] = []

        def duplicate_results(payload):
            payload["results"].append(dict(payload["results"][0]))

        def result_not_dict(payload):
            payload["results"][0] = []

        def missing_result_key(payload):
            payload["results"][0].pop("statistics")

        def wrong_input_id(payload):
            payload["results"][0]["input_id"] = "file_1"

        def non_string_text(payload):
            payload["results"][0]["anonymized_text"] = 7

        def raw_email(payload):
            payload["results"][0]["anonymized_text"] = (
                "Contact: [EMAIL_1] runpod-smoke@example.com")

        def no_placeholder(payload):
            payload["results"][0]["anonymized_text"] = "Contact"

        def wrong_placeholder(payload):
            payload["results"][0]["anonymized_text"] = "Contact: [EMAIL_2]"

        def extra_placeholder(payload):
            payload["results"][0]["anonymized_text"] = "[EMAIL_1] [ORG_1]"

        def repeated_placeholder(payload):
            payload["results"][0]["anonymized_text"] = "[EMAIL_1] [EMAIL_1]"

        def statistics_empty(payload):
            payload["results"][0]["statistics"] = {}

        def count_two(payload):
            payload["results"][0]["statistics"]["placeholder_count"] = 2

        def count_bool(payload):
            payload["results"][0]["statistics"]["placeholder_count"] = True

        def statistics_extra(payload):
            payload["results"][0]["statistics"]["extra"] = 1

        mutators = (
            extra_top, wrong_delta_type, empty_delta, wrong_delta_value,
            extra_delta, results_dict, no_results, duplicate_results,
            result_not_dict, missing_result_key, wrong_input_id, non_string_text,
            raw_email, no_placeholder, wrong_placeholder, extra_placeholder,
            repeated_placeholder, statistics_empty, count_two, count_bool,
            statistics_extra,
        )
        for mutator in mutators:
            with self.subTest(mutator=mutator.__name__):
                payload = analysis_payload()
                mutator(payload)
                with self.assertRaises(smoke.SmokeFailure) as raised:
                    smoke._validate_analysis(
                        payload, ("text",), {"[EMAIL_1]": smoke.EMAIL}, "json email")
                self.assertIn(raised.exception.message,
                              (smoke.MESSAGE_RESPONSE, smoke.MESSAGE_CHECK))
                self.assertNotIn(smoke.EMAIL, str(raised.exception))
                self.assertNotIn("other-secret", str(raised.exception))

    def test_multipart_id_mancante_o_delta_doppio(self):
        with self.assertRaises(smoke.SmokeFailure):
            smoke._validate_analysis(
                analysis_payload(("file_1",)), ("file_1", "text"),
                {"[EMAIL_1]": smoke.EMAIL}, "multipart aggregate")

        payload = analysis_payload(("file_1", "text"))
        payload["dictionary_delta"]["[EMAIL_2]"] = "other-secret@example.com"
        with self.assertRaises(smoke.SmokeFailure) as raised:
            smoke._validate_analysis(
                payload, ("file_1", "text"),
                {"[EMAIL_1]": smoke.EMAIL}, "multipart aggregate")
        self.assertNotIn("other-secret", str(raised.exception))

    def test_post_json_rifiuta_status_e_json_non_validi(self):
        for response in (FakeResponse(500, b"SECRET body"),
                         FakeResponse(200, b"SECRET not-json")):
            with self.subTest(status=response._status, body=response._body):
                opener = ScriptedOpener(lambda _request: response)
                with self.assertRaises(smoke.SmokeFailure) as raised:
                    smoke._post_json(
                        BASE, opener, TOKEN, TIMEOUT, {"text": smoke.JSON_TEXT},
                        ("text",), {"[EMAIL_1]": smoke.EMAIL}, smoke.LABEL_JSON)
                self.assertEqual(raised.exception.label, smoke.LABEL_JSON)
                self.assertNotIn("SECRET", str(raised.exception))


class SuccessSequence(unittest.TestCase):
    def test_sequenza_completa_e_richieste(self):
        opener = ScriptedOpener(success_responder)
        passed = []
        smoke.run_smoke(
            BASE, TOKEN, opener=opener, timeout=TIMEOUT, on_pass=passed.append)

        self.assertEqual(passed, [
            smoke.PASS_HEALTH,
            smoke.PASS_ANALYSES_AUTH,
            smoke.PASS_SETTINGS_AUTH,
            smoke.PASS_JSON,
            smoke.PASS_SEED,
            smoke.PASS_MULTIPART,
        ])
        self.assertEqual(len(opener.calls), 6)
        paths = [urllib.parse.urlsplit(request.full_url).path
                 for request, _ in opener.calls]
        self.assertEqual(paths, [
            "/health", "/api/v1/analyses", "/settings",
            "/api/v1/analyses", "/api/v1/analyses", "/api/v1/analyses",
        ])
        self.assertEqual([timeout for _, timeout in opener.calls], [TIMEOUT] * 6)

        requests = [request for request, _ in opener.calls]
        for request in requests:
            self.assertNotIn("?", request.full_url)
            self.assertNotIn("#", request.full_url)
            self.assertNotIn(TOKEN, request.full_url)
        self.assertEqual(
            [header(request, "Authorization") for request in requests],
            [None, None, None, "Bearer " + TOKEN, "Bearer " + TOKEN,
             "Bearer " + TOKEN])

        json_payload = json.loads(requests[3].data.decode("utf-8"))
        self.assertEqual(json_payload["categories"], ["EMAIL"])
        self.assertEqual(json_payload["text"], smoke.JSON_TEXT)
        self.assertNotIn("dictionary", json_payload)

        seed_payload = json.loads(requests[4].data.decode("utf-8"))
        self.assertEqual(seed_payload["dictionary"], {"[EMAIL_1]": smoke.EMAIL})
        self.assertEqual(seed_payload["categories"], ["EMAIL"])

        multipart = requests[5]
        self.assertTrue(header(multipart, "Content-Type").startswith(
            "multipart/form-data; boundary="))
        body = multipart.data
        self.assertIn(b'name="files"', body)
        self.assertIn(f'filename="{smoke.MULTIPART_FILENAME}"'.encode("ascii"), body)
        self.assertIn(b'name="text"', body)
        self.assertIn(b'name="categories"', body)
        self.assertIn(b'["EMAIL"]', body)
        self.assertEqual(body.count(smoke.EMAIL.encode("ascii")), 2)

    def test_main_stampa_solo_etichette_e_non_espone_dati(self):
        opener = ScriptedOpener(success_responder)
        out, err = io.StringIO(), io.StringIO()
        rc = smoke.main(
            ["--url", BASE, "--timeout", str(TIMEOUT)], opener=opener,
            environ={smoke.TOKEN_ENV: TOKEN}, stdout=out, stderr=err)

        self.assertEqual(rc, 0)
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(out.getvalue().splitlines(), [
            smoke.PASS_HEALTH,
            smoke.PASS_ANALYSES_AUTH,
            smoke.PASS_SETTINGS_AUTH,
            smoke.PASS_JSON,
            smoke.PASS_SEED,
            smoke.PASS_MULTIPART,
            smoke.PASS_FINAL,
        ])
        combined = out.getvalue() + err.getvalue()
        for secret in (TOKEN, smoke.EMAIL, smoke.MULTIPART_FILENAME,
                       "must-not-be-printed", smoke.BOUNDARY, BASE,
                       "dictionary_delta"):
            self.assertNotIn(secret, combined)

    def test_nessun_retry_su_errore_o_429(self):
        for status in (429, 500):
            with self.subTest(status=status):
                def responder(request, failing_status=status):
                    path = urllib.parse.urlsplit(request.full_url).path
                    if path == "/health":
                        return FakeResponse(200, json.dumps(HEALTH_OK).encode())
                    if path == "/settings":
                        return FakeResponse(401)
                    if path == "/api/v1/analyses":
                        if header(request, "Authorization") is None:
                            return FakeResponse(401)
                        return FakeResponse(failing_status, b"SECRET body")
                    return FakeResponse(404)

                opener = ScriptedOpener(responder)
                with self.assertRaises(smoke.SmokeFailure) as raised:
                    smoke.run_smoke(BASE, TOKEN, opener=opener, timeout=TIMEOUT)
                self.assertEqual(raised.exception.label, smoke.LABEL_JSON)
                self.assertEqual(len(opener.calls), 4)
                self.assertNotIn("SECRET", str(raised.exception))

    def test_health_oversize_redirect_cpu_e_json_rotto(self):
        cases = (
            (FakeResponse(200, b"x" * (smoke.MAX_RESPONSE_BYTES + 1)),
             smoke.MESSAGE_TOO_LARGE),
            (FakeResponse(302, b""), smoke.MESSAGE_CHECK),
            (FakeResponse(200, json.dumps({**HEALTH_OK, "device": "cpu"}).encode()),
             smoke.MESSAGE_CHECK),
            (FakeResponse(200, b"SECRET not-json"), smoke.MESSAGE_RESPONSE),
        )
        for response, message in cases:
            with self.subTest(message=message, status=response._status):
                opener = ScriptedOpener(lambda _request, r=response: r)
                with self.assertRaises(smoke.SmokeFailure) as raised:
                    smoke.run_smoke(BASE, TOKEN, opener=opener, timeout=TIMEOUT)
                self.assertEqual(raised.exception.label, smoke.LABEL_HEALTH)
                self.assertEqual(raised.exception.message, message)
                self.assertEqual(len(opener.calls), 1)
                self.assertNotIn("SECRET", str(raised.exception))


class SanitizedFailures(unittest.TestCase):
    def test_eccezione_dell_opener_non_espone_il_token(self):
        def responder(_request):
            return RuntimeError(f"SECRET {TOKEN}")

        out, err = io.StringIO(), io.StringIO()
        rc = smoke.main(
            ["--url", BASE], opener=ScriptedOpener(responder),
            environ={smoke.TOKEN_ENV: TOKEN}, stdout=out, stderr=err)
        self.assertEqual(rc, 1)
        combined = out.getvalue() + err.getvalue()
        self.assertIn(f"FAIL {smoke.LABEL_HEALTH}: {smoke.MESSAGE_REQUEST}", combined)
        self.assertNotIn(TOKEN, combined)
        self.assertNotIn("SECRET", combined)

    def test_corpo_invalido_con_pii_non_viene_stampato(self):
        body = json.dumps({
            "status": "ok", "model_loaded": True, "device": "cpu",
            "model": TOKEN, "secret": smoke.EMAIL,
        }).encode("utf-8")
        out, err = io.StringIO(), io.StringIO()
        rc = smoke.main(
            ["--url", BASE],
            opener=ScriptedOpener(lambda _request: FakeResponse(200, body)),
            environ={smoke.TOKEN_ENV: TOKEN}, stdout=out, stderr=err)
        self.assertEqual(rc, 1)
        combined = out.getvalue() + err.getvalue()
        self.assertNotIn(TOKEN, combined)
        self.assertNotIn(smoke.EMAIL, combined)
        self.assertNotIn("SECRET", combined)

    def test_configurazione_non_usa_la_rete(self):
        opener = FailOpener()
        cases = (
            (["--url", BASE], {}),
            (["--url", f"https://user:{TOKEN}@example.test"],
             {smoke.TOKEN_ENV: TOKEN}),
            (["--url", f"https://example.test/?token={TOKEN}"],
             {smoke.TOKEN_ENV: TOKEN}),
            (["--url", BASE], {smoke.TOKEN_ENV: "abc\nInjected"}),
        )
        for argv, environ in cases:
            with self.subTest(argv=argv, environ=environ):
                out, err = io.StringIO(), io.StringIO()
                rc = smoke.main(
                    argv, opener=opener, environ=environ, stdout=out, stderr=err)
                self.assertEqual(rc, 1)
                combined = out.getvalue() + err.getvalue()
                self.assertNotIn(TOKEN, combined)
                self.assertNotIn("Injected", combined)
                self.assertNotIn("example.test", combined)
        self.assertEqual(opener.calls, 0)

    def test_eccezione_imprevista_sanificata(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(smoke, "run_smoke",
                          side_effect=RuntimeError(f"{TOKEN} SECRET")):
            rc = smoke.main(
                ["--url", BASE], environ={smoke.TOKEN_ENV: TOKEN},
                stdout=out, stderr=err)
        self.assertEqual(rc, 1)
        combined = out.getvalue() + err.getvalue()
        self.assertIn(smoke.MESSAGE_INTERNAL, combined)
        self.assertNotIn(TOKEN, combined)
        self.assertNotIn("SECRET", combined)


class RedirectNotFollowed(unittest.TestCase):
    def test_redirect_non_seguito_e_token_non_inoltrato(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.server.seen.append(
                    (self.path, self.headers.get("Authorization")))
                if self.path == "/health":
                    self.send_response(302)
                    self.send_header("Location", "/captured")
                    self.end_headers()
                    return
                body = b'{"status":"ok","model_loaded":true,"device":"cuda"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        server.seen = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            result = smoke._http_request(
                smoke.build_opener(), "GET", base + "/health", token=TOKEN,
                timeout=2.0, label=smoke.LABEL_HEALTH)
            self.assertEqual(result.status, 302)
            self.assertEqual(server.seen, [("/health", "Bearer " + TOKEN)])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())


class CliSubprocess(unittest.TestCase):
    def run_cli(self, args, env_extra=None):
        env = os.environ.copy()
        env.pop(smoke.TOKEN_ENV, None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=20)

    def test_help_e_import_senza_rete(self):
        result = self.run_cli(["--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("--url", result.stdout)
        self.assertIn("--timeout", result.stdout)
        self.assertNotIn("--token", result.stdout)

        imported = subprocess.run(
            [sys.executable, "-c", "import smoke_cloud; print('OK')"],
            cwd=str(ROOT / "src" / "app"),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, text=True, timeout=20)
        self.assertEqual(imported.returncode, 0)
        self.assertEqual(imported.stdout.strip(), "OK")

    def test_token_mancante_o_passato_da_cli(self):
        missing = self.run_cli(["--url", BASE])
        self.assertEqual(missing.returncode, 1)
        combined = missing.stdout + missing.stderr
        self.assertIn(smoke.MESSAGE_TOKEN_MISSING, combined)
        self.assertNotIn(BASE, combined)

        cli_token = self.run_cli(["--url", BASE, "--token", TOKEN])
        self.assertEqual(cli_token.returncode, 2)
        combined = cli_token.stdout + cli_token.stderr
        self.assertIn("configuration error", combined)
        self.assertNotIn(TOKEN, combined)
        self.assertNotIn(BASE, combined)

    def test_argomenti_invalidi_non_ripetono_il_segreto(self):
        unknown = self.run_cli(
            ["--url", BASE, "--api-token", "super-secret-value"])
        self.assertEqual(unknown.returncode, 2)
        combined = unknown.stdout + unknown.stderr
        self.assertNotIn("super-secret-value", combined)
        self.assertNotIn("Traceback", combined)
        self.assertIn("configuration error", combined)

        bad_timeout = self.run_cli(["--url", BASE, "--timeout", "0"])
        self.assertEqual(bad_timeout.returncode, 2)
        self.assertIn("configuration error", bad_timeout.stderr)
        self.assertNotIn("Traceback", bad_timeout.stderr)


if __name__ == "__main__":
    unittest.main()
