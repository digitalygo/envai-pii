# -*- coding: utf-8 -*-
"""Guardrail API ENVAS-23 (`src/app/guardrail_api.py` + adapter in app.py).

Tre livelli, in ordine di dipendenze:
  - AppAdapter: il vero `_guardrail_detect` di app.py, ritagliato dal sorgente con
    `ast` come fanno gli altri test della repo: nessun import di torch/flask.
  - PureCore: `process_request()`, il cuore HTTP-agnostico: envelope, JSON severo,
    auth, limiti, lock, deadline, errori sanificati. Gira senza Flask.
  - FlaskEndpoint / AppWiring: integrazione col test_client e con l'app legacy.
    Questi girano solo se Flask c'e' (in CI la suite non installa nulla); il
    contratto no-store e i codici HTTP si verificano li'.

Nessun test scarica pesi o importa torch/transformers/fitz per davvero.
Tutti i valori sono SINTETICI.
"""

import ast
import json
import logging
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "app"))

import guardrail_api  # noqa: E402
import guardrail_inputs  # noqa: E402
import runtime_execution

try:
    from flask import Flask
    HAVE_FLASK = True
except ImportError:                                  # CI senza install
    Flask = None
    HAVE_FLASK = False

TOKEN = "s3cr3t-token"
AUTH = {"Authorization": "Bearer " + TOKEN}
JSON_CT = {"Content-Type": "application/json"}
PATH = "/api/v1/analyses"
APP_SRC = ROOT / "src" / "app" / "app.py"


def _tag_names():
    """I TAG_NAMES reali, letti da app.py con ast (app non e' importabile senza torch)."""
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


def _boom(_text, _check):
    raise RuntimeError("SECRET-document-value")


def detect_literals(*specs):
    """Rilevatore finto: (letterale, label) su offset locali del tratto."""
    def detect(text, _check):
        out = []
        for literal, label in specs:
            position = 0
            while True:
                found = text.find(literal, position)
                if found < 0:
                    break
                out.append({"label": label, "start": found, "end": found + len(literal),
                            "score": 0.9, "validated": False, "source": "modello"})
                position = found + 1
        return out
    return detect


class Clock:
    """Clock monotono finto: i test avanzano `now` a mano."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


# --------------------------------------------------------------------------- #
# Adapter di app.py, senza importare app
# --------------------------------------------------------------------------- #
def _load_adapter():
    tree = ast.parse(APP_SRC.read_text(encoding="utf-8"))
    function = next((node for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name == "_guardrail_detect"),
                    None)
    if function is None:
        raise AssertionError("_guardrail_detect non trovata in app.py")
    namespace = {"runtime_execution": runtime_execution}
    exec(compile(ast.Module([function], []), "app.py", "exec"), namespace)
    return namespace


class AppAdapter(unittest.TestCase):
    """Il codice che viene spedito: un chunk per chiamata, deadline tra i chunk."""

    def setUp(self):
        self.ns = _load_adapter()
        self.calls = {"nlp": [], "regex": [], "merge": [], "complete": [], "checks": 0}

    def _wire(self, chunks, nlp_results):
        def nlp(inputs):
            self.calls["nlp"].append(list(inputs))
            index = len(self.calls["nlp"]) - 1
            return [nlp_results[index]]

        def detect_regex(text):
            self.calls["regex"].append(text)
            return [{"label": "URL", "start": 0, "end": 1, "score": 1.0,
                     "validated": True, "source": "regex"}]

        def complete_time(ents, text):
            self.calls["complete"].append(text)
            return ents

        def merge(cands, text):
            self.calls["merge"].append((list(cands), text))
            return cands

        def check():
            self.calls["checks"] += 1

        self.ns.update({
            "guardrail_api": guardrail_api,
            "nlp": nlp,
            "chunk_text": lambda _text: list(chunks),
            "detect_regex": detect_regex,
            "complete_time": complete_time,
            "_merge": merge,
        })
        return self.ns["_guardrail_detect"], check

    def test_un_chunk_per_chiamata_e_offset_globali(self):
        detect, check = self._wire(
            [("aaaa", 0), ("bbbb", 5)],
            [[{"entity_group": "FULLNAME", "start": 0, "end": 2, "score": 0.9}],
             [{"entity_group": "EMAIL", "start": 0, "end": 3, "score": 0.8}]])
        out = detect("aaaa bbbb", check)
        self.assertEqual(self.calls["nlp"], [["aaaa"], ["bbbb"]])
        self.assertGreaterEqual(self.calls["checks"], 2)
        self.assertEqual(self.calls["complete"], ["aaaa bbbb"])
        self.assertEqual(self.calls["regex"], ["aaaa bbbb"])
        self.assertEqual([(e["label"], e["start"], e["end"]) for e in out],
                         [("FULLNAME", 0, 2), ("EMAIL", 5, 8), ("URL", 0, 1)])
        cands, merged_text = self.calls["merge"][0]
        self.assertEqual(merged_text, "aaaa bbbb")
        self.assertEqual([c["label"] for c in cands], ["FULLNAME", "EMAIL", "URL"])

    def test_modello_assente_solleva_model_unavailable(self):
        detect, check = self._wire([("x", 0)], [[]])
        self.ns["nlp"] = None
        with self.assertRaises(guardrail_api.ModelUnavailable):
            detect("x", check)

    def test_deadline_controllata_subito_dopo_la_chiamata_nlp(self):
        events = []
        self.ns.update({
            "guardrail_api": guardrail_api,
            "nlp": lambda _inputs: (events.append("nlp") or [[]]),
            "chunk_text": lambda _text: [("x", 0)],
            "complete_time": lambda _ents, _text: events.append("complete"),
            "detect_regex": lambda _text: events.append("regex"),
            "_merge": lambda _cands, _text: [],
        })

        def check():
            events.append("check")
            if "nlp" in events:
                raise RuntimeError("deadline")

        with self.assertRaises(RuntimeError):
            self.ns["_guardrail_detect"]("x", check)
        self.assertEqual(events, ["check", "check", "nlp", "check"])

    def test_risultato_flat_di_un_singolo_chunk(self):
        def nlp(_inputs):
            return [{"entity_group": "EMAIL", "start": 0, "end": 1, "score": 0.5}]

        detect, _check = self._wire([("x", 0)], [[]])
        self.ns["nlp"] = nlp
        out = detect("x", lambda: None)
        self.assertEqual([(e["label"], e["start"], e["end"]) for e in out],
                         [("EMAIL", 0, 1), ("URL", 0, 1)])

    def test_risultato_dict_di_un_singolo_chunk(self):
        detect, _check = self._wire([("x", 0)], [[]])
        self.ns["nlp"] = lambda _inputs: {
            "entity_group": "EMAIL", "start": 0, "end": 1, "score": 0.5}
        out = detect("x", lambda: None)
        self.assertEqual([(e["label"], e["start"], e["end"]) for e in out],
                         [("EMAIL", 0, 1), ("URL", 0, 1)])

    def test_app_registra_la_guardrail(self):
        tree = ast.parse(APP_SRC.read_text(encoding="utf-8"))
        found = False
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "register_app"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "guardrail_api"
                    and any(keyword.arg == "tags"
                            and getattr(keyword.value, "id", "") == "TAG_NAMES"
                            for keyword in node.keywords)):
                found = True
        self.assertTrue(found, "app.py non registra guardrail_api con i TAG_NAMES reali")


# --------------------------------------------------------------------------- #
# Cuore della richiesta, senza Flask
# --------------------------------------------------------------------------- #
class PureCore(unittest.TestCase):
    def setUp(self):
        self.lock = threading.Lock()
        # Igiene del test: la env del server non deve cambiare il default
        # locale (60 s) di questi clock.
        patcher = patch.dict(os.environ, {
            "PII_ANALYSIS_TIMEOUT_SECONDS": "",
            "PII_MAX_SEED_ENTRIES": "",
            "PII_MAX_ORIGINAL_CHARS": "",
            "PII_MAX_AGGREGATE_CHARS": "",
            "PII_MAX_JSON_BODY_BYTES": "",
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, payload=None, raw=None, headers=None, token=TOKEN,
             detect=_detect_none, clock=None, lock=None, readiness=None):
        all_headers = dict(JSON_CT)
        all_headers.update(AUTH)
        if headers:
            all_headers.update(headers)
        if raw is None:
            body = payload if payload is not None else {"text": "x"}
            raw = json.dumps(body).encode("utf-8")
        kwargs = {"clock": clock} if clock is not None else {}
        return guardrail_api.process_request(
            all_headers, raw, token=token, tags=TAGS, detect=detect,
            lock=lock if lock is not None else self.lock, readiness=readiness, **kwargs)

    # ---- risposta ---------------------------------------------------------- #
    def test_esempio_del_contratto(self):
        status, body = self.call(
            {"dictionary": {"[FULLNAME_7]": "Mario Rossi"},
             "text": "Mario Rossi, scrivi a mario@example.com"},
            detect=detect_literals(("mario@example.com", "EMAIL")))
        self.assertEqual(status, 200)
        self.assertEqual(body, {
            "results": [{
                "input_id": "text",
                "anonymized_text": "[FULLNAME_7], scrivi a [EMAIL_1]",
                "statistics": {"placeholder_count": 2},
            }],
            "dictionary_delta": {"[EMAIL_1]": "mario@example.com"},
        })
        self.assertEqual(set(body), {"results", "dictionary_delta"})
        self.assertEqual(set(body["results"][0]),
                         {"input_id", "anonymized_text", "statistics"})

    def test_seed_assente_o_vuoto(self):
        for payload in ({"text": "mario@example.com"},
                        {"text": "mario@example.com", "dictionary": {}}):
            status, body = self.call(payload, detect=detect_literals(
                ("mario@example.com", "EMAIL")))
            self.assertEqual(status, 200, payload)
            self.assertEqual(body["dictionary_delta"],
                             {"[EMAIL_1]": "mario@example.com"})

    def test_delta_vuoto_senza_nuove_coppie(self):
        status, body = self.call({"text": "nessuna pii qui",
                                  "dictionary": {"[FULLNAME_7]": "Mario Rossi"}})
        self.assertEqual(status, 200)
        self.assertEqual(body["dictionary_delta"], {})
        self.assertEqual(body["results"][0]["statistics"]["placeholder_count"], 0)

    def test_originale_noto_anche_se_il_modello_non_lo_vede(self):
        status, body = self.call({"text": "Mario Rossi",
                                  "dictionary": {"[FULLNAME_7]": "Mario Rossi"}})
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"], "[FULLNAME_7]")
        self.assertEqual(body["dictionary_delta"], {})

    def test_placeholder_esistenti_preservati_e_riservati(self):
        status, body = self.call(
            {"text": "[EMAIL_3] e mario@example.com"},
            detect=detect_literals(("mario@example.com", "EMAIL")))
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"],
                         "[EMAIL_3] e [EMAIL_4]")
        self.assertEqual(body["results"][0]["statistics"]["placeholder_count"], 2)
        self.assertEqual(body["dictionary_delta"], {"[EMAIL_4]": "mario@example.com"})

    def test_conteggio_placeholder_ripetuti(self):
        status, body = self.call({"text": "[EMAIL_1] e [EMAIL_1]"})
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["statistics"]["placeholder_count"], 2)

    def test_label_sconosciute_scartate(self):
        def detect(_text, _check):
            return [{"label": "OTHER", "start": 0, "end": 4, "score": 0.9,
                     "validated": False, "source": "modello"}]

        status, body = self.call({"text": "test"}, detect=detect)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"], "test")
        self.assertEqual(body["dictionary_delta"], {})

    def test_rilevatore_non_frammenta_il_seed(self):
        def detect(_text, _check):
            return [{"label": "FULLNAME", "start": -3, "end": 20,
                     "score": 0.9, "validated": False, "source": "modello"}]

        status, body = self.call(
            {"text": "Mario Rossi", "dictionary": {"[FULLNAME_7]": "Mario Rossi"}},
            detect=detect)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"], "[FULLNAME_7]")
        self.assertEqual(body["dictionary_delta"], {})

    def test_ripetizioni_normalizzate(self):
        status, body = self.call(
            {"text": "MARIO e mario"},
            detect=detect_literals(("MARIO", "FULLNAME"), ("mario", "FULLNAME")))
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"],
                         "[FULLNAME_1] e [FULLNAME_1]")
        self.assertEqual(body["dictionary_delta"], {"[FULLNAME_1]": "MARIO"})

    # ---- autenticazione ---------------------------------------------------- #
    def test_token_assente_o_vuoto_503(self):
        for token in (None, "", "   ", "\t"):
            status, body = self.call({"text": "x"}, token=token)
            self.assertEqual(status, 503, repr(token))
            self.assertEqual(body["code"], "unavailable")

    def test_credenziali_mancanti_o_sbagliate_401(self):
        for header in ("", "Basic abc", "Bearer", "Bearer sbagliato",
                       "Bearer " + TOKEN + "x"):
            status, body = self.call({"text": "x"}, headers={"Authorization": header})
            self.assertEqual(status, 401, repr(header))
            self.assertEqual(body["code"], "unauthorized")

    def test_authorization_assente_401(self):
        status, body = guardrail_api.process_request(
            dict(JSON_CT), b'{"text":"x"}', token=TOKEN, tags=TAGS,
            detect=_detect_none, lock=self.lock)
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "unauthorized")

    def test_body_none_trattato_come_vuoto(self):
        headers = dict(JSON_CT)
        headers.update(AUTH)
        status, body = guardrail_api.process_request(
            headers, None, token=TOKEN, tags=TAGS,
            detect=_detect_none, lock=self.lock)
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")

    def test_token_unicode(self):
        token = "p\u00e4ssw\u00f6rd\U0001f511"
        status, _body = self.call({"text": "x"}, token=token,
                                  headers={"Authorization": "Bearer " + token})
        self.assertEqual(status, 200)
        status, _body = self.call({"text": "x"}, token=token,
                                  headers={"Authorization": "Bearer altro"})
        self.assertEqual(status, 401)
        # un token Unicode configurato e un header ASCII non devono far cadere nulla
        status, _body = self.call({"text": "x"}, token=token,
                                  headers={"Authorization": "Bearer ascii"})
        self.assertEqual(status, 401)

    # ---- stato del servizio ------------------------------------------------ #
    def test_modello_non_disponibile_503(self):
        status, body = self.call({"text": "x"}, detect=None)
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "unavailable")

    def test_readiness_blocca_testo_tutto_protetto_prima_della_rilevazione(self):
        calls = []

        def detect(*_args):
            calls.append(True)
            return []

        payloads = [
            {"text": "Mario Rossi", "dictionary": {"[FULLNAME_1]": "Mario Rossi"}},
            {"text": "[FULLNAME_7]"},
        ]
        for payload in payloads:
            status, body = self.call(payload, detect=detect, readiness=lambda: False)
            self.assertEqual(status, 503)
            self.assertEqual(body["code"], "unavailable")
            self.assertFalse(self.lock.locked())
        self.assertEqual(calls, [])

    def test_errori_callback_readiness_sanificati(self):
        def unavailable():
            raise guardrail_api.ModelUnavailable()

        def broken():
            raise RuntimeError("SECRET-readiness-value")

        for callback, expected_status in ((unavailable, 503), (broken, 500)):
            status, body = self.call({"text": "x"}, readiness=callback)
            self.assertEqual(status, expected_status)
            self.assertEqual(body["code"],
                             "unavailable" if expected_status == 503 else "internal_error")
            self.assertNotIn("SECRET-readiness-value", json.dumps(body))
            self.assertFalse(self.lock.locked())

    def test_modello_che_sparisce_a_meta_richiesta_503(self):
        def detect(_text, _check):
            raise guardrail_api.ModelUnavailable()

        status, body = self.call({"text": "Mario"}, detect=detect)
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "unavailable")
        self.assertFalse(self.lock.locked())

    def test_busy_e_rilascio_del_lock(self):
        lock = threading.Lock()
        lock.acquire()
        try:
            status, body = self.call({"text": "x"}, lock=lock)
            self.assertEqual(status, 429)
            self.assertEqual(body["code"], "busy")
        finally:
            lock.release()
        status, _body = self.call({"text": "x"}, lock=lock)
        self.assertEqual(status, 200)

    def test_lock_rilasciato_dopo_ogni_errore(self):
        lock = threading.Lock()
        status, _body = self.call(raw=b"{", lock=lock)
        self.assertEqual(status, 400)
        self.assertFalse(lock.locked())
        status, body = self.call({"text": "x"}, detect=_boom, lock=lock)
        self.assertEqual(status, 500)
        self.assertFalse(lock.locked())
        status, _body = self.call({"text": "x"}, lock=lock)
        self.assertEqual(status, 200)

    # ---- gate prima della lettura del body -------------------------------- #
    def test_gate_prima_della_lettura_del_body(self):
        class Boom:
            def __init__(self):
                self.called = False

            def __call__(self, _cap):
                self.called = True
                raise RuntimeError("BOOM-raw-body")

        def probe(headers, *, token=TOKEN, detect=_detect_none, lock=None,
                  readiness=None):
            reader = Boom()
            status, body = guardrail_api.process_request(
                headers, reader, token=token, tags=TAGS, detect=detect,
                lock=lock if lock is not None else threading.Lock(),
                readiness=readiness)
            self.assertFalse(reader.called, "il body e' stato letto troppo presto")
            return status, body

        status, body = probe({})
        self.assertEqual((status, body["code"]), (401, "unauthorized"))
        status, body = probe({}, token="")
        self.assertEqual((status, body["code"]), (503, "unavailable"))
        status, body = probe(dict(AUTH), detect=None)
        self.assertEqual((status, body["code"]), (503, "unavailable"))
        status, body = probe(dict(AUTH), readiness=lambda: False)
        self.assertEqual((status, body["code"]), (503, "unavailable"))
        lock = threading.Lock()
        lock.acquire()
        try:
            status, body = probe(dict(AUTH), lock=lock)
        finally:
            lock.release()
        self.assertEqual((status, body["code"]), (429, "busy"))

    # ---- JSON severo ------------------------------------------------------- #
    def test_json_malformato_o_non_oggetto(self):
        for raw in (b"{", b"[]", b'"x"', b"1", b"null", b"true", b"", b"   "):
            status, body = self.call(raw=raw)
            self.assertEqual(status, 400, raw)
            self.assertEqual(body["code"], "invalid_request")

    def test_chiavi_duplicate_anche_uguali(self):
        raw = b'{"text":"a","text":"a"}'
        status, body = self.call(raw=raw)
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")
        raw = b'{"text":"a","dictionary":{"[EMAIL_1]":"x","[EMAIL_1]":"x"}}'
        status, body = self.call(raw=raw)
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")

    def test_nan_e_infinity_rifiutati(self):
        for raw in (b'{"text": NaN}', b'{"text": Infinity}', b'{"text": -Infinity}',
                    b'{"text":"a","dictionary":{"[EMAIL_1]": NaN}}'):
            status, body = self.call(raw=raw)
            self.assertEqual(status, 400, raw)
            self.assertEqual(body["code"], "invalid_request")

    def test_annidamento_profondo(self):
        raw = b"[" * 2000 + b"]" * 2000
        status, body = self.call(raw=raw)
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")

    def test_utf8_non_valido(self):
        status, body = self.call(raw=b'{"text": "\xff"}')
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")

    def test_surrogati_isolati_rifiutati_senza_valori_log_o_lock_trattenuto(self):
        class Capture(logging.Handler):
            def __init__(self):
                super().__init__()
                self.messages = []

            def emit(self, record):
                self.messages.append(record.getMessage())

        cases = [
            (b'{"text":"private-text-\\ud800"}', "invalid_request", "private-text-"),
            (b'{"text":"x","dictionary":{"[FULLNAME_1]":"private-seed-\\ud800"}}',
             "invalid_seed", "private-seed-"),
        ]
        logger = logging.getLogger()
        capture = Capture()
        logger.addHandler(capture)
        calls = []
        lock = threading.Lock()
        try:
            for raw, code, private_value in cases:
                status, body = self.call(raw=raw, detect=lambda *_args: calls.append(1),
                                         lock=lock)
                self.assertEqual(status, 400)
                self.assertEqual(body["code"], code)
                self.assertNotIn(private_value, json.dumps(body))
                self.assertFalse(lock.locked())
            self.assertEqual(calls, [])
            self.assertEqual(self.call({"text": "after rejection"}, lock=lock)[0], 200)
        finally:
            logger.removeHandler(capture)
        self.assertEqual(capture.messages, [])

    def test_coppie_surrogate_valide_accettate_come_caratteri_astrali(self):
        status, body = self.call(raw=b'{"text":"\\ud83d\\ude00"}')
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"], "\U0001f600")

        status, body = self.call(raw=(
            b'{"text":"\\ud83d\\ude00","dictionary":'
            b'{"[FULLNAME_1]":"\\ud83d\\ude00"}}'))
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"], "[FULLNAME_1]")
        self.assertEqual(body["dictionary_delta"], {})

    def test_campi_sconosciuti_nell_envelope(self):
        for extra in ({"exclude_tags": []}, {"include_mapping": False},
                      {"files": []}, {"texts": ["x"]}):
            payload = {"text": "x"}
            payload.update(extra)
            status, body = self.call(payload)
            self.assertEqual(status, 400, extra)
            self.assertEqual(body["code"], "invalid_request")

    def test_text_mancante_vuoto_o_non_stringa(self):
        for payload in ({}, {"text": ""}, {"text": " \n\t"}, {"text": 1},
                        {"text": None}, {"text": []}, {"text": {}}):
            status, body = self.call(payload)
            self.assertEqual(status, 400, payload)
            self.assertEqual(body["code"], "invalid_request")

    # ---- limiti ------------------------------------------------------------ #
    def test_limite_body(self):
        base = json.dumps({"text": "x"}).encode("utf-8")
        raw = base + b" " * (guardrail_api.MAX_BODY_BYTES - len(base))
        self.assertEqual(len(raw), guardrail_api.MAX_BODY_BYTES)
        status, _body = self.call(raw=raw)
        self.assertEqual(status, 200)
        status, body = self.call(raw=raw + b" ")
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "payload_too_large")

    def test_limite_text(self):
        status, _body = self.call({"text": "a" * 100000})
        self.assertEqual(status, 200)
        status, body = self.call({"text": "a" * 100001})
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "payload_too_large")

    def test_limite_voci_dizionario_configurato(self):
        with patch.dict(os.environ, {"PII_MAX_SEED_ENTRIES": "256"}):
            ok = {"[FULLNAME_%d]" % i: "v%d" % i for i in range(1, 257)}
            status, _body = self.call({"text": "x", "dictionary": ok})
            self.assertEqual(status, 200)
            troppe = dict(ok)
            troppe["[FULLNAME_257]"] = "v257"
            status, body = self.call({"text": "x", "dictionary": troppe})
            self.assertEqual(status, 413)
            self.assertEqual(body["code"], "payload_too_large")

    def test_limite_singolo_originale(self):
        status, _body = self.call({"text": "x", "dictionary": {"[FULLNAME_1]": "a" * 4096}})
        self.assertEqual(status, 200)
        status, body = self.call({"text": "x", "dictionary": {"[FULLNAME_1]": "a" * 4097}})
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "payload_too_large")

    def test_limite_aggregato_configurato(self):
        valori = {"[FULLNAME_%d]" % (i + 1): ("x" * 4095) + chr(0x4E00 + i)
                  for i in range(16)}
        with patch.dict(os.environ, {"PII_MAX_AGGREGATE_CHARS": "65536"}):
            status, _body = self.call({"text": "x", "dictionary": valori})
            self.assertEqual(status, 200)
            valori["[FULLNAME_17]"] = "z"
            status, body = self.call({"text": "x", "dictionary": valori})
            self.assertEqual(status, 413)
            self.assertEqual(body["code"], "payload_too_large")

    def test_default_http_seed_cap_allows_more_than_256_entries(self):
        dictionary = {"[FULLNAME_%d]" % index: "synthetic-%d" % index
                      for index in range(1, 301)}
        status, body = self.call({"text": "unmatched", "dictionary": dictionary})
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"], "unmatched")
        self.assertEqual(body["dictionary_delta"], {})

    def test_effective_seed_and_delta_limits_fail_without_originals(self):
        cases = [
            ({"PII_MAX_SEED_ENTRIES": "1"},
             {"[FULLNAME_1]": "seed-synthetic-original"},
             "delta-synthetic-original"),
            ({"PII_MAX_AGGREGATE_CHARS": "24"},
             {"[FULLNAME_1]": "seed-synthetic"},
             "delta-synthetic-original"),
        ]
        for environment, dictionary, detected in cases:
            with self.subTest(environment=environment), patch.dict(os.environ, environment):
                status, body = self.call(
                    {"text": detected, "dictionary": dictionary},
                    detect=detect_literals((detected, "FULLNAME")))
                self.assertEqual(status, 413)
                encoded = json.dumps(body)
                self.assertEqual(set(body), {"error", "code"})
                self.assertNotIn(detected, encoded)
                self.assertNotIn(next(iter(dictionary.values())), encoded)

    def test_effective_original_limit_fail_no_original(self):
        detected = "delta-synthetic-original"
        with patch.dict(os.environ, {"PII_MAX_ORIGINAL_CHARS": "5"}):
            status, body = self.call(
                {"text": detected}, detect=detect_literals((detected, "FULLNAME")))
        self.assertEqual(status, 413)
        self.assertEqual(set(body), {"error", "code"})
        self.assertNotIn(detected, json.dumps(body))

    def test_json_body_cap_is_configurable_per_request(self):
        raw = b'{"text":"x"}' + b" " * 32
        with patch.dict(os.environ, {"PII_MAX_JSON_BODY_BYTES": "32"}):
            status, body = self.call(raw=raw)
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "payload_too_large")

    def test_dictionary_limits_resolved_once_per_request(self):
        with patch.object(guardrail_api.guardrail_limits, "resolve_request_limits",
                          wraps=guardrail_api.guardrail_limits.resolve_request_limits) as resolver:
            status, _body = self.call({"text": "unmatched"})
        self.assertEqual(status, 200)
        self.assertEqual(resolver.call_count, 1)

    def test_esaurimento_id_400(self):
        status, body = self.call(
            {"text": "scrivi a x@y.it", "dictionary": {"[EMAIL_999999999]": "a@b.it"}},
            detect=detect_literals(("x@y.it", "EMAIL")))
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "allocation_exhausted")

    # ---- dizionario -------------------------------------------------------- #
    def test_dizionario_non_oggetto(self):
        for value in (None, [], "x", 5, True):
            status, body = self.call({"text": "x", "dictionary": value})
            self.assertEqual(status, 400, value)
            self.assertEqual(body["code"], "invalid_seed")

    def test_chiavi_non_canoniche(self):
        for key in ("FULLNAME_1", "[FULLNAME_01]", "[FULLNAME_0]",
                    "[FULLNAME_1000000000]", "[OTHER_1]", "[fullname_1]",
                    "[FULLNAME_1]x", "[FULLNAME_\u0661]"):
            status, body = self.call({"text": "x", "dictionary": {key: "valore"}})
            self.assertEqual(status, 400, key)
            self.assertEqual(body["code"], "invalid_seed")

    def test_valori_non_validi(self):
        for value in (1, None, True, [], "", "   "):
            status, body = self.call({"text": "x", "dictionary": {"[FULLNAME_1]": value}})
            self.assertEqual(status, 400, value)
            self.assertEqual(body["code"], "invalid_seed")

    def test_conflitto_seed(self):
        status, body = self.call({"text": "x", "dictionary": {
            "[FULLNAME_1]": "Mario Rossi", "[CITY_1]": "mario   rossi"}})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "seed_conflict")

    # ---- deadline e errori ------------------------------------------------- #
    def test_deadline_504(self):
        clock = Clock()

        def detect(_text, check):
            clock.now = 61.0
            check()
            return []

        status, body = self.call({"text": "Mario"}, detect=detect, clock=clock)
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")

    def test_fake_clock_scade_durante_la_ricerca_punteggiatura(self):
        class MatchingClock:
            def __init__(self):
                self.calls = 0

            def __call__(self):
                self.calls += 1
                return 61.0 if self.calls >= 85 else 0.0

        clock = MatchingClock()
        called = []
        payload = {"text": "!" * 20000, "dictionary": {"[EMAIL_1]": "!"}}
        status, body = self.call(payload, detect=lambda *_args: called.append(True),
                                 clock=clock)
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")
        self.assertGreaterEqual(clock.calls, 85)
        self.assertLess(clock.calls, 100)
        self.assertEqual(called, [])
        self.assertFalse(self.lock.locked())

    def test_errore_imprevisto_500_sanificato(self):
        status, body = self.call({"text": "Mario"}, detect=_boom)
        self.assertEqual(status, 500)
        self.assertEqual(body["code"], "internal_error")
        self.assertNotIn("SECRET", json.dumps(body))
        self.assertEqual(set(body), {"error", "code"})

    def test_request_entity_too_large_dal_rilevatore_413(self):
        def detect(_text, _check):
            raise guardrail_api.RequestEntityTooLarge()

        status, body = self.call({"text": "Mario"}, detect=detect)
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "payload_too_large")

    # ---- media type -------------------------------------------------------- #
    def test_content_type(self):
        casi = [(None, 415), ("text/plain", 415),
                ("application/json", 200),
                ("application/json; charset=utf-8", 200),
                ("application/json;charset=UTF-8", 200),
                ('application/json; charset="utf-8"', 200),
                ("application/json; charset=latin-1", 415),
                ("APPLICATION/JSON", 200)]
        if guardrail_inputs.native_multipart_available():
            # multipart ora e' supportato: un boundary valido con un body JSON e'
            # multipart malformato -> 400, non piu' 415 "media type non supportato".
            casi.append(("multipart/form-data; boundary=x", 400))
        else:
            # CI stdlib senza Werkzeug: il ramo multipart non esiste (503); la
            # copertura vera sta in test_guardrail_multifiles.py, saltata senza
            # il parser nativo.
            casi.append(("multipart/form-data; boundary=x", 503))
        for content_type, expected in casi:
            all_headers = dict(AUTH)
            if content_type is not None:
                all_headers["Content-Type"] = content_type
            status, _body = guardrail_api.process_request(
                all_headers, b'{"text":"x"}', token=TOKEN, tags=TAGS,
                detect=_detect_none, lock=self.lock)
            self.assertEqual(status, expected, content_type)


# --------------------------------------------------------------------------- #
# Integrazione Flask
# --------------------------------------------------------------------------- #
def _make_client(detect=_detect_none, clock=None, streaming=False, readiness=None):
    lock = threading.Lock()
    application = Flask("guardrail-test")
    application.config["TESTING"] = True
    # come app.py: il tetto del framework e' 50 MB, quello JSON e' configurabile.
    application.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
    kwargs = {"clock": clock} if clock is not None else {}
    blueprint = guardrail_api.create_blueprint(TAGS, detect, lock=lock,
                                               readiness=readiness, **kwargs)
    application.register_blueprint(blueprint)
    if streaming:
        # Simula una richiesta chunked: niente Content-Length e stream terminato
        # dal server, esattamente cio' che deve reggere il tetto JSON configurato.
        inner = application.wsgi_app

        def middleware(environ, start_response):
            environ.pop("CONTENT_LENGTH", None)
            environ["wsgi.input_terminated"] = True
            return inner(environ, start_response)

        application.wsgi_app = middleware
    return application.test_client(), lock


@unittest.skipUnless(HAVE_FLASK, "Flask assente")
class FlaskEndpoint(unittest.TestCase):
    def setUp(self):
        self.client, self.lock = _make_client()
        # Igiene del test: la env del server non deve cambiare il default
        # locale (60 s) di questi clock.
        patcher = patch.dict(os.environ, {
            "PII_API_TOKEN": TOKEN,
            "PII_ANALYSIS_TIMEOUT_SECONDS": "",
            "PII_MAX_SEED_ENTRIES": "",
            "PII_MAX_ORIGINAL_CHARS": "",
            "PII_MAX_AGGREGATE_CHARS": "",
            "PII_MAX_JSON_BODY_BYTES": "",
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, payload=None, raw=None, content_type="application/json",
             headers=None, client=None, **kwargs):
        all_headers = dict(AUTH)
        if headers:
            all_headers.update(headers)
        if raw is None:
            raw = json.dumps(payload if payload is not None else {"text": "x"}).encode()
        client = client or self.client
        if content_type is None:
            return client.post(PATH, data=raw, headers=all_headers, **kwargs)
        return client.post(PATH, data=raw, content_type=content_type,
                           headers=all_headers, **kwargs)

    def test_esempio_del_contratto(self):
        client, _lock = _make_client(
            detect=detect_literals(("mario@example.com", "EMAIL")))
        response = self.post(
            {"dictionary": {"[FULLNAME_7]": "Mario Rossi"},
             "text": "Mario Rossi, scrivi a mario@example.com"},
            headers=dict(JSON_CT), client=client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.get_json(), {
            "results": [{
                "input_id": "text",
                "anonymized_text": "[FULLNAME_7], scrivi a [EMAIL_1]",
                "statistics": {"placeholder_count": 2},
            }],
            "dictionary_delta": {"[EMAIL_1]": "mario@example.com"},
        })

    def test_surrogati_escaped_http_sanitizzati_e_coppie_valide(self):
        cases = [
            (b'{"text":"private-text-\\ud800"}', "invalid_request"),
            (b'{"text":"x","dictionary":{"[FULLNAME_1]":"private-seed-\\ud800"}}',
             "invalid_seed"),
        ]
        for raw, code in cases:
            response = self.post(raw=raw)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["code"], code)
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")
            self.assertNotIn("private-", response.get_data(as_text=True))
        response = self.post(raw=b'{"text":"\\ud83d\\ude00"}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["anonymized_text"],
                         "\U0001f600")

    def test_content_type(self):
        response = self.post({"text": "x"}, content_type="text/plain")
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.get_json()["code"], "unsupported_media_type")
        response = self.post({"text": "x"},
                             content_type="application/json; charset=latin-1")
        self.assertEqual(response.status_code, 415)
        response = self.post({"text": "x"},
                             content_type="application/json; charset=utf-8")
        self.assertEqual(response.status_code, 200)
        response = self.post({"text": "x"}, content_type=None,
                             environ_overrides={"CONTENT_TYPE": ""})
        self.assertEqual(response.status_code, 415)
        # multipart e' supportato: senza boundary il body e' malformato -> 400,
        # non piu' 415 "media type non supportato".
        response = self.post({"text": "x"}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_request")

    def test_body_oltre_il_limite(self):
        response = self.post(raw=b" " * (guardrail_api.MAX_BODY_BYTES + 1))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["code"], "payload_too_large")
        self.assertEqual(set(response.get_json()), {"error", "code"})

    def test_request_entity_too_large_del_framework_sanificato(self):
        # Il Content-Length dichiara 51 MB (oltre il tetto Flask di 50 MB): lo
        # stream del framework solleva RequestEntityTooLarge prima del nostro tetto
        # e la vista deve rispondere 413 sanificato, non l'HTML di default.
        response = self.post({"text": "x"}, environ_overrides={
            "CONTENT_LENGTH": str(51 * 1024 * 1024)})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["code"], "payload_too_large")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_content_length_mentito_non_fa_processare_oltre_il_dichiarato(self):
        # CL=10 con body oltre il cap JSON: il framing HTTP dice che fanno parte della
        # richiesta solo 10 byte. L'endpoint non deve ne' bloccarsi ne' processare
        # il resto: legge il framed stream (non i byte grezzi a valle), quindi il
        # prefisso da 10 byte e' JSON invalido -> 400, mai 200.
        raw = b'{"text":"' + b"a" * guardrail_api.MAX_BODY_BYTES + b'"}'
        response = self.post(raw=raw,
                             environ_overrides={"CONTENT_LENGTH": "10"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_request")

    def test_content_length_assente_non_bypassa_il_limite(self):
        # Body in streaming (niente Content-Length, wsgi.input_terminated): il tetto
        # deve valere sui byte letti, non sull'header mancante.
        client, _lock = _make_client(streaming=True)
        raw = b'{"text":"' + b"a" * guardrail_api.MAX_BODY_BYTES + b'"}'
        response = self.post(raw=raw, client=client)
        self.assertEqual(response.status_code, 413)

    def test_body_in_streaming_valido(self):
        client, _lock = _make_client(streaming=True)
        response = self.post({"text": "x"}, client=client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["anonymized_text"], "x")

    def test_autenticazione_via_http(self):
        with patch.dict(os.environ, {"PII_API_TOKEN": "   "}):
            response = self.post({"text": "x"})
            self.assertEqual(response.status_code, 503)
        response = self.client.post(PATH, data=b'{"text":"x"}',
                                    content_type="application/json",
                                    headers={"Authorization": "Bearer sbagliato"})
        self.assertEqual(response.status_code, 401)
        response = self.post({"text": "x"})
        self.assertEqual(response.status_code, 200)

    def test_busy_e_rilascio_lock(self):
        self.lock.acquire()
        try:
            response = self.post({"text": "x"})
        finally:
            self.lock.release()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.get_json()["code"], "busy")
        self.assertEqual(self.post({"text": "x"}).status_code, 200)

    def test_gate_prima_della_lettura_del_body_su_http(self):
        class BoomStream:
            def __init__(self):
                self.calls = 0

            def read(self, *_args):
                self.calls += 1
                raise RuntimeError("BOOM-stream")

            def readline(self, *_args):
                self.calls += 1
                raise RuntimeError("BOOM-stream")

        stream = BoomStream()
        response = self.client.post(PATH, data=b'{"text":"x"}',
                                    content_type="application/json",
                                    headers={"Authorization": "Bearer sbagliato"},
                                    environ_overrides={"wsgi.input": stream})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(stream.calls, 0)
        with patch.dict(os.environ, {"PII_API_TOKEN": ""}):
            response = self.post({"text": "x"},
                                 environ_overrides={"wsgi.input": stream})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(stream.calls, 0)
        self.lock.acquire()
        try:
            response = self.post({"text": "x"},
                                 environ_overrides={"wsgi.input": stream})
        finally:
            self.lock.release()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(stream.calls, 0)
        # Con i gate superati il body viene letto davvero: uno stream rotto
        # diventa 400 sanificato, non un 500 e mai un'eccezione esposta.
        response = self.post({"text": "x"},
                             environ_overrides={"wsgi.input": stream})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["code"], "invalid_request")
        self.assertGreaterEqual(stream.calls, 1)

    def test_lock_rilasciato_dopo_errore(self):
        self.assertEqual(self.post(raw=b"{").status_code, 400)
        self.assertEqual(self.post({"text": "x"}).status_code, 200)

    def test_modello_non_disponibile(self):
        client, _lock = _make_client(detect=None)
        response = self.post({"text": "x"}, client=client)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "unavailable")

    def test_deadline(self):
        clock = Clock()

        def detect(_text, check):
            clock.now = 61.0
            check()
            return []

        client, _lock = _make_client(detect=detect, clock=clock)
        response = self.post({"text": "Mario"}, client=client)
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.get_json()["code"], "deadline_exceeded")

    def test_errore_500_sanificato(self):
        client, _lock = _make_client(detect=_boom)
        response = self.post({"text": "Mario"}, client=client)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("SECRET", response.get_data(as_text=True))
        self.assertEqual(response.get_json()["code"], "internal_error")

    def test_no_store_su_ogni_risposta(self):
        responses = [self.post({"text": "x"})]
        responses.append(self.client.post(PATH, data=b"{",
                                          content_type="application/json",
                                          headers=dict(AUTH)))
        responses.append(self.client.post(
            PATH, data=b'{"text":"x"}', content_type="application/json",
            headers={"Authorization": "Bearer sbagliato"}))
        responses.append(self.post(raw=b" " * (guardrail_api.MAX_BODY_BYTES + 1)))
        responses.append(self.post({"text": "x"}, content_type="text/plain"))
        self.lock.acquire()
        try:
            responses.append(self.post({"text": "x"}))
        finally:
            self.lock.release()
        client500, _lock = _make_client(detect=_boom)
        responses.append(self.post({"text": "Mario"}, client=client500))
        with patch.dict(os.environ, {"PII_API_TOKEN": ""}):
            responses.append(self.post({"text": "x"}))
        clock = Clock()

        def detect(_text, check):
            clock.now = 61.0
            check()
            return []

        client504, _lock = _make_client(detect=detect, clock=clock)
        responses.append(self.post({"text": "Mario"}, client=client504))
        self.assertEqual(sorted(response.status_code for response in responses),
                         [200, 400, 401, 413, 415, 429, 500, 503, 504])
        for response in responses:
            self.assertEqual(response.headers.get("Cache-Control"), "no-store",
                             response.status_code)

    def test_route_solo_post(self):
        response = self.client.get(PATH)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_no_store_su_options_e_metodi_non_supportati(self):
        response = self.client.options(PATH)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(response.status_code, 200)

    def test_errore_creazione_risposta_sanificato(self):
        with patch.object(guardrail_api.json, "dumps",
                          side_effect=RuntimeError("SECRET-response-value")):
            response = guardrail_api._flask_response(200, {"text": "x"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {
            "error": "Internal error.", "code": "internal_error"})
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertNotIn("SECRET-response-value", response.get_data(as_text=True))


# --------------------------------------------------------------------------- #
# Cablaggio con l'app legacy (import con dipendenze pesanti finte)
# --------------------------------------------------------------------------- #
def _import_app_with_mocks():
    if "app" in sys.modules:
        return sys.modules["app"]
    saved = {name: sys.modules.get(name) for name in ("torch", "transformers", "fitz")}
    for name in saved:
        sys.modules[name] = MagicMock()
    previous = os.environ.get("PII_MODEL_DIR")
    os.environ["PII_MODEL_DIR"] = str(ROOT / "tests")
    try:
        import app as app_module
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
        # pdf_export/pdf_text sono rimasti legati ai mock: chi li rivuole li reimporta veri
        sys.modules.pop("pdf_export", None)
        sys.modules.pop("pdf_text", None)
    return app_module


@unittest.skipUnless(HAVE_FLASK, "Flask assente")
class AppWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.APP = _import_app_with_mocks()

    def test_route_registrata(self):
        rules = {str(rule) for rule in self.APP.app.url_map.iter_rules()}
        self.assertIn(PATH, rules)

    def test_endpoint_usa_il_modello_finto(self):
        def fake_nlp(chunks):
            return [[{"entity_group": "FULLNAME", "start": 0, "end": 5,
                      "score": 0.9, "word": "Mario"}] for _chunks in chunks]

        with patch.dict(os.environ, {"PII_API_TOKEN": TOKEN}), \
                patch.object(self.APP, "nlp", fake_nlp):
            response = self.APP.app.test_client().post(
                PATH, data=json.dumps({"text": "Mario"}),
                content_type="application/json", headers=dict(AUTH))
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["results"][0]["anonymized_text"], "[FULLNAME_1]")
        self.assertEqual(body["dictionary_delta"], {"[FULLNAME_1]": "Mario"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_modello_assente_sull_endpoint_503_anche_se_testo_protetto(self):
        client = self.APP.app.test_client()
        payloads = [
            {"text": "Mario Rossi", "dictionary": {"[FULLNAME_1]": "Mario Rossi"}},
            {"text": "[FULLNAME_7]"},
        ]
        with patch.dict(os.environ, {"PII_API_TOKEN": TOKEN}), \
                patch.object(self.APP, "nlp", None):
            for payload in payloads:
                response = client.post(
                    PATH, data=json.dumps(payload),
                    content_type="application/json", headers=dict(AUTH))
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.get_json()["code"], "unavailable")
                self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_route_legacy_intatte(self):
        def fake_nlp(chunks):
            return [[] for _chunks in chunks]

        with patch.object(self.APP, "nlp", fake_nlp), \
                patch.object(self.APP, "_get_prefs", lambda: (set(), True)):
            response = self.APP.app.test_client().post(
                "/analyze", json={"text": "Mario Rossi"})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        for key in ("anonymized_text", "mapping", "segments", "n_chunks",
                    "source_text"):
            self.assertIn(key, body)

    def test_health_legacy_ancora_vivo(self):
        response = self.APP.app.test_client().get("/health")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()