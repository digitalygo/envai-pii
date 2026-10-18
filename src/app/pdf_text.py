# -*- coding: utf-8 -*-
"""Testo leggibile di un PDF: content stream + annotazioni + campi modulo + TOC.

Come `detectors` e `pdf_export`, questo modulo lavora solo su oggetti duck-typed:
nessun import di torch/transformers/fitz, quindi e' testabile in isolamento.
`app._text_from_bytes` e `pdf_export._readable_text` lo usano sullo stesso
documento aperto da PyMuPDF.

Nei PDF fillable (AcroForm) il valore sta nel widget, non nel content stream:
`page.get_text()` torna vuoto e /analyze rispondeva 400 (issue #85).

Parametri opzionali keyword-only (percorso strict della guardrail multifile):
  - `max_chars`: budget di caratteri del risultato, contando anche i separatori
    "\\n" del join finale; superato -> `PdfTextTooLarge` subito, senza aspettare
    la fine del documento;
  - `check_deadline`: callback cooperativa richiamata a ogni pagina, annotazione,
    widget e voce TOC;
  - `strict`: False (default) mantiene la tolleranza storica su annots/widgets/
    TOC; True la converte in `PdfTextError`, per non dichiarare "nessun testo"
    quando l'estrazione e' stata incompleta.

Senza parametri opzionali il comportamento resta identico a prima, byte per byte.
"""

import pii_dictionary

# PyMuPDF: fitz.PDF_ANNOT_REDACT. Le annotazioni di redazione non sono testo
# del documento, e in verifica residui andrebbero contate due volte.
REDACT_ANNOT = 12


class PdfTextError(Exception):
    """Estrazione non affidabile (modalita' strict) o fallita."""


class PdfTextTooLarge(PdfTextError):
    """Il testo leggibile eccede il budget `max_chars`."""


def collect_readable_text(doc, redact_annot_type=REDACT_ANNOT, *, max_chars=None,
                          check_deadline=None, strict=False):
    """TUTTO il testo leggibile: pagine + annotazioni + campi modulo + segnalibri.

    `doc` e' un iterabile di pagine con `get_text()`, `annots()`, `widgets()`
    e (sul documento) `get_toc(simple=True)`: il contratto di PyMuPDF, senza
    importarlo. NB: non vede il testo dentro immagini raster.
    """
    parts = []
    length = 0

    def check():
        if check_deadline is not None:
            check_deadline()

    def add(piece):
        nonlocal length
        length += (1 if parts else 0) + len(piece)
        if max_chars is not None and length > max_chars:
            raise PdfTextTooLarge()
        parts.append(piece)

    def add_all(pieces):
        # add() per elemento: una callback che fallisce a meta' lascia i pezzi
        # gia' raccolti, come faceva `parts.extend(generator)` nello storico.
        for piece in pieces:
            add(piece)

    def tolerant(collect):
        try:
            collect()
        except (pii_dictionary.DeadlineExceeded, PdfTextTooLarge):
            raise                      # deadline e limite non si degradano mai
        except Exception:
            if strict:
                raise PdfTextError()

    for page in doc:
        check()
        try:
            page_text = page.get_text()
        except Exception:
            if strict:
                raise PdfTextError()
            raise
        check()                    # get_text e' nativo e non interrompibile
        add(page_text or "")

        def collect_annots(page=page):
            for a in page.annots() or ():
                check()
                if a.type[0] == redact_annot_type:
                    continue
                info = a.info or {}
                add_all(str(info.get(k) or "")
                        for k in ("content", "subject", "title"))

        tolerant(collect_annots)

        def collect_widgets(page=page):
            for w in page.widgets() or ():
                check()
                val = w.field_value
                if isinstance(val, str) and val:
                    add(val)

        tolerant(collect_widgets)

    def collect_toc():
        for entry in doc.get_toc(simple=True) or ():
            check()
            add(str(entry[1] or ""))

    tolerant(collect_toc)
    return "\n".join(parts)
