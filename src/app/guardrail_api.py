# -*- coding: utf-8 -*-
"""
Guardrail API v1 (ENVAS-23, prima slice): POST /api/v1/analyses.

Endpoint additivo e versionato: il contratto e' docs/GUARDRAIL_API.md +
docs/guardrail-openapi.yaml, le route legacy non vengono toccate. Stateless: nessun
dizionario globale, nessuna lettura/scrittura di prefs.json, nessuna persistenza e
nessun log di testo, seed o token.

La logica di richiesta vive in process_request(), che non dipende da Flask: prende
header e body gia' letti e ritorna (status, corpo). Il blueprint Flask e' un guscio
sottile intorno a quella funzione, cosi' la parte difficile e' testabile anche dove
Flask non e' installato.

Sicurezze coperte qui:
  - limite configurato e bounded applicato ai BYTE LETTI davvero (mai al Content-Length,
    che puo' mentire o mancare) prima di decodifica e parser;
  - parsing JSON severo: NaN/Infinity, chiavi duplicate anche a valori uguali,
    annidamento eccessivo, UTF-8 non valido, campi sconosciuti;
  - whitelist opzionale `categories` (JSON o campo multipart): array di TAG_NAMES
    canonici, mai prefs/EXCLUDED_TAGS/env/CLI; assente o vuota = catalogo intero;
  - autenticazione Bearer con secrets.compare_digest su bytes (token Unicode compreso),
    fail-closed 503 se PII_API_TOKEN manca o e' vuoto, 401 se assente o sbagliato;
  - un solo processo alla volta per endpoint (lock non bloccante, rilascio in finally);
  - deadline cooperativa (default 60 s, override server PII_ANALYSIS_TIMEOUT_SECONDS)
    controllata ai confini di fase;
  - errori sanificati {error, code}, nessun valore della richiesta o eccezione;
  - Cache-Control: no-store su ogni risposta.
"""

import json
import math
import os
import secrets
import threading
import time

import guardrail_inputs
import guardrail_limits
import pii_dictionary
from pii_dictionary import MAX_TEXT_CHARS

try:                                             # il guscio HTTP serve solo in produzione
    from flask import Blueprint, Response, request
    from werkzeug.exceptions import RequestEntityTooLarge
except ImportError:                              # tests stdlib / ambienti senza Flask
    Blueprint = None
    Response = None
    request = None

    class RequestEntityTooLarge(Exception):
        """Segnaposto: senza Flask il framework non esiste, il tipo serve solo per l'API."""


MAX_BODY_BYTES = guardrail_limits.DEFAULT_JSON_BODY_BYTES
MAX_CATEGORIES = 24             # voci GREZZE ammesse nel campo `categories`
DEFAULT_DEADLINE_SECONDS = 60.0  # budget cooperativo per richiesta (env: PII_ANALYSIS_TIMEOUT_SECONDS)
TIMEOUT_SECONDS_ENV = "PII_ANALYSIS_TIMEOUT_SECONDS"

ERROR_MESSAGES = {
    "invalid_request": "Invalid request.",
    "invalid_seed": "Invalid seed dictionary.",
    "seed_conflict": "Conflicting seed entries.",
    "allocation_exhausted": "No free placeholder id left.",
    "payload_too_large": "Payload too large.",
    "unsupported_media_type": "Unsupported media type.",
    "unsupported_file_type": "Unsupported file type.",
    "empty_file": "File is empty.",
    "unreadable_file": "Unable to read file.",
    "no_extractable_text": "File has no extractable text. OCR is not available.",
    "unauthorized": "Unauthorized.",
    "busy": "Another analysis is in progress.",
    "unavailable": "Service unavailable.",
    "deadline_exceeded": "Deadline exceeded.",
    "internal_error": "Internal error.",
}


class ModelUnavailable(Exception):
    """Sollevata dall'adapter quando il modello non e' pronto (-> 503)."""


class _Failure(Exception):
    """Errore interno con status/codice: gia' sanificato, mai esposto come eccezione."""

    def __init__(self, status, code):
        super().__init__(code)
        self.status = status
        self.code = code


class _Invalid(Exception):
    """JSON non conforme: viene tradotto in invalid_request."""


class _Deadline:
    """Budget wall-clock cooperativo, con clock iniettabile per i test."""

    __slots__ = ("_clock", "_start", "_seconds")

    def __init__(self, clock, seconds):
        self._clock = clock
        self._start = clock()
        self._seconds = seconds

    def check(self):
        if self._clock() - self._start > self._seconds:
            raise pii_dictionary.DeadlineExceeded()


# --------------------------------------------------------------------------- #
# Helper puri
# --------------------------------------------------------------------------- #
def _header(headers, name):
    """Valore di un header da un mapping Flask o da un dict semplice."""
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter(name)
    if value is None:
        value = getter(name.lower())
    return value


def parse_content_type(value):
    """(mime, parametri) da un Content-Type. Mime None se assente o malformato."""
    if not value or not isinstance(value, str):
        return None, {}
    parts = value.split(";")
    mime = parts[0].strip().lower()
    params = {}
    for part in parts[1:]:
        if "=" in part:
            key, raw = part.split("=", 1)
            params[key.strip().lower()] = raw.strip().strip('"')
    return (mime or None), params


def _authorized(headers, token):
    """True solo per `Authorization: Bearer <token>` esatto.

    Il confronto e' su bytes con compare_digest (niente short-circuit sul valore):
    il token puo' essere Unicode e non deve mai far cadere il confronto. Lo schema
    HTTP e' case-insensitive per RFC 7235.
    """
    header = _header(headers, "Authorization")
    if not isinstance(header, str):
        return False
    parts = header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    try:
        expected = str(token).encode("utf-8", "surrogatepass")
        presented = parts[1].encode("utf-8", "surrogatepass")
    except (UnicodeError, AttributeError):
        return False
    return secrets.compare_digest(expected, presented)


def _pairs_hook(pairs):
    """object_pairs_hook: chiavi duplicate rifiutate anche a valori identici."""
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise _Invalid()
        seen[key] = value
    return seen


def _reject_constant(_name):
    """parse_constant: NaN, Infinity e -Infinity non fanno parte del contratto."""
    raise _Invalid()


def _parse_json_object(raw):
    """JSON severo dal body: ritorna l'oggetto top-level o solleva _Invalid."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _Invalid()
    value = _parse_json_value(text)
    if not isinstance(value, dict):
        raise _Invalid()
    return value


def _parse_json_value(text):
    """json.loads severo (chiavi duplicate, NaN, annidamento) o _Invalid."""
    try:
        return json.loads(text, object_pairs_hook=_pairs_hook,
                          parse_constant=_reject_constant)
    except _Invalid:
        raise
    except (ValueError, RecursionError):
        # ValueError comprende JSONDecodeError; RecursionError copre l'annidamento
        # oltre il limite del parser (che non deve diventare un 500).
        raise _Invalid()


def _validate_envelope(payload):
    """Estrae (text, dictionary, categories_raw) validando envelope e campo text.

    Campi sconosciuti: invalid_request. `text` deve essere una stringa con almeno
    un carattere non whitespace, max 100000 code point. `dictionary` assente vale {}.
    `categories` torna grezzo: la whitelist e' validata a parte, col catalogo.
    """
    if set(payload) - {"text", "dictionary", "categories"}:
        raise _Invalid()
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise _Invalid()
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise _Invalid()
    if len(text) > MAX_TEXT_CHARS:
        raise _Failure(413, "payload_too_large")
    dictionary = payload.get("dictionary", {})
    if not isinstance(dictionary, dict):
        raise _Failure(400, "invalid_seed")
    return text, dictionary, payload.get("categories")


def _parse_categories(value, tags):
    """Whitelist `categories` di un valore JSON, o None = catalogo intero.

    Valori accettati: assente/null, stringa vuota o di soli spazi, lista vuota
    (tutte: nessuna restrizione) oppure lista di label canoniche di `tags`.
    Qualunque altro tipo, label sconosciuta o label non canonica (maiuscole
    esatte, senza spazi ai bordi) e' invalid_request. I duplicati sono ammessi e
    deduplicati; piu' di MAX_CATEGORIES voci GREZZE no. Una lista che copre
    l'intero catalogo vale come nessuna selezione.
    """
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        raise _Invalid()
    if not isinstance(value, list):
        raise _Invalid()
    if not value:
        return None
    if len(value) > MAX_CATEGORIES:
        raise _Invalid()
    known = set(tags)
    active = set()
    for item in value:
        if not isinstance(item, str) or item not in known:
            raise _Invalid()
        active.add(item)
    if len(active) == len(known):
        return None
    return frozenset(active)


def _parse_multipart_categories(raw, tags):
    """`categories` multipart: assente/blank = tutte, altrimenti JSON severo.

    Il contenuto del campo e' un DOCUMENTO JSON, non una lista di stringhe
    letterali: decode severo (null/[]/stringa blank valgono come nessuna
    selezione), poi le stesse regole dell'arm JSON.
    """
    if raw is None or not raw.strip():
        return None
    return _parse_categories(_parse_json_value(raw), tags)


def _bind_detect(detect, detect_for_categories, categories):
    """Rilevatore request-local: binding alla whitelist attiva se c'e' selezione.

    Nessuna selezione (None) o nessun binder => callback originale, invariato:
    il percorso di default non costruisce closure e conserva i risultati di prima.
    """
    if categories is None or detect_for_categories is None:
        return detect
    return detect_for_categories(categories)


def _error_body(code):
    return {"error": ERROR_MESSAGES[code], "code": code}


def _error(status, code):
    return status, _error_body(code)


def _body_cap(mime, limits):
    """Tetto del body grezzo per media type, scelto prima della lettura."""
    if mime == "application/json":
        return limits.json_body_bytes
    return guardrail_inputs.MAX_MULTIPART_BODY_BYTES


def _resolve_deadline_seconds():
    """Budget cooperativo in secondi dalla env del server, con fallback sicuro.

    Letta una volta per richiesta autenticata, quando si costruisce la deadline:
    assente, blank, non numerica, non positiva, NaN o infinita vale il default.
    Il valore risolto non viene mai loggato, restituito o messo nel body.
    """
    raw = os.environ.get(TIMEOUT_SECONDS_ENV)
    if raw is None:
        return DEFAULT_DEADLINE_SECONDS
    try:
        seconds = float(raw.strip())
    except (AttributeError, TypeError, ValueError):
        return DEFAULT_DEADLINE_SECONDS
    if not math.isfinite(seconds) or seconds <= 0.0:
        return DEFAULT_DEADLINE_SECONDS
    return seconds


def _handle_locked(headers, raw_body, *, tags, detect, extract, clock,
                   detect_for_categories=None):
    """Fasi della richiesta con il lock gia' preso. Solleva errori tipizzati/sanificati."""
    limits = guardrail_limits.resolve_request_limits()
    mime, params = parse_content_type(_header(headers, "Content-Type"))
    if mime not in ("application/json", "multipart/form-data"):
        raise _Failure(415, "unsupported_media_type")
    charset = params.get("charset")
    if charset is not None and charset.lower() != "utf-8":
        raise _Failure(415, "unsupported_media_type")

    # Il tetto dipende dal media type e viene scelto PRIMA della lettura: il
    # limite JSON non diventa mai quello multipart e viceversa.
    cap = _body_cap(mime, limits)
    if callable(raw_body):
        try:
            raw_body = raw_body(cap)
        except RequestEntityTooLarge:
            raise _Failure(413, "payload_too_large")
        except _Failure:
            raise
        except Exception:
            # Lettura fallita (client disconnesso, stream rotto): 400 sanificato.
            raise _Failure(400, "invalid_request")
    if raw_body is None:
        raw_body = b""

    # Limite sui byte LETTI davvero, prima di decodifica e parser: il Content-Length
    # non viene mai consultato ne' creduto.
    if len(raw_body) > cap:
        raise _Failure(413, "payload_too_large")

    # Il budget parte DOPO la lettura bounded, dentro il lock: copre parsing,
    # estrazione, analisi e allocazione, non l'upload. Il valore e' risolto qui,
    # una sola volta per richiesta, dalla env del server.
    deadline = _Deadline(clock, _resolve_deadline_seconds())
    deadline.check()
    if mime == "application/json":
        return _handle_json(raw_body, tags=tags, detect=detect,
                            detect_for_categories=detect_for_categories,
                            deadline=deadline, limits=limits)
    return _handle_multipart(raw_body, params, tags=tags, detect=detect,
                             detect_for_categories=detect_for_categories,
                             extract=extract, deadline=deadline, limits=limits)


def _handle_json(raw_body, *, tags, detect, detect_for_categories, deadline, limits):
    payload = _parse_json_object(raw_body)
    text, dictionary, categories_raw = _validate_envelope(payload)
    categories = _parse_categories(categories_raw, tags)
    seed = pii_dictionary.parse_seed(dictionary, tags, limits=limits)
    deadline.check()

    request_detect = _bind_detect(detect, detect_for_categories, categories)
    result = pii_dictionary.anonymize(text, seed, tags, detect=request_detect,
                                      check_deadline=deadline.check,
                                      categories=categories, limits=limits)
    deadline.check()
    return 200, {
        "results": [{
            "input_id": "text",
            "anonymized_text": result["anonymized_text"],
            "statistics": {"placeholder_count": result["placeholder_count"]},
        }],
        "dictionary_delta": result["dictionary_delta"],
    }


def _parse_multipart_dictionary(raw, tags, limits):
    """Seed del campo multipart `dictionary`: JSON severo, errori del contratto.

    Campo assente = seed vuoto; contenuto vuoto o JSON malformato/chiavi
    duplicate = invalid_request; JSON valido ma non oggetto = invalid_seed;
    poi valgono le stesse regole del dizionario JSON.
    """
    if raw is None:
        return pii_dictionary.parse_seed({}, tags, limits=limits)
    if not raw.strip():
        raise _Invalid()
    value = _parse_json_value(raw)
    if not isinstance(value, dict):
        raise _Failure(400, "invalid_seed")
    return pii_dictionary.parse_seed(value, tags, limits=limits)


def _handle_multipart(raw_body, params, *, tags, detect, detect_for_categories,
                      extract, deadline, limits):
    try:
        (documents, text, dictionary_raw,
         categories_raw) = guardrail_inputs.parse_multipart(
            raw_body, params, deadline.check, limits=limits)
    except guardrail_inputs.InputError as exc:
        raise _Failure(exc.status, exc.code)
    if not documents and text is None:
        raise _Failure(400, "invalid_request")

    # Seed e input sono validati ed estratti TUTTI prima di qualunque inferenza:
    # una richiesta respinta non produce ne' risultati ne' chiamate al modello.
    categories = _parse_multipart_categories(categories_raw, tags)
    seed = _parse_multipart_dictionary(dictionary_raw, tags, limits)
    deadline.check()
    if documents and extract is None:
        raise _Failure(503, "unavailable")
    try:
        inputs = guardrail_inputs.extract_inputs(documents, text, extract,
                                                 deadline.check)
    except guardrail_inputs.InputError as exc:
        raise _Failure(exc.status, exc.code)
    deadline.check()

    request_detect = _bind_detect(detect, detect_for_categories, categories)
    results, delta = pii_dictionary.anonymize_batch(
        inputs, seed, tags, detect=request_detect, check_deadline=deadline.check,
        categories=categories, limits=limits)
    deadline.check()
    return 200, {
        "results": [
            {
                "input_id": input_id,
                "anonymized_text": result["anonymized_text"],
                "statistics": {"placeholder_count": result["placeholder_count"]},
            }
            for input_id, result in results
        ],
        "dictionary_delta": delta,
    }


def process_request(headers, raw_body, *, token, tags, detect, extract=None,
                    clock=time.monotonic, lock, readiness=None,
                    detect_for_categories=None):
    """Cuore della richiesta, indipendente da Flask. Ritorna (status, corpo).

    Ordine di valutazione: configurazione (503 se il token manca o e' vuoto),
    credenziali (401), disponibilita' del modello (503), poi lock per-request (429).
    Autenticazione, readiness e lock precedono la lettura del body: una richiesta
    non autorizzata o respinta perche' un'altra analisi e' in corso non
    materializza mai il payload. `raw_body` puo' essere bytes (gia' letto) oppure
    una callable `reader(cap)` che legge il body GREZZO bounded dentro il lock;
    `extract` e' la callback che estrae un file multipart; `detect_for_categories`
    e' il binder opzionale che, SOLO per una selezione attiva, restituisce il
    rilevatore request-local filtrato. Il lock viene SEMPRE rilasciato, su ogni
    uscita, grazie al finally.
    """
    if token is None or not str(token).strip():
        return _error(503, "unavailable")
    if not _authorized(headers, token):
        return _error(401, "unauthorized")
    if detect is None:
        return _error(503, "unavailable")
    if readiness is not None:
        try:
            if not readiness():
                return _error(503, "unavailable")
        except ModelUnavailable:
            return _error(503, "unavailable")
        except Exception:
            return _error(500, "internal_error")

    if not lock.acquire(blocking=False):
        return _error(429, "busy")
    try:
        try:
            return _handle_locked(headers, raw_body, tags=tags, detect=detect,
                                  extract=extract, clock=clock,
                                  detect_for_categories=detect_for_categories)
        except _Failure as failure:
            return _error(failure.status, failure.code)
        except _Invalid:
            return _error(400, "invalid_request")
        except guardrail_inputs.InputError as exc:
            return _error(exc.status, exc.code)
        except pii_dictionary.PiiDictionaryError as exc:
            return _error(exc.status, exc.code)
        except ModelUnavailable:
            return _error(503, "unavailable")
        except RequestEntityTooLarge:
            return _error(413, "payload_too_large")
        except Exception:
            # Volutamente senza dettagli: l'eccezione puo' contenere valori della
            # richiesta, il token o testo del documento. Niente log, niente traceback.
            return _error(500, "internal_error")
    finally:
        lock.release()


# --------------------------------------------------------------------------- #
# Guscio Flask
# --------------------------------------------------------------------------- #
def _read_body(cap):
    """Legge il body grezzo a blocchi, al massimo `cap` + 1 byte.

    Il tetto dipende dal media type (configurabile JSON, 20 MiB multipart) e viene
    scelto PRIMA della lettura. Si legge `request.stream`, cioe' lo stream gia' delimitato
    dal FRAMING della richiesta (Content-Length o chunked): cosi' una richiesta
    normale non blocca mai in attesa di byte che il client non ha promesso, e un
    Content-Length assente non fa cadere il limite. Il Content-Length NON viene
    usato come permesso: il tetto e' applicato ai byte letti davvero, prima di
    decodifica e parser. Se il framework ha gia' un tetto minore (Flask
    MAX_CONTENT_LENGTH = 50 MB) il suo 413 viene intercettato dal chiamante e
    sanificato.
    """
    stream = request.stream
    limit = cap + 1
    chunks = []
    remaining = limit
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _flask_response(status, body):
    try:
        payload = json.dumps(body, ensure_ascii=True, separators=(",", ":"))
        response = Response(payload, status=status, mimetype="application/json")
    except Exception:
        # Response creation must never expose serializer or framework exception text.
        response = Response(
            '{"error":"Internal error.","code":"internal_error"}',
            status=500, mimetype="application/json")
    response.headers["Cache-Control"] = "no-store"
    return response


def create_blueprint(tags, detect, clock=time.monotonic, lock=None, readiness=None,
                     extract=None, detect_for_categories=None):
    """Blueprint con l'endpoint versionato. `lock` e' iniettabile per i test.

    `extract` e' la callback che estrae un file della richiesta multipart
    (firma: `extract(name, data, remaining_chars, check_deadline)`); JSON e
    richieste senza file non la usano.
    """
    if Blueprint is None:
        raise RuntimeError("Flask non e' disponibile: impossibile creare l'endpoint guardrail.")
    if lock is None:
        lock = threading.Lock()
    tags = tuple(tags)

    blueprint = Blueprint("guardrail_api", __name__, url_prefix="/api/v1")

    @blueprint.route("/analyses", methods=["POST"])
    def create_analysis():
        # Il body non viene letto qui: process_request valuta token, credenziali,
        # readiness e lock prima, e legge il body GREZZO bounded dentro il lock.
        # Gli errori di lettura (413 del framework, stream rotto) sono sanificati
        # li' dentro.
        status, body = process_request(
            request.headers, _read_body,
            token=os.environ.get("PII_API_TOKEN"),
            tags=tags, detect=detect, extract=extract, clock=clock, lock=lock,
            readiness=readiness, detect_for_categories=detect_for_categories,
        )
        return _flask_response(status, body)

    @blueprint.after_app_request
    def _no_store_on_guardrail_path(response):
        # Also covers routing-level 405 and automatic OPTIONS responses; legacy
        # routes retain their existing caching behavior.
        if request.path == "/api/v1/analyses":
            response.headers["Cache-Control"] = "no-store"
        return response

    @blueprint.errorhandler(RequestEntityTooLarge)
    def _payload_too_large(_exc):
        # Rete di sicurezza per un 413 sollevato dal framework prima del nostro check.
        return _flask_response(413, _error_body("payload_too_large"))

    return blueprint


def register_app(app, *, tags, detect, clock=time.monotonic, readiness=None,
                 extract=None, detect_for_categories=None):
    """Registra l'endpoint sull'app Flask legacy senza toccarne le route."""
    app.register_blueprint(create_blueprint(
        tags=tags, detect=detect, clock=clock, readiness=readiness,
        extract=extract, detect_for_categories=detect_for_categories))