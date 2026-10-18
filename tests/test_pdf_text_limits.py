# -*- coding: utf-8 -*-
"""`pdf_text.collect_readable_text` con i parametri opzionali della guardrail.

Il percorso multifile usa massimo caratteri, deadline cooperativa e modalita'
strict; il percorso legacy (senza parametri) deve restare identico, tolleranza
su annots/widgets/TOC compresa. Tutto duck-typed: nessun import di PyMuPDF,
gira sulla sola libreria standard. I valori sono SINTETICI.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "app"))

import pdf_text  # noqa: E402
import pii_dictionary  # noqa: E402


class FakeWidget:
    def __init__(self, value):
        self.field_value = value


class FakeAnnot:
    def __init__(self, content="", subject="", title="", type_id=0):
        self.type = (type_id, "Text")
        self.info = {"content": content, "subject": subject, "title": title}


class FakePage:
    def __init__(self, text="", widgets=(), annots=(), annots_broken=False,
                 widgets_broken=False):
        self._text = text
        self._widgets = list(widgets)
        self._annots = list(annots)
        self._annots_broken = annots_broken
        self._widgets_broken = widgets_broken
        self.text_calls = 0

    def get_text(self):
        self.text_calls += 1
        return self._text

    def widgets(self):
        if self._widgets_broken:
            raise RuntimeError("widget rotti")
        return iter(self._widgets)

    def annots(self):
        if self._annots_broken:
            raise RuntimeError("annots rotti")
        return iter(self._annots)


class FakeDoc(list):
    def __init__(self, pages, toc=None, toc_broken=False):
        super().__init__(pages)
        self._toc = list(toc or [])
        self._toc_broken = toc_broken

    def get_toc(self, simple=True):
        if self._toc_broken:
            raise RuntimeError("toc rotta")
        return self._toc


class MaxChars(unittest.TestCase):
    def test_conta_anche_i_separatori_del_join(self):
        doc = FakeDoc([FakePage(text="abc"), FakePage(text="de")])
        self.assertEqual(pdf_text.collect_readable_text(doc), "abc\nde")
        self.assertEqual(
            pdf_text.collect_readable_text(doc, max_chars=6), "abc\nde")
        with self.assertRaises(pdf_text.PdfTextTooLarge):
            pdf_text.collect_readable_text(doc, max_chars=5)

    def test_i_pezzi_vuoti_contano_come_separatori(self):
        doc = FakeDoc([FakePage(text=""), FakePage(text="")])
        self.assertEqual(pdf_text.collect_readable_text(doc), "\n")
        self.assertEqual(pdf_text.collect_readable_text(doc, max_chars=1), "\n")
        with self.assertRaises(pdf_text.PdfTextTooLarge):
            pdf_text.collect_readable_text(doc, max_chars=0)

    def test_abort_anticipato_non_visita_le_pagine_dopo(self):
        first = FakePage(text="x" * 100)
        second = FakePage(text="mai")
        doc = FakeDoc([first, second])
        with self.assertRaises(pdf_text.PdfTextTooLarge):
            pdf_text.collect_readable_text(doc, max_chars=10)
        self.assertEqual(first.text_calls, 1)
        self.assertEqual(second.text_calls, 0)

    def test_e_un_pdf_text_error(self):
        self.assertTrue(issubclass(pdf_text.PdfTextTooLarge, pdf_text.PdfTextError))


class StrictMode(unittest.TestCase):
    def test_annots_rotti_tollerati_di_default_e_strict_errore(self):
        doc = FakeDoc([FakePage(text="corpo", annots_broken=True)])
        self.assertEqual(pdf_text.collect_readable_text(doc), "corpo")
        with self.assertRaises(pdf_text.PdfTextError):
            pdf_text.collect_readable_text(doc, strict=True)

    def test_widgets_rotti_tollerati_di_default_e_strict_errore(self):
        doc = FakeDoc([FakePage(text="corpo", widgets_broken=True)])
        self.assertEqual(pdf_text.collect_readable_text(doc), "corpo")
        with self.assertRaises(pdf_text.PdfTextError):
            pdf_text.collect_readable_text(doc, strict=True)

    def test_toc_rotta_tollerata_di_default_e_strict_errore(self):
        doc = FakeDoc([FakePage(text="corpo")], toc_broken=True)
        self.assertEqual(pdf_text.collect_readable_text(doc), "corpo")
        with self.assertRaises(pdf_text.PdfTextError):
            pdf_text.collect_readable_text(doc, strict=True)

    def test_legacy_tollera_anche_il_valore_singolo_rotto(self):
        class BrokenInfo:
            def __getitem__(self, _key):
                raise RuntimeError("info rotta")

        annot = FakeAnnot()
        annot.info = BrokenInfo()
        doc = FakeDoc([FakePage(text="corpo", annots=[annot])])
        self.assertEqual(pdf_text.collect_readable_text(doc), "corpo")
        with self.assertRaises(pdf_text.PdfTextError):
            pdf_text.collect_readable_text(doc, strict=True)

    def test_get_text_rotto_propaga_in_tolleranza_e_diventa_strict(self):
        class BrokenPage:
            def get_text(self):
                raise RuntimeError("get_text rotta")

        doc = [BrokenPage()]
        with self.assertRaises(RuntimeError):
            pdf_text.collect_readable_text(doc)
        with self.assertRaises(pdf_text.PdfTextError):
            pdf_text.collect_readable_text(doc, strict=True)


class Deadline(unittest.TestCase):
    def test_controllata_a_pagine_annotazioni_widget_e_toc(self):
        calls = []

        def check():
            calls.append(1)

        doc = FakeDoc(
            [FakePage(text="a", annots=[FakeAnnot(content="b")],
                      widgets=[FakeWidget("c")])],
            toc=[[1, "d", 1]],
        )
        out = pdf_text.collect_readable_text(doc, check_deadline=check)
        self.assertIn("d", out)
        self.assertGreaterEqual(len(calls), 4)

    def test_deadline_non_viene_degradata_dalla_tolleranza(self):
        def check():
            raise pii_dictionary.DeadlineExceeded()

        doc = FakeDoc([FakePage(text="a", annots=[FakeAnnot(content="b")])])
        with self.assertRaises(pii_dictionary.DeadlineExceeded):
            pdf_text.collect_readable_text(doc, check_deadline=check)
        with self.assertRaises(pii_dictionary.DeadlineExceeded):
            pdf_text.collect_readable_text(doc, check_deadline=check, strict=True)

    def test_deadline_subito_dopo_get_text_precede_limite_caratteri(self):
        class Page(FakePage):
            returned = False

            def get_text(self):
                self.text_calls += 1
                self.returned = True
                return "x"

        page = Page()

        def check():
            if page.returned:
                raise pii_dictionary.DeadlineExceeded()

        with self.assertRaises(pii_dictionary.DeadlineExceeded):
            pdf_text.collect_readable_text(
                FakeDoc([page]), max_chars=0, check_deadline=check, strict=True)
        self.assertEqual(page.text_calls, 1)

    def test_limite_non_viene_degradato_dalla_tolleranza(self):
        doc = FakeDoc([FakePage(text="a", annots=[FakeAnnot(content="b" * 100)])])
        with self.assertRaises(pdf_text.PdfTextTooLarge):
            pdf_text.collect_readable_text(doc, max_chars=5)


class LegacyDefault(unittest.TestCase):
    def test_output_invariato_senza_parametri(self):
        doc = FakeDoc(
            [FakePage(text="pagina", annots=[FakeAnnot(content="nota"),
                                             FakeAnnot(content="redazione",
                                                       type_id=12)],
                      widgets=[FakeWidget("campo"), FakeWidget("")])],
            toc=[[1, "titolo", 1]],
        )
        expected = "\n".join(["pagina", "nota", "", "", "campo", "titolo"])
        self.assertEqual(pdf_text.collect_readable_text(doc), expected)

    def test_secondo_argomento_posizionale_invariato(self):
        doc = FakeDoc([FakePage(text="p", annots=[FakeAnnot(content="rossa",
                                                           type_id=12)])])
        self.assertEqual(pdf_text.collect_readable_text(doc, 12), "p")

    def test_doc_vuoto(self):
        self.assertEqual(pdf_text.collect_readable_text(FakeDoc([])), "")


if __name__ == "__main__":
    unittest.main()
