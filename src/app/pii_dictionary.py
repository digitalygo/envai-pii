# -*- coding: utf-8 -*-
"""
Motore del dizionario seed per la guardrail API (ENVAS-23, prima slice).

Solo standard library: nessun import di Flask/torch/fitz, nessun accesso a modello,
rete o disco. Il rilevatore e il callback di deadline sono iniettati, cosi' il modulo
e' testabile in isolamento e riusabile fuori da Flask.

Implementa la parte di contratto di docs/GUARDRAIL_API.md che riguarda il testo:
normalizzazione (casefold Unicode + strip/collapse degli spazi, niente NFC o rimozione
di accenti/punteggiatura), validazione del seed, localizzazione letterale delle PII note
sugli offset ORIGINALI, protezione dei placeholder gia' presenti, fusione con le entita'
del rilevatore nei soli tratti non protetti, allocazione degli ID per categoria in
ordine di incontro, delta dei soli valori nuovi e conteggio dei placeholder finali.

Una sola passata in costruzione: il testo prodotto da una sostituzione non viene mai
riscansionato.

Tutti i valori usati nei test sono SINTETICI.
"""

import heapq
import re
from bisect import bisect_right

MAX_TEXT_CHARS = 100000          # caratteri Unicode (code point) del campo `text`
MAX_SEED_ENTRIES = 256           # voci del dizionario seed
MAX_ORIGINAL_CHARS = 4096        # caratteri di un singolo originale
MAX_AGGREGATE_CHARS = 65536      # somma delle lunghezze di tutti gli originali
MAX_PLACEHOLDER_INDEX = 999999999

# Un token tra spazi: usato per normalizzare e, in parallelo, per mappare ogni
# carattere normalizzato sul carattere originale che lo ha prodotto.
_TOKEN_RE = re.compile(r"\S+")

# Placeholder canonico: [LABEL_N], LABEL fra i tag passati dal chiamante, N intero
# positivo ASCII senza zeri iniziali. Le parentesi fanno parte del token.
_PLACEHOLDER_RE = re.compile(r"\[([A-Za-z0-9_]+)_([1-9][0-9]{0,8})\]")


# --------------------------------------------------------------------------- #
# Errori tipizzati: il chiamante (guardrail_api) li traduce in {error, code}.
# --------------------------------------------------------------------------- #
class PiiDictionaryError(Exception):
    """Errore con un codice stabile del contratto."""

    code = "invalid_seed"
    status = 400

    def __init__(self):
        super().__init__(self.code)


class InvalidSeed(PiiDictionaryError):
    code = "invalid_seed"


class SeedConflict(PiiDictionaryError):
    code = "seed_conflict"


class PayloadTooLarge(PiiDictionaryError):
    code = "payload_too_large"
    status = 413


class AllocationExhausted(PiiDictionaryError):
    code = "allocation_exhausted"


class DeadlineExceeded(PiiDictionaryError):
    code = "deadline_exceeded"
    status = 504


# --------------------------------------------------------------------------- #
# Normalizzazione
# --------------------------------------------------------------------------- #
def normalize(value):
    """Identita' di un originale: casefold Unicode + strip/collapse degli spazi.

    Non rimuove accenti ne' punteggiatura e non applica NFC/NFKC: "Rossi" e "Ròssi"
    restano due identita' diverse. E' la stessa normalizzazione usata per i conflitti
    del seed e per localizzare gli originali nel testo.
    """
    return " ".join(match.group(0) for match in _TOKEN_RE.finditer(value)).casefold()


def _normalize_with_map(value, check_deadline=None):
    """normalize() + mappa offset: (testo, ranges, starts, ends).

    Per ogni carattere del testo normalizzato:
      ranges[i] = (start, end) del carattere ORIGINALE che lo ha prodotto;
      starts[i] = True se e' il primo carattere dell'espansione di quel carattere;
      ends[i]   = True se e' l'ultimo.

    Serve per i casefold che cambiano la lunghezza ("ß" -> "ss", "ﬀ" -> "ff"): un
    match che comincia o finisce a meta' espansione va rifiutato, altrimenti verrebbe
    sostituito mezzo carattere originale.
    """
    parts, ranges, starts, ends = [], [], [], []
    previous_end = 0
    first = True
    work = 0
    for match in _TOKEN_RE.finditer(value):
        if not first:
            parts.append(" ")                      # spazio di collasso tra due token
            ranges.append((previous_end, match.start()))
            starts.append(True)
            ends.append(True)
        first = False
        base = match.start()
        for offset, char in enumerate(match.group(0)):
            folded = char.casefold()
            last = len(folded) - 1
            for index, folded_char in enumerate(folded):
                parts.append(folded_char)
                ranges.append((base + offset, base + offset + 1))
                starts.append(index == 0)
                ends.append(index == last)
            work += 1
            if check_deadline is not None and work >= 256:
                check_deadline()
                work = 0
        previous_end = match.end()
    return "".join(parts), ranges, starts, ends


def _is_word(char):
    """Carattere "interno a una parola": lettera o cifra Unicode, oppure underscore."""
    return char.isalnum() or char == "_"


# --------------------------------------------------------------------------- #
# Placeholder canonici
# --------------------------------------------------------------------------- #
def parse_placeholder(key, labels):
    """(label, index) se `key` e' un placeholder canonico con label nota, altrimenti None."""
    if not isinstance(key, str):
        return None
    match = _PLACEHOLDER_RE.fullmatch(key)
    if match is None:
        return None
    label = match.group(1)
    if label not in labels:
        return None
    return label, int(match.group(2))


def find_placeholders(text, labels):
    """Placeholder canonici nel testo: [(start, end, label, index), ...] in ordine."""
    labels = set(labels)
    found = []
    for match in _PLACEHOLDER_RE.finditer(text):
        label = match.group(1)
        if label not in labels:
            continue
        found.append((match.start(), match.end(), label, int(match.group(2))))
    return found


def count_placeholders(text, labels):
    """Occorrenze di placeholder canonici nel testo (ogni ripetizione conta)."""
    return len(find_placeholders(text, labels))


# --------------------------------------------------------------------------- #
# Seed
# --------------------------------------------------------------------------- #
class Seed:
    """Seed validato e immutabile. Le coppie non vengono mai riassegnate o modificate."""

    __slots__ = ("_pairs", "_by_normalized", "_reserved")

    def __init__(self, pairs):
        self._pairs = tuple(pairs)
        self._by_normalized = {
            normalize(original): (label, placeholder)
            for placeholder, label, _index, original in pairs
        }
        reserved = {}
        for _placeholder, label, index, _original in pairs:
            if index > reserved.get(label, 0):
                reserved[label] = index
        self._reserved = reserved

    @property
    def pairs(self):
        """Coppie (placeholder, label, index, originale) nell'ordine del dizionario."""
        return self._pairs

    def reserved_ids(self):
        """Copia del massimo ID occupato per categoria (chiavi del seed)."""
        return dict(self._reserved)

    def lookup(self, label, normalized):
        """Placeholder del seed se label e originale normalizzato combaciano, else None."""
        entry = self._by_normalized.get(normalized)
        if entry is not None and entry[0] == label:
            return entry[1]
        return None


def parse_seed(dictionary, tags):
    """Valida il dizionario seed e lo congela in un Seed. Solleva errori tipizzati.

    Limiti (dal contratto): <= 256 voci, un originale <= 4096 caratteri, somma degli
    originali <= 65536. Chiavi canoniche per i `tags` passati (i TAG_NAMES reali).
    Due originali con la stessa normalizzazione confliggono, anche con label diverse.
    """
    if not isinstance(dictionary, dict):
        raise InvalidSeed()
    labels = set(tags)
    if len(dictionary) > MAX_SEED_ENTRIES:
        raise PayloadTooLarge()
    pairs = []
    seen = set()
    total = 0
    for key, value in dictionary.items():
        parsed = parse_placeholder(key, labels)
        if parsed is None:
            raise InvalidSeed()
        label, index = parsed
        if not isinstance(value, str) or not value.strip():
            raise InvalidSeed()
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise InvalidSeed()
        if len(value) > MAX_ORIGINAL_CHARS:
            raise PayloadTooLarge()
        total += len(value)
        if total > MAX_AGGREGATE_CHARS:
            raise PayloadTooLarge()
        normalized = normalize(value)
        if normalized in seen:
            raise SeedConflict()
        seen.add(normalized)
        pairs.append((key, label, index, value))
    return Seed(pairs)


# --------------------------------------------------------------------------- #
# Localizzazione dei seed noti nel testo
# --------------------------------------------------------------------------- #
def _locate_seed_spans(text, seed, placeholder_spans, check_deadline):
    """Match delle PII note sugli offset originali, piu' lungo vince.

    Ritorna [(start, end, placeholder), ...] ordinati per start. Il confronto e' sul
    testo normalizzato, ma gli offset restituiti sono quelli del testo originale. I
    placeholder canonici sono occupati da subito: un match del seed non li sovrascrive
    e non li spezza. A parita' di lunghezza decide il placeholder (ordine lessicale),
    quindi il risultato non dipende dall'ordine del dizionario.
    """
    if not seed.pairs or not text:
        return []
    normalized_text, ranges, starts, ends = _normalize_with_map(text, check_deadline)
    if not normalized_text:
        return []

    # Occupied bytes track placeholder spans and accepted matches. A compact block
    # index bounds overlap lookups, while the heap retains at most one candidate per
    # original start instead of every seed/occurrence pair.
    block_size = 256
    occupied = bytearray(len(text))
    block_flags = bytearray((len(text) + block_size - 1) // block_size)

    def mark(start, end):
        occupied[start:end] = b"\x01" * (end - start)
        first_block = start // block_size
        last_block = (end - 1) // block_size
        block_flags[first_block:last_block + 1] = b"\x01" * (last_block - first_block + 1)

    def first_occupied(start, end):
        if start >= end:
            return -1
        first_block = start // block_size
        boundary = min(end, (first_block + 1) * block_size)
        found = occupied.find(b"\x01", start, boundary)
        if found >= 0:
            return found
        next_block = first_block + 1
        last_block = (end - 1) // block_size
        next_block = block_flags.find(b"\x01", next_block, last_block + 1)
        if next_block < 0:
            return -1
        return occupied.find(b"\x01", next_block * block_size,
                             min(end, (next_block + 1) * block_size))

    for start, end, _label, _index in placeholder_spans:
        check_deadline()
        mark(start, end)
    placeholder_starts = [span[0] for span in placeholder_spans]

    def overlaps_placeholder(start, end):
        index = bisect_right(placeholder_starts, start) - 1
        if index >= 0 and placeholder_spans[index][1] > start:
            return True
        index += 1
        return index < len(placeholder_spans) and placeholder_starts[index] < end

    needles = []
    for placeholder, _label, _index, original in seed.pairs:
        check_deadline()
        needle = normalize(original)
        if needle:
            needles.append((placeholder, needle))

    work = 0

    def check_periodically():
        nonlocal work
        work += 1
        if work >= 256:
            check_deadline()
            work = 0

    def candidate_at(found, placeholder, needle, limit=None):
        norm_end = found + len(needle)
        # Mai a meta' di un'espansione casefold ("ß" -> "ss").
        if not starts[found] or not ends[norm_end - 1]:
            return None
        # Confini di parola sul testo normalizzato: lettera/cifra/_ a entrambi i lati.
        if found > 0 and _is_word(normalized_text[found - 1]):
            return None
        if norm_end < len(normalized_text) and _is_word(normalized_text[norm_end]):
            return None
        start = ranges[found][0]
        end = ranges[norm_end - 1][1]
        if limit is not None:
            if end > limit:
                return None
        elif overlaps_placeholder(start, end):
            return None
        return start, end, placeholder, found

    # Keep only the best candidate at each original start. A conflicting long
    # candidate may later expose a shorter same-start candidate after another span
    # wins globally, so those alternatives are recomputed from the normalized seeds.
    best_by_start = {}
    for placeholder, needle in needles:
        check_deadline()
        position = 0
        while True:
            found = normalized_text.find(needle, position)
            if found < 0:
                break
            position = found + 1
            check_periodically()
            candidate = candidate_at(found, placeholder, needle)
            if candidate is None:
                continue
            start = candidate[0]
            previous = best_by_start.get(start)
            if (previous is None
                    or (-(candidate[1] - candidate[0]), candidate[2])
                    < (-(previous[1] - previous[0]), previous[2])):
                best_by_start[start] = candidate

    def best_at(start, norm_start, limit):
        best = None
        for placeholder, needle in needles:
            check_periodically()
            if not normalized_text.startswith(needle, norm_start):
                continue
            candidate = candidate_at(norm_start, placeholder, needle, limit)
            if candidate is None or candidate[0] != start:
                continue
            if (best is None
                    or (-(candidate[1] - candidate[0]), candidate[2])
                    < (-(best[1] - best[0]), best[2])):
                best = candidate
        return best

    candidates = [(-(end - start), placeholder, start, end, norm_start)
                  for start, end, placeholder, norm_start in best_by_start.values()]
    heapq.heapify(candidates)
    accepted = []
    while candidates:
        check_periodically()
        _negative_length, placeholder, start, end, norm_start = heapq.heappop(candidates)
        if occupied[start]:
            continue
        blocker = first_occupied(start, end)
        if blocker >= 0:
            # A later, higher-priority match occupied part of this span. Try the
            # best shorter candidate at this same start that ends before the blocker.
            replacement = best_at(start, norm_start, blocker)
            if replacement is not None:
                _start, new_end, new_placeholder, new_norm_start = replacement
                heapq.heappush(candidates, (-(new_end - start), new_placeholder,
                                            start, new_end, new_norm_start))
            continue
        mark(start, end)
        accepted.append((start, end, placeholder))

    accepted.sort()
    return accepted


# --------------------------------------------------------------------------- #
# Fusione e allocazione
# --------------------------------------------------------------------------- #
def _gaps(protected, text_length):
    """Tratti NON protetti: il complemento degli intervalli protetti."""
    gaps = []
    position = 0
    for start, end, _kind, _payload in protected:
        if start > position:
            gaps.append((position, start))
        position = max(position, end)
    if position < text_length:
        gaps.append((position, text_length))
    return gaps


def _collect_detected(text, detect, protected, labels, check_deadline):
    """Entita' del rilevatore sui soli tratti non protetti, su offset globali.

    Il rilevatore gira per tratto (e al suo interno un chunk per volta, vedi
    l'adapter in app.py): non puo' quindi frammentare una coppia del seed ne'
    corrompere un placeholder, perche' quei tratti non li vede proprio.
    """
    detected = []
    for gap_start, gap_end in _gaps(protected, len(text)):
        check_deadline()
        gap = text[gap_start:gap_end]
        if not gap.strip():
            continue
        entities = detect(gap, check_deadline)
        if entities:
            for entity in entities:
                label = entity.get("label")
                if label not in labels:
                    continue
                try:
                    start = int(entity["start"])
                    end = int(entity["end"])
                except (KeyError, TypeError, ValueError):
                    continue
                if start < 0 or end <= start or end > len(gap):
                    continue
                detected.append((gap_start + start, gap_start + end, label))
        check_deadline()
    return detected


def _resolve_detected_overlaps(protected, detected, text_length, check_deadline=None):
    """Difesa in profondita': scarta le entita' rilevate che si sovrappongono.

    L'adapter restituisce span gia' fusi, ma il motore non si fida del callback:
    in caso di conflitto vince lo span che inizia prima e, a pari start, il piu'
    lungo (il codice che ha scritto il contratto: mai due placeholder sullo stesso
    carattere). Le entita' che toccano un intervallo protetto vengono comunque
    scartate: la protezione vale anche se il callback esce dai tratti assegnati.
    """
    if not detected:
        return []
    occupied = bytearray(text_length)
    for start, end, _kind, _payload in protected:
        occupied[start:end] = b"\x01" * (end - start)
    detected.sort(key=lambda entity: (entity[0], -(entity[1] - entity[0]), entity[2]))
    kept = []
    for index, (start, end, label) in enumerate(detected):
        if check_deadline is not None and index % 256 == 0:
            check_deadline()
        if occupied.find(b"\x01", start, end) >= 0:
            continue
        occupied[start:end] = b"\x01" * (end - start)
        kept.append((start, end, label))
    return kept


def anonymize(text, seed, tags, detect=None, check_deadline=None):
    """Anonimizza `text` con il seed e il rilevatore iniettato.

    Ritorna {"anonymized_text", "dictionary_delta", "placeholder_count"}.
    Il seed non viene modificato; nessuno stato sopravvive alla chiamata.
    """
    check = check_deadline if check_deadline is not None else (lambda: None)
    if not isinstance(text, str):
        raise TypeError("text deve essere una stringa")
    if len(text) > MAX_TEXT_CHARS:
        raise PayloadTooLarge()
    check()

    labels = set(tags)
    placeholder_spans = find_placeholders(text, labels)
    check()
    seed_spans = _locate_seed_spans(text, seed, placeholder_spans, check)
    check()

    # Intervalli protetti: placeholder canonici (vincolanti) + match del seed.
    protected = [(start, end, "placeholder", text[start:end])
                 for start, end, _label, _index in placeholder_spans]
    protected += [(start, end, "seed", placeholder)
                  for start, end, placeholder in seed_spans]
    protected.sort(key=lambda interval: interval[0])

    detected = []
    if detect is not None:
        detected = _collect_detected(text, detect, protected, labels, check)
        detected = _resolve_detected_overlaps(protected, detected, len(text), check)
    check()

    # ID occupati: chiavi del seed + placeholder presenti nel testo.
    reserved = seed.reserved_ids()
    for span_index, (_start, _end, label, index) in enumerate(placeholder_spans):
        if span_index % 256 == 0:
            check()
        if index > reserved.get(label, 0):
            reserved[label] = index

    allocated = {}     # (label, normalizzato) -> placeholder
    next_ids = {}      # label -> ultimo ID assegnato in questa richiesta
    delta = {}
    pieces = []
    position = 0
    intervals = protected + [(start, end, "detected", label)
                             for start, end, label in detected]
    check()
    intervals.sort(key=lambda interval: interval[0])

    for interval_index, (start, end, kind, payload) in enumerate(intervals):
        if interval_index % 256 == 0:
            check()
        if start < position:
            continue                                   # difensivo: mai sovrapposti
        if start > position:
            pieces.append(text[position:start])
        if kind == "detected":
            value = text[start:end]
            placeholder = seed.lookup(payload, normalize(value))
            if placeholder is None:
                key = (payload, normalize(value))
                placeholder = allocated.get(key)
                if placeholder is None:
                    current = next_ids.get(payload)
                    if current is None:
                        current = reserved.get(payload, 0)
                    index = current + 1
                    if index > MAX_PLACEHOLDER_INDEX:
                        raise AllocationExhausted()
                    next_ids[payload] = index
                    placeholder = "[%s_%d]" % (payload, index)
                    allocated[key] = placeholder
                    delta[placeholder] = value
            pieces.append(placeholder)
        else:
            pieces.append(payload)                     # placeholder: seed o gia' presente
        position = end
    pieces.append(text[position:])
    check()

    anonymized = "".join(pieces)
    return {
        "anonymized_text": anonymized,
        "dictionary_delta": delta,
        "placeholder_count": count_placeholders(anonymized, labels),
    }