# -*- coding: utf-8 -*-
"""Guardrail API v1: timeout server e file opzionali (ENVAS-23).

Copre `PII_ANALYSIS_TIMEOUT_SECONDS` (default 60 s), il budget congelato una
volta per richiesta, i confini 200/504 sugli arm JSON e multipart, e la
regressione dei file opzionali: un `text` senza file funziona senza extractor,
mentre file presenti vuoti o malformati restano errori. Flask/Werkzeug si
saltano solo se mancano, come nella suite dichiarata; nessun peso, nessuna
rete, nessun server. Tutti i valori sono SINTETICI.
"""

import ast
import json
import logging
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "app"))

import guardrail_api  # noqa: E402
import guardrail_inputs  # noqa: E402

HAVE_NATIVE = guardrail_inputs.native_multipart_available()

try:
    from flask import Flask
    HAVE_FLASK = True
except ImportError:
    Flask = None
    HAVE_FLASK = False

TOKEN = "timeout-token"
AUTH = {"Authorization": "Bearer " + TOKEN}
JSON_CT = {"Content-Type": "application/json"}
PATH = "/api/v1/analyses"
APP_SRC = ROOT / "src" / "app" / "app.py"
BOUND = "BOUND"
ENV = "PII_ANALYSIS_TIMEOUT_SECONDS"
DEFAULT = 60.0


def _tag_names():
    tree = ast.parse(APP_SRC.read_text(encoding="utf-8"))
    namespace = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(target, "id", "") in ("TAGS", "TAG_NAMES")
                for target in node.targets):
            exec(compile(ast.Module([node], []), "app.py", "exec"), namespace)
    return namespace["TAG_NAMES"]


TAGS = _tag_names()


def _detect_none(_text, _check):
    return []


def _advance(clock, value):
    def detect(_text, check):
        clock.now = value
        check()
        return []
    return detect


def _extract_utf8(_name, data, _remaining, _check):
    return data.decode("utf-8")


def _body(parts, boundary=BOUND):
    """Corpo multipart grezzo: parts = [(name, filename_o_None, bytes|str)]."""
    chunks = []
    for name, filename, data in parts:
        head = 'Content-Disposition: form-data; name="%s"' % name
        if filename is not None:
            head += '; filename="%s"' % filename
        chunks.append(("--%s\r\n%s\r\n\r\n" % (boundary, head)).encode("utf-8"))
        chunks.append(data if isinstance(data, bytes) else data.encode("utf-8"))
        chunks.append(b"\r\n")
    chunks.append(("--%s--\r\n" % boundary).encode("ascii"))
    return b"".join(chunks)


def _make_client(detect=_detect_none, extract=_extract_utf8, clock=None):
    lock = threading.Lock()
    application = Flask("guardrail-timeout-test")
    application.config["TESTING"] = True
    application.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
    kwargs = {"clock": clock} if clock is not None else {}
    blueprint = guardrail_api.create_blueprint(TAGS, detect, lock=lock,
                                               extract=extract, **kwargs)
    application.register_blueprint(blueprint)
    return application.test_client(), lock


class Clock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


class _IsolatedEnv(unittest.TestCase):
    """Env vuoto e ripristinato: nessun valore ambientale entra nei test."""

    def setUp(self):
        self._env = patch.dict(os.environ, {}, clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)


class EnvTimeout(_IsolatedEnv):
    """Resolver: lettura singola, fallback sicuro, nessun echo dei valori."""

    def resolve(self, value):
        os.environ.pop(ENV, None)
        if value is not None:
            os.environ[ENV] = value
        return guardrail_api._resolve_deadline_seconds()

    def test_default_esplicito_sessanta(self):
        self.assertEqual(guardrail_api.DEFAULT_DEADLINE_SECONDS, DEFAULT)
        self.assertEqual(self.resolve(None), DEFAULT)

    def test_blank_e_malformati_tornano_al_default(self):
        for value in ("", "   ", "\t\n", "abc", "60s", "1,5", "1.2.3",
                      "0x10", "--1", "1e", "sessanta"):
            with self.subTest(value=value):
                self.assertEqual(self.resolve(value), DEFAULT)

    def test_non_positivi_tornano_al_default(self):
        for value in ("0", "0.0", "-0", "-1", "-0.5", "1e-999"):
            with self.subTest(value=value):
                self.assertEqual(self.resolve(value), DEFAULT)

    def test_non_finiti_e_overflow_tornano_al_default(self):
        for value in ("nan", "NaN", "+nan", "-nan", "inf", "+inf", "-inf",
                      "Infinity", "-Infinity", "1e999", "-1e999", "1e309"):
            with self.subTest(value=value):
                self.assertEqual(self.resolve(value), DEFAULT)

    def test_positivi_interi_e_decimali_accettati(self):
        for value, expected in (("1", 1.0), ("5", 5.0), ("60", 60.0),
                                ("90", 90.0), ("120", 120.0), ("+61", 61.0),
                                ("0.5", 0.5), ("2.75", 2.75),
                                ("60.0", 60.0), (" 61 ", 61.0)):
            with self.subTest(value=value):
                self.assertEqual(self.resolve(value), expected)


class TimeoutGuardCore(_IsolatedEnv):
    """process_request, arm JSON: default, override, freeze e sanitizzazione."""

    def setUp(self):
        super().setUp()
        self.lock = threading.Lock()

    def call(self, *, clock, detect=_detect_none, payload=None, reader=None,
             token=TOKEN):
        headers = dict(JSON_CT)
        headers.update(AUTH)
        if reader is None:
            raw = json.dumps(payload if payload is not None
                             else {"text": "Mario"}).encode("utf-8")
        else:
            raw = reader
        return guardrail_api.process_request(
            headers, raw, token=token, tags=TAGS, detect=detect, clock=clock,
            lock=self.lock)

    def test_31_secondi_sotto_il_default_passano(self):
        clock = Clock()
        status, body = self.call(clock=clock, detect=_advance(clock, 31.0))
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"], "Mario")

    def test_60_esatto_al_confine_passa(self):
        clock = Clock()
        status, body = self.call(clock=clock, detect=_advance(clock, 60.0))
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"], "Mario")

    def test_61_secondi_oltre_il_default_504(self):
        clock = Clock()
        status, body = self.call(clock=clock, detect=_advance(clock, 61.0))
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")

    def test_env_corto_5_respinge_a_6(self):
        os.environ[ENV] = "5"
        clock = Clock()
        status, body = self.call(clock=clock, detect=_advance(clock, 6.0))
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")

    def test_env_lungo_120_accetta_61(self):
        os.environ[ENV] = "120"
        clock = Clock()
        status, _body = self.call(clock=clock, detect=_advance(clock, 61.0))
        self.assertEqual(status, 200)

    def test_env_lungo_120_respinge_a_121(self):
        os.environ[ENV] = "120"
        clock = Clock()
        status, body = self.call(clock=clock, detect=_advance(clock, 121.0))
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")

    def test_env_decimale_usata_come_tale(self):
        os.environ[ENV] = "2.5"
        clock = Clock()
        status, _body = self.call(clock=clock, detect=_advance(clock, 2.5))
        self.assertEqual(status, 200)
        clock = Clock()
        status, body = self.call(clock=clock, detect=_advance(clock, 2.6))
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")

    def test_env_invalida_non_disattiva_la_deadline(self):
        os.environ[ENV] = "abc"
        clock = Clock()
        status, _body = self.call(clock=clock, detect=_advance(clock, 31.0))
        self.assertEqual(status, 200)
        clock = Clock()
        status, body = self.call(clock=clock, detect=_advance(clock, 61.0))
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")

    def test_campi_timeout_nel_json_400(self):
        calls = []
        for field in ("timeout_seconds", "timeout", "analysis_timeout_seconds"):
            payload = {"text": "Mario", field: 120}
            status, body = self.call(
                clock=Clock(), payload=payload,
                detect=lambda *_args: calls.append(1) or [])
            self.assertEqual(status, 400, field)
            self.assertEqual(body["code"], "invalid_request")
        self.assertEqual(calls, [])

    def test_delay_lettura_body_non_addebitato(self):
        clock = Clock()

        def reader(_cap):
            clock.now = 1000.0
            return b'{"text":"Mario"}'

        status, _body = self.call(clock=clock, reader=reader,
                                  detect=_advance(clock, 1059.0))
        self.assertEqual(status, 200)

    def test_budget_parte_dopo_la_lettura(self):
        clock = Clock()

        def reader(_cap):
            clock.now = 1000.0
            return b'{"text":"Mario"}'

        status, body = self.call(clock=clock, reader=reader,
                                 detect=_advance(clock, 1061.0))
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")

    def test_env_snapshot_e_cambi_a_meta_richiesta_non_estendono(self):
        os.environ[ENV] = "5"
        clock = Clock()

        def detect(_text, check):
            clock.now = 6.0
            os.environ[ENV] = "120"
            check()
            return []

        status, body = self.call(clock=clock, detect=detect)
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")
        self.assertEqual(os.environ[ENV], "120")

        os.environ[ENV] = "120"
        clock = Clock()

        def short_detect(_text, check):
            clock.now = 61.0
            os.environ[ENV] = "5"
            check()
            return []

        status, _body = self.call(clock=clock, detect=short_detect)
        self.assertEqual(status, 200)

    def test_resolver_letto_una_volta_per_richiesta(self):
        clock = Clock()
        with patch.object(guardrail_api, "_resolve_deadline_seconds",
                          wraps=guardrail_api._resolve_deadline_seconds) as resolver:
            status, _body = self.call(clock=clock,
                                      detect=_advance(clock, 31.0))
            self.assertEqual(status, 200)
            self.assertEqual(resolver.call_count, 1)
            clock = Clock()
            status, _body = self.call(clock=clock,
                                      detect=_advance(clock, 31.0))
            self.assertEqual(status, 200)
        self.assertEqual(resolver.call_count, 2)

    def test_504_sanificato_senza_output_parziali_o_segreti(self):
        os.environ[ENV] = "7.25"
        clock = Clock()

        class Capture(logging.Handler):
            def __init__(self):
                super().__init__()
                self.messages = []

            def emit(self, record):
                self.messages.append(record.getMessage())

        capture = Capture()
        root = logging.getLogger()
        root.addHandler(capture)
        try:
            def detect(_text, check):
                clock.now = 7.3
                check()
                return []

            status, body = self.call(clock=clock, detect=detect,
                                     payload={"text": "SEGRETO-PII-123"})
        finally:
            root.removeHandler(capture)
        self.assertEqual(status, 504)
        self.assertEqual(body, {"error": "Deadline exceeded.",
                                "code": "deadline_exceeded"})
        encoded = json.dumps(body)
        for secret in ("SEGRETO-PII-123", TOKEN, "7.25"):
            self.assertNotIn(secret, encoded)
        self.assertFalse(self.lock.locked())
        joined = "\n".join(capture.messages)
        self.assertNotIn("SEGRETO-PII-123", joined)

    def test_token_blank_503_anche_con_timeout_impostato(self):
        os.environ[ENV] = "120"
        status, body = self.call(clock=Clock(), token="   ")
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "unavailable")
        self.assertFalse(self.lock.locked())


@unittest.skipUnless(HAVE_NATIVE, "Werkzeug assente: parser multipart non disponibile")
class TimeoutGuardMultipart(_IsolatedEnv):
    """Arm multipart: budget globale, file opzionali, errori non soppressi."""

    def setUp(self):
        super().setUp()
        self.lock = threading.Lock()

    def call(self, raw, *, clock, extract=_extract_utf8, detect=_detect_none):
        headers = dict(AUTH)
        headers["Content-Type"] = "multipart/form-data; boundary=" + BOUND
        return guardrail_api.process_request(
            headers, raw, token=TOKEN, tags=TAGS, detect=detect, extract=extract,
            clock=clock, lock=self.lock)

    def test_budget_condiviso_tra_input_multipli(self):
        os.environ[ENV] = "10"
        clock = Clock()
        calls = []

        def detect(text, check):
            calls.append(text)
            clock.now = 6.0 if len(calls) == 1 else 11.0
            check()
            return []

        raw = _body([("files", "a.txt", "uno"), ("files", "b.txt", "due")])
        status, body = self.call(raw, clock=clock, detect=detect)
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.lock.locked())

    def test_tempo_di_estrazione_nel_budget_condiviso(self):
        os.environ[ENV] = "10"
        clock = Clock()

        def extract(_name, data, _remaining, _check):
            clock.now = 6.0
            return data.decode("utf-8")

        status, body = self.call(
            _body([("files", "a.txt", "uno"), ("text", None, "due")]),
            clock=clock, extract=extract, detect=_advance(clock, 11.0))
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")

    def test_text_only_con_seed_senza_extractor(self):
        raw = _body([
            ("dictionary", None, '{"[FULLNAME_7]": "Mario Rossi"}'),
            ("text", None, "Mario Rossi"),
        ])
        status, body = self.call(raw, clock=Clock(), extract=None)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["input_id"], "text")
        self.assertEqual(body["results"][0]["anonymized_text"], "[FULLNAME_7]")
        self.assertEqual(body["dictionary_delta"], {})

    def test_text_only_senza_seed_senza_extractor(self):
        status, body = self.call(_body([("text", None, "solo testo")]),
                                 clock=Clock(), extract=None)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["input_id"], "text")
        self.assertEqual(body["results"][0]["anonymized_text"], "solo testo")

    def test_dizionario_solo_e_text_blank_400(self):
        for raw in (_body([("dictionary", None, "{}")]),
                    _body([("text", None, "   ")])):
            status, body = self.call(raw, clock=Clock())
            self.assertEqual(status, 400)
            self.assertEqual(body["code"], "invalid_request")
            self.assertFalse(self.lock.locked())

    def test_file_vuoto_presente_422_senza_soppressione(self):
        calls = []

        def extract(_name, data, _remaining, _check):
            if not data:
                raise guardrail_inputs.InputError(422, "empty_file")
            return data.decode("utf-8")

        raw = _body([("files", "vuoto.txt", b""), ("text", None, "ciao")])
        status, body = self.call(raw, clock=Clock(), extract=extract,
                                 detect=lambda *_args: calls.append(1) or [])
        self.assertEqual(status, 422)
        self.assertEqual(body, {"error": "File is empty.", "code": "empty_file"})
        self.assertEqual(calls, [])
        self.assertFalse(self.lock.locked())

    def test_file_malformato_presente_422_senza_soppressione(self):
        calls = []

        def extract(_name, _data, _remaining, _check):
            raise guardrail_inputs.InputError(422, "unreadable_file")

        raw = _body([("files", "rotto.pdf", b"%PDF-rotto"),
                     ("text", None, "ciao")])
        status, body = self.call(raw, clock=Clock(), extract=extract,
                                 detect=lambda *_args: calls.append(1) or [])
        self.assertEqual(status, 422)
        self.assertEqual(body["code"], "unreadable_file")
        self.assertEqual(calls, [])
        self.assertFalse(self.lock.locked())

    def test_campo_timeout_multipart_400(self):
        raw = _body([("timeout_seconds", None, "120"), ("text", None, "x")])
        status, body = self.call(raw, clock=Clock())
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")


@unittest.skipUnless(HAVE_NATIVE and HAVE_FLASK,
                     "Flask/Werkzeug assenti: HTTP multipart non testabile")
class TimeoutHTTP(unittest.TestCase):
    """Flask test client, Werkzeug nativo, modello finto: nessun peso reale."""

    def setUp(self):
        self._env = patch.dict(os.environ, {"PII_API_TOKEN": TOKEN}, clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)

    def post(self, raw, client,
             content_type="multipart/form-data; boundary=" + BOUND):
        return client.post(PATH, data=raw, content_type=content_type,
                           headers=dict(AUTH))

    def test_504_http_no_store_sanificato_e_lock_rilasciato(self):
        clock = Clock()
        client, lock = _make_client(detect=_advance(clock, 61.0), clock=clock)
        response = self.post(_body([("text", None, "Mario")]), client)
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.get_json()["code"], "deadline_exceeded")
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(set(response.get_json()), {"error", "code"})
        self.assertNotIn(TOKEN, response.get_data(as_text=True))
        self.assertFalse(lock.locked())

    def test_env_120_http_61_passa(self):
        os.environ[ENV] = "120"
        clock = Clock()
        client, _lock = _make_client(detect=_advance(clock, 61.0), clock=clock)
        response = self.post(_body([("text", None, "Mario")]), client)
        self.assertEqual(response.status_code, 200)

    def test_env_5_http_6_504(self):
        os.environ[ENV] = "5"
        clock = Clock()
        client, _lock = _make_client(detect=_advance(clock, 6.0), clock=clock)
        response = self.post(_body([("text", None, "Mario")]), client)
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.get_json()["code"], "deadline_exceeded")

    def test_text_only_con_seed_http_senza_extractor(self):
        client, _lock = _make_client(extract=None)
        raw = _body([
            ("dictionary", None, '{"[FULLNAME_7]": "Mario Rossi"}'),
            ("text", None, "Mario Rossi"),
        ])
        response = self.post(raw, client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["anonymized_text"],
                         "[FULLNAME_7]")

    def test_text_only_senza_seed_http_senza_extractor(self):
        client, _lock = _make_client(extract=None)
        response = self.post(_body([("text", None, "solo testo")]), client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["input_id"], "text")

    def test_dizionario_solo_e_text_blank_http_400(self):
        client, lock = _make_client()
        for raw in (_body([("dictionary", None, "{}")]),
                    _body([("text", None, "   ")])):
            response = self.post(raw, client)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["code"], "invalid_request")
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")
            self.assertFalse(lock.locked())

    def test_campo_timeout_http_400(self):
        client, _lock = _make_client()
        raw = _body([("timeout_seconds", None, "120"), ("text", None, "x")])
        response = self.post(raw, client)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
