# -*- coding: utf-8 -*-
"""
Input multipart della guardrail API v1 (ENVAS-23, estensione multifile).

Modulo separato dal guscio HTTP: la struttura `multipart/form-data` viene letta
con il `MultipartDecoder` NATIVO di Werkzeug (eventi Field/File/Data/Preamble/
Epilogue/NeedData), alimentato a blocchi da un buffer in memoria. Mai
`request.files`/`request.form` (spillano su disco e decodificano i campi con
`replace`), mai file temporanei, mai scritture su disco: tutti i buffer restano
in RAM e vengono rilasciati alla fine della chiamata.

Solo il percorso multipart tocca Werkzeug: JSON, motore del dizionario e testo
PDF restano importabili e testabili sulla sola libreria standard.

Responsabilita':
  - validazione strutturale del multipart (boundary, Content-Disposition,
    nomi campo, filename, estensioni, limiti di parte/file/campo);
  - `text`, `dictionary` e `categories` come stringhe UTF-8 STRETTE (niente
    `replace`);
  - estrazione dei documenti tramite callback iniettata, con budget aggregato.

Gli errori sono `InputError(status, code)`: il chiamante li traduce nel corpo
`{error, code}` senza esporre mai valori, filename o eccezioni.
"""

import io
import os

import pii_dictionary

MAX_MULTIPART_BODY_BYTES = 20971520   # body multipart grezzo (20 MiB)
MAX_FILE_BYTES = 5242880              # una file part (5 MiB)
MAX_FILES = 10                        # file part accettate
MAX_MULTIPART_PARTS = 13              # 10 file + text + dictionary + categories
MAX_FORM_FIELD_BYTES = 1048576        # limiti dei campi text e categories (1 MiB)
MAX_PDF_PAGES = 200                   # pagine di un PDF multifile
READ_CHUNK_BYTES = 64 * 1024          # blocco con cui si alimenta il decoder

TEXT_EXTS = frozenset({".txt", ".text", ".md", ".markdown"})
PDF_EXT = ".pdf"
ACCEPTED_EXTS = frozenset(TEXT_EXTS | {PDF_EXT})

VALUE_FIELDS = frozenset({"text", "dictionary", "categories"})
FILE_FIELD = "files"
_HTTP_TOKEN_CHARS = frozenset(
    "!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


class InputError(Exception):
    """Errore di input con status e codice del contratto (gia' sanificato)."""

    def __init__(self, status, code):
        super().__init__(code)
        self.status = status
        self.code = code


def native_multipart_available():
    """True se il parser multipart nativo di Werkzeug e' importabile."""
    try:
        import werkzeug.sansio.multipart  # noqa: F401
    except ImportError:
        return False
    return True


def _validate_content_disposition(value):
    """Validate MIME parameter syntax before Werkzeug's last-value-wins parse.

    Returns the disposition token and normalized raw parameter names. Quoted
    strings are scanned with backslash escapes, so semicolons and `name=` text
    inside a filename are data, not parameter delimiters. Duplicate parameter
    names are rejected case-insensitively; `filename` plus RFC 2231 `filename*`
    remains valid as an extended/fallback pair.
    """
    if not isinstance(value, str):
        raise InputError(400, "invalid_request")

    length = len(value)
    position = 0

    def skip_ows():
        nonlocal position
        while position < length and value[position] in " \t":
            position += 1

    def read_token():
        nonlocal position
        start = position
        while (position < length and value[position].isascii()
               and value[position] in _HTTP_TOKEN_CHARS):
            position += 1
        if position == start:
            raise InputError(400, "invalid_request")
        return value[start:position]

    skip_ows()
    disposition = read_token().lower()
    parameter_names = set()
    skip_ows()
    while position < length:
        if value[position] != ";":
            raise InputError(400, "invalid_request")
        position += 1
        skip_ows()
        key = read_token().lower()
        skip_ows()
        if position >= length or value[position] != "=":
            raise InputError(400, "invalid_request")
        position += 1
        skip_ows()
        if position >= length:
            raise InputError(400, "invalid_request")

        if value[position] == '"':
            position += 1
            closed = False
            while position < length:
                char = value[position]
                codepoint = ord(char)
                if char == "\\":
                    position += 1
                    if position >= length:
                        raise InputError(400, "invalid_request")
                    escaped = ord(value[position])
                    if (escaped < 32 and value[position] != "\t") or escaped == 127:
                        raise InputError(400, "invalid_request")
                    position += 1
                elif char == '"':
                    position += 1
                    closed = True
                    break
                elif (codepoint < 32 and char != "\t") or codepoint == 127:
                    raise InputError(400, "invalid_request")
                else:
                    position += 1
            if not closed:
                raise InputError(400, "invalid_request")
        else:
            read_token()

        if key in parameter_names:
            raise InputError(400, "invalid_request")
        parameter_names.add(key)
        skip_ows()

    return disposition, parameter_names


def parse_multipart(raw_body, params, check_deadline=None, *, limits=None):
    """(documents, text, dictionary_raw, categories_raw) dal body gia' letto.

    `documents` = [(filename, bytes), ...] nell'ordine delle parti, `text` e'
    None se il campo manca o e' solo spazi (l'originale non viene strippato),
    `dictionary_raw` e `categories_raw` sono None se il campo manca. I filename
    servono SOLO a scegliere l'estrattore e non vengono mai restituiti, loggati
    o messi negli errori. Solleva InputError: 400 struttura, 413 limiti, 415
    estensione, 503 se il parser nativo non e' disponibile.
    """
    check = check_deadline if check_deadline is not None else (lambda: None)
    boundary = params.get("boundary") if params else None
    if not isinstance(boundary, str) or not boundary:
        raise InputError(400, "invalid_request")
    try:
        boundary_bytes = boundary.encode("ascii")
    except UnicodeEncodeError:
        raise InputError(400, "invalid_request")
    if (not 1 <= len(boundary_bytes) <= 70
            or any(chr(byte) not in _HTTP_TOKEN_CHARS for byte in boundary_bytes)):
        raise InputError(400, "invalid_request")

    try:
        from werkzeug.exceptions import RequestEntityTooLarge
        from werkzeug.http import parse_options_header
        from werkzeug.sansio.multipart import (Data, Epilogue, Field, File,
                                               MultipartDecoder)
    except ImportError:
        raise InputError(503, "unavailable")

    documents = []
    text = None
    dictionary_raw = None
    categories_raw = None
    seen_value_fields = set()
    active = None
    finished = False
    try:
        dictionary_limit = (MAX_FORM_FIELD_BYTES if limits is None
                            else limits.json_body_bytes)
        decoder = MultipartDecoder(
            boundary_bytes,
            max_form_memory_size=max(MAX_FORM_FIELD_BYTES, dictionary_limit),
            max_parts=MAX_MULTIPART_PARTS,
        )
        for event in _decoder_events(decoder, raw_body, check):
            if isinstance(event, (Field, File)):
                if active is not None:
                    raise InputError(400, "invalid_request")
                active = _begin_part(event, File, parse_options_header,
                                     documents, seen_value_fields)
            elif isinstance(event, Data):
                if active is None:
                    raise InputError(400, "invalid_request")
                _extend_part(active, event.data, limits)
                if not event.more_data:
                    finished_part = _end_part(active, documents)
                    if finished_part is not None:
                        name, value = finished_part
                        if name == "text":
                            if value.strip():
                                text = value
                        elif name == "dictionary":
                            dictionary_raw = value
                        else:
                            categories_raw = value
                    active = None
            elif isinstance(event, Epilogue):
                finished = True
                break
    except RequestEntityTooLarge:
        raise InputError(413, "payload_too_large")
    except ValueError:
        # JSON errato no, multipart malformato si': boundary mancante o non
        # trovato, header non decodificabili, corpo troncato. ValueError copre
        # anche UnicodeDecodeError degli header.
        raise InputError(400, "invalid_request")
    if active is not None or not finished:
        raise InputError(400, "invalid_request")
    return documents, text, dictionary_raw, categories_raw


def extract_inputs(documents, text, extract, check_deadline=None):
    """[(input_id, testo), ...] estraendo i file, senza sforare l'aggregato.

    `extract(filename, data, remaining_chars, check_deadline)` e' la callback
    del chiamante ed e' responsabile degli errori di contenuto (InputError).
    `remaining_chars` e' il budget residuo sui 100000 caratteri complessivi,
    `text` incluso: l'estrattore puo' interrompersi prima. Il controllo finale
    del budget resta qui, cosi' una callback che lo ignora non sfonda il limite.
    """
    check = check_deadline if check_deadline is not None else (lambda: None)
    remaining = pii_dictionary.MAX_TEXT_CHARS - (len(text) if text is not None else 0)
    if remaining < 0:
        raise InputError(413, "payload_too_large")
    inputs = []
    for index, (filename, data) in enumerate(documents, start=1):
        check()
        extracted = extract(filename, data, remaining, check)
        if not isinstance(extracted, str):
            raise InputError(500, "internal_error")
        if len(extracted) > remaining:
            raise InputError(413, "payload_too_large")
        remaining -= len(extracted)
        inputs.append(("file_%d" % index, extracted))
    if text is not None:
        inputs.append(("text", text))
    return inputs


# --------------------------------------------------------------------------- #
# Interni del parser nativo
# --------------------------------------------------------------------------- #
def _decoder_events(decoder, raw_body, check):
    """Eventi del decoder alimentato a blocchi dal body gia' in memoria."""
    from werkzeug.sansio.multipart import Epilogue, NeedData

    stream = io.BytesIO(raw_body)
    while True:
        chunk = stream.read(READ_CHUNK_BYTES)
        decoder.receive_data(chunk if chunk else None)
        if chunk:
            check()
        while True:
            event = decoder.next_event()
            if isinstance(event, NeedData):
                break
            yield event
            if isinstance(event, Epilogue):
                return


def _begin_part(event, file_cls, parse_options_header, documents, seen):
    """Valida la testa di una parte e prepara l'accumulatore.

    `active` = [kind, name, filename, bytearray, ext]; kind "file" o "field".
    """
    name = event.name
    if not isinstance(name, str) or not name:
        raise InputError(400, "invalid_request")
    dispositions = event.headers.getlist("content-disposition")
    if len(dispositions) != 1:
        raise InputError(400, "invalid_request")
    raw_disposition = dispositions[0]
    disposition_token, parameter_names = _validate_content_disposition(
        raw_disposition)
    if disposition_token != "form-data" or "name" not in parameter_names:
        raise InputError(400, "invalid_request")
    disposition, options = parse_options_header(raw_disposition)
    if disposition.strip().lower() != "form-data":
        raise InputError(400, "invalid_request")
    filename = options.get("filename")
    if isinstance(event, file_cls):
        if not isinstance(filename, str) or not filename:
            raise InputError(400, "invalid_request")
        if name != FILE_FIELD:
            raise InputError(400, "invalid_request")
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ACCEPTED_EXTS:
            raise InputError(415, "unsupported_file_type")
        if len(documents) >= MAX_FILES:
            raise InputError(413, "payload_too_large")
        return ["file", name, filename, bytearray(), ext]
    if filename is not None:
        raise InputError(400, "invalid_request")
    if name not in VALUE_FIELDS:
        raise InputError(400, "invalid_request")
    if name in seen:
        raise InputError(400, "invalid_request")
    seen.add(name)
    return ["field", name, None, bytearray(), None]


def _extend_part(active, data, limits=None):
    accumulator = active[3]
    accumulator.extend(data)
    if active[0] == "file":
        limit = MAX_FILE_BYTES
    elif active[1] == "dictionary" and limits is not None:
        limit = limits.json_body_bytes
    else:
        limit = MAX_FORM_FIELD_BYTES
    if len(accumulator) > limit:
        raise InputError(413, "payload_too_large")


def _end_part(active, documents):
    """Chiude una parte: file -> documents; campo -> (nome, stringa UTF-8)."""
    raw = bytes(active[3])
    if active[0] == "file":
        documents.append((active[2], raw))
        return None
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise InputError(400, "invalid_request")
    return active[1], value
