# -*- coding: utf-8 -*-
"""Privacy dei PDF nella guardrail v1, correzione B1 (diagnostiche native MuPDF).

Un PDF valido con un content stream malformato contenente un token sintetico
faceva scrivere il token DAL C di MuPDF su stdout (`MuPDF error: syntax error:
unknown keyword: 'PRIVATE_PATIENT_TOKEN_999'`) e lasciava lo stesso testo nel
buffer nativo `TOOLS.mupdf_warnings`. La prova principale e' a livello di FILE
DESCRIPTOR: un processo figlio fresco (PyMuPDF e Flask veri, torch/transformers
finti, PII_MODEL_DIR su tests/) forza le flag native a ON prima di importare
app.py, poi esegue l'estrattore vero oppure una richiesta multipart vera. Il
padre lancia il figlio con subprocess.run(capture_output=True) e controlla i
pipe: senza la correzione il marcatore compare in stdout, con la correzione no,
e il buffer nativo resta vuoto dopo la chiamata. Un CaptureHandler da solo NON
sarebbe una prova: non vede la scrittura dal C.

I test in-process coprono la validazione delle capability native, il blocco PDF
fail-closed quando il controllo privacy manca o si rompe, gli errori tipizzati
(422/413/504) e il reset con PyMuPDF vero. Le dipendenze Flask/PyMuPDF fanno
saltare solo i test che le richiedono (suite stdlib). Valori SINTETICI, nessun
peso, nessuna rete.
"""

import contextlib
import json
import logging
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "app"))

import guardrail_inputs  # noqa: E402
import pii_dictionary  # noqa: E402

try:
    import fitz

    HAVE_FITZ = not isinstance(fitz, MagicMock)
except ImportError:
    fitz = None
    HAVE_FITZ = False

try:
    from flask import Flask  # noqa: F401

    HAVE_FLASK = True
except ImportError:
    Flask = None
    HAVE_FLASK = False


MARKER = "PRIVATE_PATIENT_TOKEN_999"
CHILD_FLAG = "--child"
RESULT_PREFIX = "__PDF_PRIVACY__ "
BOUND = "PRIVACYBOUND"
TOKEN = "token-pdf-privacy"
PATH = "/api/v1/analyses"
CORRUPT_NUL_PDF = (b"%PDF-1.7\n" + b"1 0 obj\n<<>>\nendobj\n" + b"\x00" * 64
                   + b"trailer\n<<>>\n%%EOF\n")


def _load_app():
    """app.py coi pesi finti: riusa l'istanza gia' importata, altrimenti importa.

    `fitz` resta quello vero quando c'e' (serve per i test in-process); se manca
    si sostituisce con un mock, come fanno gli altri helper, cosi' l'import resta
    possibile anche dove PyMuPDF non e' installato.
    """
    module = sys.modules.get("app")
    if module is not None:
        return module
    saved = {name: sys.modules.get(name) for name in ("torch", "transformers")}
    if not HAVE_FITZ:
        saved["fitz"] = sys.modules.get("fitz")
        sys.modules["fitz"] = MagicMock()
    for name in ("torch", "transformers"):
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
    return app_module


def build_marker_pdf():
    """PDF valido di una pagina con un operatore malformato che contiene MARKER.

    `(Hello) Tj` e' valido e resta estraibile; MARKER no: MuPDF lo segnala come
    "unknown keyword" e scrive il token nella diagnostica nativa. Il fixture
    serve anche a dimostrare che il percorso vero (/pdf magic su .txt/.md)
    instrada lo stesso contenuto.
    """
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello")
    target = None
    for xref in range(1, doc.xref_length()):
        if not doc.xref_is_stream(xref):
            continue
        try:
            stream = doc.xref_stream(xref)
        except Exception:
            continue
        if b"TJ" in stream:
            target = xref
            break
    if target is None:                   # difensivo: content stream non trovato
        doc.close()
        raise RuntimeError("content stream non trovato nel PDF di prova")
    doc.update_stream(
        target,
        b"BT /helv 12 Tf 72 72 Td (Hello) Tj " + MARKER.encode("ascii") + b" ET")
    data = doc.tobytes()
    doc.close()
    return data


def build_blank_pdf(pages):
    """PDF di `pages` pagine vuote (per il tetto pagine)."""
    doc = fitz.open()
    for _index in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def populate_native_warnings():
    """Riempie il buffer nativo con warning REALI (PDF corrotto con byte NUL).

    Ritorna la lunghezza del buffer senza restituirne o stamparne il contenuto:
    e' la prova che il reset successivo ha davvero qualcosa da svuotare.
    """
    doc = fitz.open(stream=CORRUPT_NUL_PDF, filetype="pdf")
    try:
        for page in doc:
            page.get_text()
    finally:
        doc.close()
    return len(fitz.TOOLS.mupdf_warnings(reset=False))


def multipart_body(parts, boundary=BOUND):
    """Corpo multipart grezzo: parts = [(nome, filename_o_None, bytes|str)]."""
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


# --------------------------------------------------------------------------- #
# Modalita' figlio: processo fresco, PyMuPDF/Flask veri, modello finto.
#
# Il figlio serializza SOLO booleani, contatori e testo sanificato (mai il
# contenuto del buffer nativo, mai il marcatore). La prova FD e' del padre.
# --------------------------------------------------------------------------- #
class _LogCapture(logging.Handler):
    """Cattura i record Python: il marcatore non deve passare nemmeno da qui."""

    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        try:
            self.messages.append(record.getMessage())
        except Exception:
            self.messages.append("<non formattabile>")


def _logging_marker_present(capture):
    return any(MARKER in message for message in capture.messages)


def _emit(facts):
    print(RESULT_PREFIX + json.dumps(facts, ensure_ascii=True, sort_keys=True))


def _install_fake_heavy_deps():
    """torch/transformers finti: nessun peso, nessuna CUDA, nessun download."""
    torch = types.ModuleType("torch")

    class Cuda:
        @staticmethod
        def is_available():
            return False

    torch.cuda = Cuda()
    sys.modules["torch"] = torch
    transformers = types.ModuleType("transformers")
    transformers.pipeline = lambda *_args, **_kwargs: (
        lambda chunks: [[] for _chunk in chunks])
    sys.modules["transformers"] = transformers


def _child_startup():
    """Forza le flag native a ON PRIMA di importare app e misura l'effetto."""
    flags_before = [int(fitz.TOOLS.mupdf_display_errors()),
                    int(fitz.TOOLS.mupdf_display_warnings())]
    fitz.TOOLS.mupdf_display_errors(True)
    fitz.TOOLS.mupdf_display_warnings(True)
    flags_forced = [int(fitz.TOOLS.mupdf_display_errors()),
                    int(fitz.TOOLS.mupdf_display_warnings())]
    os.environ["PII_MODEL_DIR"] = str(ROOT / "tests")
    _install_fake_heavy_deps()
    import app as app_module
    flags_after = [int(fitz.TOOLS.mupdf_display_errors()),
                   int(fitz.TOOLS.mupdf_display_warnings())]
    return app_module, {
        "flags_before_force": flags_before,
        "flags_forced_on": flags_forced,
        "flags_after_import": flags_after,
        "privacy_ok": app_module.MUPDF_PRIVACY_OK,
    }


def _child_direct():
    app_module, facts = _child_startup()
    pdf = build_marker_pdf()
    capture = _LogCapture()
    logging.getLogger().addHandler(capture)
    try:
        extracted = app_module._guardrail_extract(
            "synthetic.pdf", pdf, 100000, lambda: None)
    finally:
        logging.getLogger().removeHandler(capture)
    facts["mode"] = "direct"
    facts["extracted"] = extracted
    facts["warnings_len_after"] = len(fitz.TOOLS.mupdf_warnings(reset=True))
    facts["logging_marker"] = _logging_marker_present(capture)
    _emit(facts)


def _child_http():
    app_module, facts = _child_startup()
    os.environ["PII_API_TOKEN"] = TOKEN
    raw = multipart_body([("files", "synthetic.pdf", build_marker_pdf())])
    capture = _LogCapture()
    logging.getLogger().addHandler(capture)
    try:
        response = app_module.app.test_client().post(
            PATH, data=raw,
            content_type="multipart/form-data; boundary=" + BOUND,
            headers={"Authorization": "Bearer " + TOKEN})
        body = response.get_json()
    finally:
        logging.getLogger().removeHandler(capture)
    facts["mode"] = "http"
    facts["status"] = response.status_code
    facts["anonymized"] = body["results"][0]["anonymized_text"]
    facts["warnings_len_after"] = len(fitz.TOOLS.mupdf_warnings(reset=True))
    facts["logging_marker"] = _logging_marker_present(capture)
    _emit(facts)


def _child_failure():
    app_module, facts = _child_startup()
    pdf = build_marker_pdf()
    cases = []
    capture = _LogCapture()
    logging.getLogger().addHandler(capture)

    def run(label, expected, call_):
        try:
            value = call_()
        except guardrail_inputs.InputError as exc:
            got = [exc.status, exc.code]
        except app_module.pii_dictionary.DeadlineExceeded:
            got = [504, "deadline_exceeded"]
        except BaseException as exc:  # noqa: BLE001 - solo il tipo, mai il messaggio
            got = ["unexpected", type(exc).__name__]
        else:
            got = ["ok", value]
        cases.append({
            "case": label,
            "expected": expected,
            "got": got,
            "warnings_len_after": len(fitz.TOOLS.mupdf_warnings(reset=True)),
        })

    def deadline_check():
        raise app_module.pii_dictionary.DeadlineExceeded()

    facts["prepopulated_len"] = populate_native_warnings()
    run("misnamed_txt", ["ok", "Hello\n"],
        lambda: app_module._guardrail_extract(
            "misnamed.txt", pdf, 100000, lambda: None))
    run("misnamed_md", ["ok", "Hello\n"],
        lambda: app_module._guardrail_extract(
            "misnamed.md", pdf, 100000, lambda: None))
    run("open_invalid", [422, "unreadable_file"],
        lambda: app_module._guardrail_extract(
            "broken.pdf", b"%PDF-1.7\nnot really a pdf", 100000, lambda: None))
    run("page_limit", [413, "payload_too_large"],
        lambda: app_module._guardrail_extract(
            "long.pdf", build_blank_pdf(201), 100000, lambda: None))
    run("char_limit", [413, "payload_too_large"],
        lambda: app_module._guardrail_extract(
            "synthetic.pdf", pdf, 3, lambda: None))
    run("deadline", [504, "deadline_exceeded"],
        lambda: app_module._guardrail_extract(
            "synthetic.pdf", pdf, 100000, deadline_check))
    facts["cases"] = cases

    # strict failure con il buffer riempito PRIMA della chiamata vera
    real_collect = app_module.pdf_text.collect_readable_text
    facts["strict_prepopulated_len"] = populate_native_warnings()

    def strict_boom(*_args, **_kwargs):
        raise app_module.pdf_text.PdfTextError()

    app_module.pdf_text.collect_readable_text = strict_boom
    try:
        run("strict_failure", [422, "unreadable_file"],
            lambda: app_module._guardrail_extract(
                "synthetic.pdf", pdf, 100000, lambda: None))
    finally:
        app_module.pdf_text.collect_readable_text = real_collect
        logging.getLogger().removeHandler(capture)
    facts["mode"] = "failure"
    facts["logging_marker"] = _logging_marker_present(capture)
    _emit(facts)


def _child_main(mode):
    if mode == "direct":
        _child_direct()
    elif mode == "http":
        _child_http()
    elif mode == "failure":
        _child_failure()
    else:
        raise SystemExit("modalita' figlio sconosciuta: %r" % (mode,))


@unittest.skipUnless(HAVE_FLASK and HAVE_FITZ, "Flask/PyMuPDF assenti")
class SubprocessFdPrivacy(unittest.TestCase):
    """La prova FD: il marcatore non esce dai pipe del processo figlio."""

    def _run_child(self, mode):
        env = dict(os.environ)
        env.pop("COVERAGE_PROCESS_START", None)
        env.pop("COVERAGE_PROCESS_CONFIG", None)
        env["PII_MODEL_DIR"] = str(ROOT / "tests")
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), CHILD_FLAG, mode],
            capture_output=True, cwd=str(ROOT), env=env, timeout=300)

    def _facts(self, proc):
        stdout = proc.stdout.decode("utf-8", "replace")
        stderr = proc.stderr.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 0,
                         "figlio fallito:\n" + stderr[-4000:])
        lines = [line for line in stdout.splitlines()
                 if line.startswith(RESULT_PREFIX)]
        self.assertTrue(lines, "nessun risultato serializzato dal figlio")
        return json.loads(lines[-1][len(RESULT_PREFIX):]), stdout, stderr

    def _assert_privacy(self, facts, stdout, stderr):
        self.assertNotIn(MARKER, stdout)
        self.assertNotIn(MARKER, stderr)
        self.assertNotIn(MARKER, json.dumps(facts))
        self.assertEqual(facts["flags_forced_on"], [1, 1],
                         "il figlio non e' partito con le flag su ON")
        self.assertEqual(facts["flags_after_import"], [0, 0],
                         "app non ha spento le diagnostiche native all'avvio")
        self.assertTrue(facts["privacy_ok"],
                        "app non ha verificato tutte le capability native")
        self.assertFalse(facts["logging_marker"])

    def test_estrazione_diretta_senza_marcatore_sui_fd(self):
        facts, stdout, stderr = self._facts(self._run_child("direct"))
        self._assert_privacy(facts, stdout, stderr)
        self.assertEqual(facts["extracted"], "Hello\n")
        self.assertEqual(facts["warnings_len_after"], 0)

    def test_richiesta_multipart_senza_marcatore_sui_fd(self):
        facts, stdout, stderr = self._facts(self._run_child("http"))
        self._assert_privacy(facts, stdout, stderr)
        self.assertEqual(facts["status"], 200)
        self.assertEqual(facts["anonymized"], "Hello\n")
        self.assertEqual(facts["warnings_len_after"], 0)

    def test_percorsi_di_errore_svuotano_il_buffer_e_non_declassano(self):
        facts, stdout, stderr = self._facts(self._run_child("failure"))
        self._assert_privacy(facts, stdout, stderr)
        self.assertGreater(facts["prepopulated_len"], 0,
                           "il buffer nativo non si e' riempito: prova debole")
        self.assertGreater(facts["strict_prepopulated_len"], 0)
        self.assertEqual(
            [(case["case"], case["got"]) for case in facts["cases"]],
            [("misnamed_txt", ["ok", "Hello\n"]),
             ("misnamed_md", ["ok", "Hello\n"]),
             ("open_invalid", [422, "unreadable_file"]),
             ("page_limit", [413, "payload_too_large"]),
             ("char_limit", [413, "payload_too_large"]),
             ("deadline", [504, "deadline_exceeded"]),
             ("strict_failure", [422, "unreadable_file"])])
        for case in facts["cases"]:
            self.assertEqual(case["warnings_len_after"], 0, case["case"])


@unittest.skipUnless(HAVE_FLASK, "app non importabile senza Flask")
class StartupSilencePolicy(unittest.TestCase):
    """All'import si spengono UNA volta errori/warning; niente toggle per richiesta."""

    def test_spegne_i_display_native_e_non_li_riaccende_mai(self):
        saved_app = sys.modules.pop("app", None)
        saved = {name: sys.modules.get(name)
                 for name in ("torch", "transformers", "fitz")}
        fake_fitz = MagicMock()
        fake_fitz.TOOLS.mupdf_display_errors.return_value = 0
        fake_fitz.TOOLS.mupdf_display_warnings.return_value = 0
        fake_fitz.TOOLS.mupdf_warnings.return_value = "SENSITIVE-RESET-RESULT"
        fake_fitz.open.return_value = _FakeDoc()
        previous = os.environ.get("PII_MODEL_DIR")
        fresh = None
        try:
            sys.modules["torch"] = MagicMock()
            sys.modules["transformers"] = MagicMock()
            sys.modules["fitz"] = fake_fitz
            os.environ["PII_MODEL_DIR"] = str(ROOT / "tests")
            import app as fresh  # noqa: F401
        finally:
            if previous is None:
                os.environ.pop("PII_MODEL_DIR", None)
            else:
                os.environ["PII_MODEL_DIR"] = previous
            sys.modules.pop("app", None)
            if saved_app is not None:
                sys.modules["app"] = saved_app
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
        self.assertIsNotNone(fresh)
        self.assertTrue(fresh.MUPDF_PRIVACY_OK)
        for name in ("mupdf_display_errors", "mupdf_display_warnings"):
            self.assertEqual(getattr(fake_fitz.TOOLS, name).call_args_list,
                             [call(False), call()])
        self.assertEqual(fake_fitz.TOOLS.mupdf_warnings.call_args_list,
                         [call(reset=True)])
        # Una richiesta PDF pulita resetta il buffer, ma non ritocca flag o getter.
        with patch.object(fresh.pdf_text, "collect_readable_text",
                          return_value="Hello"):
            self.assertEqual(fresh._guardrail_extract(
                "a.pdf", b"%PDF-", 100, lambda: None), "Hello")
        for name in ("mupdf_display_errors", "mupdf_display_warnings"):
            self.assertEqual(getattr(fake_fitz.TOOLS, name).call_args_list,
                             [call(False), call()])
        self.assertEqual(fake_fitz.TOOLS.mupdf_warnings.call_args_list,
                         [call(reset=True), call(reset=True)])


class _FakeDoc:
    is_pdf = True
    needs_pass = False
    is_encrypted = False
    page_count = 1

    def __init__(self):
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def close(self):
        self.closed = True


@unittest.skipUnless(HAVE_FLASK, "app non importabile senza Flask")
class ExtractFinallyReset(unittest.TestCase):
    """`_guardrail_extract`: reset, errori originali e degradazione fail-closed."""

    @classmethod
    def setUpClass(cls):
        cls.APP = _load_app()

    def _patched(self, *, document=None, open_error=None, collect=None):
        fake = MagicMock()
        if open_error is not None:
            fake.open.side_effect = open_error
        else:
            fake.open.return_value = document if document is not None else _FakeDoc()
        self.enter = contextlib.ExitStack()
        self.addCleanup(self.enter.close)
        self.enter.enter_context(patch.object(self.APP, "MUPDF_PRIVACY_OK", True))
        self.enter.enter_context(patch.object(self.APP, "fitz", fake))
        self.fake = fake
        if collect is not None:
            self.enter.enter_context(
                patch.object(self.APP.pdf_text, "collect_readable_text", collect))
        return fake

    def _assert_reset_once(self):
        self.assertEqual(self.fake.TOOLS.mupdf_warnings.call_args_list,
                         [call(reset=True)])

    def test_successo_reset_dopo_estrazione(self):
        events = []

        def collect(*_args, **_kwargs):
            events.append("collect")
            return "Hello"

        fake = self._patched(collect=collect)
        fake.TOOLS.mupdf_warnings.side_effect = (
            lambda *_args, **_kwargs: events.append("reset"))
        out = self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self.assertEqual(out, "Hello")
        self.assertEqual(events, ["collect", "reset"])
        self._assert_reset_once()

    def test_reset_helper_reports_success_without_retaining_result(self):
        fake = self._patched()
        fake.TOOLS.mupdf_warnings.return_value = "SENSITIVE-DIAGNOSTIC"
        self.assertTrue(self.APP._reset_native_mupdf_warnings())
        self.assertTrue(self.APP.MUPDF_PRIVACY_OK)
        self._assert_reset_once()

    def test_limite_413_non_degradato_e_reset(self):
        def collect(*_args, **_kwargs):
            raise self.APP.pdf_text.PdfTextTooLarge()

        self._patched(collect=collect)
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (413, "payload_too_large"))
        self._assert_reset_once()

    def test_errore_strict_422_e_reset(self):
        def collect(*_args, **_kwargs):
            raise self.APP.pdf_text.PdfTextError()

        self._patched(collect=collect)
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (422, "unreadable_file"))
        self._assert_reset_once()

    def test_deadline_504_e_reset(self):
        def collect(*_args, **_kwargs):
            raise self.APP.pii_dictionary.DeadlineExceeded()

        self._patched(collect=collect)
        with self.assertRaises(self.APP.pii_dictionary.DeadlineExceeded):
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self._assert_reset_once()

    def test_open_fallita_422_e_reset(self):
        self._patched(open_error=RuntimeError("PDF rotto"))
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (422, "unreadable_file"))
        self._assert_reset_once()

    def test_pdf_blank_422_e_reset(self):
        self._patched(collect=lambda *_args, **_kwargs: "   ")
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (422, "no_extractable_text"))
        self._assert_reset_once()

    def test_deadline_dopo_open_chiude_documento_e_reset(self):
        document = _FakeDoc()
        opened = False
        deadline_raised = False
        fake = self._patched(document=document)

        def open_document(*_args, **_kwargs):
            nonlocal opened
            opened = True
            return document

        fake.open.side_effect = open_document

        def check_deadline():
            nonlocal deadline_raised
            if opened and not deadline_raised:
                deadline_raised = True
                raise self.APP.pii_dictionary.DeadlineExceeded()

        with self.assertRaises(self.APP.pii_dictionary.DeadlineExceeded):
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, check_deadline)
        fake.open.assert_called_once()
        self.assertTrue(document.closed)
        self._assert_reset_once()

    def test_deadline_prima_di_open_recupera_pdf_lane(self):
        document = _FakeDoc()
        fake = self._patched(
            document=document, collect=lambda *_args, **_kwargs: "Hello")

        def expired():
            raise self.APP.pii_dictionary.DeadlineExceeded()

        with self.assertRaises(self.APP.pii_dictionary.DeadlineExceeded):
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, expired)
        fake.open.assert_not_called()
        fake.TOOLS.mupdf_warnings.assert_not_called()
        self.assertTrue(self.APP.MUPDF_PRIVACY_OK)

        self.assertEqual(self.APP._guardrail_extract(
            "a.pdf", b"%PDF-", 100, lambda: None), "Hello")
        fake.open.assert_called_once()
        self._assert_reset_once()

    def test_reset_rotto_non_sostituisce_errore_e_blocca_i_pdf_successivi(self):
        def collect(*_args, **_kwargs):
            raise self.APP.pdf_text.PdfTextTooLarge()

        fake = self._patched(collect=collect)
        fake.TOOLS.mupdf_warnings.side_effect = RuntimeError("cleanup rotto")
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (413, "payload_too_large"))
        self.assertFalse(self.APP.MUPDF_PRIVACY_OK)
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (503, "unavailable"))
        self.assertEqual(fake.open.call_count, 1)

    def test_reset_rotto_preserva_422_413_504_e_disabilita_pdf_successivi(self):
        cases = (
            (self.APP.pdf_text.PdfTextError(), (422, "unreadable_file")),
            (self.APP.pdf_text.PdfTextTooLarge(), (413, "payload_too_large")),
            (self.APP.pii_dictionary.DeadlineExceeded(),
             (504, "deadline_exceeded")),
        )
        for error, expected in cases:
            with self.subTest(expected=expected):
                fake = MagicMock()
                fake.open.return_value = _FakeDoc()
                fake.TOOLS.mupdf_warnings.side_effect = RuntimeError("cleanup rotto")
                with patch.object(self.APP, "MUPDF_PRIVACY_OK", True):
                    with patch.object(self.APP, "fitz", fake):
                        with patch.object(
                                self.APP.pdf_text, "collect_readable_text",
                                side_effect=error):
                            error_type = (self.APP.pii_dictionary.DeadlineExceeded
                                          if expected[0] == 504
                                          else guardrail_inputs.InputError)
                            with self.assertRaises(error_type) as ctx:
                                self.APP._guardrail_extract(
                                    "a.pdf", b"%PDF-", 100, lambda: None)
                        self.assertEqual((ctx.exception.status, ctx.exception.code),
                                         expected)
                        self.assertFalse(self.APP.MUPDF_PRIVACY_OK)
                        with self.assertRaises(guardrail_inputs.InputError) as ctx:
                            self.APP._guardrail_extract(
                                "a.pdf", b"%PDF-", 100, lambda: None)
                        self.assertEqual((ctx.exception.status, ctx.exception.code),
                                         (503, "unavailable"))
                fake.open.assert_called_once()

    def test_reset_rotto_su_successo_rende_la_richiesta_unavailable(self):
        fake = self._patched(collect=lambda *_args, **_kwargs: "Hello")
        fake.TOOLS.mupdf_warnings.side_effect = RuntimeError("cleanup rotto")
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (503, "unavailable"))
        self.assertFalse(self.APP.MUPDF_PRIVACY_OK)
        with self.assertRaises(guardrail_inputs.InputError) as ctx:
            self.APP._guardrail_extract("a.pdf", b"%PDF-", 100, lambda: None)
        self.assertEqual((ctx.exception.status, ctx.exception.code),
                         (503, "unavailable"))
        self.assertEqual(fake.open.call_count, 1)

    def test_tools_assenti_bloccano_pdf_prima_di_open_ma_non_il_testo(self):
        fake = SimpleNamespace(open=MagicMock())
        with patch.object(self.APP, "fitz", fake):
            with patch.object(self.APP, "MUPDF_PRIVACY_OK", False):
                for filename in ("a.pdf", "misnamed.md"):
                    with self.subTest(filename=filename):
                        with self.assertRaises(guardrail_inputs.InputError) as ctx:
                            self.APP._guardrail_extract(
                                filename, b"%PDF-", 100, lambda: None)
                        self.assertEqual((ctx.exception.status, ctx.exception.code),
                                         (503, "unavailable"))
                self.assertEqual(self.APP._guardrail_extract(
                    "a.txt", b"plain text", 100, lambda: None), "plain text")
        fake.open.assert_not_called()

    def test_reset_assente_o_raising_disabilita_capability(self):
        for fitz_module in (SimpleNamespace(),
                            SimpleNamespace(TOOLS=SimpleNamespace(
                                mupdf_warnings=lambda **_kwargs: (_ for _ in ()).throw(
                                    RuntimeError("reset rotto"))))):
            with self.subTest(fitz_module=fitz_module):
                with patch.object(self.APP, "MUPDF_PRIVACY_OK", True):
                    with patch.object(self.APP, "fitz", fitz_module):
                        self.assertFalse(self.APP._reset_native_mupdf_warnings())
                        self.assertFalse(self.APP.MUPDF_PRIVACY_OK)

    def test_probe_fail_closed_per_getter_setter_e_reset_mancanti_o_rotti(self):
        def fake_native(*, include_errors_get=True, include_warnings_set=True,
                        include_reset=True, reset_error=False, setter_error=False,
                        ignored=False, truthy_getter=False):
            initial = 1 if ignored or truthy_getter else 0
            state = {"errors": initial, "warnings": initial}

            def display(key):
                def call(value=None):
                    if value is not None:
                        if setter_error:
                            raise RuntimeError("display setter rotto")
                        if not ignored:
                            state[key] = value
                        return 0
                    return 1 if truthy_getter else state[key]
                return call

            tools = {
                "mupdf_display_errors": display("errors"),
                "mupdf_display_warnings": display("warnings"),
            }
            if not include_errors_get:
                # Setter remains available, but there is no getter to verify it.
                tools["mupdf_display_errors"] = lambda _value: None
            if not include_warnings_set:
                tools.pop("mupdf_display_warnings")
            if include_reset:
                if reset_error:
                    def reset(**_kwargs):
                        raise RuntimeError("reset probe rotto")
                else:
                    reset = lambda **_kwargs: "SENSITIVE-DIAGNOSTIC"
                tools["mupdf_warnings"] = reset
            return SimpleNamespace(TOOLS=SimpleNamespace(**tools))

        cases = (
            (SimpleNamespace(), False, "all missing"),
            (fake_native(include_errors_get=False), False, "getter missing"),
            (fake_native(include_warnings_set=False), False, "setter missing"),
            (fake_native(include_reset=False), False, "reset missing"),
            (fake_native(reset_error=True), False, "reset raising"),
            (fake_native(setter_error=True), False, "setter raising"),
            (fake_native(ignored=True), False, "setter ignores False"),
            (fake_native(truthy_getter=True), False, "getter remains on"),
        )
        for fitz_module, expected, label in cases:
            with self.subTest(case=label), patch.object(self.APP, "fitz", fitz_module):
                self.assertIs(self.APP._silence_native_mupdf_diagnostics(), expected)

    def test_probe_accetta_solo_false_o_zero_e_rifiuta_altri_falsy(self):
        def fake_native(statuses):
            def display(status):
                def call(value=None):
                    return 0 if value is not None else status
                return call

            return SimpleNamespace(TOOLS=SimpleNamespace(
                mupdf_display_errors=display(statuses["errors"]),
                mupdf_display_warnings=display(statuses["warnings"]),
                mupdf_warnings=lambda **_kwargs: "SENSITIVE-DIAGNOSTIC",
            ))

        for status in (False, 0):
            with self.subTest(accepted_status=status):
                with patch.object(self.APP, "fitz", fake_native({
                        "errors": status, "warnings": status})):
                    self.assertTrue(self.APP._silence_native_mupdf_diagnostics())

        for status in (None, "", [], (), {}, b"", 0.0):
            for getter_name in ("errors", "warnings"):
                with self.subTest(rejected_status=status, getter=getter_name):
                    statuses = {"errors": False, "warnings": False}
                    statuses[getter_name] = status
                    with patch.object(self.APP, "fitz", fake_native(statuses)):
                        self.assertFalse(
                            self.APP._silence_native_mupdf_diagnostics())

    def test_probe_supporta_lookup_module_level_se_fitz_tools_non_espone_funzioni(self):
        state = {"errors": 1, "warnings": 1}

        def display(key):
            def call(value=None):
                if value is not None:
                    state[key] = value
                    return 0
                return state[key]
            return call

        fake_fitz = SimpleNamespace(
            TOOLS=SimpleNamespace(),
            mupdf_display_errors=display("errors"),
            mupdf_display_warnings=display("warnings"),
            mupdf_warnings=lambda **_kwargs: "SENSITIVE-DIAGNOSTIC",
        )
        with patch.object(self.APP, "fitz", fake_fitz):
            self.assertTrue(self.APP._silence_native_mupdf_diagnostics())
        self.assertEqual(state, {"errors": False, "warnings": False})


@unittest.skipUnless(HAVE_FLASK, "Flask assente")
class PrivacyUnavailableRequests(unittest.TestCase):
    """La guardia PDF non deve allargarsi a JSON, testo o inferenza del modello."""

    @classmethod
    def setUpClass(cls):
        cls.APP = _load_app()

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"PII_API_TOKEN": TOKEN}))
        self.client = self.APP.app.test_client()

    @staticmethod
    def _no_entities(chunks):
        return [[] for _chunk in chunks]

    def test_json_txt_md_succeededono_con_capability_pdf_false(self):
        headers = {"Authorization": "Bearer " + TOKEN}
        with patch.object(self.APP, "MUPDF_PRIVACY_OK", False):
            with patch.object(self.APP, "nlp", self._no_entities):
                response = self.client.post(PATH, json={"text": "plain JSON"},
                                        headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["results"][0]["anonymized_text"],
                                 "plain JSON")
                for filename in ("plain.txt", "plain.md"):
                    response = self.client.post(
                        PATH,
                        data=multipart_body([("files", filename, "plain text")]),
                        content_type="multipart/form-data; boundary=" + BOUND,
                        headers=headers)
                    self.assertEqual(response.status_code, 200, filename)
                    self.assertEqual(
                        response.get_json()["results"][0]["anonymized_text"],
                        "plain text")

    def test_pdf_in_mixed_batch_blocked_before_open_or_inference(self):
        headers = {"Authorization": "Bearer " + TOKEN}
        fake_fitz = SimpleNamespace(open=MagicMock())
        model_calls = []

        def model(chunks):
            model_calls.extend(chunks)
            return self._no_entities(chunks)

        raw = multipart_body([
            ("files", "first.txt", "safe text"),
            ("files", "private.md", b"%PDF-opaque synthetic bytes"),
            ("dictionary", None, '{"[FULLNAME_9]":"SYNTHETIC SEED"}'),
        ])
        with patch.object(self.APP, "MUPDF_PRIVACY_OK", False):
            with patch.object(self.APP, "fitz", fake_fitz):
                with patch.object(self.APP, "nlp", model):
                    response = self.client.post(
                        PATH, data=raw,
                        content_type="multipart/form-data; boundary=" + BOUND,
                        headers=headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {
            "error": "Service unavailable.", "code": "unavailable"})
        fake_fitz.open.assert_not_called()
        self.assertEqual(model_calls, [])


@unittest.skipUnless(HAVE_FLASK and HAVE_FITZ, "Flask/PyMuPDF assenti")
class RealFitzWarningBuffer(unittest.TestCase):
    """PyMuPDF vero in-process: il fixture genera warning nativi e il reset li svuota."""

    @classmethod
    def setUpClass(cls):
        cls.APP = _load_app()

    def setUp(self):
        self._stack = contextlib.ExitStack()
        self.addCleanup(self._stack.close)
        self._stack.enter_context(patch.object(self.APP, "fitz", fitz))
        self.addCleanup(fitz.TOOLS.mupdf_warnings, reset=True)
        fitz.TOOLS.mupdf_warnings(reset=True)

    def test_il_fixture_genera_warning_nativi(self):
        doc = fitz.open(stream=build_marker_pdf(), filetype="pdf")
        try:
            for page in doc:
                page.get_text()
        finally:
            doc.close()
        self.assertGreater(len(fitz.TOOLS.mupdf_warnings(reset=False)), 0)

    def test_buffer_prepopolato_svuotato_da_estrazione_vera(self):
        pdf = build_marker_pdf()
        self.assertGreater(populate_native_warnings(), 0)
        out = self.APP._guardrail_extract("misnamed.txt", pdf, 100000,
                                          lambda: None)
        self.assertEqual(out, "Hello\n")
        self.assertEqual(fitz.TOOLS.mupdf_warnings(reset=False), "")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == CHILD_FLAG:
        _child_main(sys.argv[2])
    else:
        raise SystemExit("uso: %s --child {direct|http|failure}" % sys.argv[0])
