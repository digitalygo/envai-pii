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
  - limite di 1 MiB applicato ai BYTE LETTI davvero (mai al Content-Length, che puo'
    mentire o mancare) prima di decodifica e parser;
  - parsing JSON severo: NaN/Infinity, chiavi duplicate anche a valori uguali,
    annidamento eccessivo, UTF-8 non valido, campi sconosciuti;
  - autenticazione Bearer con secrets.compare_digest su bytes (token Unicode compreso),
    fail-closed 503 se PII_API_TOKEN manca o e' vuoto, 401 se assente o sbagliato;
  - un solo processo alla volta per endpoint (lock non bloccante, rilascio in finally);
  - deadline cooperativa di 30 s controllata ai confini di fase;
  - errori sanificati {error, code}, nessun valore della richiesta o eccezione;
  - Cache-Control: no-store su ogni risposta.
"""

import json
import os
import secrets
import threading
import time

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


MAX_BODY_BYTES = 1048576        # limite del body grezzo (1 MiB), fisso e non segreto
DEADLINE_SECONDS = 30.0         # budget cooperativo per richiesta

ERROR_MESSAGES = {
    "invalid_request": "Invalid request.",
    "invalid_seed": "Invalid seed dictionary.",
    "seed_conflict": "Conflicting seed entries.",
    "allocation_exhausted": "No free placeholder id left.",
    "payload_too_large": "Payload too large.",
    "unsupported_media_type": "Unsupported media type.",
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
    try:
        value = json.loads(text, object_pairs_hook=_pairs_hook,
                           parse_constant=_reject_constant)
    except _Invalid:
        raise
    except (ValueError, RecursionError):
        # ValueError comprende JSONDecodeError; RecursionError copre l'annidamento
        # oltre il limite del parser (che non deve diventare un 500).
        raise _Invalid()
    if not isinstance(value, dict):
        raise _Invalid()
    return value


def _validate_envelope(payload):
    """Estrae (text, dictionary) validando envelope e campo text.

    Campi sconosciuti: invalid_request. `text` deve essere una stringa con almeno
    un carattere non whitespace, max 100000 code point. `dictionary` assente vale {}.
    """
    if set(payload) - {"text", "dictionary"}:
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
    return text, dictionary


def _error_body(code):
    return {"error": ERROR_MESSAGES[code], "code": code}


def _error(status, code):
    return status, _error_body(code)


def _handle_locked(headers, raw_body, *, tags, detect, clock):
    """Fasi della richiesta con il lock gia' preso. Solleva errori tipizzati/sanificati."""
    deadline = _Deadline(clock, DEADLINE_SECONDS)

    # Limite sui byte LETTI davvero, prima di decodifica e parser: il Content-Length
    # non viene mai consultato ne' creduto.
    if raw_body is None:
        raw_body = b""
    if len(raw_body) > MAX_BODY_BYTES:
        raise _Failure(413, "payload_too_large")

    mime, params = parse_content_type(_header(headers, "Content-Type"))
    if mime != "application/json":
        raise _Failure(415, "unsupported_media_type")
    charset = params.get("charset")
    if charset is not None and charset.lower() != "utf-8":
        raise _Failure(415, "unsupported_media_type")
    deadline.check()

    payload = _parse_json_object(raw_body)
    text, dictionary = _validate_envelope(payload)
    seed = pii_dictionary.parse_seed(dictionary, tags)
    deadline.check()

    result = pii_dictionary.anonymize(text, seed, tags, detect=detect,
                                      check_deadline=deadline.check)
    deadline.check()
    return 200, {
        "results": [{
            "input_id": "text",
            "anonymized_text": result["anonymized_text"],
            "statistics": {"placeholder_count": result["placeholder_count"]},
        }],
        "dictionary_delta": result["dictionary_delta"],
    }


def process_request(headers, raw_body, *, token, tags, detect, clock=time.monotonic,
                    lock, readiness=None):
    """Cuore della richiesta, indipendente da Flask. Ritorna (status, corpo).

    Ordine di valutazione: configurazione (503 se il token manca o e' vuoto),
    credenziali (401), disponibilita' del modello (503), poi lock per-request (429).
    Il lock viene SEMPRE rilasciato, su ogni uscita, grazie al finally.
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
            return _handle_locked(headers, raw_body, tags=tags, detect=detect, clock=clock)
        except _Failure as failure:
            return _error(failure.status, failure.code)
        except _Invalid:
            return _error(400, "invalid_request")
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
def _read_body():
    """Legge il body grezzo a blocchi, al massimo MAX_BODY_BYTES + 1 byte.

    Si legge `request.stream`, cioe' lo stream gia' delimitato dal FRAMING della
    richiesta (Content-Length o chunked): cosi' una richiesta normale non blocca
    mai in attesa di byte che il client non ha promesso, e un Content-Length assente
    non fa cadere il limite. Il Content-Length NON viene usato come permesso: il
    tetto e' applicato ai byte letti davvero, prima di decodifica e parser. Se il
    framework ha gia' un tetto minore (Flask MAX_CONTENT_LENGTH = 50 MB) il suo 413
    viene intercettato dal chiamante e sanificato.
    """
    stream = request.stream
    limit = MAX_BODY_BYTES + 1
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


def create_blueprint(tags, detect, clock=time.monotonic, lock=None, readiness=None):
    """Blueprint con l'endpoint versionato. `lock` e' iniettabile per i test."""
    if Blueprint is None:
        raise RuntimeError("Flask non e' disponibile: impossibile creare l'endpoint guardrail.")
    if lock is None:
        lock = threading.Lock()
    tags = tuple(tags)

    blueprint = Blueprint("guardrail_api", __name__, url_prefix="/api/v1")

    @blueprint.route("/analyses", methods=["POST"])
    def create_analysis():
        try:
            raw_body = _read_body()
        except RequestEntityTooLarge:
            return _flask_response(413, _error_body("payload_too_large"))
        except Exception:
            # Lettura del body fallita (client disconnesso, stream rotto): risposta
            # sanificata invece dell'HTML di default del framework.
            return _flask_response(400, _error_body("invalid_request"))
        status, body = process_request(
            request.headers, raw_body,
            token=os.environ.get("PII_API_TOKEN"),
            tags=tags, detect=detect, clock=clock, lock=lock,
            readiness=readiness,
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


def register_app(app, *, tags, detect, clock=time.monotonic, readiness=None):
    """Registra l'endpoint sull'app Flask legacy senza toccarne le route."""
    app.register_blueprint(create_blueprint(tags=tags, detect=detect, clock=clock,
                                            readiness=readiness))