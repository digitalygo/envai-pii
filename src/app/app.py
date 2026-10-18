# -*- coding: utf-8 -*-
"""
Server HTTP locale per l'anonimizzazione reversibile di documenti con il modello PII.

Flusso d'uso (solo API: nessuna pagina, nessun asset statico):
  1) ANONIMIZZA  - POST /analyze con testo o file; il modello + una rete regex/checksum
     trovano le PII. Ogni entita' riceve un ID univoco e reversibile: [FULLNAME_1],
     [IBAN_1], ... (valori uguali condividono lo stesso ID).
  2) COPIA       - il chiamante copia il testo anonimizzato e lo incolla in ChatGPT/altro LLM.
  3) RIPRISTINA  - il ripristino e' del chiamante: usa il dizionario
     {placeholder -> valore} restituito dalla risposta.

L'inferenza gira in locale sul modello, senza chiamate a provider LLM esterni: il testo,
il dizionario e il PDF anonimizzato tornano via HTTP al chiamante autorizzato che li ha
richiesti.

Il modello e' affiancato da una rete REGEX + CHECKSUM (EMAIL, TELEFONO, IBAN, CF, PIVA,
carta di credito, importi, targhe, URL, IP). Le entita' validate matematicamente (IBAN/CF/
PIVA/carta) hanno priorita' sul modello in caso di sovrapposizione.

Il dizionario di ripristino si puo' DISATTIVARE (--no-mapping, PII_MAPPING=0, campo
include_mapping): l'anonimizzazione diventa definitiva, nessuna chiave
placeholder->valore viene costruita.

Endpoint HTTP:
  GET  /health    liveness/readiness senza inference (200 = modello caricato, 503 = no)
  POST /analyze   {"text": ...} oppure multipart con un file (.pdf/.md/.txt); campi
                  opzionali "exclude_tags" e "include_mapping" per override per-richiesta
  POST /pdf       stesso input di /analyze -> scarica il PDF ANONIMIZZATO (redazione
                  vera del PDF caricato, oppure PDF ricostruito dal testo)
  POST /preview   multipart con un .pdf -> lo tiene in memoria per l'ANTEPRIMA a video e
                  ritorna {doc_id, n_pages, text}
  POST /pdf/preview  come /pdf, ma invece del binario ritorna {doc_id, n_pages, ...}:
                  il PDF anonimizzato resta in memoria e si guarda pagina per pagina
  GET  /doc/<id>/page/<n>.png   pagina renderizzata (anteprima a video)
  GET  /doc/<id>/file.pdf       download del documento tenuto in memoria
  GET  /settings  legenda dei 24 tag, tag esclusi, stato del dizionario reversibile
  POST /settings  {"excluded_tags": [...], "mapping_enabled": bool} -> salva in prefs.json
                  (/tags e' un alias storico degli stessi due endpoint)
  GET  /config, POST /config, GET /port-check   host/porta del server
  POST /api/v1/analyses   guardrail v1 (Bearer PII_API_TOKEN): un solo testo JSON con
                  seed opzionale -> testo anonimizzato + delta del dizionario

Avvio:  python app.py   ->   http://127.0.0.1:5005
Configurazione host/porta (precedenza): CLI --host/--port > env PII_HOST/PII_PORT >
  config.json (vedi server_config.py) > default 127.0.0.1:5005
Preferenze di anonimizzazione (precedenza): campo nella richiesta > CLI --exclude-tags/
  --no-mapping > env PII_EXCLUDE_TAGS/PII_MAPPING > prefs.json > default
"""

import bisect
import json
import os
import re
import secrets
import sys
import threading
from collections import OrderedDict
from http import HTTPStatus
from pathlib import Path

import fitz  # PyMuPDF
import torch
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

import guardrail_api
import guardrail_inputs
import pdf_export
import pdf_text
import pii_dictionary
import server_config
# Rete REGEX + CHECKSUM: modulo a parte, senza dipendenze dal modello. I nomi
# restano importabili da qui (`app.detect_regex`) per non rompere chi li usa.
from detectors import (DETECTORS, SOFT_REGEX_LABELS, cf_ok,  # noqa: F401
                       complete_time, detect_iban, detect_regex, iban_ok, luhn_ok,
                       piva_ok)
from transformers import pipeline


# --------------------------------------------------------------------------- #
# Privacy: diagnostiche native di MuPDF spente una volta per processo
#
# Errori e warning di MuPDF sono scritti DAL C su stdout (verificato: un content
# stream PDF malformato con un token lo fa comparire in chiaro) e accumulati in
# un buffer process-wide. Qui si spegne la sola STAMPA, una volta e prima di
# qualunque richiesta; il buffer viene poi svuotato a fine di ogni estrazione PDF
# della guardrail. Nessun re-enable a fine richiesta, nessun toggle per-richiesta
# (le richieste legacy non lo toccano) e nessun redirect di sys.stdout/stderr.
# --------------------------------------------------------------------------- #
def _mupdf_tool(name):
    """Funzione nativa di MuPDF col nome dato, se esposta da TOOLS o dal modulo."""
    try:
        tool = getattr(getattr(fitz, "TOOLS", None), name, None)
    except Exception:
        tool = None
    if callable(tool):
        return tool
    try:
        tool = getattr(fitz, name, None)
    except Exception:
        return None
    return tool if callable(tool) else None


def _silence_native_mupdf_diagnostics():
    """Verifica il controllo privacy nativo di MuPDF una volta all'avvio.

    Ogni API e' necessaria: i setter devono accettare False, i getter devono
    confermare entrambe le flag spente e il reset del buffer deve riuscire. I
    valori diagnostici restituiti dal reset sono scartati. Non si sollevano
    errori, cosi' gli altri tipi di input e il servizio restano disponibili.
    """
    names = ("mupdf_display_errors", "mupdf_display_warnings", "mupdf_warnings")
    tools = [_mupdf_tool(name) for name in names]
    ok = all(callable(tool) for tool in tools)

    for setter in tools[:2]:
        if not callable(setter):
            continue
        try:
            setter(False)
        except Exception:
            ok = False

    for getter in tools[:2]:
        if not callable(getter):
            continue
        try:
            status = getter()
            if type(status) not in (bool, int) or status != 0:
                ok = False
        except Exception:
            ok = False

    reset = tools[2]
    if callable(reset):
        try:
            reset(reset=True)  # scartare il buffer: potrebbe contenere testo PDF
        except Exception:
            ok = False
    return ok


def _reset_native_mupdf_warnings():
    """Svuota il buffer nativo e segnala se la privacy resta verificata."""
    global MUPDF_PRIVACY_OK
    reset = _mupdf_tool("mupdf_warnings")
    if reset is None:
        MUPDF_PRIVACY_OK = False
        return False
    try:
        reset(reset=True)  # il valore puo' contenere testo PDF: non conservarlo
    except Exception:
        MUPDF_PRIVACY_OK = False
        return False
    return True


# Le diagnostiche native possono contenere parti dei documenti. Il controllo e'
# process-wide e non viene mai ritentato o riattivato durante le richieste.
MUPDF_PRIVACY_OK = _silence_native_mupdf_diagnostics()


def _resource_path(rel):
    """Percorso risorsa accettato anche da un bundle PyInstaller (sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


# MODELLO usato dall'app. Accetta tre forme, provate in quest'ordine:
#   "1.2.0"  -> models/rizzo-pii-0.3B-v1.2.0/   (versione di un run di training)
#   "main"   -> models/rizzo-pii-0.3B-main/     (revision scaricata da HF, senza numero)
#   percorso -> usato tal quale (assoluto o relativo alla root della repo)
# Metti None per usare AUTOMATICAMENTE l'ultima versione `-v*` disponibile.
APP_MODEL_VERSION = "1.5.0"

# In un bundle PyInstaller il modello e' impacchettato come "pii_model".
# In sviluppo: pin sopra -> auto-ultima versione -> vecchio non versionato -> legacy.
# Override puntuale a runtime: env PII_MODEL_DIR.
if getattr(sys, "_MEIPASS", None):
    MODEL_DIR = _resource_path("pii_model")
elif os.environ.get("PII_MODEL_DIR"):
    MODEL_DIR = os.environ["PII_MODEL_DIR"]
else:
    import re
    _models = Path(__file__).resolve().parents[2] / "models"
    _cands = []
    if APP_MODEL_VERSION:
        _cands = [_models / f"rizzo-pii-0.3B-v{APP_MODEL_VERSION}",
                  _models / f"rizzo-pii-0.3B-{APP_MODEL_VERSION}"]
        if os.sep in APP_MODEL_VERSION or "/" in APP_MODEL_VERSION:   # e' un percorso
            _cands += [Path(APP_MODEL_VERSION), _models.parent / APP_MODEL_VERSION]
    _pinned = next((p for p in _cands if p.is_dir()), None)
    _versioned = [p for p in _models.glob("rizzo-pii-0.3B-v*") if p.is_dir()]
    if _pinned:
        MODEL_DIR = str(_pinned)
    elif _versioned:
        MODEL_DIR = str(max(_versioned, key=lambda p: tuple(
            int(x) for x in re.search(r"-v([0-9][0-9.]*)$", p.name).group(1).split("."))))
    else:
        _prod = _models / "rizzo-pii-0.3B"
        MODEL_DIR = str(_prod if _prod.exists() else _models / "pii_model_legacy")

# Se la cartella non c'e', dirlo QUI e con il comando giusto: senza questo controllo si
# arriva a from_pretrained() con un path inventato (pii_model_legacy, ultimo fallback) e
# l'errore parla di una cartella che l'utente non ha mai sentito nominare.
if not getattr(sys, "_MEIPASS", None) and not os.path.isdir(MODEL_DIR):
    _v = APP_MODEL_VERSION or "1.5.0"
    print(f"ERRORE: modello non trovato in {MODEL_DIR}\n"
          f"Scaricalo con (la revision e la cartella devono combaciare):\n"
          f"  hf download rizzoaiacademy/rizzo-pii-0.3B --revision v{_v} "
          f"--local-dir models/rizzo-pii-0.3B-v{_v}\n"
          f"Oppure indica una cartella tua con la variabile PII_MODEL_DIR.",
          file=sys.stderr)
    sys.exit(2)

APP_VERSION = "2.0.0"                    # versione applicativa riportata da /health
MAX_WORDS = 120      # parole per chunk (~180 subword, sotto i 512 del training)
OVERLAP = 20         # parole di sovrapposizione tra chunk consecutivi

# --------------------------------------------------------------------------- #
# Caricamento modello (una sola volta all'avvio)
# --------------------------------------------------------------------------- #
device = 0 if torch.cuda.is_available() else -1
print(f"Carico il modello da {MODEL_DIR} su {'GPU' if device == 0 else 'CPU'}...")
nlp = pipeline(
    "token-classification",
    model=MODEL_DIR,
    tokenizer=MODEL_DIR,
    aggregation_strategy="simple",
    device=device,
)
print("Modello pronto.")

# API-only: nessuna pagina e nessun asset statico. static_folder=None toglie anche
# la route /static/<path> che Flask creerebbe da solo.
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

# Estensioni accettate dall'upload (il PDF passa da PyMuPDF, il resto e' testo puro).
TEXT_EXTS = {".md", ".markdown", ".txt", ".text"}

# --------------------------------------------------------------------------- #
# Anteprima dei PDF (documento caricato e documento anonimizzato)
#
# I PDF vengono renderizzati QUI, con PyMuPDF, e serviti come PNG per pagina: il
# chiamante non ha bisogno di un viewer PDF ne' di una libreria esterna.
#
# I documenti restano in memoria (mai su disco: valgono quanto il documento stesso)
# in una LRU piccola, e muoiono con il processo. Il render di una pagina e' pigro e
# poi tenuto in cache: aprire un PDF di 200 pagine non costa 200 render.
# --------------------------------------------------------------------------- #
PREVIEW_DPI = 110          # ~1150 px di larghezza su un A4: leggibile senza pesare
MAX_DOCS = 6               # documenti tenuti in memoria (LRU, i piu' vecchi cadono)

_DOCS = OrderedDict()      # doc_id -> {"pdf": bytes, "pages": {n: png}, "n_pages", "name"}
_DOCS_LOCK = threading.Lock()


def _safe_name(name, default="documento.pdf"):
    """Nome file pulito per Content-Disposition (ASCII, niente separatori)."""
    base = os.path.basename(name or "").strip()
    base = re.sub(r"[^A-Za-z0-9._\- ]+", "_", base).strip(" ._")
    return base or default


def _store_doc(data, name="documento.pdf"):
    """Mette un PDF nello store dell'anteprima. Ritorna (doc_id, n_pages)."""
    with fitz.open(stream=data, filetype="pdf") as doc:
        n_pages = doc.page_count
    doc_id = secrets.token_urlsafe(12)
    with _DOCS_LOCK:
        _DOCS[doc_id] = {"pdf": data, "pages": {}, "n_pages": n_pages,
                         "name": _safe_name(name)}
        while len(_DOCS) > MAX_DOCS:
            _DOCS.popitem(last=False)
    return doc_id, n_pages


def _get_doc(doc_id):
    with _DOCS_LOCK:
        d = _DOCS.get(doc_id)
        if d is not None:
            _DOCS.move_to_end(doc_id)          # LRU: l'uso lo tiene in vita
    return d


def _page_png(d, n, dpi=PREVIEW_DPI):
    """PNG della pagina n (0-based) del documento, con cache. None se fuori range."""
    if not (0 <= n < d["n_pages"]):
        return None
    key = (n, dpi)
    with _DOCS_LOCK:
        png = d["pages"].get(key)
    if png is None:
        with fitz.open(stream=d["pdf"], filetype="pdf") as doc:
            png = doc.load_page(n).get_pixmap(dpi=dpi).tobytes("png")
        with _DOCS_LOCK:
            d["pages"][key] = png
    return png


# --------------------------------------------------------------------------- #
# Legenda dei tag + tag esclusi dall'anonimizzazione
#
# I 22 tag del modello (docs/TASSONOMIA_TAG.md) + URL e IPADDR, che sono solo-regex:
# il modello non e' stato addestrato su di essi, li trova la rete regex.
# L'utente puo' DESELEZIONARE un tag: le entita' di quel tipo vengono rilevate ma non
# sostituite (restano in chiaro). Serve a chi deve confrontare gli importi (AMOUNT) o
# tenere eta'/sesso in un caso clinico.
# --------------------------------------------------------------------------- #
TAGS = [
    ("FULLNAME", "Nome di persona (anche ruoli legali: giudice, avvocato, parti, teste)",
     "Person name (legal roles included: judge, lawyer, parties, witness)", "Mario Rossi"),
    ("AGE", "Età", "Age", "45 anni"),
    ("GENDER", "Sesso / genere", "Sex / gender", "Femmina"),
    ("DATE", "Data di calendario", "Calendar date", "12/06/1985"),
    ("TIME", "Ora", "Time of day", "ore 15:30"),
    ("STREET", "Via / piazza / corso", "Street / square", "Via Garibaldi"),
    ("BUILDINGNUM", "Numero civico", "Building number", "24"),
    ("ZIPCODE", "CAP", "ZIP / postal code", "00185"),
    ("CITY", "Città", "City", "Milano"),
    ("PROVINCE", "Sigla della provincia", "Province code", "MI"),
    ("EMAIL", "Email, PEC inclusa", "Email, certified mail included", "m.rossi@studio.it"),
    ("TELEPHONENUM", "Numero di telefono", "Phone number", "+39 333 1234567"),
    ("CF", "Codice fiscale (checksum verificato)", "Italian tax code (checksum verified)",
     "RSSMRA85H12F205Y"),
    ("PIVA", "Partita IVA (checksum verificato)", "VAT number (checksum verified)", "12345678903"),
    ("ID_DOC", "Numero di documento d'identità (carta, passaporto, patente)",
     "Identity document number (ID card, passport, driving licence)", "CA12345AB"),
    ("IBAN", "IBAN / numero di conto (checksum verificato)",
     "IBAN / account number (checksum verified)", "IT60X0542811101000000123456"),
    ("CREDITCARDNUMBER", "Numero di carta di credito (Luhn verificato)",
     "Credit card number (Luhn verified)", "4111 1111 1111 1111"),
    ("AMOUNT", "Importo in denaro", "Money amount", "€ 12.500,00"),
    ("TARGA", "Targa di veicolo", "Vehicle plate", "AB 123 CD"),
    ("ORG", "Ragione sociale privata: società, studio legale, banca",
     "Private organization: company, law firm, bank", "Edilnord S.r.l."),
    ("DOCID", "Codice di un atto: ruolo generale, protocollo, repertorio, sentenza",
     "Document code: case number, protocol, repertoire, judgment", "1234/2024"),
    ("CATASTO", "Dati catastali: foglio, particella, subalterno",
     "Land registry data: sheet, parcel, subordinate", "Foglio 12, part. 345, sub. 6"),
    ("URL", "Indirizzo web (rilevato solo dalla rete regex, non dal modello)",
     "Web address (regex net only, not from the model)", "https://www.studiorossi.it"),
    ("IPADDR", "Indirizzo IP, anche subnet CIDR o range (rilevato solo dalla rete regex)",
     "IP address, including CIDR subnet or range (regex net only)", "192.168.1.1"),
]
TAG_NAMES = [t[0] for t in TAGS]

# Preferenze di default del server (env > prefs.json). Gli argomenti CLI le sovrascrivono
# all'avvio; ogni singola richiesta puo' comunque passare le proprie.
#
# MAPPING_ENABLED = False -> l'anonimizzazione e' DEFINITIVA: nessun dizionario
# placeholder->valore viene costruito, restituito o salvato, e la risposta non contiene
# piu' il testo originale delle entita' (nemmeno dentro `segments`). Serve a chi non
# vuole che una chiave di ripristino esista, da nessuna parte.
_prefs = server_config.load_prefs()
EXCLUDED_TAGS = _prefs["excluded_tags"]
MAPPING_ENABLED = _prefs["mapping_enabled"]
_PREFS_LOCK = threading.Lock()   # protegge la lettura/scrittura ATOMICA della coppia sopra


def _get_prefs():
    """Snapshot coerente di (excluded_tags, mapping_enabled): mai una POST /settings a meta'."""
    with _PREFS_LOCK:
        return EXCLUDED_TAGS, MAPPING_ENABLED


# --------------------------------------------------------------------------- #
# Chunking word-safe + inferenza del modello su tutto il documento
# --------------------------------------------------------------------------- #
def chunk_text(text, max_words=MAX_WORDS, overlap=OVERLAP):
    """Ritorna [(sottostringa, offset_char_globale), ...] senza tagliare parole."""
    words = list(re.finditer(r"\S+", text))
    if not words:
        return []
    chunks, i = [], 0
    step = max(1, max_words - overlap)
    while i < len(words):
        block = words[i:i + max_words]
        start, end = block[0].start(), block[-1].end()
        chunks.append((text[start:end], start))      # slice esatto -> offset diretti
        if i + max_words >= len(words):
            break
        i += step
    return chunks


def detect_model(text):
    """Entita' trovate dal modello mmBERT su tutti i chunk, su offset globali."""
    chunks = chunk_text(text)
    ents = []
    if chunks:
        results = nlp([c for c, _ in chunks])
        if isinstance(results, dict):                 # singolo chunk -> normalizza
            results = [results]
        for (_, off), res in zip(chunks, results):
            for e in res:
                ents.append({
                    "label": e["entity_group"],
                    "start": int(e["start"]) + off,
                    "end": int(e["end"]) + off,
                    "score": float(e["score"]),
                    "validated": False,
                    "source": "modello",
                })
    return ents, len(chunks)


# --------------------------------------------------------------------------- #
# Fusione modello + regex, ID reversibili, testo anonimizzato
# --------------------------------------------------------------------------- #
def _is_word(ch):
    """Carattere interno a una parola (lettere accentate e cifre incluse)."""
    return ch.isalnum() or ch == "_"


def _merge(cands, text):
    """Greedy senza overlap. Priorita': checksum-valido > regex (non soft) > score
    > lunghezza.
    La rete regex copre campi a forma molto specifica: per quegli span e' piu' affidabile
    del modello (evita la frammentazione di CF/IBAN/carta in piu' pezzi). Fanno eccezione
    i tag in SOFT_REGEX_LABELS, dove la forma non ha un checksum a confermarla."""
    order = sorted(
        cands,
        key=lambda e: (1 if e["validated"] else 0,
                       1 if (e["source"] == "regex"
                             and e["label"] not in SOFT_REGEX_LABELS) else 0,
                       e["score"], e["end"] - e["start"]),
        reverse=True,
    )
    kept = []
    for e in order:
        # kept resta ordinata per start e senza sovrapposizioni: allora un candidato puo'
        # accavallarsi solo con i due vicini, che la ricerca binaria trova subito. Il
        # confronto con TUTTA kept era O(n^2): su un documento con 40.000 entita' (una chat
        # esportata di qualche MB) erano 111 s spesi qui, dopo l'inferenza.
        i = bisect.bisect_right(kept, e["start"], key=lambda k: k["start"])
        if (i and kept[i - 1]["end"] > e["start"]) or \
           (i < len(kept) and kept[i]["start"] < e["end"]):
            continue
        kept.insert(i, e)
    # niente spazi inglobati nei placeholder (il modello a volte include lo spazio iniziale)
    for e in kept:
        while e["start"] < e["end"] and text[e["start"]].isspace():
            e["start"] += 1
        while e["end"] > e["start"] and text[e["end"] - 1].isspace():
            e["end"] -= 1
    kept = [e for e in kept if e["end"] > e["start"]]

    # Allineamento ai confini di parola. Il modello etichetta i sotto-token e a volte ne
    # copre solo una parte ("No" di "Novara"): sostituendo la span cosi' com'e' resterebbe
    # "[CITY_1]vara", cioe' un valore ancora ricostruibile. Se una span taglia una parola
    # a meta', la si estende fino a coprirla. Nel dubbio si maschera un carattere in piu':
    # per un anonimizzatore l'errore per eccesso e' l'unico accettabile.
    for e in kept:
        while (e["start"] > 0
               and _is_word(text[e["start"] - 1]) and _is_word(text[e["start"]])):
            e["start"] -= 1
        while (e["end"] < len(text)
               and _is_word(text[e["end"]]) and _is_word(text[e["end"] - 1])):
            e["end"] += 1

    # L'estensione puo' rendere due span sovrapposte o adiacenti: si fondono, altrimenti
    # una stessa parola verrebbe sostituita due volte ("[CATASTO_1][CATASTO_2]").
    kept.sort(key=lambda e: (e["start"], -(e["end"] - e["start"])))
    merged = []
    for e in kept:
        if merged and e["start"] < merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], e["end"])
            continue
        if merged and e["start"] == merged[-1]["end"] and e["label"] == merged[-1]["label"]:
            merged[-1]["end"] = e["end"]
            continue
        merged.append(e)
    return merged


def _norm(s):
    return re.sub(r"\s+", " ", s.strip()).casefold()


def analyze(text, excluded=None, mapping_enabled=True):
    """excluded = tag da NON anonimizzare: le entita' di quel tipo vengono scartate
    prima della fusione, quindi il valore resta in chiaro nel testo di output.

    mapping_enabled=False -> anonimizzazione DEFINITIVA: nessun dizionario
    placeholder->valore, e i segmenti-entita' non riportano il testo originale
    (che altrimenti permetterebbe di ricostruire il dizionario dalla risposta).
    La numerazione dei placeholder resta: dice che due occorrenze sono lo stesso
    soggetto, ma da sola non fa risalire al valore."""
    excluded = set(excluded or ())
    model_ents, n_chunks = detect_model(text)
    # il modello taglia i minuti delle ore: la regex dell'ora completa SOLO le sue span TIME
    complete_time(model_ents, text)
    cands = model_ents + detect_regex(text)
    if excluded:
        cands = [e for e in cands if e["label"] not in excluded]
    kept = _merge(cands, text)

    # ID reversibili: stesso (label, valore-normalizzato) -> stesso placeholder.
    counters, seen, mapping = {}, {}, {}
    for e in kept:
        val = text[e["start"]:e["end"]]
        key = (e["label"], _norm(val))
        if key in seen:
            e["ph"] = seen[key]
        else:
            counters[e["label"]] = counters.get(e["label"], 0) + 1
            ph = f"[{e['label']}_{counters[e['label']]}]"
            seen[key] = ph
            if mapping_enabled:
                mapping[ph] = val
            e["ph"] = ph

    # segmenti per la preview + testo anonimizzato + statistiche
    segments, anon, by_label, by_source, pos = [], [], {}, {}, 0
    for e in kept:
        if e["start"] > pos:
            segments.append({"t": text[pos:e["start"]]})
            anon.append(text[pos:e["start"]])
        seg = {
            "label": e["label"],
            "ph": e["ph"],
            "src": e["source"],
            "validated": e["validated"],
        }
        if mapping_enabled:                       # senza dizionario niente valore originale
            seg["t"] = text[e["start"]:e["end"]]
        segments.append(seg)
        anon.append(e["ph"])
        by_label[e["label"]] = by_label.get(e["label"], 0) + 1
        by_source[e["source"]] = by_source.get(e["source"], 0) + 1
        pos = e["end"]
    if pos < len(text):
        segments.append({"t": text[pos:]})
        anon.append(text[pos:])

    return {
        "segments": segments,
        "anonymized_text": "".join(anon),
        "mapping": mapping,
        "mapping_enabled": mapping_enabled,
        "n_chunks": n_chunks,
        "n_chars": len(text),
        "n_entities": len(kept),
        "n_unique": len(seen),
        "by_label": dict(sorted(by_label.items(), key=lambda x: -x[1])),
        "by_source": by_source,
        "excluded_tags": sorted(excluded),
    }


# --------------------------------------------------------------------------- #
# Guardrail API v1 (ENVAS-23, prima slice): endpoint additivo sotto /api/v1.
# Il contratto e' docs/GUARDRAIL_API.md + docs/guardrail-openapi.yaml; le route
# legacy qui sopra non cambiano. Il motore del seed sta in pii_dictionary.py, il
# guscio HTTP in guardrail_api.py. Qui c'e' solo l'adapter verso la pipeline
# esistente: detect_model/completa-confini/regex/_merge, senza riscriverli.
# --------------------------------------------------------------------------- #
def _guardrail_detect(text, check_deadline, categories=None):
    """Rilevamento su un tratto NON protetto per la guardrail API.

    Differenza voluta da detect_model(): l'inferenza gira un chunk per volta, cosi'
    il callback di deadline viene controllato tra un chunk e l'altro. Una singola
    chiamata a nlp() non e' interrompibile; il contratto lo dice esplicitamente
    (docs/GUARDRAIL_API.md, sezione Deadline): la deadline e' cooperativa.
    `categories` opzionale restringe modello E rete regex PRIMA di _merge
    (None = tutte): una regex di una categoria inattiva non deve sopprimere un
    candidato attivo del modello nella fusione.
    """
    if nlp is None:
        raise guardrail_api.ModelUnavailable()
    ents = []
    for chunk, offset in chunk_text(text):
        check_deadline()
        results = nlp([chunk])                 # stessa forma batch, un chunk per call
        check_deadline()
        if isinstance(results, dict):
            results = [results]
        res = (results[0] if len(results) == 1 and isinstance(results[0], (list, tuple))
               else results)
        for e in res:
            ents.append({
                "label": e["entity_group"],
                "start": int(e["start"]) + offset,
                "end": int(e["end"]) + offset,
                "score": float(e["score"]),
                "validated": False,
                "source": "modello",
            })
    complete_time(ents, text)
    check_deadline()
    regex_ents = detect_regex(text)
    check_deadline()
    cands = ents + regex_ents
    if categories is not None:
        # La selezione della richiesta vale PRIMA della fusione: una regex di una
        # categoria inattiva non deve sopprimere un candidato attivo del modello.
        cands = [candidate for candidate in cands if candidate["label"] in categories]
    check_deadline()
    return _merge(cands, text)


def _guardrail_detect_for_categories(categories):
    """Binder request-local: closure immutabile per la whitelist attiva.

    Ritorna un rilevatore con la stessa firma a due argomenti di _guardrail_detect
    ma con la selezione gia' fissata: il core resta generico e il percorso senza
    selezione non costruisce nessuna closure.
    """
    active = frozenset(categories)

    def detect_active(text, check_deadline):
        return _guardrail_detect(text, check_deadline, categories=active)

    return detect_active


def _guardrail_extract(name, data, remaining_chars, check_deadline):
    """Testo di un file della guardrail v1 (multipart): nome -> estrattore.

    L'estensione accettata sceglie la famiglia di input; il contenuto PDF viene
    comunque instradato nel percorso strict e bounded anche quando il file e'
    chiamato .txt/.md. PDF -> PyMuPDF solo con controllo nativo privacy
    verificato, altrimenti 503 senza aprire il documento; testo -> la policy di
    codifica legacy di `_text_from_bytes`, poi char bound e blank check. Gli
    errori sono tipizzati con status/codice del contratto e non contengono mai
    il nome file. Deadline e limite caratteri restano 504/413. Un reset nativo
    fallito disabilita i PDF fino al riavvio, senza sostituire errori originali.
    """
    ext = os.path.splitext((name or "").lower())[1]
    if ext not in guardrail_inputs.ACCEPTED_EXTS:
        raise guardrail_inputs.InputError(415, "unsupported_file_type")

    if _is_pdf(name, data):
        if not MUPDF_PRIVACY_OK:
            raise guardrail_inputs.InputError(503, "unavailable")
        try:
            try:
                document = fitz.open(stream=data, filetype="pdf")
                try:
                    check_deadline()   # fitz.open e' nativo e non interrompibile
                except BaseException:
                    close = getattr(document, "close", None)
                    if callable(close):
                        try:
                            close()
                        except Exception:
                            pass
                    raise
                with document as doc:
                    if not bool(getattr(doc, "is_pdf", False)):
                        raise guardrail_inputs.InputError(422, "unreadable_file")
                    if (bool(getattr(doc, "needs_pass", False))
                            or bool(getattr(doc, "is_encrypted", False))):
                        raise guardrail_inputs.InputError(422, "unreadable_file")
                    page_count = int(doc.page_count)
                    check_deadline()
                    if page_count > guardrail_inputs.MAX_PDF_PAGES:
                        raise guardrail_inputs.InputError(413, "payload_too_large")
                    text = pdf_text.collect_readable_text(
                        doc, max_chars=remaining_chars,
                        check_deadline=check_deadline, strict=True)
            except guardrail_inputs.InputError:
                raise
            except pii_dictionary.DeadlineExceeded:
                raise                      # la deadline resta 504, mai un 422
            except pdf_text.PdfTextTooLarge:
                raise guardrail_inputs.InputError(413, "payload_too_large")
            except Exception:
                raise guardrail_inputs.InputError(422, "unreadable_file")
        except BaseException:
            # Il cleanup non deve rimpiazzare 413/504 o un altro errore originale.
            _reset_native_mupdf_warnings()
            raise
        if not _reset_native_mupdf_warnings():
            raise guardrail_inputs.InputError(503, "unavailable")
        if not text.strip():
            raise guardrail_inputs.InputError(422, "no_extractable_text")
        return text

    try:
        text = _text_from_bytes(name, data)
    except Exception:
        raise guardrail_inputs.InputError(422, "unreadable_file")
    if len(text) > remaining_chars:
        raise guardrail_inputs.InputError(413, "payload_too_large")
    if not text.strip():
        raise guardrail_inputs.InputError(422, "empty_file")
    return text


guardrail_api.register_app(app, tags=TAG_NAMES, detect=_guardrail_detect,
                           detect_for_categories=_guardrail_detect_for_categories,
                           extract=_guardrail_extract,
                           readiness=lambda: nlp is not None)


# --------------------------------------------------------------------------- #
# Errori HTTP generati dal framework (404, 405, 413, 500, ...) -> JSON
#
# Questa e' l'UNICA gestione globale: intercetta solo le HTTPException sollevate
# dal framework (route inesistente, metodo sbagliato, body oltre
# MAX_CONTENT_LENGTH, eccezione non gestita). Gli errori "di merito" che le route
# restituiscono restano i loro JSON {"error": ...}, e i successi binari restano
# binari. Nessuna descrizione, URL o valore della richiesta finisce nel corpo:
# solo la frase standard del codice. Si riusa la risposta del framework per
# conservarne gli header di protocollo (Allow, WWW-Authenticate, Retry-After).
# --------------------------------------------------------------------------- #
@app.errorhandler(HTTPException)
def _http_error(e):
    resp = e.get_response()
    if resp.status_code < 400:               # HTTPException senza codice -> 500
        resp.status_code = 500
    status = resp.status_code
    try:
        info = HTTPStatus(status)
    except ValueError:                       # codice non standard: fallback neutro
        error_text, code = "HTTP error.", f"http_{status}"
    else:
        error_text, code = info.phrase + ".", info.name.lower()
    resp.set_data(json.dumps({"error": error_text, "code": code}))
    resp.mimetype = "application/json"
    resp.headers["Cache-Control"] = "no-store"   # gli errori non si mettono in cache
    return resp


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.route("/health")
@app.route("/healthz")
def health():
    """Liveness/readiness SENZA inference: sonda economica per orchestratori e process manager.
    200 = modello caricato e pronto; 503 = server su ma modello non disponibile."""
    ready = nlp is not None
    excl, mapping = _get_prefs()
    body = {
        "status": "ok" if ready else "loading",
        "model_loaded": ready,
        "model": os.path.basename(str(MODEL_DIR).rstrip("/\\")),
        "model_version": APP_MODEL_VERSION,
        "app_version": APP_VERSION,
        "device": "cuda" if device == 0 else "cpu",
        "tags": len(TAG_NAMES),
        "excluded_tags": excl,
        "mapping_enabled": mapping,
    }
    return jsonify(body), (200 if ready else 503)


def _is_pdf(name, data):
    return os.path.splitext((name or "").lower())[1] == ".pdf" or data[:5] == b"%PDF-"


def _text_from_bytes(name, data):
    """Testo dai bytes di un upload: PDF via PyMuPDF, .md/.txt come testo puro.

    Per i PDF non basta `page.get_text()`: nei moduli AcroForm il valore sta
    nei widget (issue #85). `pdf_text.collect_readable_text` allinea
    l'estrazione a quanto `pdf_export` gia' ispezionava per i residui.
    """
    name = (name or "").lower()
    ext = os.path.splitext(name)[1]
    if _is_pdf(name, data):
        with fitz.open(stream=data, filetype="pdf") as doc:
            # Non solo page.get_text(): nei PDF fillable il valore sta nei
            # widget AcroForm (issue #85). Stesso contratto di pdf_export.
            return pdf_text.collect_readable_text(doc)
    if ext in TEXT_EXTS or not ext:
        # utf-16 solo col BOM: senza, il codec accetta qualunque sequenza di lunghezza pari
        # e si mangia i .txt a 8 bit. cp1252 prima di latin-1: e' quello che scrivono Word
        # e il Blocco note italiani, e i due differiscono su euro e virgolette tipografiche.
        primo = ("utf-16",) if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ()
        for enc in primo + ("utf-8-sig", "cp1252", "latin-1"):
            try:
                # Via i byte nulli. Un utf-16 SENZA BOM finisce per forza su una codifica a
                # 8 bit e il testo esce "M\0a\0r\0i\0o": a schermo non si vede niente (in
                # HTML il NUL e' invisibile), quindi l'utente legge il documento intero,
                # non trova segnaposti e conclude che non ci fosse nulla da anonimizzare -
                # mentre i rilevatori, che lavorano sul testo vero, non trovano niente.
                # In un utf-16 latino il byte alto e' proprio quello nullo: tolto, il testo
                # torna esatto e le PII tornano trovabili. Riconoscere l'utf-16 contando i
                # byte nulli, invece, sbaglia in entrambe le direzioni.
                return data.decode(enc).replace("\x00", "")
            except UnicodeDecodeError:
                continue
    raise ValueError(
        f"Formato non supportato: {ext or name or 'sconosciuto'}. "
        "Accetto .pdf, .md, .txt oppure testo incollato."
    )


def _extract_upload(fs):
    """Testo da un file caricato (consuma lo stream)."""
    return _text_from_bytes(fs.filename, fs.read())


def _uploaded_file():
    """Il file dell'upload, se c'e'. "pdf" e' il nome storico del campo, "file" e'
    l'alias nuovo."""
    return next((request.files[k] for k in ("pdf", "file")
                 if k in request.files and request.files[k].filename), None)


@app.route("/analyze", methods=["POST"])
def analyze_route():
    up = _uploaded_file()
    if up is not None:
        try:
            text = _extract_upload(up)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:                       # PDF corrotto / protetto
            return jsonify({"error": f"Impossibile leggere il file: {e}"}), 400
        raw_excl = request.form.get("exclude_tags")
        raw_map = request.form.get("include_mapping")
    else:
        payload = request.get_json(silent=True) or {}
        text = payload.get("text", "")
        raw_excl = payload.get("exclude_tags")
        raw_map = payload.get("include_mapping")

    text = (text or "").strip()
    if not text:
        return jsonify({"error": "Nessun testo da analizzare."}), 400

    # override per-richiesta; senza override vale la configurazione del server
    # (snapshot atomico: una POST /settings concorrente non deve far leggere
    # un tag escluso aggiornato insieme a un mapping_enabled non ancora aggiornato, o viceversa)
    default_excl, default_map = _get_prefs()
    excl = server_config.parse_tag_list(raw_excl) if raw_excl is not None else default_excl
    keep_map = (server_config.parse_bool(raw_map, default_map)
                if raw_map is not None else default_map)
    out = analyze(text, excl, keep_map)
    # Il testo originale torna solo col dizionario attivo (il chiamante lo usa per
    # il ripristino). In modalita' definitiva la risposta non deve contenere nessun
    # valore in chiaro: la chiave manca del tutto, come il valore nei segmenti (#118).
    if keep_map:
        out["source_text"] = text
    return jsonify(out)


# --------------------------------------------------------------------------- #
# PDF anonimizzato da scaricare (issue #7, punto 1)
# --------------------------------------------------------------------------- #
def _pdf_response(data, report, redactions, filename="documento_anonimizzato.pdf"):
    """Risposta binaria + intestazioni diagnostiche. X-PII-Residual e
    X-PII-Skipped sono le due da tradurre in un avviso al chiamante: valori del
    documento che, per motivi diversi, sono rimasti in chiaro."""
    resp = app.response_class(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f"attachment; filename={filename}"
    resp.headers["X-PII-Redactions"] = str(redactions)
    resp.headers["X-PII-Residual"] = str(len(report.get("residual", [])))
    resp.headers["X-PII-Skipped"] = str(len(report.get("skipped", [])))
    resp.headers["X-PII-Notfound"] = str(len(report.get("not_found", [])))
    return resp


class _ReqError(Exception):
    """Errore da rendere al client come {"error": ...} con uno status preciso."""

    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.msg, self.status = msg, status


def _build_anonymized_pdf():
    """Costruisce il PDF ANONIMIZZATO dall'input della richiesta. Stesso input di
    /analyze:

    - multipart con un file .pdf  -> REDAZIONE VERA del documento originale: le
      PII sono rimosse dal content stream e sostituite dai placeholder, il layout
      resta quello di partenza (piu' metadati/annotazioni/campi modulo/segnalibri
      ripuliti e allegati rimossi);
    - multipart con .md/.txt oppure {"text": ...} -> PDF ricostruito impaginando
      da zero il solo testo anonimizzato.

    Il dizionario placeholder->valore NON viaggia sulla rete in nessuna delle due
    direzioni: viene ricostruito qui, serve solo a localizzare le PII nel PDF e
    muore con la richiesta. Per questo funziona identico anche con il dizionario
    reversibile disattivato (MAPPING_ENABLED=False), dove il client non ne ha
    nessuno.

    Ritorna (bytes, report, n_redazioni, nome_file). Solleva _ReqError sugli errori.
    """
    up = _uploaded_file()
    if up is not None:
        name, data = up.filename, up.read()
        try:
            text = _text_from_bytes(name, data)
        except ValueError as e:
            raise _ReqError(str(e))
        except Exception as e:                       # PDF corrotto / protetto
            raise _ReqError(f"Impossibile leggere il file: {e}")
        raw_excl = request.form.get("exclude_tags")
    else:
        payload = request.get_json(silent=True) or {}
        name, data, text = "", b"", payload.get("text", "")
        raw_excl = payload.get("exclude_tags")

    text = (text or "").strip()
    if not text:
        raise _ReqError("Nessun testo da anonimizzare.")

    stem = os.path.splitext(_safe_name(name, "documento.pdf"))[0] or "documento"
    out_name = f"{stem}_anonimizzato.pdf"

    excl = (server_config.parse_tag_list(raw_excl) if raw_excl is not None
            else _get_prefs()[0])
    # mapping_enabled=True e' interno: il risultato non esce da questa funzione.
    res = analyze(text, excl, mapping_enabled=True)
    if not res["mapping"]:
        raise _ReqError("Nessuna PII trovata: non c'e' niente da "
                        "anonimizzare in questo documento.", 422)

    if data and _is_pdf(name, data):
        try:
            out, report = pdf_export.redact_pdf(data, res["mapping"])
        except pdf_export.PdfError as e:
            raise _ReqError(str(e))
        if report["occurrences"] == 0:
            raise _ReqError("Nessuna occorrenza trovata nel PDF: se il documento "
                            "e' una scansione (testo dentro un'immagine) la "
                            "redazione del layer testuale non puo' agire.", 422)
        return out, report, report["occurrences"], out_name

    try:
        out = pdf_export.text_to_pdf(res["anonymized_text"])
    except pdf_export.PdfError as e:
        raise _ReqError(str(e))
    # testo reimpaginato da zero: nell'output c'e' solo il testo anonimizzato,
    # quindi niente residui e niente valori saltati da segnalare.
    return out, {}, res["n_entities"], out_name


@app.route("/pdf", methods=["POST"])
def pdf_route():
    """Scarica il documento ANONIMIZZATO in PDF (vedi _build_anonymized_pdf)."""
    try:
        out, report, redactions, name = _build_anonymized_pdf()
    except _ReqError as e:
        return jsonify({"error": e.msg}), e.status
    return _pdf_response(out, report, redactions, name)


@app.route("/pdf/preview", methods=["POST"])
def pdf_preview_route():
    """Come /pdf, ma il binario resta in memoria e si guarda a video: la risposta
    e' il descrittore del documento ({doc_id, n_pages, ...}), le pagine si prendono
    poi da /doc/<id>/page/<n>.png e il file da /doc/<id>/file.pdf.

    Serve a non anonimizzare due volte: l'anteprima via API e il download del PDF
    usano lo STESSO documento, generato una volta sola."""
    try:
        out, report, redactions, name = _build_anonymized_pdf()
    except _ReqError as e:
        return jsonify({"error": e.msg}), e.status
    doc_id, n_pages = _store_doc(out, name)
    return jsonify({
        "doc_id": doc_id,
        "n_pages": n_pages,
        "filename": name,
        "redactions": redactions,
        "residual": len(report.get("residual", [])),
        "skipped": len(report.get("skipped", [])),
        "not_found": len(report.get("not_found", [])),
    })


# --------------------------------------------------------------------------- #
# Anteprima a video del documento CARICATO + pagine renderizzate
# --------------------------------------------------------------------------- #
@app.route("/preview", methods=["POST"])
def preview_route():
    """Tiene in memoria il PDF appena caricato per l'anteprima e ne ritorna anche
    il testo estratto (cosi' il chiamante non deve fare una seconda estrazione)."""
    up = _uploaded_file()
    if up is None:
        return jsonify({"error": "Nessun file caricato."}), 400
    name, data = up.filename, up.read()
    if not _is_pdf(name, data):
        return jsonify({"error": "L'anteprima renderizzata vale solo per i PDF."}), 400
    try:
        text = _text_from_bytes(name, data)
        doc_id, n_pages = _store_doc(data, name)
    except Exception as e:                           # PDF corrotto / protetto
        return jsonify({"error": f"Impossibile leggere il file: {e}"}), 400
    return jsonify({"doc_id": doc_id, "n_pages": n_pages,
                    "filename": _safe_name(name), "text": text})


@app.route("/doc/<doc_id>/page/<int:n>.png")
def doc_page(doc_id, n):
    """Pagina n (0-based) renderizzata in PNG. 404 se il documento e' scaduto
    dalla LRU: in quel caso il chiamante rifa' l'upload."""
    d = _get_doc(doc_id)
    if d is None:
        return ("", 404)
    png = _page_png(d, n)
    if png is None:
        return ("", 404)
    resp = app.response_class(png, mimetype="image/png")
    resp.headers["Cache-Control"] = "private, max-age=600"
    return resp


@app.route("/doc/<doc_id>/file.pdf")
def doc_file(doc_id):
    """Download del PDF tenuto in memoria (quello gia' anonimizzato da
    /pdf/preview): non ricalcola niente."""
    d = _get_doc(doc_id)
    if d is None:
        return jsonify({"error": "Documento non piu' disponibile."}), 404
    resp = app.response_class(d["pdf"], mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f"attachment; filename={d['name']}"
    return resp


# --------------------------------------------------------------------------- #
# Impostazioni: legenda dei tag, tag esclusi, dizionario reversibile on/off
# (/tags resta come alias storico dello stesso endpoint)
# --------------------------------------------------------------------------- #
@app.route("/settings", methods=["GET"])
@app.route("/tags", methods=["GET"])
def settings_get():
    excl, mapping = _get_prefs()
    return jsonify({
        "tags": [{"tag": t, "it": it, "en": en, "example": ex} for t, it, en, ex in TAGS],
        "excluded_tags": excl,
        "mapping_enabled": mapping,
        "config_path": str(server_config.prefs_path()),
        "env_override": "PII_EXCLUDE_TAGS" in os.environ or "PII_MAPPING" in os.environ,
    })


@app.route("/settings", methods=["POST"])
@app.route("/tags", methods=["POST"])
def settings_post():
    global EXCLUDED_TAGS, MAPPING_ENABLED
    data = request.get_json(silent=True) or {}
    tags = None
    if "excluded_tags" in data:
        tags = server_config.parse_tag_list(data["excluded_tags"])
        unknown = [t for t in tags if t not in TAG_NAMES]
        if unknown:
            return jsonify({"error": f"Tag sconosciuti: {', '.join(unknown)}"}), 400
    mapping = data.get("mapping_enabled")
    if tags is None and mapping is None:
        return jsonify({"error": "Niente da salvare: passa excluded_tags e/o mapping_enabled."}), 400
    saved = server_config.save_prefs(excluded_tags=tags, mapping_enabled=mapping)
    with _PREFS_LOCK:
        EXCLUDED_TAGS = saved["excluded_tags"]
        MAPPING_ENABLED = saved["mapping_enabled"]
    return jsonify({"ok": True, "excluded_tags": EXCLUDED_TAGS,
                    "mapping_enabled": MAPPING_ENABLED})


# --------------------------------------------------------------------------- #
# Config host/porta (GET = leggi, POST = salva per il prossimo avvio)
# --------------------------------------------------------------------------- #
@app.route("/config", methods=["GET"])
def config_get():
    cfg = server_config.load_config()
    return jsonify({
        "host": cfg.get("host", server_config.DEFAULT_HOST),
        "port": cfg.get("port", server_config.DEFAULT_PORT),
        "config_path": str(server_config.config_path()),
    })


@app.route("/config", methods=["POST"])
def config_post():
    data = request.get_json(silent=True) or {}
    host = str(data.get("host", server_config.DEFAULT_HOST)).strip()
    try:
        port = int(data.get("port", server_config.DEFAULT_PORT))
    except (ValueError, TypeError):
        return jsonify({"error": "Porta non valida."}), 400
    if not (1024 <= port <= 65535):
        return jsonify({"error": "La porta deve essere tra 1024 e 65535."}), 400
    server_config.save_config(host, port)
    return jsonify({"ok": True, "host": host, "port": port})


@app.route("/port-check")
def port_check():
    host = request.args.get("host", server_config.DEFAULT_HOST)
    try:
        port = int(request.args.get("port", server_config.DEFAULT_PORT))
    except (ValueError, TypeError):
        return jsonify({"available": False})
    return jsonify({"available": server_config.port_available(host, port)})


if __name__ == "__main__":
    import argparse as _ap
    _p = _ap.ArgumentParser(description="Rizzo PII — server locale di anonimizzazione.")
    _p.add_argument("--host", default=None, help="indirizzo su cui ascoltare (default da config/env/127.0.0.1)")
    _p.add_argument("--port", type=int, default=None, help="porta su cui ascoltare (default da config/env/5005)")
    _p.add_argument("--exclude-tags", default=None, metavar="TAG,TAG",
                    help="tag PII da NON anonimizzare, es. AGE,GENDER (default da env/prefs.json)")
    _p.add_argument("--no-mapping", action="store_true",
                    help="anonimizzazione definitiva: non costruire il dizionario di ripristino")
    _args = _p.parse_args()

    if _args.exclude_tags is not None:
        EXCLUDED_TAGS = server_config.parse_tag_list(_args.exclude_tags)
        _unknown = [t for t in EXCLUDED_TAGS if t not in TAG_NAMES]
        if _unknown:
            print(f"ERRORE: tag sconosciuti in --exclude-tags: {', '.join(_unknown)}")
            print(f"Tag validi: {', '.join(TAG_NAMES)}")
            sys.exit(2)
    if _args.no_mapping:
        MAPPING_ENABLED = False
    if EXCLUDED_TAGS:
        print(f"Tag esclusi dall'anonimizzazione: {', '.join(EXCLUDED_TAGS)}")
    print("Dizionario reversibile: " +
          ("ATTIVO (si puo' ripristinare)" if MAPPING_ENABLED
           else "DISATTIVO (anonimizzazione definitiva)"))

    _host, _port = server_config.resolve(cli_host=_args.host, cli_port=_args.port)

    if not server_config.port_available(_host, _port):
        print(f"ERRORE: porta {_port} occupata su {_host}")
        sys.exit(server_config.EXIT_PORT_CONFLICT)

    print(f"Server su http://{_host}:{_port}")
    try:
        app.run(host=_host, port=_port, threaded=True)
    except OSError as e:
        print(f"ERRORE bind: {e}")
        sys.exit(server_config.EXIT_PORT_CONFLICT)
