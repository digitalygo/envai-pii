# -*- coding: utf-8 -*-
"""Guardrail API v1: whitelist `categories` per-richiesta (ENVAS-23).

Copre il motore (`pii_dictionary`), il guscio HTTP-agnostico (`process_request`),
il parser multipart, il binder `detect_for_categories` e il cablaggio reale di
app.py (modello finto, regex vera, PyMuPDF vero quando c'e'). Flask, Werkzeug e
PyMuPDF si saltano SOLO se la dipendenza manca (CI stdlib); nella venv reale
girano tutti. Nessun peso, nessuna rete, nessun server, nessun file utente:
tutti i valori sono SINTETICI.
"""

import ast
import contextlib
import json
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
import pii_dictionary  # noqa: E402
import runtime_execution

HAVE_NATIVE = guardrail_inputs.native_multipart_available()

try:
    from flask import Flask
    HAVE_FLASK = True
except ImportError:
    Flask = None
    HAVE_FLASK = False

try:
    import fitz
    HAVE_FITZ = True
except ImportError:
    fitz = None
    HAVE_FITZ = False

TOKEN = "token-categories"
AUTH = {"Authorization": "Bearer " + TOKEN}
JSON_CT = {"Content-Type": "application/json"}
PATH = "/api/v1/analyses"
BOUND = "BOUND"
APP_SRC = ROOT / "src" / "app" / "app.py"
ALL = "ALL"          # sentinella di prova: nessuna selezione (catalogo intero)


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
                out.append({"label": label, "start": found,
                            "end": found + len(literal), "score": 0.9,
                            "validated": False, "source": "modello"})
                position = found + 1
        return out
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


class Clock:
    """Clock monotono finto: i test avanzano `now` a mano."""

    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


# --------------------------------------------------------------------------- #
# Motore: `categories` governa match noti, filtro e allocazioni
# --------------------------------------------------------------------------- #
class CoreCategories(unittest.TestCase):
    """pii_dictionary con `categories`: valori sintetici, nessuna dipendenza."""

    def seed(self, dictionary):
        return pii_dictionary.parse_seed(dictionary, TAGS)

    def test_selezione_sostituisce_solo_le_label_attive(self):
        out = pii_dictionary.anonymize(
            "Mario x@y.it", self.seed({}), TAGS,
            detect=detect_literals(("Mario", "FULLNAME"), ("x@y.it", "EMAIL")),
            categories={"FULLNAME"})
        self.assertEqual(out["anonymized_text"], "[FULLNAME_1] x@y.it")
        self.assertEqual(out["dictionary_delta"], {"[FULLNAME_1]": "Mario"})
        self.assertEqual(out["placeholder_count"], 1)

    def test_none_e_catalogo_intero_sono_identici(self):
        detect = detect_literals(("Mario", "FULLNAME"), ("x@y.it", "EMAIL"))
        seed = self.seed({"[FULLNAME_7]": "Mario"})
        senza = pii_dictionary.anonymize("Mario x@y.it", seed, TAGS, detect=detect)
        intero = pii_dictionary.anonymize("Mario x@y.it", seed, TAGS, detect=detect,
                                          categories=frozenset(TAGS))
        self.assertEqual(senza, intero)

    def test_insieme_vuoto_non_sostituisce_ma_protegge_i_placeholder(self):
        out = pii_dictionary.anonymize(
            "Mario [EMAIL_3] x@y.it", self.seed({}), TAGS,
            detect=detect_literals(("Mario", "FULLNAME"), ("x@y.it", "EMAIL")),
            categories=frozenset())
        self.assertEqual(out["anonymized_text"], "Mario [EMAIL_3] x@y.it")
        self.assertEqual(out["dictionary_delta"], {})
        self.assertEqual(out["placeholder_count"], 1)

    def test_seed_inattivo_non_matcha_ne_entra_nel_delta(self):
        seed = self.seed({"[CITY_1]": "Milano"})
        out = pii_dictionary.anonymize(
            "Milano", seed, TAGS,
            detect=detect_literals(("Milano", "CITY")),
            categories={"FULLNAME"})
        self.assertEqual(out["anonymized_text"], "Milano")
        self.assertEqual(out["dictionary_delta"], {})
        self.assertEqual(seed.pairs, (("[CITY_1]", "CITY", 1, "Milano"),))

    def test_seed_inattivo_rilevato_attivo_riusa_il_binding_esistente(self):
        seed = self.seed({"[CITY_7]": "Milano"})
        out = pii_dictionary.anonymize(
            "Milano", seed, TAGS,
            detect=detect_literals(("Milano", "FULLNAME")),
            categories={"FULLNAME"})
        self.assertEqual(out["anonymized_text"], "[CITY_7]")
        self.assertEqual(out["dictionary_delta"], {})
        self.assertEqual(seed.pairs, (("[CITY_7]", "CITY", 7, "Milano"),))

    def test_placeholder_inattivo_preservato_e_conteggiato(self):
        out = pii_dictionary.anonymize(
            "[EMAIL_3] e Milano", self.seed({}), TAGS,
            detect=_detect_none, categories={"FULLNAME"})
        self.assertEqual(out["anonymized_text"], "[EMAIL_3] e Milano")
        self.assertEqual(out["placeholder_count"], 1)
        self.assertEqual(out["dictionary_delta"], {})

    def test_seed_inattivo_piu_lungo_non_blocca_il_match_attivo(self):
        seed = self.seed({"[ORG_1]": "Studio Rossi & Associati",
                          "[FULLNAME_1]": "Rossi"})
        out = pii_dictionary.anonymize("Studio Rossi & Associati", seed, TAGS,
                                       categories={"FULLNAME"})
        self.assertEqual(out["anonymized_text"], "Studio [FULLNAME_1] & Associati")
        self.assertEqual(out["dictionary_delta"], {})

    def test_seed_inattivo_piu_lungo_non_blocca_il_rilevatore(self):
        seed = self.seed({"[ORG_1]": "Studio Rossi"})
        out = pii_dictionary.anonymize(
            "Studio Rossi", seed, TAGS,
            detect=detect_literals(("Rossi", "FULLNAME")),
            categories={"FULLNAME"})
        self.assertEqual(out["anonymized_text"], "Studio [FULLNAME_1]")
        self.assertEqual(out["dictionary_delta"], {"[FULLNAME_1]": "Rossi"})

    def test_id_del_seed_inattivo_restano_prenotati(self):
        seed = self.seed({"[EMAIL_5]": "a@b.it"})
        out = pii_dictionary.anonymize(
            "x@y.it", seed, TAGS,
            detect=detect_literals(("x@y.it", "EMAIL")),
            categories={"EMAIL"})
        self.assertEqual(out["anonymized_text"], "[EMAIL_6]")
        self.assertEqual(out["dictionary_delta"], {"[EMAIL_6]": "x@y.it"})

    def test_label_inattive_non_consumano_id(self):
        detect = detect_literals(("Milano", "CITY"), ("x@y.it", "EMAIL"))
        out = pii_dictionary.anonymize("Milano x@y.it", self.seed({}), TAGS,
                                       detect=detect, categories={"EMAIL"})
        self.assertEqual(out["anonymized_text"], "Milano [EMAIL_1]")
        self.assertEqual(out["dictionary_delta"], {"[EMAIL_1]": "x@y.it"})

    def test_seed_riusabile_dopo_una_selezione(self):
        seed = self.seed({"[CITY_1]": "Milano"})
        subset = pii_dictionary.anonymize("Milano", seed, TAGS,
                                          categories={"FULLNAME"})
        intero = pii_dictionary.anonymize("Milano", seed, TAGS)
        self.assertEqual(subset["anonymized_text"], "Milano")
        self.assertEqual(subset["dictionary_delta"], {})
        self.assertEqual(intero["anonymized_text"], "[CITY_1]")
        self.assertEqual(seed.pairs, (("[CITY_1]", "CITY", 1, "Milano"),))

    def test_seed_inattivo_resta_validato_e_bloccante(self):
        # Conflitto su label inattive: le regole del seed non dipendono da categories.
        with self.assertRaises(pii_dictionary.SeedConflict):
            self.seed({"[CITY_1]": "Milano", "[ORG_1]": "milano"})
        with self.assertRaises(pii_dictionary.InvalidSeed):
            self.seed({"[CITY_01]": "Milano"})
        with self.assertRaises(pii_dictionary.InvalidSeed):
            self.seed({"[CITY_1]": "   "})
        troppe = {"[CITY_%d]" % i: "valore %d" % i
                  for i in range(1, pii_dictionary.MAX_SEED_ENTRIES + 2)}
        with self.assertRaises(pii_dictionary.PayloadTooLarge):
            self.seed(troppe)
        with self.assertRaises(pii_dictionary.PayloadTooLarge):
            self.seed({"[CITY_1]": "a" * (pii_dictionary.MAX_ORIGINAL_CHARS + 1)})
        # Limite aggregato oltre la soglia con label inattive.
        valori = {"[CITY_%d]" % (i + 1): ("x" * 4095) + chr(0x4E00 + i)
                  for i in range(16)}
        valori["[CITY_17]"] = "z"
        with self.assertRaises(pii_dictionary.PayloadTooLarge):
            self.seed(valori)

    def test_prenotazione_placeholder_di_tutti_gli_input(self):
        inputs = [("file_1", "scrivi a x@y.it"), ("file_2", "placeholder [EMAIL_1]")]
        results, delta = pii_dictionary.anonymize_batch(
            inputs, self.seed({}), TAGS,
            detect=detect_literals(("x@y.it", "EMAIL")),
            categories={"EMAIL"})
        self.assertEqual(results[0][1]["anonymized_text"], "scrivi a [EMAIL_2]")
        self.assertEqual(results[1][1]["anonymized_text"], "placeholder [EMAIL_1]")
        self.assertEqual(results[1][1]["placeholder_count"], 1)
        self.assertEqual(delta, {"[EMAIL_2]": "x@y.it"})

    def test_riuso_normalizzato_cross_file_e_delta_delle_sole_attive(self):
        calls = []

        def detect(text, _check):
            calls.append(text)
            out = []
            if len(calls) == 1:
                position = text.find("x@y.it")
                out.append({"label": "EMAIL", "start": position,
                            "end": position + 6, "score": 0.9,
                            "validated": False, "source": "modello"})
            position = text.find("Mario")
            if position >= 0:
                out.append({"label": "FULLNAME", "start": position,
                            "end": position + 5, "score": 0.9,
                            "validated": False, "source": "modello"})
            return out

        inputs = [("file_1", "Mario x@y.it"), ("file_2", "Mario scrive a x@y.it")]
        results, delta = pii_dictionary.anonymize_batch(
            inputs, self.seed({}), TAGS, detect=detect, categories={"EMAIL"})
        self.assertEqual(results[0][1]["anonymized_text"], "Mario [EMAIL_1]")
        self.assertEqual(results[1][1]["anonymized_text"], "Mario scrive a [EMAIL_1]")
        self.assertEqual(delta, {"[EMAIL_1]": "x@y.it"})

    def test_input_batch_con_placeholder_inattivo_non_cambia(self):
        inputs = [("file_1", "scrivi a [EMAIL_9] e x@y.it"), ("file_2", "[FULLNAME_2]")]
        results, delta = pii_dictionary.anonymize_batch(
            inputs, self.seed({}), TAGS,
            detect=detect_literals(("x@y.it", "EMAIL")),
            categories={"FULLNAME"})
        self.assertEqual(results[0][1]["anonymized_text"],
                         "scrivi a [EMAIL_9] e x@y.it")
        self.assertEqual(results[0][1]["placeholder_count"], 1)
        self.assertEqual(results[1][1]["anonymized_text"], "[FULLNAME_2]")
        self.assertEqual(delta, {})


# --------------------------------------------------------------------------- #
# Arm JSON: whitelist, validazione, binder, gate
# --------------------------------------------------------------------------- #
class CategoriesJson(unittest.TestCase):
    """`process_request` arm JSON, senza Flask."""

    def setUp(self):
        self.lock = threading.Lock()
        patcher = patch.dict(os.environ, {"PII_ANALYSIS_TIMEOUT_SECONDS": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, payload=None, raw=None, detect=_detect_none, *, binder=None,
             clock=None, lock=None, token=TOKEN, headers=None, readiness=None):
        all_headers = dict(JSON_CT)
        all_headers.update(AUTH)
        if headers:
            all_headers.update(headers)
        if raw is None:
            body = payload if payload is not None else {"text": "x"}
            raw = json.dumps(body).encode("utf-8")
        kwargs = {}
        if binder is not None:
            kwargs["detect_for_categories"] = binder
        if clock is not None:
            kwargs["clock"] = clock
        return guardrail_api.process_request(
            all_headers, raw, token=token, tags=TAGS, detect=detect,
            lock=lock if lock is not None else self.lock, readiness=readiness,
            **kwargs)

    def test_assente_null_vuoto_e_catalogo_intero_sono_il_default(self):
        detect = detect_literals(("Mario", "FULLNAME"), ("x@y.it", "EMAIL"))
        baseline = self.call({"text": "Mario x@y.it"}, detect=detect)
        self.assertEqual(baseline[0], 200)
        for payload in (
                {"text": "Mario x@y.it"},
                {"text": "Mario x@y.it", "categories": None},
                {"text": "Mario x@y.it", "categories": []},
                {"text": "Mario x@y.it", "categories": ""},
                {"text": "Mario x@y.it", "categories": " \t\n"},
                {"text": "Mario x@y.it", "categories": list(TAGS)}):
            with self.subTest(payload=payload):
                self.assertEqual(self.call(payload, detect=detect), baseline)

    def test_selezione_filtra_anche_un_rilevatore_che_ignora_il_filtro(self):
        detect = detect_literals(("Mario", "FULLNAME"), ("x@y.it", "EMAIL"))
        status, body = self.call(
            {"text": "Mario x@y.it", "categories": ["FULLNAME"]}, detect=detect)
        self.assertEqual(status, 200)
        self.assertEqual(body, {
            "results": [{
                "input_id": "text",
                "anonymized_text": "[FULLNAME_1] x@y.it",
                "statistics": {"placeholder_count": 1},
            }],
            "dictionary_delta": {"[FULLNAME_1]": "Mario"},
        })
        self.assertEqual(set(body), {"results", "dictionary_delta"})
        self.assertEqual(set(body["results"][0]),
                         {"input_id", "anonymized_text", "statistics"})

    def test_valori_non_validi_400(self):
        for value in (
                "FULLNAME", "[]", "x",
                1, 0, 1.5, True, False, {"a": 1},
                [1], [None], [True], [""], ["FULLNAME", 1],
                ["NOPE"], ["fullname"], ["FULL NAME"], [" FULLNAME"],
                ["FULLNAME "], ["*"]):
            with self.subTest(value=value):
                status, body = self.call({"text": "x", "categories": value})
                self.assertEqual(status, 400, value)
                self.assertEqual(body["code"], "invalid_request")

    def test_duplicati_ammessi_e_deduplicati(self):
        detect = detect_literals(("Mario", "FULLNAME"))
        status, body = self.call(
            {"text": "Mario", "categories": ["FULLNAME", "FULLNAME", "FULLNAME"]},
            detect=detect)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"], "[FULLNAME_1]")

    def test_massimo_ventiquattro_voci_grezze(self):
        detect = detect_literals(("Mario", "FULLNAME"))
        status, _body = self.call(
            {"text": "Mario", "categories": ["FULLNAME"] * 24}, detect=detect)
        self.assertEqual(status, 200)
        status, body = self.call(
            {"text": "Mario", "categories": ["FULLNAME"] * 25}, detect=detect)
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")

    def test_chiave_categories_duplicata_400(self):
        raw = (b'{"text":"x","categories":["FULLNAME"],'
               b'"categories":["EMAIL"]}')
        status, body = self.call(raw=raw)
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")

    def test_categorie_sconosciute_prima_del_rilevatore(self):
        calls = []
        status, body = self.call(
            {"text": "Mario", "categories": ["NOPE"]},
            detect=lambda *_args: calls.append(1) or [])
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")
        self.assertEqual(calls, [])
        self.assertFalse(self.lock.locked())

    def test_binder_solo_con_selezione_attiva(self):
        seen = []

        def binder(categories):
            seen.append(categories)
            return _detect_none

        full = detect_literals(("Mario", "FULLNAME"))
        status, body = self.call({"text": "Mario"}, detect=full, binder=binder)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"], "[FULLNAME_1]")
        self.assertEqual(seen, [])
        status, body = self.call({"text": "Mario", "categories": list(TAGS)},
                                 detect=full, binder=binder)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"], "[FULLNAME_1]")
        self.assertEqual(seen, [])
        status, body = self.call({"text": "Mario", "categories": ["EMAIL"]},
                                 detect=full, binder=binder)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"], "Mario")
        self.assertEqual(seen, [frozenset({"EMAIL"})])

    def test_richieste_consecutive_indipendenti(self):
        detect = detect_literals(("Mario", "FULLNAME"), ("x@y.it", "EMAIL"))
        first = self.call({"text": "Mario x@y.it", "categories": ["FULLNAME"]},
                          detect=detect)
        second = self.call({"text": "Mario x@y.it", "categories": ["EMAIL"]},
                           detect=detect)
        third = self.call({"text": "Mario x@y.it"}, detect=detect)
        self.assertEqual(first[1]["results"][0]["anonymized_text"],
                         "[FULLNAME_1] x@y.it")
        self.assertEqual(second[1]["results"][0]["anonymized_text"],
                         "Mario [EMAIL_1]")
        self.assertEqual(third[1]["results"][0]["anonymized_text"],
                         "[FULLNAME_1] [EMAIL_1]")

    def test_richieste_concorrenti_indipendenti(self):
        detect = detect_literals(("Mario", "FULLNAME"), ("x@y.it", "EMAIL"))
        out = {}

        def worker(name, categories):
            out[name] = self.call(
                {"text": "Mario x@y.it", "categories": categories},
                detect=detect, lock=threading.Lock())

        threads = [threading.Thread(target=worker, args=("fullname", ["FULLNAME"])),
                   threading.Thread(target=worker, args=("email", ["EMAIL"]))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(out["fullname"][1]["results"][0]["anonymized_text"],
                         "[FULLNAME_1] x@y.it")
        self.assertEqual(out["email"][1]["results"][0]["anonymized_text"],
                         "Mario [EMAIL_1]")

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
        status, body = probe({}, token="   ")
        self.assertEqual((status, body["code"]), (503, "unavailable"))
        status, body = probe(dict(JSON_CT, **AUTH), detect=None)
        self.assertEqual((status, body["code"]), (503, "unavailable"))
        status, body = probe(dict(JSON_CT, **AUTH), readiness=lambda: False)
        self.assertEqual((status, body["code"]), (503, "unavailable"))
        lock = threading.Lock()
        lock.acquire()
        try:
            status, body = probe(dict(JSON_CT, **AUTH), lock=lock)
        finally:
            lock.release()
        self.assertEqual((status, body["code"]), (429, "busy"))

    def test_timeout_con_categories_504_e_lock_rilasciato(self):
        clock = Clock()

        def detect(_text, check):
            clock.now = 61.0
            check()
            return []

        status, body = self.call({"text": "Mario", "categories": ["EMAIL"]},
                                 detect=detect, clock=clock)
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")
        self.assertFalse(self.lock.locked())

    def test_readiness_false_non_chiama_il_rilevatore(self):
        calls = []
        status, body = self.call(
            {"text": "Mario", "categories": ["EMAIL"]},
            detect=lambda *_args: calls.append(1) or [],
            readiness=lambda: False)
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "unavailable")
        self.assertEqual(calls, [])
        self.assertFalse(self.lock.locked())

    def test_errore_sanificato_senza_echo_della_label(self):
        secret = "LABEL-SEGRETA-123"
        status, body = self.call({"text": "Mario", "categories": [secret]})
        self.assertEqual(status, 400)
        self.assertEqual(set(body), {"error", "code"})
        self.assertNotIn(secret, json.dumps(body))

    def test_regex_only_url_e_ipaddr_selezionabili(self):
        detect = detect_literals(("www.studiorossi.it", "URL"),
                                 ("192.168.1.1", "IPADDR"),
                                 ("Mario", "FULLNAME"))
        payload = {"text": "Mario www.studiorossi.it 192.168.1.1",
                   "categories": ["URL", "IPADDR"]}
        status, body = self.call(payload, detect=detect)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"],
                         "Mario [URL_1] [IPADDR_1]")
        self.assertEqual(body["dictionary_delta"],
                         {"[URL_1]": "www.studiorossi.it",
                          "[IPADDR_1]": "192.168.1.1"})


# --------------------------------------------------------------------------- #
# Arm multipart: campo categories, limiti, estrazione
# --------------------------------------------------------------------------- #
@unittest.skipUnless(HAVE_NATIVE, "Werkzeug assente: parser multipart non disponibile")
class MultipartParserCategories(unittest.TestCase):
    def parse(self, parts):
        return guardrail_inputs.parse_multipart(
            _body(parts), {"boundary": BOUND}, None)

    def test_quarta_componente_e_facoltativa(self):
        documents, text, dictionary, categories = self.parse(
            [("categories", None, '["EMAIL"]'), ("text", None, "x")])
        self.assertEqual(documents, [])
        self.assertEqual(text, "x")
        self.assertIsNone(dictionary)
        self.assertEqual(categories, '["EMAIL"]')
        _docs, _text, _dict, categories = self.parse([("text", None, "x")])
        self.assertIsNone(categories)


@unittest.skipUnless(HAVE_NATIVE, "Werkzeug assente: parser multipart non disponibile")
class MultipartCategories(unittest.TestCase):
    """`process_request` multipart: selezione, validazione e indipendenza."""

    def setUp(self):
        self.lock = threading.Lock()
        patcher = patch.dict(os.environ, {"PII_ANALYSIS_TIMEOUT_SECONDS": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, raw, *, detect=_detect_none, extract=_extract_utf8,
             binder=None, clock=None, lock=None):
        headers = dict(AUTH)
        headers["Content-Type"] = "multipart/form-data; boundary=" + BOUND
        kwargs = {}
        if binder is not None:
            kwargs["detect_for_categories"] = binder
        if clock is not None:
            kwargs["clock"] = clock
        return guardrail_api.process_request(
            headers, raw, token=TOKEN, tags=TAGS, detect=detect, extract=extract,
            lock=lock if lock is not None else self.lock, **kwargs)

    def test_selezione_multipart_filtra_i_file(self):
        detect = detect_literals(("Mario", "FULLNAME"), ("x@y.it", "EMAIL"))
        raw = _body([
            ("categories", None, '["FULLNAME"]'),
            ("files", "a.txt", "Mario scrive a x@y.it"),
        ])
        status, body = self.call(raw, detect=detect)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"],
                         "[FULLNAME_1] scrive a x@y.it")
        self.assertEqual(body["dictionary_delta"], {"[FULLNAME_1]": "Mario"})

    def test_assente_blank_null_lista_e_stringa_blank_sono_default(self):
        detect = detect_literals(("Mario", "FULLNAME"), ("x@y.it", "EMAIL"))
        baseline = self.call(_body([("text", None, "Mario x@y.it")]),
                             detect=detect)
        self.assertEqual(baseline[0], 200)
        for value in (None, "", "   ", "null", "[]", '"   "', '""'):
            with self.subTest(value=value):
                parts = []
                if value is not None:
                    parts.append(("categories", None, value))
                parts.append(("text", None, "Mario x@y.it"))
                self.assertEqual(self.call(_body(parts), detect=detect), baseline)

    def test_valori_multipart_non_validi_400(self):
        for value in ('"FULLNAME"', '["FULLNAME"', '["NOPE"]', "[1]",
                      '{"a": 1}', "FULLNAME", b"\xff", '["fullname"]',
                      '[" FULLNAME"]'):
            with self.subTest(value=value):
                raw = _body([("categories", None, value), ("text", None, "x")])
                status, body = self.call(raw)
                self.assertEqual(status, 400, value)
                self.assertEqual(body["code"], "invalid_request")
                self.assertFalse(self.lock.locked())

    def test_categories_duplicato_o_file_part_400(self):
        raw = _body([("categories", None, "[]"), ("categories", None, "[]"),
                     ("text", None, "x")])
        status, body = self.call(raw)
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")
        raw = _body([("categories", "lista.txt", "[]"), ("text", None, "x")])
        status, body = self.call(raw)
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")

    def test_categorie_sconosciute_prima_di_estrazione_e_rilevatore(self):
        calls = []

        def extract(*_args):
            calls.append("extract")
            return "x"

        status, body = self.call(
            _body([("categories", None, '["NOPE"]'),
                   ("files", "a.txt", "Mario")]),
            extract=extract, detect=lambda *_args: calls.append("detect") or [])
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")
        self.assertEqual(calls, [])
        self.assertFalse(self.lock.locked())

    def test_tredici_parti_valide_e_quattordici_respinte(self):
        self.assertEqual(guardrail_inputs.MAX_MULTIPART_PARTS, 13)
        detect = detect_literals(("x@y.it", "EMAIL"))
        parts = [("files", "f%d.txt" % i, "testo %d" % i) for i in range(10)]
        parts += [("text", None, "coda x@y.it"), ("dictionary", None, "{}"),
                  ("categories", None, '["EMAIL"]')]
        status, body = self.call(_body(parts), detect=detect)
        self.assertEqual(status, 200)
        self.assertEqual(len(body["results"]), 11)
        self.assertEqual(body["results"][0]["input_id"], "file_1")
        self.assertEqual(body["results"][10]["input_id"], "text")
        self.assertIn("[EMAIL_1]", body["results"][10]["anonymized_text"])
        parts.append(("text", None, "ancora"))
        status, body = self.call(_body(parts), detect=detect)
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "payload_too_large")

    def test_selezione_su_file_piu_text_opzionale_ed_extractor_assente(self):
        detect = detect_literals(("Mario", "FULLNAME"), ("x@y.it", "EMAIL"))
        raw = _body([
            ("categories", None, '["EMAIL"]'),
            ("text", None, "coda Mario x@y.it"),
        ])
        status, body = self.call(raw, detect=detect, extract=None)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["input_id"], "text")
        self.assertEqual(body["results"][0]["anonymized_text"],
                         "coda Mario [EMAIL_1]")

    def test_binder_multipart_e_skip_del_default(self):
        seen = []

        def binder(categories):
            seen.append(categories)
            return _detect_none

        status, _response = self.call(
            _body([("categories", None, '["EMAIL"]'), ("text", None, "x")]),
            binder=binder)
        self.assertEqual(status, 200)
        self.assertEqual(seen, [frozenset({"EMAIL"})])
        status, _response = self.call(_body([("text", None, "x")]), binder=binder)
        self.assertEqual(status, 200)
        self.assertEqual(seen, [frozenset({"EMAIL"})])

    def test_seed_inattivo_non_blocca_il_file(self):
        seed = '{"[ORG_1]": "Studio Rossi"}'
        detect = detect_literals(("Rossi", "FULLNAME"))
        raw = _body([
            ("categories", None, '["FULLNAME"]'),
            ("dictionary", None, seed),
            ("files", "a.txt", "Studio Rossi"),
        ])
        status, body = self.call(raw, detect=detect)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"],
                         "Studio [FULLNAME_1]")
        self.assertEqual(body["dictionary_delta"], {"[FULLNAME_1]": "Rossi"})

    def test_file_vuoto_all_or_nothing_con_selezione(self):
        calls = []

        def extract(_name, data, _remaining, _check):
            if not data:
                raise guardrail_inputs.InputError(422, "empty_file")
            return data.decode("utf-8")

        raw = _body([
            ("categories", None, '["FULLNAME"]'),
            ("files", "ok.txt", "Mario"),
            ("files", "vuoto.txt", b""),
        ])
        status, body = self.call(
            raw, extract=extract,
            detect=lambda *_args: calls.append(1) or [])
        self.assertEqual(status, 422)
        self.assertEqual(body, {"error": "File is empty.", "code": "empty_file"})
        self.assertEqual(calls, [])
        self.assertFalse(self.lock.locked())


# --------------------------------------------------------------------------- #
# Adapter di app.py: filtro PRIMA del merge e binder
# --------------------------------------------------------------------------- #
def _load_adapter_functions():
    """Estrae `_guardrail_detect` + `_guardrail_detect_for_categories` con ast."""
    tree = ast.parse(APP_SRC.read_text(encoding="utf-8"))
    wanted = ("_guardrail_detect", "_guardrail_detect_for_categories")
    functions = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in wanted]
    if len(functions) != len(wanted):
        raise AssertionError("adapter guardrail non trovato in app.py")
    namespace = {"runtime_execution": runtime_execution}
    exec(compile(ast.Module(functions, []), "app.py", "exec"), namespace)
    return namespace


class AppAdapterCategories(unittest.TestCase):
    """Il codice spedito: la selezione vale PRIMA della fusione modello+regex."""

    def setUp(self):
        self.ns = _load_adapter_functions()
        self.calls = {"nlp": [], "regex": [], "merge": [], "checks": 0}

    def _wire(self, chunks, nlp_results, regex):
        def nlp(inputs):
            self.calls["nlp"].append(list(inputs))
            return [nlp_results[len(self.calls["nlp"]) - 1]]

        def detect_regex(text):
            self.calls["regex"].append(text)
            return list(regex)

        def complete_time(ents, _text):
            return ents

        def merge(cands, _text):
            self.calls["merge"].append([c["label"] for c in cands])
            return cands

        self.ns.update({
            "guardrail_api": guardrail_api,
            "nlp": nlp,
            "chunk_text": lambda _text: list(chunks),
            "detect_regex": detect_regex,
            "complete_time": complete_time,
            "_merge": merge,
        })

    def test_filtro_prima_del_merge_tiene_il_modello_attivo(self):
        self._wire(
            [("www.studiorossi.it", 0)],
            [[{"entity_group": "FULLNAME", "start": 0, "end": 18, "score": 0.9}]],
            [{"label": "URL", "start": 0, "end": 18, "score": 0.9,
              "validated": False, "source": "regex"}])
        detect = self.ns["_guardrail_detect_for_categories"](frozenset({"FULLNAME"}))
        out = detect("www.studiorossi.it", lambda: None)
        self.assertEqual(self.calls["merge"], [["FULLNAME"]])
        self.assertEqual([(e["label"], e["start"], e["end"]) for e in out],
                         [("FULLNAME", 0, 18)])

    def test_senza_selezione_il_merge_vede_entrambi(self):
        self._wire(
            [("www.studiorossi.it", 0)],
            [[{"entity_group": "FULLNAME", "start": 0, "end": 18, "score": 0.9}]],
            [{"label": "URL", "start": 0, "end": 18, "score": 0.9,
              "validated": False, "source": "regex"}])
        out = self.ns["_guardrail_detect"]("www.studiorossi.it", lambda: None)
        self.assertEqual(self.calls["merge"], [["FULLNAME", "URL"]])
        self.assertEqual(len(out), 2)

    def test_binder_filtra_anche_url_e_ipaddr(self):
        self._wire(
            [("Mario www.studiorossi.it 192.168.1.1", 0)],
            [[{"entity_group": "FULLNAME", "start": 0, "end": 5, "score": 0.9}]],
            [{"label": "URL", "start": 6, "end": 24, "score": 0.9,
              "validated": False, "source": "regex"},
             {"label": "IPADDR", "start": 25, "end": 36, "score": 0.9,
              "validated": False, "source": "regex"}])
        detect = self.ns["_guardrail_detect_for_categories"](["URL", "IPADDR"])
        out = detect("Mario www.studiorossi.it 192.168.1.1", lambda: None)
        self.assertEqual(self.calls["merge"], [["URL", "IPADDR"]])
        self.assertEqual([e["label"] for e in out], ["URL", "IPADDR"])

    def test_binder_istanze_indipendenti(self):
        self._wire(
            [("Mario www.studiorossi.it", 0)],
            [[{"entity_group": "FULLNAME", "start": 0, "end": 5, "score": 0.9}],
             [{"entity_group": "FULLNAME", "start": 0, "end": 5, "score": 0.9}]],
            [{"label": "URL", "start": 6, "end": 24, "score": 0.9,
              "validated": False, "source": "regex"}])
        fullname = self.ns["_guardrail_detect_for_categories"](["FULLNAME"])
        url = self.ns["_guardrail_detect_for_categories"](["URL"])
        fullname("Mario www.studiorossi.it", lambda: None)
        url("Mario www.studiorossi.it", lambda: None)
        self.assertEqual(self.calls["merge"], [["FULLNAME"], ["URL"]])


# --------------------------------------------------------------------------- #
# Cablaggio reale con app.py: regex vera, modello finto
# --------------------------------------------------------------------------- #
def _import_app_with_mocks():
    if "app" in sys.modules:
        return sys.modules["app"]
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
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        sys.modules.pop("pdf_export", None)
        sys.modules.pop("pdf_text", None)
    return app_module


def _real_module(name):
    module = sys.modules.get(name)
    if module is None or isinstance(module, MagicMock):
        sys.modules.pop(name, None)
        return __import__(name)
    return module


def _pdf_bytes(lines):
    doc = fitz.open()
    page = doc.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72, 72 + 14 * index), line)
    data = doc.tobytes()
    doc.close()
    return data


@unittest.skipUnless(HAVE_NATIVE and HAVE_FLASK,
                     "Flask/Werkzeug assenti: cablaggio app non testabile")
class AppWiringCategories(unittest.TestCase):
    """app.py vero: regex vera, modello finto, PyMuPDF vero quando c'e'."""

    @classmethod
    def setUpClass(cls):
        cls.APP = _import_app_with_mocks()

    def setUp(self):
        self._stack = contextlib.ExitStack()
        self.addCleanup(self._stack.close)
        self._stack.enter_context(patch.dict(os.environ, {"PII_API_TOKEN": TOKEN}))
        if HAVE_FITZ:
            self._stack.enter_context(patch.object(self.APP, "fitz",
                                                   _real_module("fitz")))
            self._stack.enter_context(patch.object(self.APP, "pdf_text",
                                                   _real_module("pdf_text")))
        self.client = self.APP.app.test_client()

    def _nlp(self, pairs):
        def nlp(chunks):
            out = []
            for chunk in chunks:
                entities = []
                for label, literal in pairs:
                    position = chunk.find(literal)
                    if position >= 0:
                        entities.append({"entity_group": label, "start": position,
                                         "end": position + len(literal),
                                         "score": 0.9, "word": literal})
                out.append(entities)
            return out
        return nlp

    def post(self, payload):
        return self.client.post(
            PATH, data=json.dumps(payload).encode("utf-8"),
            content_type="application/json", headers=dict(AUTH))

    def test_binder_reale_risolve_l_overlap_prima_del_merge(self):
        with patch.object(self.APP, "nlp",
                          self._nlp([("FULLNAME", "www.studiorossi.it")])):
            response = self.post({"text": "www.studiorossi.it",
                                  "categories": ["FULLNAME"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["anonymized_text"],
                         "[FULLNAME_1]")
        with patch.object(self.APP, "nlp",
                          self._nlp([("FULLNAME", "www.studiorossi.it")])):
            response = self.post({"text": "www.studiorossi.it"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["anonymized_text"],
                         "[URL_1]")

    def test_regex_url_e_ipaddr_reali_selezionabili(self):
        with patch.object(self.APP, "nlp",
                          self._nlp([("FULLNAME", "Mario Rossi")])):
            response = self.post({
                "text": "Mario Rossi www.studiorossi.it 192.168.1.1",
                "categories": ["URL", "IPADDR"]})
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["results"][0]["anonymized_text"],
                         "Mario Rossi [URL_1] [IPADDR_1]")
        with patch.object(self.APP, "nlp",
                          self._nlp([("FULLNAME", "Mario Rossi")])):
            response = self.post({
                "text": "Mario Rossi www.studiorossi.it 192.168.1.1",
                "categories": ["FULLNAME"]})
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["results"][0]["anonymized_text"],
                         "[FULLNAME_1] www.studiorossi.it 192.168.1.1")

    def test_solo_la_richiesta_sceglie_ignora_env_e_preferenze(self):
        with patch.dict(os.environ, {"PII_EXCLUDE_TAGS": "FULLNAME",
                                     "PII_MAPPING": "0"}), \
                patch.object(self.APP, "EXCLUDED_TAGS", {"FULLNAME"}), \
                patch.object(self.APP, "nlp",
                             self._nlp([("FULLNAME", "Mario Rossi"),
                                        ("EMAIL", "mario.rossi@example.com")])):
            selected = self.post({
                "text": "Mario Rossi mario.rossi@example.com",
                "categories": ["EMAIL"]})
            full = self.post({"text": "Mario Rossi mario.rossi@example.com"})
        self.assertEqual(selected.get_json()["results"][0]["anonymized_text"],
                         "Mario Rossi [EMAIL_1]")
        self.assertEqual(full.get_json()["results"][0]["anonymized_text"],
                         "[FULLNAME_1] [EMAIL_1]")

    def test_richieste_consecutive_http_indipendenti(self):
        with patch.object(self.APP, "nlp",
                          self._nlp([("FULLNAME", "Mario Rossi"),
                                     ("EMAIL", "mario.rossi@example.com")])):
            first = self.post({"text": "Mario Rossi mario.rossi@example.com",
                               "categories": ["FULLNAME"]})
            second = self.post({"text": "Mario Rossi mario.rossi@example.com",
                                "categories": ["EMAIL"]})
        self.assertEqual(first.get_json()["results"][0]["anonymized_text"],
                         "[FULLNAME_1] mario.rossi@example.com")
        self.assertEqual(second.get_json()["results"][0]["anonymized_text"],
                         "Mario Rossi [EMAIL_1]")

    def test_errore_categories_http_no_store_e_sanificato(self):
        secret = "LABEL-SEGRETA-999"
        response = self.post({"text": "Mario Rossi", "categories": [secret]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(set(response.get_json()), {"error", "code"})
        self.assertNotIn(secret, response.get_data(as_text=True))

    def test_gate_http_token_sbagliato_non_legge_il_body(self):
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
        payload = b'{"text":"Mario","categories":["EMAIL"]}'
        response = self.client.post(
            PATH, data=payload, content_type="application/json",
            headers={"Authorization": "Bearer sbagliato"},
            environ_overrides={"wsgi.input": stream})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(stream.calls, 0)

    def test_pdf_reale_con_selezione_categories(self):
        if not HAVE_FITZ:
            self.skipTest("PyMuPDF assente")
        self.assertTrue(self.APP.MUPDF_PRIVACY_OK)
        pdf = _pdf_bytes(["Mario Rossi mario.rossi@example.com"])
        with patch.object(self.APP, "nlp",
                          self._nlp([("FULLNAME", "Mario Rossi")])):
            emails = self.client.post(
                PATH, data=_body([("categories", None, '["EMAIL"]'),
                                  ("files", "atto.pdf", pdf)]),
                content_type="multipart/form-data; boundary=" + BOUND,
                headers=dict(AUTH))
            names = self.client.post(
                PATH, data=_body([("categories", None, '["FULLNAME"]'),
                                  ("files", "atto.pdf", pdf)]),
                content_type="multipart/form-data; boundary=" + BOUND,
                headers=dict(AUTH))
        self.assertEqual(emails.status_code, 200)
        self.assertEqual(names.status_code, 200)
        email_text = emails.get_json()["results"][0]["anonymized_text"]
        name_text = names.get_json()["results"][0]["anonymized_text"]
        self.assertIn("Mario Rossi", email_text)
        self.assertIn("[EMAIL_1]", email_text)
        self.assertIn("[FULLNAME_1]", name_text)
        self.assertIn("mario.rossi@example.com", name_text)
        self.assertNotIn("[EMAIL_1]", name_text)
        self.assertEqual(emails.get_json()["dictionary_delta"],
                         {"[EMAIL_1]": "mario.rossi@example.com"})


@unittest.skipUnless(HAVE_FLASK, "Flask assente")
class CategoriesHTTP(unittest.TestCase):
    """Test client Flask: sola selezione della richiesta, no-store invariato."""

    def setUp(self):
        self.lock = threading.Lock()
        application = Flask("guardrail-categories-test")
        application.config["TESTING"] = True
        application.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
        blueprint = guardrail_api.create_blueprint(
            TAGS, detect_literals(("Mario", "FULLNAME"), ("x@y.it", "EMAIL")),
            lock=self.lock)
        application.register_blueprint(blueprint)
        self.client = application.test_client()
        patcher = patch.dict(os.environ, {"PII_API_TOKEN": TOKEN,
                                          "PII_ANALYSIS_TIMEOUT_SECONDS": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, payload=None, raw=None):
        if raw is None:
            raw = json.dumps(payload if payload is not None
                             else {"text": "Mario x@y.it"}).encode("utf-8")
        return self.client.post(PATH, data=raw,
                                content_type="application/json",
                                headers=dict(AUTH))

    def test_selezione_http_e_forma_della_risposta(self):
        response = self.post({"text": "Mario x@y.it", "categories": ["EMAIL"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        body = response.get_json()
        self.assertEqual(body, {
            "results": [{
                "input_id": "text",
                "anonymized_text": "Mario [EMAIL_1]",
                "statistics": {"placeholder_count": 1},
            }],
            "dictionary_delta": {"[EMAIL_1]": "x@y.it"},
        })

    def test_categories_non_valido_http_400_no_store(self):
        response = self.post({"text": "x", "categories": "EMAIL"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.get_json()["code"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
