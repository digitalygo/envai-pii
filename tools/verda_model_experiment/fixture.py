from __future__ import annotations

import hashlib
import json

TEXT_PARAGRAPHS = (
    "Il fascicolo del sig. Mario Rossi, nato a Milano il 12 maggio 1985, riporta il codice fiscale RSSMRA85M01H501Q.",
    "La pratica presso Comune di Firenze, partita IVA 01234567890, reca il riferimento di protocollo 2026/0042.",
    "Il pagamento è disposto sul conto IBAN IT60X0542811101000000123456 entro trenta giorni dalla ricezione."
    "Per le comunicazioni formali usare l'ufficio protocollo e conservare la ricevuta originale nel registro annuale.",
    "La sede legale è in Via Roma 12, Torino; il recapito telefonico 011 1234567 è indicato a fini amministrativi."
    "Il verbale descrive la consegna documentale, gli allegati, il responsabile e la successiva data di archiviazione.",
    "La parte interessata può presentare osservazioni scritte entro il termine previsto dalla comunicazione notificata."
    "L'ufficio competente confronta i dati dichiarati con l'atto depositato e registra ogni aggiornamento autorizzato.",
    "La copia conforme resta disponibile presso la segreteria per consultazione nei giorni e negli orari di apertura.",
    "Gli importi, le scadenze e gli estremi del procedimento sono riepilogati nella tabella allegata al fascicolo.",
)

FIXTURE_CHAR_COUNT = 45_000
FIXTURE_REQUEST_NUMBER = 42
FIXTURE_TEXT_SHA256 = "97adc9b463df5728344baa30b734db39a09d24986a1c3d01ffccde3ade3e6fca"
FIXTURE_BODY_SHA256 = "d2a274f2ab87b0d3d71f2b9be595350e5a9ce0c919f11a7eea12a2d168d33b59"
FIXTURE_BODY_BYTES = 45_174


def generate_text(char_count: int, request_number: int) -> str:
    if type(char_count) is not int or char_count < 1:
        raise ValueError("invalid character count")
    if type(request_number) is not int or request_number < 0:
        raise ValueError("invalid request number")
    email = f"req{request_number}@example.com"
    if len(email) + 1 > char_count:
        raise ValueError("request email does not fit")
    pieces = [email, " "]
    remaining = char_count - len(email) - 1
    paragraph_index = request_number % len(TEXT_PARAGRAPHS)
    while remaining:
        paragraph = TEXT_PARAGRAPHS[paragraph_index]
        paragraph_index = (paragraph_index + 3) % len(TEXT_PARAGRAPHS)
        paragraph = paragraph.replace("2026/0042", f"2026/{request_number % 10000:04d}")
        segment = paragraph + " "
        pieces.append(segment[:remaining])
        remaining -= min(remaining, len(segment))
    result = "".join(pieces)
    if len(result) != char_count:
        raise AssertionError("synthetic text length mismatch")
    return result


def build_json_body(text: str) -> bytes:
    return json.dumps({"text": text}, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def fixture_integrity() -> dict[str, int | str]:
    body = build_json_body(FIXTURE_TEXT)
    return {
        "text_codepoints": len(FIXTURE_TEXT),
        "text_utf8_bytes": len(FIXTURE_TEXT.encode("utf-8")),
        "text_sha256": hashlib.sha256(FIXTURE_TEXT.encode("utf-8")).hexdigest(),
        "body_bytes": len(body),
        "body_sha256": hashlib.sha256(body).hexdigest(),
    }


FIXTURE_TEXT = generate_text(FIXTURE_CHAR_COUNT, FIXTURE_REQUEST_NUMBER)
FIXTURE_BODY = build_json_body(FIXTURE_TEXT)
