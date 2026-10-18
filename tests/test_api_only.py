# -*- coding: utf-8 -*-
"""API-only (ENVAS-23): la UI browser e' stata ritirata, restano HTTP API e PDF.

Verifica, sul sorgente e sull'app Flask vera, che il ritiro della pagina HTML/CSS/JS
non abbia toccato l'API:

  - il sorgente non contiene piu' PAGE, asset o route web;
  - le route HTTP sono esattamente quelle attese: niente "/", niente statiche;
  - gli errori del framework (404/405/413/500) escono in JSON sanificato, con gli
    header di protocollo conservati (Allow, WWW-Authenticate, Retry-After);
  - /analyze, /pdf, /preview, /doc/<id>/... e la guardrail /api/v1/analyses
    rispondono come prima.

Il modello neurale e' finto (nessun peso, nessun torch): i test degli handler e
delle route girano con Flask vero; quelli dei PDF con PyMuPDF vero, se installato.
Senza Flask la suite si limita ai controlli statici (CI stdlib). I valori sono
SINTETICI.
"""

import ast
import contextlib
import importlib
import io
import os
import sys
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
APP_SRC = ROOT / "src" / "app" / "app.py"
sys.path.insert(0, str(ROOT / "src" / "app"))

try:
    from flask import Flask
    from werkzeug.datastructures import WWWAuthenticate
    from werkzeug.exceptions import (HTTPException, InternalServerError,
                                     MethodNotAllowed, TooManyRequests,
                                     Unauthorized)
    HAVE_FLASK = True
except ImportError:                                  # CI stdlib: girano i test statici
    Flask = None
    HAVE_FLASK = False

# Route attese sull'app: ogni decoratore @app.route e' una regola. L'endpoint
# versionato /api/v1/analyses vive nel blueprint di guardrail_api.py.
DECORATORI_ATTESI = sorted([
    "/analyze", "/config", "/config",
    "/doc/<doc_id>/file.pdf", "/doc/<doc_id>/page/<int:n>.png",
    "/health", "/healthz", "/pdf", "/pdf/preview", "/port-check", "/preview",
    "/settings", "/settings", "/tags", "/tags",
])

REGOLE_ATTESE = {
    ("/analyze", ("POST",)),
    ("/api/v1/analyses", ("POST",)),
    ("/config", ("GET",)),
    ("/config", ("POST",)),
    ("/doc/<doc_id>/file.pdf", ("GET",)),
    ("/doc/<doc_id>/page/<int:n>.png", ("GET",)),
    ("/health", ("GET",)),
    ("/healthz", ("GET",)),
    ("/pdf", ("POST",)),
    ("/pdf/preview", ("POST",)),
    ("/port-check", ("GET",)),
    ("/preview", ("POST",)),
    ("/settings", ("GET",)),
    ("/settings", ("POST",)),
    ("/tags", ("GET",)),
    ("/tags", ("POST",)),
}

TOKEN = "token-di-prova"


def _import_app():
    """Importa app.py coi pesi finti: il modello vero qui non serve.

    Il finto transformers va messo in sys.modules (non patch("transformers.pipeline"):
    un `from transformers import pipeline` su un _LazyModule non passa dall'attributo
    patchato). La voce si sostituisce e ripristina a mano: patch.dict(sys.modules) al
    ripristino svuota anche l'app appena importata. PII_MODEL_DIR punta a una cartella
    esistente, altrimenti il controllo del modello mancante fa sys.exit(2).
    """
    if "app" in sys.modules:
        return sys.modules["app"]
    finto = MagicMock()
    finto.pipeline.return_value = MagicMock(return_value=[])
    salvati = {nome: sys.modules.get(nome) for nome in ("torch", "transformers")}
    for nome in salvati:
        sys.modules[nome] = MagicMock()
    sys.modules["transformers"] = finto
    prima = os.environ.get("PII_MODEL_DIR")
    os.environ["PII_MODEL_DIR"] = str(ROOT / "tests")
    try:
        import app as pii_app
    finally:
        for nome, modulo in salvati.items():
            if modulo is None:
                sys.modules.pop(nome, None)
            else:
                sys.modules[nome] = modulo
        if prima is None:
            os.environ.pop("PII_MODEL_DIR", None)
        else:
            os.environ["PII_MODEL_DIR"] = prima
    return pii_app


if HAVE_FLASK:
    try:
        APP = _import_app()
    except Exception:  # noqa: BLE001 - import mancante (per esempio fitz)
        APP = None
else:
    APP = None
HAVE_APP = APP is not None


def nlp_fullname(valore="Mario Rossi"):
    """Pipeline finta: FULLNAME su ogni occorrenza del valore in ogni chunk."""
    def nlp(chunks):
        out = []
        for chunk in chunks:
            i = chunk.find(valore)
            if i < 0:
                out.append([])
            else:
                out.append([{"entity_group": "FULLNAME", "start": i,
                             "end": i + len(valore), "score": 0.9, "word": valore}])
        return out
    return nlp


def nlp_vuoto(chunks):
    return [[] for _ in chunks]


def _registrato(mappa, ecc):
    """True se `ecc` compare come chiave in un albero di mapping di error handler
    (la forma esatta cambia fra le versioni di Flask)."""
    if not isinstance(mappa, dict):
        return False
    return ecc in mappa or any(_registrato(v, ecc) for v in mappa.values())


# --------------------------------------------------------------------------- #
# Controlli statici: girano anche senza Flask (CI stdlib)
# --------------------------------------------------------------------------- #
class SorgenteApiOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = APP_SRC.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.src)

    def test_pagina_html_css_js_rimossa(self):
        self.assertNotIn("<!doctype html>", self.src.lower())
        self.assertNotIn("localStorage", self.src)
        self.assertNotIn("render_template_string", self.src)
        self.assertNotIn("send_from_directory", self.src)

    def test_niente_pagina_asset_o_route_web(self):
        funzioni = {n.name for n in self.tree.body if isinstance(n, ast.FunctionDef)}
        for vietata in ("_page", "index", "assets", "favicon", "not_found"):
            self.assertNotIn(vietata, funzioni, vietata)
        assegnazioni = {t.id for n in self.tree.body if isinstance(n, ast.Assign)
                        for t in n.targets if isinstance(t, ast.Name)}
        self.assertNotIn("PAGE", assegnazioni)
        self.assertNotIn("ASSETS_DIR", assegnazioni)

    def test_solo_route_api(self):
        rotte = []
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "route" and node.args
                    and isinstance(node.args[0], ast.Constant)):
                rotte.append(node.args[0].value)
        self.assertEqual(sorted(rotte), DECORATORI_ATTESI)
        for vietata in ("/", "/favicon.ico"):
            self.assertNotIn(vietata, rotte)
        self.assertFalse(any(r.startswith("/assets/") or r.startswith("/static/")
                             for r in rotte))

    def test_asset_e_test_js_ritirati(self):
        self.assertFalse((ROOT / "src" / "app" / "assets").exists())
        self.assertFalse((ROOT / "tests" / "test_ripristino_placeholder.py").exists())

    def test_docker_e_compose_api_only(self):
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertNotIn("src/app/assets", dockerignore)
        self.assertIn("**/__pycache__/", dockerignore)
        self.assertIn("**/*.pyc", dockerignore)
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertNotIn("server Flask + UI", dockerfile)
        self.assertNotIn("webapp", compose)
        self.assertIn("preferenze legacy dell'API", dockerfile)
        self.assertIn("Preferenze legacy dell'API", compose)


# --------------------------------------------------------------------------- #
# App Flask vera, modello finto
# --------------------------------------------------------------------------- #
class _BaseApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if APP is None:
            raise unittest.SkipTest("app.py non importabile (torch/fitz assenti)")

    def setUp(self):
        self.client = APP.app.test_client()
        prefs = patch.object(APP, "_get_prefs", lambda: (set(), True))
        prefs.start()
        self.addCleanup(prefs.stop)


@unittest.skipUnless(HAVE_FLASK, "Flask assente")
class RouteEApiOnly(_BaseApp):
    def test_superficie_http_esatta(self):
        regole = {(str(rule.rule),
                   tuple(sorted((rule.methods or set()) - {"HEAD", "OPTIONS"})))
                  for rule in APP.app.url_map.iter_rules()}
        self.assertEqual(regole, REGOLE_ATTESE)
        self.assertIsNone(APP.app.static_folder)
        self.assertFalse(APP.app.has_static_folder)
        for nome in ("PAGE", "ASSETS_DIR", "_page", "index", "assets", "favicon",
                     "not_found"):
            self.assertFalse(hasattr(APP, nome), nome)

    def test_404_radice_json(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.mimetype, "application/json")
        self.assertEqual(r.get_json()["code"], "not_found")
        self.assertNotIn("<!doctype", r.get_data(as_text=True).lower())

    def test_404_sconosciuto_non_riflette_url(self):
        r = self.client.get("/nope/mario.rossi@example.com?token=TOKEN-SEGRETO")
        corpo = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.mimetype, "application/json")
        self.assertNotIn("mario.rossi", corpo)
        self.assertNotIn("TOKEN-SEGRETO", corpo)

    def test_404_asset_favicon_static_json(self):
        for percorso in ("/assets/mascot_shield.png", "/favicon.ico",
                         "/static/app.js"):
            r = self.client.get(percorso)
            self.assertEqual(r.status_code, 404, percorso)
            self.assertEqual(r.mimetype, "application/json", percorso)

    def test_404_di_route_restano_del_mercato(self):
        r = self.client.get("/doc/inesistente/file.pdf")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["error"],
                         "Documento non piu' disponibile.")
        r = self.client.get("/doc/inesistente/page/0.png")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_data(), b"")

    def test_405_json_allow_e_no_store(self):
        r = self.client.post("/health")
        self.assertEqual(r.status_code, 405)
        self.assertEqual(r.mimetype, "application/json")
        self.assertEqual(r.get_json()["code"], "method_not_allowed")
        self.assertIn("GET", r.headers.get("Allow", ""))
        self.assertEqual(r.headers.get("Cache-Control"), "no-store")
        r = self.client.delete("/analyze")
        self.assertEqual(r.status_code, 405)
        self.assertIn("POST", r.headers.get("Allow", ""))

    def test_head_errore_senza_corpo(self):
        get = self.client.get("/")
        head = self.client.head("/")
        self.assertEqual(head.status_code, 404)
        self.assertEqual(head.get_data(), b"")
        self.assertEqual(head.mimetype, "application/json")
        self.assertEqual(head.headers["Content-Length"],
                         str(len(get.get_data())))

    def test_options_semantica_framework_e_no_store(self):
        r = self.client.options("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_data(), b"")
        self.assertIn("GET", r.headers.get("Allow", ""))
        r = self.client.options("/")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.mimetype, "application/json")
        self.assertEqual(r.headers.get("Cache-Control"), "no-store")
        r = self.client.options("/api/v1/analyses")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("Cache-Control"), "no-store")

    def test_413_oltre_il_limite_del_framework_json(self):
        with patch.dict(APP.app.config, {"MAX_CONTENT_LENGTH": 16}):
            r = self.client.post("/analyze", json={"text": "x" * 200})
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.mimetype, "application/json")
        atteso = HTTPStatus(413)
        self.assertEqual(r.get_json(), {"error": atteso.phrase + ".",
                                        "code": atteso.name.lower()})
        self.assertEqual(r.headers.get("Cache-Control"), "no-store")

    def test_413_guardrail_conserva_il_codice_del_contratto(self):
        with patch.dict(os.environ, {"PII_API_TOKEN": TOKEN}), \
                patch.dict(APP.app.config, {"MAX_CONTENT_LENGTH": 8}):
            r = self.client.post("/api/v1/analyses", data=b'{"text":"x"}',
                                 content_type="application/json",
                                 headers={"Authorization": "Bearer " + TOKEN})
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.get_json()["code"], "payload_too_large")
        self.assertEqual(r.headers.get("Cache-Control"), "no-store")

    def test_500_di_una_route_non_riflette_leccezione(self):
        with patch.object(APP, "detect_model",
                          side_effect=RuntimeError("SEGRETO-documento")), \
                patch.object(APP.app, "log_exception"):
            r = self.client.post("/analyze", json={"text": "ciao"})
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.mimetype, "application/json")
        self.assertEqual(r.get_json()["code"], "internal_server_error")
        self.assertNotIn("SEGRETO", r.get_data(as_text=True))

    def test_handler_registrato_e_descrizione_sanificata(self):
        self.assertTrue(_registrato(APP.app.error_handler_spec, HTTPException))

        def boom():
            raise InternalServerError(
                description="SEGRETO-documento https://host-segreto/x?token=TOKEN")

        probe = Flask("probe-500")
        probe.register_error_handler(HTTPException, APP._http_error)
        probe.add_url_rule("/boom", view_func=boom)
        r = probe.test_client().get("/boom")
        corpo = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.mimetype, "application/json")
        self.assertEqual(r.headers.get("Cache-Control"), "no-store")
        self.assertEqual(r.headers["Content-Length"], str(len(r.get_data())))
        self.assertNotIn("SEGRETO", corpo)
        self.assertNotIn("host-segreto", corpo)
        self.assertNotIn("TOKEN", corpo)

    def test_handler_conserva_gli_header_di_protocollo(self):
        auth = WWWAuthenticate("Bearer", {"realm": "api"})
        r = APP._http_error(Unauthorized(www_authenticate=auth))
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers.get("WWW-Authenticate"), str(auth))
        r = APP._http_error(TooManyRequests(retry_after=42))
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.headers.get("Retry-After"), "42")
        r = APP._http_error(MethodNotAllowed(["PATCH"]))
        self.assertEqual(r.status_code, 405)
        self.assertEqual(r.headers.get("Allow"), "PATCH")

    def test_handler_codice_non_standard_e_senza_codice(self):
        class Strano(HTTPException):
            code = 599

        r = APP._http_error(Strano(description="SEGRETO"))
        self.assertEqual(r.status_code, 599)
        self.assertEqual(r.get_json(), {"error": "HTTP error.",
                                        "code": "http_599"})
        self.assertNotIn("SEGRETO", r.get_data(as_text=True))
        r = APP._http_error(HTTPException(description="SEGRETO"))
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.get_json()["code"], "internal_server_error")
        self.assertNotIn("SEGRETO", r.get_data(as_text=True))


@unittest.skipUnless(HAVE_FLASK, "Flask assente")
class AnalyzeEApi(_BaseApp):
    TESTO = "Mario Rossi scrive a mario.rossi@example.com"

    def test_analyze_campi_invariati(self):
        with patch.object(APP, "nlp", nlp_fullname()):
            r = self.client.post("/analyze", json={"text": self.TESTO})
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(set(d), {
            "segments", "anonymized_text", "mapping", "mapping_enabled",
            "n_chunks", "n_chars", "n_entities", "n_unique", "by_label",
            "by_source", "excluded_tags", "source_text"})
        self.assertEqual(d["source_text"], self.TESTO)
        self.assertEqual(d["mapping"], {"[FULLNAME_1]": "Mario Rossi",
                                        "[EMAIL_1]": "mario.rossi@example.com"})
        entita = [s for s in d["segments"] if "label" in s]
        self.assertTrue(entita)
        for seg in entita:
            self.assertLessEqual({"label", "ph", "src", "validated", "t"},
                                 set(seg))

    def test_analyze_senza_dizionario_non_espone_valori(self):
        with patch.object(APP, "nlp", nlp_fullname()):
            r = self.client.post("/analyze",
                                 json={"text": self.TESTO,
                                       "include_mapping": False})
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertNotIn("source_text", d)
        self.assertEqual(d["mapping"], {})
        self.assertFalse(d["mapping_enabled"])
        self.assertTrue(all("t" not in s for s in d["segments"] if "label" in s))
        corpo = r.get_data(as_text=True)
        self.assertNotIn("Mario Rossi", corpo)
        self.assertNotIn("mario.rossi@example.com", corpo)

    def test_guardrail_seed_delta_e_regex_reale(self):
        payload = {"text": self.TESTO,
                   "dictionary": {"[FULLNAME_1]": "Mario Rossi"}}
        with patch.dict(os.environ, {"PII_API_TOKEN": TOKEN}), \
                patch.object(APP, "nlp", nlp_fullname()):
            r = self.client.post("/api/v1/analyses", json=payload,
                                 headers={"Authorization": "Bearer " + TOKEN})
        self.assertEqual(r.status_code, 200)
        corpo = r.get_json()
        self.assertEqual(corpo["results"][0]["anonymized_text"],
                         "[FULLNAME_1] scrive a [EMAIL_1]")
        self.assertEqual(corpo["results"][0]["statistics"]["placeholder_count"], 2)
        self.assertEqual(corpo["dictionary_delta"],
                         {"[EMAIL_1]": "mario.rossi@example.com"})
        self.assertEqual(r.headers.get("Cache-Control"), "no-store")


@unittest.skipUnless(HAVE_FLASK, "Flask assente")
class PdfRoundtrip(_BaseApp):
    """PDF veri con PyMuPDF vero. Ripara il mock di fitz lasciato da
    test_guardrail_api._import_app_with_mocks() prima di usare l'app."""

    TESTO_PDF = "Mario Rossi, IBAN IT60X0542811101000000123456"

    @staticmethod
    def _modulo_reale(nome):
        modulo = sys.modules.get(nome)
        if modulo is None or isinstance(modulo, MagicMock):
            sys.modules.pop(nome, None)
            return importlib.import_module(nome)
        if nome in ("pdf_export", "pdf_text"):
            return importlib.reload(modulo)
        return modulo

    def setUp(self):
        super().setUp()
        try:
            fitz_mod = self._modulo_reale("fitz")
            pdf_text_mod = self._modulo_reale("pdf_text")
            pdf_export_mod = self._modulo_reale("pdf_export")
        except ImportError as e:                     # PyMuPDF non installato
            self.skipTest(f"PyMuPDF assente: {e}")
        self.enter = contextlib.ExitStack()
        self.addCleanup(self.enter.close)
        for nome, modulo in (("fitz", fitz_mod), ("pdf_text", pdf_text_mod),
                             ("pdf_export", pdf_export_mod)):
            self.enter.enter_context(patch.object(APP, nome, modulo))
        self.enter.enter_context(patch.object(APP, "nlp", nlp_vuoto))
        self.pdf_export = pdf_export_mod
        self.addCleanup(self._svuota_documenti)

    def _svuota_documenti(self):
        with APP._DOCS_LOCK:
            APP._DOCS.clear()

    def _pdf_di_prova(self):
        return self.pdf_export.text_to_pdf(self.TESTO_PDF)

    def test_pdf_da_testo_e_application_pdf(self):
        r = self.client.post("/pdf",
                             json={"text": "Scrivi a mario.rossi@example.com"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/pdf")
        self.assertTrue(r.get_data().startswith(b"%PDF-"))
        self.assertTrue(r.headers["Content-Disposition"].startswith("attachment;"))
        self.assertGreaterEqual(int(r.headers["X-PII-Redactions"]), 1)

    def test_pdf_preview_poi_file_e_pagina_png(self):
        r = self.client.post("/pdf/preview", data={
            "pdf": (io.BytesIO(self._pdf_di_prova()), "atto.pdf")},
            content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertGreaterEqual(d["n_pages"], 1)
        self.assertGreaterEqual(d["redactions"], 1)
        for chiave in ("residual", "skipped", "not_found"):
            self.assertIsInstance(d[chiave], int)
        doc_id = d["doc_id"]

        r = self.client.get(f"/doc/{doc_id}/file.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/pdf")
        self.assertTrue(r.get_data().startswith(b"%PDF-"))

        r = self.client.get(f"/doc/{doc_id}/page/0.png")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "image/png")
        self.assertTrue(r.get_data().startswith(b"\x89PNG"))
        self.assertEqual(r.headers.get("Cache-Control"), "private, max-age=600")

        r = self.client.get(f"/doc/{doc_id}/page/999.png")
        self.assertEqual(r.status_code, 404)

    def test_preview_upload_e_png(self):
        r = self.client.post("/preview", data={
            "pdf": (io.BytesIO(self._pdf_di_prova()), "documento.pdf")},
            content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertGreaterEqual(d["n_pages"], 1)
        self.assertIn("IT60X0542811101000000123456", d["text"])
        r = self.client.get(f"/doc/{d['doc_id']}/page/0.png")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "image/png")
        self.assertTrue(r.get_data().startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()