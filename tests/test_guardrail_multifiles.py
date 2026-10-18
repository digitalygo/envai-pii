# -*- coding: utf-8 -*-
"""Guardrail API v1, estensione multifile (`multipart/form-data`).

Copre il parser nativo Werkzeug, la validazione del contratto, i limiti, lo
stato condiviso fra input, il cablaggio Flask e il cablaggio reale con app.py
(regex vera, PyMuPDF vero, modello finto). I test che richiedono Werkzeug,
Flask o PyMuPDF si saltano SOLO se la dipendenza manca (CI stdlib); nella
venv reale girano tutti. Nessun peso, nessuna rete, nessun server. Valori
SINTETICI.
"""

import ast
import contextlib
import json
import logging
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "app"))

import guardrail_api  # noqa: E402
import guardrail_inputs  # noqa: E402
import pii_dictionary  # noqa: E402

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

TOKEN = "token-multifiles"
AUTH = {"Authorization": "Bearer " + TOKEN}
PATH = "/api/v1/analyses"
APP_SRC = ROOT / "src" / "app" / "app.py"
BOUND = "BOUND"


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


def _extract_error(status, code):
    def extract(_name, _data, _remaining, _check):
        raise guardrail_inputs.InputError(status, code)
    return extract


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
    def __init__(self, now=0.0, after=0):
        self.now = now
        self.after = after
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.after and self.calls >= self.after:
            return 61.0
        return self.now


@unittest.skipUnless(HAVE_NATIVE, "Werkzeug assente: parser multipart non disponibile")
class MultipartParsing(unittest.TestCase):
    def parse(self, raw, params=None, check=None):
        return guardrail_inputs.parse_multipart(
            raw, params if params is not None else {"boundary": BOUND}, check)

    def assert_input_error(self, raw, status, code, params=None):
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.parse(raw, params)
        self.assertEqual(ctx.exception.status, status)
        self.assertEqual(ctx.exception.code, code)

    def test_campi_base(self):
        raw = _body([("files", "nota.txt", "ciao"),
                     ("text", None, "Referente"),
                     ("dictionary", None, "{}")])
        documents, text, dictionary, _categories = self.parse(raw)
        self.assertEqual(documents, [("nota.txt", b"ciao")])
        self.assertEqual(text, "Referente")
        self.assertEqual(dictionary, "{}")

    def test_text_blank_e_assente_e_originale_non_strippato(self):
        _docs, text, _dict, _categories = self.parse(_body([("text", None, "   \n")]))
        self.assertIsNone(text)
        _docs, text, _dict, _categories = self.parse(_body([("text", None, "  ciao  ")]))
        self.assertEqual(text, "  ciao  ")

    def test_testo_prima_dei_file_nel_body(self):
        raw = _body([("text", None, "dopo"),
                     ("files", "a.txt", "uno"),
                     ("files", "b.txt", "due")])
        documents, text, _dict, _categories = self.parse(raw)
        self.assertEqual([name for name, _data in documents], ["a.txt", "b.txt"])
        self.assertEqual(text, "dopo")

    def test_filename_duplicati_validi_e_distinti(self):
        documents, _text, _dict, _categories = self.parse(
            _body([("files", "uguale.txt", "uno"), ("files", "uguale.txt", "due")]))
        self.assertEqual(documents, [("uguale.txt", b"uno"), ("uguale.txt", b"due")])

    def test_estensioni_case_insensitive(self):
        documents, _text, _dict, _categories = self.parse(
            _body([("files", "ATTO.PDF", b"%PDF"),
                   ("files", "Note.MD", "x"),
                   ("files", "a.MARKDOWN", "y"),
                   ("files", "b.TEXT", "z")]))
        self.assertEqual(len(documents), 4)

    def test_filename_utf8_e_rfc2231(self):
        documents, _text, _dict, _categories = self.parse(
            _body([("files", "näme.txt", "x")]))
        self.assertEqual(documents[0][0], "näme.txt")
        raw = (b"--BOUND\r\nContent-Disposition: form-data; name=\"files\"; "
               b"filename*=utf-8''n%C3%A4me.pdf\r\n\r\ndata\r\n--BOUND--\r\n")
        documents, _text, _dict, _categories = self.parse(raw)
        self.assertEqual(documents[0][0], "näme.pdf")
        fallback = (b"--BOUND\r\nContent-Disposition: form-data; name=\"files\"; "
                    b"filename=legacy.txt; filename*=utf-8''n%C3%A4me.pdf\r\n"
                    b"\r\ndata\r\n--BOUND--\r\n")
        documents, _text, _dict, _categories = self.parse(fallback)
        self.assertEqual(documents[0][0], "näme.pdf")

    def test_filename_quoted_con_semicolon_e_testo_name_equals(self):
        raw = (b"--BOUND\r\nContent-Disposition: form-data; name=\"files\"; "
               b'filename="note; name=inside.txt"\r\n\r\nhello\r\n'
               b"--BOUND--\r\n")
        documents, _text, _dict, _categories = self.parse(raw)
        self.assertEqual(documents, [("note; name=inside.txt", b"hello")])
        escaped_quote = (b"--BOUND\r\nContent-Disposition: form-data; "
                         b'name="files"; filename="note\\\"; name=inside.txt"'
                         b"\r\n\r\nhello\r\n--BOUND--\r\n")
        documents, _text, _dict, _categories = self.parse(escaped_quote)
        self.assertEqual(documents, [("note\"; name=inside.txt", b"hello")])

    def test_estensione_non_supportata_415(self):
        for filename in ("atto.docx", "script.exe", "senzaestensione", ".txt"):
            self.assert_input_error(_body([("files", filename, "x")]),
                                    415, "unsupported_file_type")

    def test_campi_valore_utf8_stretti(self):
        raw = _body([("text", None, b"\xff\xfe")])
        self.assert_input_error(raw, 400, "invalid_request")
        raw = _body([("dictionary", None, b"\xff")])
        self.assert_input_error(raw, 400, "invalid_request")

    def test_boundary_mancante_vuoto_non_ascii_o_lungo(self):
        raw = _body([("text", None, "x")])
        self.assert_input_error(raw, 400, "invalid_request", params={})
        self.assert_input_error(raw, 400, "invalid_request",
                                params={"boundary": ""})
        self.assert_input_error(raw, 400, "invalid_request",
                                params={"boundary": "caf\u00e9"})
        self.assert_input_error(raw, 400, "invalid_request",
                                params={"boundary": "x" * 71})
        for boundary in ("x\r\ny", "x\x00y", "white space"):
            self.assert_input_error(raw, 400, "invalid_request",
                                    params={"boundary": boundary})

    def test_corpo_troncato_o_non_multipart_400(self):
        good = _body([("text", None, "x")])
        self.assert_input_error(good[:-len(b"--BOUND--\r\n")] + b"x",
                                400, "invalid_request")
        self.assert_input_error(b"", 400, "invalid_request")
        self.assert_input_error(b"non e' multipart", 400, "invalid_request")
        self.assert_input_error(b'{"text":"x"}', 400, "invalid_request")

    def test_content_disposition_tokenizer_rejects_malformed_parameters(self):
        malformed = (
            None,
            "; name=text",
            "form-data name=text",
            "form-data; name",
            "form-data; name=",
            'form-data; filename="unterminated',
            'form-data; filename="trailing' + chr(92),
            'form-data; filename="escaped' + "\\" + "\x00\"",
            'form-data; filename="raw\x00control"',
        )
        for raw in malformed:
            with self.subTest(raw=raw):
                with self.assertRaises(guardrail_inputs.InputError):
                    guardrail_inputs._validate_content_disposition(raw)

    def test_content_disposition_ambigua(self):
        self.assert_input_error(
            b"--BOUND\r\nContent-Disposition: form-data\r\n\r\nx\r\n"
            b"--BOUND--\r\n", 400, "invalid_request")
        self.assert_input_error(
            b"--BOUND\r\nContent-Disposition: attachment; name=\"text\"\r\n\r\nx\r\n"
            b"--BOUND--\r\n", 400, "invalid_request")
        self.assert_input_error(
            b"--BOUND\r\nContent-Disposition: form-data; name=\"text\"\r\n"
            b"Content-Disposition: form-data; name=\"text\"\r\n\r\nx\r\n"
            b"--BOUND--\r\n", 400, "invalid_request")
        self.assert_input_error(
            b"--BOUND\r\nContent-Disposition: form-data; name\r\n\r\nx\r\n"
            b"--BOUND--\r\n", 400, "invalid_request")
        for disposition in (
                b'form-data; name="dictionary"; name="files"; filename="note.txt"',
                b'form-data; name="files"; NAME="files"; filename="note.txt"',
                b'form-data; name="files"; filename="note.txt"; FILENAME="note.txt"',
                b'form-data; name="text'):
            raw = (b"--BOUND\r\nContent-Disposition: " + disposition
                   + b"\r\n\r\nhello\r\n--BOUND--\r\n")
            self.assert_input_error(raw, 400, "invalid_request")
        # Header non decodificabile in UTF-8: mai un replace silenzioso.
        self.assert_input_error(
            b"--BOUND\r\nContent-Disposition: form-data; name=\"te\xffxt\"\r\n\r\nx\r\n"
            b"--BOUND--\r\n", 400, "invalid_request")

    def test_nomi_campo_e_filename(self):
        self.assert_input_error(_body([("altro", None, "x")]), 400, "invalid_request")
        self.assert_input_error(_body([("text", None, "a"), ("text", None, "b")]),
                                400, "invalid_request")
        self.assert_input_error(_body([("files", None, "x")]), 400, "invalid_request")
        self.assert_input_error(_body([("files", "", "x")]), 400, "invalid_request")
        self.assert_input_error(_body([("file", "a.txt", "x")]), 400, "invalid_request")
        self.assert_input_error(_body([("Files", "a.txt", "x")]),
                                400, "invalid_request")
        self.assert_input_error(_body([("text", "a.txt", "x")]),
                                400, "invalid_request")
        self.assert_input_error(_body([("dictionary", "a.txt", "{}")]),
                                400, "invalid_request")
        self.assert_input_error(
            _body([("dictionary", None, "{}"), ("dictionary", None, "{}")]),
            400, "invalid_request")

    def test_limite_part_count_14(self):
        parts = [("files", "f%d.txt" % i, "x") for i in range(10)]
        parts += [("text", None, "t"), ("dictionary", None, "{}"),
                  ("categories", None, '["EMAIL"]'), ("text", None, "ancora")]
        self.assert_input_error(_body(parts), 413, "payload_too_large")

    def test_limite_dieci_file(self):
        parts = [("files", "f%d.txt" % i, "x") for i in range(11)]
        self.assert_input_error(_body(parts), 413, "payload_too_large")

    def test_limite_file_5mib(self):
        limit = guardrail_inputs.MAX_FILE_BYTES
        self.assert_input_error(
            _body([("files", "grande.txt", b"a" * (limit + 1))]),
            413, "payload_too_large")
        documents, _text, _dict, _categories = self.parse(
            _body([("files", "grande.txt", b"a" * limit)]))
        self.assertEqual(len(documents[0][1]), limit)

    def test_limite_campo_valore_1mib(self):
        limit = guardrail_inputs.MAX_FORM_FIELD_BYTES
        self.assert_input_error(_body([("text", None, b"a" * (limit + 1))]),
                                413, "payload_too_large")

    def test_epilogo_ignorato(self):
        raw = _body([("text", None, "x")]) + b"spazzatura di epilogo"
        documents, text, _dict, _categories = self.parse(raw)
        self.assertEqual((documents, text), ([], "x"))


@unittest.skipUnless(HAVE_NATIVE, "Werkzeug assente: parser multipart non disponibile")
class EndpointMultipart(unittest.TestCase):
    """`process_request` con il ramo multipart, senza Flask."""

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

    def call(self, raw, *, extract=_extract_utf8, detect=_detect_none, token=TOKEN,
             content_type="multipart/form-data; boundary=" + BOUND, headers=None,
             clock=None, lock=None):
        all_headers = dict(AUTH)
        if content_type is not None:
            all_headers["Content-Type"] = content_type
        if headers:
            all_headers.update(headers)
        kwargs = {"clock": clock} if clock is not None else {}
        return guardrail_api.process_request(
            all_headers, raw, token=token, tags=TAGS, detect=detect,
            extract=extract, lock=lock if lock is not None else self.lock, **kwargs)

    def test_content_type_multipart_charset(self):
        raw = _body([("text", None, "x")])
        status, body = self.call(
            raw, content_type="multipart/form-data; boundary=" + BOUND
            + "; charset=UTF-8")
        self.assertEqual(status, 200)
        status, body = self.call(
            raw, content_type="multipart/form-data; boundary=" + BOUND
            + "; charset=latin-1")
        self.assertEqual(status, 415)
        self.assertEqual(body["code"], "unsupported_media_type")

    def test_boundary_lungo_settanta_byte(self):
        boundary = "x" * 70
        raw = _body([("text", None, "x")], boundary=boundary)
        status, _body_response = self.call(
            raw, content_type="multipart/form-data; boundary=" + boundary)
        self.assertEqual(status, 200)

    def test_dieci_file_piu_text_undici_risultati(self):
        parts = [("dictionary", None, "{}")]
        parts += [("files", "f%d.txt" % i, "testo %d" % i) for i in range(10)]
        parts.append(("text", None, "testo finale"))
        status, body = self.call(_body(parts))    # 12 parti: sotto il tetto esatto di 13
        # (10 file + text + dictionary + categories)
        self.assertEqual(status, 200)
        self.assertEqual([r["input_id"] for r in body["results"]],
                         ["file_%d" % i for i in range(1, 11)] + ["text"])
        self.assertEqual(len(body["results"]), 11)
        self.assertEqual(body["dictionary_delta"], {})
        self.assertEqual(set(body), {"results", "dictionary_delta"})

    def test_solo_text_e_solo_file(self):
        status, body = self.call(_body([("text", None, "solo testo")]))
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["input_id"], "text")
        status, body = self.call(_body([("files", "a.txt", "solo file")]))
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["input_id"], "file_1")

    def test_json_e_multipart_condividono_seed_configurabile_oltre_1mib(self):
        dictionary = {
            "[FULLNAME_%d]" % index:
                ("value-%03d" % index) + ("x" * 3591)
            for index in range(1, 301)
        }
        dictionary_json = json.dumps(dictionary, separators=(",", ":"))
        self.assertGreater(len(dictionary_json.encode("utf-8")),
                           guardrail_inputs.MAX_FORM_FIELD_BYTES)
        environment = {
            "PII_MAX_SEED_ENTRIES": "300",
            "PII_MAX_ORIGINAL_CHARS": "4096",
            "PII_MAX_AGGREGATE_CHARS": "1500000",
            "PII_MAX_JSON_BODY_BYTES": "2097152",
        }
        with patch.dict(os.environ, environment):
            json_body = json.dumps(
                {"text": "unmatched", "dictionary": dictionary},
                separators=(",", ":")).encode("utf-8")
            json_status, json_response = guardrail_api.process_request(
                {"Authorization": "Bearer " + TOKEN,
                 "Content-Type": "application/json"},
                json_body, token=TOKEN, tags=TAGS, detect=_detect_none,
                lock=threading.Lock())
            multipart_status, multipart_response = self.call(_body([
                ("dictionary", None, dictionary_json),
                ("text", None, "unmatched"),
            ]), lock=threading.Lock())
        self.assertEqual(json_status, 200)
        self.assertEqual(multipart_status, 200)
        self.assertEqual(json_response["results"][0]["anonymized_text"], "unmatched")
        self.assertEqual(multipart_response["results"][0]["anonymized_text"], "unmatched")
        self.assertEqual(json_response["dictionary_delta"], {})
        self.assertEqual(multipart_response["dictionary_delta"], {})

    def test_multipart_merged_state_overflow_has_no_originals(self):
        seed_value = "seed-synthetic-original"
        detected = "delta-synthetic-original"
        raw = _body([
            ("dictionary", None, json.dumps({"[FULLNAME_1]": seed_value})),
            ("text", None, detected),
        ])
        with patch.dict(os.environ, {"PII_MAX_SEED_ENTRIES": "1"}):
            status, body = self.call(
                raw, detect=detect_literals((detected, "FULLNAME")),
                lock=threading.Lock())
        encoded = json.dumps(body)
        self.assertEqual(status, 413)
        self.assertEqual(set(body), {"error", "code"})
        self.assertNotIn(seed_value, encoded)
        self.assertNotIn(detected, encoded)

    def test_text_solo_con_seed_non_richiede_extractor(self):
        raw = _body([
            ("dictionary", None, '{"[FULLNAME_7]": "Mario Rossi"}'),
            ("text", None, "Mario Rossi"),
        ])
        status, body = self.call(raw, extract=None)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"], "[FULLNAME_7]")
        self.assertEqual(body["dictionary_delta"], {})

    def test_dizionario_solo_400_e_text_blank_senza_file_400(self):
        status, body = self.call(_body([("dictionary", None, "{}")]))
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")
        status, body = self.call(_body([("text", None, "   ")]))
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")

    def test_dictionary_vuoto_e_malformato(self):
        cases = [("", 400, "invalid_request"),
                 ("{", 400, "invalid_request"),
                 ('{"a": 1, "a": 1}', 400, "invalid_request"),
                 ('{"[FULLNAME_1]": NaN}', 400, "invalid_request"),
                 ('{"[FULLNAME_1]": "x", "z": {"a": 1, "a": 2}}',
                  400, "invalid_request"),
                 ("[[]]", 400, "invalid_seed"),
                 ("null", 400, "invalid_seed"),
                 ("[]", 400, "invalid_seed"),
                 ("5", 400, "invalid_seed"),
                 ('"[FULLNAME_1]"', 400, "invalid_seed"),
                 ('{"[FULLNAME_1]": "\\ud800"}', 400, "invalid_seed"),
                 ("{ }", 200, None)]
        for content, status, code in cases:
            response_status, body = self.call(
                _body([("dictionary", None, content), ("text", None, "x")]))
            self.assertEqual(response_status, status, content)
            if code:
                self.assertEqual(body["code"], code, content)

    def test_annidamento_oltre_il_limite_del_parser_400_e_lock_rilasciato(self):
        # Il limite ricorsivo del parser JSON cambia fra interpreti: qui il
        # RecursionError del parser e' reso deterministico dal patch, cosi' il
        # test copre SEMPRE il ramo parser-errore (400 invalid_request) e non
        # il ramo JSON valido ma non oggetto (400 invalid_seed) gia' coperto
        # da test_dictionary_vuoto_e_malformato con "[[]]".
        calls = []

        def detect(text, _check):
            calls.append(text)
            return []

        raw = _body([("dictionary", None, "[" * 2000 + "]" * 2000),
                     ("text", None, "x")])
        with patch.object(guardrail_api.json, "loads", side_effect=RecursionError):
            status, body = self.call(raw, detect=detect)
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_request")
        self.assertEqual(calls, [])
        self.assertFalse(self.lock.locked())

    def test_seed_multipart_riusato(self):
        raw = _body([
            ("dictionary", None, '{"[FULLNAME_7]": "Mario Rossi"}'),
            ("files", "a.txt", "Mario Rossi scrive."),
            ("text", None, "Referente: Mario Rossi."),
        ])
        status, body = self.call(raw)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"],
                         "[FULLNAME_7] scrive.")
        self.assertEqual(body["results"][1]["anonymized_text"],
                         "Referente: [FULLNAME_7].")
        self.assertEqual(body["dictionary_delta"], {})

    def test_ordine_di_processamento_file_prima_di_text_anche_se_prima_nel_body(self):
        raw = _body([
            ("text", None, "prima email x@y.it"),
            ("files", "a.txt", "seconda email z@w.it"),
        ])
        detect = detect_literals(("x@y.it", "EMAIL"), ("z@w.it", "EMAIL"))
        status, body = self.call(raw, detect=detect)
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["input_id"], "file_1")
        self.assertEqual(body["results"][1]["input_id"], "text")
        self.assertEqual(body["results"][0]["anonymized_text"], "seconda email [EMAIL_1]")
        self.assertEqual(body["results"][1]["anonymized_text"],
                         "prima email [EMAIL_2]")

    def test_riuso_cross_file_anche_se_il_modello_non_vede(self):
        calls = []

        def detect(text, _check):
            calls.append(text)
            if len(calls) > 1:
                return []
            position = text.find("Mario Rossi")
            return [{"label": "FULLNAME", "start": position, "end": position + 11,
                     "score": 0.9, "validated": False, "source": "modello"}]

        raw = _body([("files", "a.txt", "Mario Rossi"),
                     ("files", "b.txt", "mario   rossi"),
                     ("text", None, "MARIO ROSSI")])
        status, body = self.call(raw, detect=detect)
        self.assertEqual(status, 200)
        self.assertEqual([r["anonymized_text"] for r in body["results"]],
                         ["[FULLNAME_1]", "[FULLNAME_1]", "[FULLNAME_1]"])
        self.assertEqual(body["dictionary_delta"], {"[FULLNAME_1]": "Mario Rossi"})

    def test_placeholder_in_un_file_successivo_riserva_gli_id(self):
        raw = _body([("files", "a.txt", "scrivi a x@y.it"),
                     ("files", "b.txt", "placeholder [EMAIL_9]")])
        status, body = self.call(raw, detect=detect_literals(("x@y.it", "EMAIL")))
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["anonymized_text"], "scrivi a [EMAIL_10]")
        self.assertEqual(body["results"][1]["anonymized_text"], "placeholder [EMAIL_9]")
        self.assertEqual(body["dictionary_delta"], {"[EMAIL_10]": "x@y.it"})

    def test_limite_aggregato_100000(self):
        raw = _body([("files", "a.txt", "a" * 60000),
                     ("files", "b.txt", "b" * 60000)])
        status, body = self.call(raw)
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "payload_too_large")
        # Al limite esatto (100000 caratteri) tutto passa.
        status, body = self.call(_body([("files", "a.txt", "a" * 100000)]))
        self.assertEqual(status, 200)
        self.assertEqual(
            len(body["results"][0]["anonymized_text"]), 100000)

    def test_limite_body_multipart_20mib(self):
        limit = guardrail_inputs.MAX_MULTIPART_BODY_BYTES
        status, body = self.call(b"x" * (limit + 1))
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "payload_too_large")

    def test_cap_scelto_dal_media_type(self):
        seen = []

        def reader_json(cap):
            seen.append(cap)
            return b'{"text":"x"}'

        status, _response = self.call(reader_json, content_type="application/json")
        self.assertEqual(status, 200)
        self.assertEqual(seen, [guardrail_api.MAX_BODY_BYTES])

        def reader_multipart(cap):
            seen.append(cap)
            return _body([("text", None, "x")])

        status, _response = self.call(reader_multipart)
        self.assertEqual(status, 200)
        self.assertEqual(seen[1], guardrail_inputs.MAX_MULTIPART_BODY_BYTES)

    def test_cap_json_non_diventa_quello_multipart(self):
        raw = b'{"text":"' + b"a" * (guardrail_api.MAX_BODY_BYTES + 10) + b'"}'
        status, body = self.call(raw, content_type="application/json")
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "payload_too_large")

    def test_estrazione_fallita_e_all_or_nothing(self):
        calls = []

        def detect(*_args):
            calls.append(True)
            return []

        extract = _extract_error(422, "unreadable_file")
        raw = _body([("files", "a.txt", "x"), ("files", "b.txt", "y")])
        status, body = self.call(raw, extract=extract, detect=detect)
        self.assertEqual(status, 422)
        self.assertEqual(body, {"error": "Unable to read file.",
                                "code": "unreadable_file"})
        self.assertEqual(calls, [])
        self.assertFalse(self.lock.locked())

    def test_estensione_non_supportata_non_estrae_niente(self):
        calls = []

        def extract(*_args):
            calls.append(True)
            return ""

        raw = _body([("files", "ok.txt", "x"), ("files", "bad.exe", "y")])
        status, body = self.call(raw, extract=extract)
        self.assertEqual(status, 415)
        self.assertEqual(body["error"], "Unsupported file type.")
        self.assertEqual(calls, [])

    def test_codici_di_estrazione_passano_come_sono(self):
        for status_code, code, message in (
                (422, "empty_file", "File is empty."),
                (422, "no_extractable_text",
                 "File has no extractable text. OCR is not available."),
                (413, "payload_too_large", "Payload too large.")):
            status, body = self.call(
                _body([("files", "a.txt", "x")]),
                extract=_extract_error(status_code, code))
            self.assertEqual(status, status_code)
            self.assertEqual(body, {"error": message, "code": code})

    def test_text_oltre_100000_413(self):
        raw = _body([("text", None, "a" * 100001)])
        status, body = self.call(raw)
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "payload_too_large")

    def test_extract_callback_non_stringa_500(self):
        status, body = self.call(
            _body([("files", "a.txt", "x")]),
            extract=lambda _name, _data, _remaining, _check: None)
        self.assertEqual(status, 500)
        self.assertEqual(body["code"], "internal_error")

    def test_multipart_senza_extractor_503(self):
        raw = _body([("files", "a.txt", "x")])
        status, body = self.call(raw, extract=None)
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "unavailable")
        self.assertFalse(self.lock.locked())

    def test_errore_senza_valori_nome_o_seed(self):
        seed_value = "VALORE-SEGRETO-SEED"
        raw = _body([("files", "NOME-SEGRETO-123.exe", b"x"),
                     ("dictionary", None,
                      '{"[FULLNAME_1]": "%s"}' % seed_value)])
        status, body = self.call(raw)
        self.assertEqual(status, 415)
        encoded = json.dumps(body)
        self.assertNotIn("NOME-SEGRETO-123", encoded)
        self.assertNotIn(seed_value, encoded)
        self.assertEqual(set(body), {"error", "code"})

    def test_nome_file_e_seed_non_echo_nel_successo(self):
        raw = _body([("files", "NOME-SEGRETO-123.txt", "ciao"),
                     ("dictionary", None, '{"[FULLNAME_8]": "VALORE-SEGRETO"}')])
        status, body = self.call(raw)
        self.assertEqual(status, 200)
        encoded = json.dumps(body)
        self.assertNotIn("NOME-SEGRETO-123", encoded)
        self.assertNotIn("VALORE-SEGRETO", encoded)

    def test_deadline_su_parsing_504_e_lock_rilasciato(self):
        clock = Clock(after=2)     # la prima check dopo l'init vede 61.0
        raw = _body([("files", "a.txt", "x" * 100000)])
        status, body = self.call(raw, clock=clock)
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")
        self.assertFalse(self.lock.locked())

    def test_deadline_su_estrazione_504(self):
        clock = Clock()

        def extract(_name, data, _remaining, check):
            clock.now = 61.0
            check()
            return data.decode("utf-8")

        raw = _body([("files", "a.txt", "x"), ("files", "b.txt", "y")])
        status, body = self.call(raw, extract=extract, clock=clock)
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")
        self.assertFalse(self.lock.locked())

    def test_deadline_su_rilevatore_504(self):
        clock = Clock()

        def detect(_text, check):
            clock.now = 61.0
            check()
            return []

        status, body = self.call(_body([("files", "a.txt", "x")]),
                                 detect=detect, clock=clock)
        self.assertEqual(status, 504)
        self.assertEqual(body["code"], "deadline_exceeded")
        self.assertFalse(self.lock.locked())

    def test_gate_prima_della_lettura_del_body_multipart(self):
        class Boom:
            def __init__(self):
                self.called = False

            def __call__(self, _cap):
                self.called = True
                raise RuntimeError("BOOM")

        def probe(headers, *, token=TOKEN, detect=_detect_none, lock=None):
            reader = Boom()
            status, body = guardrail_api.process_request(
                headers, reader, token=token, tags=TAGS, detect=detect,
                extract=_extract_utf8,
                lock=lock if lock is not None else threading.Lock())
            self.assertFalse(reader.called)
            return status, body

        multipart_headers = {"Content-Type": "multipart/form-data; boundary=" + BOUND}
        status, body = probe(multipart_headers)
        self.assertEqual((status, body["code"]), (401, "unauthorized"))
        status, body = probe(dict(multipart_headers, **AUTH), token="")
        self.assertEqual((status, body["code"]), (503, "unavailable"))
        status, body = probe(dict(multipart_headers, **AUTH), detect=None)
        self.assertEqual((status, body["code"]), (503, "unavailable"))
        lock = threading.Lock()
        lock.acquire()
        try:
            status, body = probe(dict(multipart_headers, **AUTH), lock=lock)
        finally:
            lock.release()
        self.assertEqual((status, body["code"]), (429, "busy"))


def _make_client(detect=_detect_none, extract=_extract_utf8, clock=None, lock=None):
    if lock is None:
        lock = threading.Lock()
    application = Flask("multifiles-test")
    application.config["TESTING"] = True
    application.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
    kwargs = {"clock": clock} if clock is not None else {}
    blueprint = guardrail_api.create_blueprint(TAGS, detect, lock=lock,
                                               extract=extract, **kwargs)
    application.register_blueprint(blueprint)
    return application.test_client(), lock


@unittest.skipUnless(HAVE_NATIVE and HAVE_FLASK, "Flask/Werkzeug assenti")
class FlaskMultipart(unittest.TestCase):
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

    def post(self, raw, content_type="multipart/form-data; boundary=" + BOUND,
             headers=None, client=None):
        all_headers = dict(AUTH)
        if headers:
            all_headers.update(headers)
        return (client or self.client).post(PATH, data=raw,
                                            content_type=content_type,
                                            headers=all_headers)

    def test_multipart_flask_shape_e_no_store(self):
        raw = _body([("files", "a.txt", "Mario Rossi"),
                     ("text", None, "Ciao"),
                     ("dictionary", None, '{"[FULLNAME_7]": "Mario Rossi"}')])
        response = self.post(raw)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        body = response.get_json()
        self.assertEqual(body["results"][0]["input_id"], "file_1")
        self.assertEqual(body["results"][0]["anonymized_text"], "[FULLNAME_7]")
        self.assertEqual(body["results"][0]["statistics"]["placeholder_count"], 1)
        self.assertEqual(body["results"][1]["input_id"], "text")
        self.assertEqual(body["dictionary_delta"], {})

    def test_factory_flask_text_solo_senza_extractor(self):
        client, _lock = _make_client(extract=None)
        raw = _body([
            ("dictionary", None, '{"[FULLNAME_7]": "Mario Rossi"}'),
            ("text", None, "Mario Rossi"),
        ])
        response = self.post(raw, client=client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["anonymized_text"],
                         "[FULLNAME_7]")

    def test_errori_multipart_shape_no_store_e_cache(self):
        responses = [
            self.post(b""),                                   # 400
            self.post(b"x", content_type="text/plain"),       # 415
            self.post(_body([("files", "a.exe", "x")])),      # 415
            self.post(_body([("text", None, "   ")])),        # 400 manca input
        ]
        for response in responses:
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")
            self.assertEqual(set(response.get_json()), {"error", "code"})
        self.assertEqual([r.status_code for r in responses], [400, 415, 415, 400])

    def test_405_e_options_no_store_sul_percorso_multipart(self):
        response = self.client.get(PATH, headers=dict(AUTH))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertIn("POST", response.headers.get("Allow", ""))

    def test_json_oltre_default_8mib_resta_413(self):
        raw = b'{"text":"' + b"a" * (guardrail_api.MAX_BODY_BYTES + 10) + b'"}'
        response = self.post(raw, content_type="application/json")
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["code"], "payload_too_large")

    def test_file_grande_senza_spool_su_disco(self):
        # Il file supera la soglia di spooling di SpooledTemporaryFile (500 KB);
        # l'estrattore restituisce poco testo per non sfondare il limite aggregato.
        client, _lock = _make_client(
            extract=lambda _name, _data, _remaining, _check: "poco testo")
        raw = _body([("files", "grande.txt", b"a" * (512 * 1024 + 7))])
        with patch.object(tempfile, "SpooledTemporaryFile",
                          side_effect=AssertionError("spool su disco")), \
                patch.object(tempfile, "TemporaryFile",
                             side_effect=AssertionError("file temporaneo")):
            response = self.post(raw, client=client)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["anonymized_text"],
                         "poco testo")

    def test_request_files_non_usato(self):
        from werkzeug.formparser import MultiPartParser

        raw = _body([("files", "a.txt", "x")])
        with patch.object(MultiPartParser, "parse",
                          side_effect=AssertionError("parser Flask usato")):
            response = self.post(raw)
        self.assertEqual(response.status_code, 200)

    def test_deadline_flask_504_e_rilascio_lock(self):
        clock = Clock()

        def extract(_name, data, _remaining, check):
            clock.now = 61.0
            check()
            return data.decode("utf-8")

        client, lock = _make_client(extract=extract, clock=clock)
        response = self.post(_body([("files", "a.txt", "x")]), client=client)
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.get_json()["code"], "deadline_exceeded")
        self.assertFalse(lock.locked())

    def test_busy_non_legge_il_body_multipart(self):
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
        self.lock.acquire()
        try:
            response = self.client.post(
                PATH, data=b"x", content_type="multipart/form-data; boundary=" + BOUND,
                headers=dict(AUTH), environ_overrides={"wsgi.input": stream})
        finally:
            self.lock.release()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(stream.calls, 0)


def _import_app_with_mocks():
    if "app" in sys.modules:
        return sys.modules["app"]
    saved = {name: sys.modules.get(name)
             for name in ("torch", "transformers", "fitz")}
    for name in saved:
        sys.modules[name] = MagicMock()
    fake_fitz = sys.modules["fitz"]
    # This fixture represents a verified native API, not an unsupported build:
    # startup setters are followed by explicit falsy getter readbacks.
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


def _pdf_bytes(lines, pages=1, blank=False):
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        if not blank:
            for index, line in enumerate(lines):
                page.insert_text((72, 72 + 14 * index), line)
    data = doc.tobytes()
    doc.close()
    return data


@unittest.skipUnless(HAVE_NATIVE and HAVE_FLASK,
                     "Flask/Werkzeug assenti: cablaggio app non testabile")
class FunctionalApp(unittest.TestCase):
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

    def post(self, raw, content_type="multipart/form-data; boundary=" + BOUND):
        return self.client.post(PATH, data=raw, content_type=content_type,
                                headers=dict(AUTH))

    def test_mixed_txt_md_pdf_text_seed_e_riuso(self):
        if not HAVE_FITZ:
            self.skipTest("PyMuPDF assente")
        pdf = _pdf_bytes(["Mario Rossi, IBAN IT60X0542811101000000123456"])
        raw = _body([
            ("dictionary", None, '{"[FULLNAME_7]": "Mario Rossi"}'),
            ("files", "atto.txt", b"Mario Rossi scrive a mario.rossi@example.com"),
            ("files", "nota.md", b"Conferma per Mario Rossi"),
            ("files", "contratto.pdf", pdf),
            ("text", None, "Referente: Mario Rossi"),
        ])
        with patch.object(self.APP, "nlp", self._nlp([("FULLNAME", "Mario Rossi")])):
            response = self.post(raw)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual([r["input_id"] for r in body["results"]],
                         ["file_1", "file_2", "file_3", "text"])
        self.assertEqual(body["results"][0]["anonymized_text"],
                         "[FULLNAME_7] scrive a [EMAIL_1]")
        self.assertEqual(body["results"][1]["anonymized_text"],
                         "Conferma per [FULLNAME_7]")
        self.assertIn("[FULLNAME_7]", body["results"][2]["anonymized_text"])
        self.assertIn("[IBAN_1]", body["results"][2]["anonymized_text"])
        self.assertEqual(body["results"][3]["anonymized_text"],
                         "Referente: [FULLNAME_7]")
        self.assertEqual(body["dictionary_delta"],
                         {"[EMAIL_1]": "mario.rossi@example.com",
                          "[IBAN_1]": "IT60X0542811101000000123456"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_zero_byte_txt_422_e_pdf_zero_byte_422(self):
        raw = _body([("files", "vuoto.txt", b"")])
        response = self.post(raw)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["code"], "empty_file")
        raw = _body([("files", "vuoto.pdf", b"")])
        response = self.post(raw)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["code"], "unreadable_file")

    def test_file_testo_blank_decodificato_422(self):
        raw = _body([("files", "spazi.txt", b"   \n\t")])
        response = self.post(raw)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["code"], "empty_file")

    def test_pdf_corrotto_422(self):
        raw = _body([("files", "rotto.pdf", b"%PDF-rotto")])
        response = self.post(raw)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["code"], "unreadable_file")

    def test_pdf_senza_testo_422_e_ocr_non_disponibile(self):
        if not HAVE_FITZ:
            self.skipTest("PyMuPDF assente")
        raw = _body([("files", "scansione.pdf", _pdf_bytes([], blank=True))])
        response = self.post(raw)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["code"], "no_extractable_text")
        self.assertIn("OCR is not available", response.get_json()["error"])

    def test_pdf_cifrato_422(self):
        if not HAVE_FITZ:
            self.skipTest("PyMuPDF assente")
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "Mario Rossi")
        encrypted = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,
                                owner_pw="owner", user_pw="user")
        doc.close()
        raw = _body([("files", "cifrato.pdf", encrypted)])
        response = self.post(raw)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["code"], "unreadable_file")

    def test_pdf_oltre_200_pagine_413(self):
        if not HAVE_FITZ:
            self.skipTest("PyMuPDF assente")
        raw = _body([("files", "lungo.pdf", _pdf_bytes([], pages=201, blank=True))])
        response = self.post(raw)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["code"], "payload_too_large")
        # Al tetto esatto di 200 pagine il limite non scatta.
        raw = _body([("files", "lungo.pdf",
                      _pdf_bytes(["Mario Rossi"], pages=200))])
        with patch.object(self.APP, "nlp", self._nlp([("FULLNAME", "Mario Rossi")])):
            response = self.post(raw)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["input_id"], "file_1")

    def test_pdf_magic_su_txt_md_usa_estrazione_strict_bounded(self):
        if not HAVE_FITZ:
            self.skipTest("PyMuPDF assente")
        oversized_doc = fitz.open()
        oversized_doc.new_page().insert_text((72, 72), "mario@example.com")
        for _index in range(200):
            oversized_doc.new_page()
        oversized = oversized_doc.tobytes()
        oversized_doc.close()
        for filename in ("misnamed.txt", "misnamed.md"):
            with self.subTest(filename=filename):
                with self.assertRaises(guardrail_inputs.InputError) as ctx:
                    self.APP._guardrail_extract(
                        filename, oversized, 100000, lambda: None)
                self.assertEqual((ctx.exception.status, ctx.exception.code),
                                 (413, "payload_too_large"))
                response = self.post(_body([("files", filename, oversized)]))
                self.assertEqual(response.status_code, 413)
                self.assertEqual(response.get_json()["code"], "payload_too_large")

        pdf = _pdf_bytes(["mario@example.com"])
        expected_text = self.APP._guardrail_extract(
            "source.pdf", pdf, 100000, lambda: None)
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("misnamed.md", pdf, 3, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (413, "payload_too_large"))
        for filename in ("misnamed.txt", "misnamed.md"):
            self.assertEqual(self.APP._guardrail_extract(
                filename, pdf, 100000, lambda: None), expected_text)

        responses = []
        with patch.object(self.APP, "nlp", self._nlp([])):
            for filename in ("source.pdf", "misnamed.txt", "misnamed.md"):
                response = self.post(_body([("files", filename, pdf)]))
                self.assertEqual(response.status_code, 200)
                responses.append(response.get_json())
        self.assertEqual(responses[1:], [responses[0], responses[0]])
        self.assertEqual(responses[0]["dictionary_delta"],
                         {"[EMAIL_1]": "mario@example.com"})

        model_calls = []

        def model(chunks):
            model_calls.extend(chunks)
            return [[] for _chunk in chunks]

        response = self.post(_body([("files", "not-a-pdf.jpg", pdf)]))
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.get_json()["code"], "unsupported_file_type")
        with patch.object(self.APP, "nlp", model):
            response = self.post(_body([
                ("files", "first.txt", "mario@example.com"),
                ("files", "last.md", oversized),
            ]))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["code"], "payload_too_large")
        self.assertEqual(model_calls, [])

    def test_codifica_legacy_cp1252_utf16_bom_nul(self):
        cp1252 = "Città è già ok".encode("cp1252")
        utf16 = "Città è già ok".encode("utf-16")     # BOM compreso
        with_nul = "Città è già ok".encode("utf-8") + b"\x00"
        raw = _body([("files", "a.txt", cp1252),
                     ("files", "b.text", utf16),
                     ("files", "c.md", with_nul)])
        with patch.object(self.APP, "nlp", self._nlp([])):
            response = self.post(raw)
        self.assertEqual(response.status_code, 200)
        texts = [r["anonymized_text"] for r in response.get_json()["results"]]
        for text in texts:
            self.assertIn("Città è già ok", text)
            self.assertNotIn("\x00", text)

    def test_nessuna_scrittura_su_docs_o_prefs(self):
        docs_before = dict(self.APP._DOCS)
        prefs_path = self.APP.server_config.prefs_path()
        prefs_before = prefs_path.read_bytes() if prefs_path.exists() else None
        raw = _body([("files", "a.txt", "Mario Rossi"),
                     ("text", None, "Ciao")])
        with patch.object(self.APP, "nlp", self._nlp([("FULLNAME", "Mario Rossi")])):
            response = self.post(raw)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(dict(self.APP._DOCS), docs_before)
        prefs_after = prefs_path.read_bytes() if prefs_path.exists() else None
        self.assertEqual(prefs_after, prefs_before)

    def test_legacy_analyze_preservato(self):
        with patch.object(self.APP, "nlp", self._nlp([("FULLNAME", "Mario Rossi")])):
            response = self.APP.app.test_client().post(
                "/analyze", json={"text": "Mario Rossi scrive a x@y.it"})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        for key in ("anonymized_text", "mapping", "segments", "source_text"):
            self.assertIn(key, body)

    def test_rotte_api_only_preservate(self):
        rules = {(str(rule), tuple(sorted((rule.methods or set()) - {"HEAD", "OPTIONS"})))
                 for rule in self.APP.app.url_map.iter_rules()}
        self.assertIn((PATH, ("POST",)), rules)
        self.assertIn(("/analyze", ("POST",)), rules)
        self.assertIn(("/health", ("GET",)), rules)
        self.assertEqual(len(rules), 16)

    def test_nessun_valore_di_richiesta_nei_log(self):
        class Capture(logging.Handler):
            def __init__(self):
                super().__init__()
                self.messages = []

            def emit(self, record):
                self.messages.append(record.getMessage())

        handler = Capture()
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            raw = _body([
                ("files", "NOME-SEGRETO-999.txt", "VALORE-UNO"),
                ("dictionary", None, '{"[FULLNAME_9]": "VALORE-SEED"}'),
            ])
            with patch.object(self.APP, "nlp",
                              self._nlp([("FULLNAME", "VALORE-UNO")])):
                response = self.post(raw)
        finally:
            root.removeHandler(handler)
        self.assertEqual(response.status_code, 200)
        joined = "\n".join(handler.messages)
        for secret in ("NOME-SEGRETO-999", "VALORE-UNO", "VALORE-SEED"):
            self.assertNotIn(secret, joined)


@unittest.skipUnless(HAVE_FLASK, "app non importabile senza Flask")
class GuardrailExtractUnit(unittest.TestCase):
    """`app._guardrail_extract`: rami che l'endpoint non raggiunge mai da solo."""

    @classmethod
    def setUpClass(cls):
        cls.APP = _import_app_with_mocks()

    def setUp(self):
        self._stack = contextlib.ExitStack()
        self.addCleanup(self._stack.close)

    def test_ramo_testo(self):
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.exe", b"x", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (415, "unsupported_file_type"))
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.txt", b"x" * 10, 2, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (413, "payload_too_large"))
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.txt", b"", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (422, "empty_file"))
        # .txt che comincia con %PDF-: _text_from_bytes prova PyMuPDF e fallisce
        with patch.object(self.APP.fitz, "open",
                          side_effect=RuntimeError("PDF rotto")):
            with self.assertRaises(guardrail_inputs.InputError) as ctx:
                self.APP._guardrail_extract("a.txt", b"%PDF-rotto", 100,
                                            lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (422, "unreadable_file"))
        with patch.object(self.APP, "_text_from_bytes",
                          side_effect=RuntimeError("testo non leggibile")):
            with self.assertRaises(guardrail_inputs.InputError) as ctx:
                self.APP._guardrail_extract("a.txt", b"plain text", 100,
                                            lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (422, "unreadable_file"))

    def test_ramo_pdf(self):
        class FakeDoc:
            is_pdf = True
            needs_pass = False
            is_encrypted = False
            page_count = 1

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        fake_fitz = MagicMock()
        self._stack.enter_context(patch.object(self.APP, "fitz", fake_fitz))
        collect = self._stack.enter_context(
            patch.object(self.APP.pdf_text, "collect_readable_text"))
        fake_fitz.open.return_value = FakeDoc()

        collect.side_effect = pii_dictionary.DeadlineExceeded()
        with self.assertRaises(pii_dictionary.DeadlineExceeded):
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)

        collect.side_effect = self.APP.pdf_text.PdfTextTooLarge()
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (413, "payload_too_large"))

        collect.side_effect = None
        collect.return_value = "   "
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (422, "no_extractable_text"))

        class NotPdf(FakeDoc):
            is_pdf = False

        fake_fitz.open.return_value = NotPdf()
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (422, "unreadable_file"))

        class Encrypted(FakeDoc):
            needs_pass = True

        fake_fitz.open.return_value = Encrypted()
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (422, "unreadable_file"))

        class TooManyPages(FakeDoc):
            page_count = guardrail_inputs.MAX_PDF_PAGES + 1

        fake_fitz.open.return_value = TooManyPages()
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (413, "payload_too_large"))

    def test_pdf_sniffed_usa_collettore_strict_con_budget(self):
        class FakeDoc:
            is_pdf = True
            needs_pass = False
            is_encrypted = False
            page_count = 1

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        fake_fitz = MagicMock()
        fake_fitz.open.return_value = FakeDoc()
        collect = MagicMock(side_effect=self.APP.pdf_text.PdfTextError())
        check_deadline = lambda: None
        with patch.object(self.APP, "fitz", fake_fitz):
            with patch.object(self.APP.pdf_text, "collect_readable_text", collect):
                with self.assertRaises(guardrail_inputs.InputError) as ctx:
                    self.APP._guardrail_extract(
                        "misnamed.txt", b"%PDF-valid", 17, check_deadline)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (422, "unreadable_file"))
        collect.assert_called_once_with(
            fake_fitz.open.return_value, max_chars=17,
            check_deadline=check_deadline, strict=True)

    def test_deadline_immediata_dopo_pdf_open_precede_classificazione(self):
        class Uninspectable:
            closed = False

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def close(self):
                self.closed = True

            @property
            def is_pdf(self):
                raise AssertionError("document inspected after expired open")

        document = Uninspectable()
        fake_fitz = MagicMock()
        fake_fitz.open.return_value = document
        with patch.object(self.APP, "fitz", fake_fitz):
            def check_deadline():
                if fake_fitz.open.called:
                    raise pii_dictionary.DeadlineExceeded()

            with self.assertRaises(pii_dictionary.DeadlineExceeded):
                self.APP._guardrail_extract(
                    "misnamed.txt", b"%PDF-valid", 100, check_deadline)
        fake_fitz.open.assert_called_once()
        self.assertTrue(document.closed)

        failed_close = Uninspectable()

        def close_with_error():
            failed_close.closed = True
            raise RuntimeError("close failed")

        failed_close.close = close_with_error
        fake_fitz.open.return_value = failed_close
        with patch.object(self.APP, "fitz", fake_fitz):
            with self.assertRaises(pii_dictionary.DeadlineExceeded):
                self.APP._guardrail_extract(
                    "misnamed.txt", b"%PDF-valid", 100, check_deadline)
        self.assertTrue(failed_close.closed)

        class NoClose:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        fake_fitz.open.return_value = NoClose()
        with patch.object(self.APP, "fitz", fake_fitz):
            with self.assertRaises(pii_dictionary.DeadlineExceeded):
                self.APP._guardrail_extract(
                    "misnamed.txt", b"%PDF-valid", 100, check_deadline)

    def test_deadline_immediata_dopo_get_text_precede_blank_check(self):
        class Page:
            def get_text(self):
                return ""

            def annots(self):
                return ()

            def widgets(self):
                return ()

        class Doc:
            is_pdf = True
            needs_pass = False
            is_encrypted = False
            page_count = 1

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def __iter__(self):
                return iter((Page(),))

            def get_toc(self, simple=True):
                raise AssertionError("TOC read before post-get_text deadline check")

        fake_fitz = MagicMock()
        fake_fitz.open.return_value = Doc()
        checks = 0

        def check_deadline():
            nonlocal checks
            checks += 1
            if checks == 4:
                raise pii_dictionary.DeadlineExceeded()

        with patch.object(self.APP, "fitz", fake_fitz):
            with self.assertRaises(pii_dictionary.DeadlineExceeded):
                self.APP._guardrail_extract(
                    "misnamed.md", b"%PDF-valid", 100, check_deadline)
        self.assertEqual(checks, 4)


if __name__ == "__main__":
    unittest.main()
