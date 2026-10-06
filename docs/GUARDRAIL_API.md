# Guardrail PII API contract (ENVAS-23 first slice)

> **Status: single-text slice implemented, schema version 0.1.0.** The endpoint described here is
> implemented in this repository: the dependency-free engine in `src/app/pii_dictionary.py`, the
> HTTP shell in `src/app/guardrail_api.py`, the adapter registered from `src/app/app.py`, and
> dedicated tests in `tests/test_pii_dictionary.py` and `tests/test_guardrail_api.py`. The wire
> contract below is frozen for this slice; legacy routes and preferences are unchanged. Other
> ENVAS-23 acceptance criteria beyond this single-text endpoint are out of scope and not claimed
> as complete.

This document and [guardrail-openapi.yaml](guardrail-openapi.yaml) (schema version 0.1.0)
describe the same contract. The OpenAPI 3.1 file is the machine-readable reference for the wire
schema; this document records the semantics, limits and decisions behind it.

## Decisions at a glance

| Area | Decision |
|---|---|
| Endpoint | `POST /api/v1/analyses`, one JSON text, no batch in this slice |
| Request | `text` (required) and `dictionary` seed (optional) only |
| Response | One `results` element (`input_id: "text"`) plus `dictionary_delta` |
| Authentication | Bearer secret `PII_API_TOKEN`; 503 when unset, 401 when missing or wrong |
| Readiness | Model readiness checked before the lock; 503 even when seed or placeholders cover the text |
| State | Stateless; all `TAG_NAMES` categories enabled; legacy preferences ignored |
| Placeholders | Canonical `[LABEL_N]`; 24 `TAG_NAMES` labels; N from 1 to 999999999 |
| Seed | Immutable and reused on match; conflicts on the same normalized original rejected |
| New IDs | Allocated above the maximum occupied per category by seed and input placeholders |
| Delta | New pairs only, value is the first observed surface form |
| Limits | Body 1048576 bytes, text 100000 chars, dictionary 256, original 4096, aggregate 65536 |
| Deadline | 30-second processing budget starting after the bounded body read; cooperative; 504 at the next check |
| Concurrency | One analysis in flight per process; contention rejected with 429 |
| Errors | `POST` errors are exactly `{error, code}` with stable codes, no request values or secrets; method-level responses keep framework semantics |
| Caching | `Cache-Control: no-store` on every response at the endpoint path, including 405 and OPTIONS |
| Out of scope | Batch, multipart, files, OCR and any AAAS change |

## Scope and non-goals

This slice covers exactly one endpoint: `POST /api/v1/analyses`. It accepts a single UTF-8 JSON
object with one text and an optional dictionary seed, and returns the anonymized text plus the
delta of newly allocated placeholder pairs.

The following are explicitly out of scope and must not be assumed as promised by this document:

- batch processing of multiple texts or files: no `files` field, no multipart, no array input and
  no batch response;
- PDF, TXT or Markdown upload, PDF redaction, OCR and raster anonymization of documents;
- any change to the Envai AaaS monorepo, its placeholder registry, its OpenAPI contract or its
  runtime;
- persistence, TTL, key custody and scope policy for the dictionary, which are caller-side
  decisions;
- the remaining ENVAS-23 acceptance criteria beyond this endpoint contract, such as cross-repo
  smoke tests, streaming holdback, compaction and tool-call restore, and fail-closed behaviour
  after the provider accepted the turn.

## Compatibility with existing endpoints and preferences

The legacy routes (`/analyze`, `/pdf`, `/pdf/preview`, `/preview`, `/settings`, `/health`,
`/doc/...`, `/config`, `/port-check`) and the web UI keep their current semantics, including
`mapping` as the full `placeholder -> value` map. The new endpoint is additive and versioned under
`/api/v1/`.

The new endpoint is stateless: it keeps no dictionary between requests, never reads or writes
`prefs.json`, and never reuses the legacy app's request-local `mapping` (the
`placeholder -> value` map that `/analyze` builds for its own response). Legacy preferences
(`EXCLUDED_TAGS`, `MAPPING_ENABLED` and the CLI, environment or per-request overrides) do not
apply: every category in `TAG_NAMES` is detected and anonymized, and the internal working map is
built only for the duration of the request. Legacy request fields such as `exclude_tags` or
`include_mapping` are unknown fields and are rejected.

## Authentication

- The credential is the server-only environment secret `PII_API_TOKEN`. Its value is never
  documented, logged, echoed or returned. The token is configured on the server; clients cannot
  supply or choose it.
- When `PII_API_TOKEN` is unset or blank, the endpoint is disabled and answers `503` with code
  `unavailable`.
- Requests must send `Authorization: Bearer <token>`. A missing or wrong credential answers `401`
  with code `unauthorized`.
- Configuration state is evaluated before credentials: a disabled endpoint answers `503`
  regardless of the credential presented.
- After credentials, model readiness is checked before the per-process lock; an unavailable model
  answers `503` with code `unavailable` even when the text could be resolved from the seed or
  from placeholders already present.
- No other authentication mode is accepted.

## Deployment

- The service stays internal and authenticated, on loopback or a private network.
- Exposing it beyond loopback or a private network requires an authenticated internal proxy and
  TLS in front of the service. The endpoint must not be reachable directly from untrusted
  networks.

## Request

### Envelope

- Media type: `application/json` encoded as UTF-8. A different `Content-Type`, including
  multipart, answers `415` with code `unsupported_media_type`. A `charset` parameter, when
  present, must be UTF-8; any other charset also answers `415`.
- The top-level JSON value must be an object. Arrays, strings, numbers, booleans and `null` answer
  `400` with code `invalid_request`.
- A body that is not valid UTF-8 answers `400` with code `invalid_request`.
- Only the fields in this section are allowed. Any extra or unknown field answers `400` with code
  `invalid_request`.

### text (required)

- Type: string, required.
- It must contain at least one non-whitespace character. Missing, empty, whitespace-only or
  non-string values (`null`, number, boolean, array, object) answer `400` with code
  `invalid_request`.
- Maximum length: 100000 Unicode characters (code points), counted after decoding. Exceeding it
  answers `413` with code `payload_too_large`.
- The decoded string must be encodable as UTF-8. An unpaired UTF-16 surrogate (for example a lone
  `\ud800` escape) answers `400` with code `invalid_request`; valid surrogate pairs, such as
  astral-plane characters and emoji, are accepted as single code points.
- The value is treated as plain text. It is not parsed as Markdown or HTML.

### dictionary (optional)

The dictionary is the seed of known `placeholder -> original` pairs.

- Absent or `{}` means an empty seed. `null`, an array, a string, a number or a boolean answer
  `400` with code `invalid_seed`.
- Keys must be canonical placeholders as defined below. A malformed key (missing or extra
  brackets, unknown label, index zero, leading zero, out of range, non-ASCII digits) answers `400`
  with code `invalid_seed`.
- Values must be strings with at least one non-whitespace character. A non-string, empty or
  whitespace-only value answers `400` with code `invalid_seed`. String values keep their exact
  characters; they are not trimmed or rewritten.
- A value must also be encodable as UTF-8: an unpaired UTF-16 surrogate answers `400` with code
  `invalid_seed`, while valid surrogate pairs are accepted.
- The seed is not echoed back, not extended in place and not returned in full.

### Strict JSON rules

Strict parsing applies to the whole body. The following are rejected:

- malformed JSON: `400` `invalid_request`;
- duplicate object keys, even when the duplicated values are identical, at any nesting level:
  `400` `invalid_request`;
- a top-level value that is not an object, or a `dictionary` value that is not an object: `400`
  `invalid_request` or `invalid_seed` respectively;
- unknown or extra fields at the envelope level: `400` `invalid_request`;
- dictionary keys that are not canonical placeholders: `400` `invalid_seed`;
- invalid, blank or non-string dictionary values: `400` `invalid_seed`.

The request is all-or-nothing: a rejected request produces no partial output and no side effects.

### Fixed limits

These limits are fixed, non-secret constants of this slice. Any change requires a contract update.

| Scope | Limit | On violation |
|---|---|---|
| Raw request body | 1048576 bytes | `413` `payload_too_large` |
| `text` | 100000 Unicode characters | `413` `payload_too_large` |
| `dictionary` entries | 256 | `413` `payload_too_large` |
| One seed original | 4096 characters | `413` `payload_too_large` |
| Aggregate seed originals | 65536 characters (sum of the lengths of all values) | `413` `payload_too_large` |
| Placeholder index | 1 to 999999999 per category | `400` `allocation_exhausted` |

## Placeholder format and categories

A canonical placeholder is `[LABEL_N]` where:

- `LABEL` is one of the current `TAG_NAMES` categories, the source of truth being `TAG_NAMES` in
  `src/app/app.py`;
- `N` is a positive ASCII integer from 1 to 999999999, written without leading zeros;
- brackets are part of the canonical token, both in a dictionary key and in the anonymized text,
  matching the convention of the existing app.

Examples: `[FULLNAME_7]` is valid; `FULLNAME_7`, `[FULLNAME_07]`, `[fullname_7]`, `[FULLNAME_0]`,
`[OTHER_1]` and `[FULLNAME_1000000000]` are invalid.

The current categories, 24 in total, are the 22 model categories `AGE`, `AMOUNT`, `BUILDINGNUM`,
`CATASTO`, `CF`, `CITY`, `CREDITCARDNUMBER`, `DATE`, `DOCID`, `EMAIL`, `FULLNAME`, `GENDER`,
`IBAN`, `ID_DOC`, `ORG`, `PIVA`, `PROVINCE`, `STREET`, `TARGA`, `TELEPHONENUM`, `TIME`, `ZIPCODE`,
plus the regex-only `URL` and `IPADDR`. All are enabled on this endpoint, with no per-request or
server-side opt-out in this slice.

## Seed handling

### Normalization

Identity of an original is decided by a server-side normalization policy:

1. apply Unicode casefold;
2. strip leading and trailing whitespace and collapse every whitespace run to a single ASCII
   space.

The policy does not remove accents, does not apply Unicode NFC or NFKC folding and does not strip
punctuation. The same normalization is used for conflict checks on the seed and for locating seed
originals in the text.

### Seed immutability and reuse

- Seed pairs are immutable: the endpoint never reassigns a seed placeholder to another value and
  never changes a seed value.
- A seed pair is reused when its category and normalized original match a detected entity or a
  located occurrence in the text, whether the model finds it or not. The output uses the seed
  placeholder and the pair does not appear in the delta.
- The seed is never returned in full and never modified.

### Locating known originals

- Known seed originals are located in `text` by literal matching after normalization, even when
  the model and the regex net do not detect them. Matching therefore accepts casefold and
  whitespace variants produced by the normalization policy.
- Matches must respect safe boundaries in the normalized text: the characters immediately before
  and after a match must not be a Unicode letter, digit or underscore. This prevents substring
  hits such as a two-letter value inside a longer word.
- Replacement operates on the original offsets of the input text and in a single pass. There is no
  naive string replace and no recursive replacement: text produced by a substitution is never
  rescanned.
- The longest non-overlapping matches win. For example, with seeds `[FULLNAME_1] = "Mario Rossi"`
  and `[FULLNAME_2] = "Rossi"` in the text `Mario Rossi`, the longer span wins and `Rossi` is not
  replaced separately. Ties are broken deterministically on the placeholder string in ascending
  order, so the output does not depend on iteration order.

### Conflicts

- Two seed entries whose originals normalize to the same string conflict, even when their labels
  differ (for example `FULLNAME` and `CITY` bound to the same value). The request is rejected with
  `400` and code `seed_conflict`.
- Conflict detection uses the normalized identity, so accents and punctuation stay significant:
  `"Rossi"` and `"Ròssi"` do not conflict.

### Existing placeholders in the input

- Canonical placeholder tokens already present in `text` are kept untouched in `anonymized_text`.
- Their IDs are reserved per category: new allocations start above the maximum ID observed among
  seed keys and placeholder tokens found in the input.
- Such tokens are not added to the delta and carry no value: this endpoint does not return or
  authorize a value for them, and callers must not treat them as authorized for restore.

### New IDs and delta

- A detected entity that does not match a seed pair or a previous allocation in the same request
  gets the next free ID in its category, starting above the maximum already occupied by seed keys
  and by placeholder tokens in the input.
- The same category and normalized original map to the same placeholder within the request.
- The delta contains new pairs only. Each new placeholder appears once, with the value of the
  first observed surface form of the original in the text, preserving its casing and spacing. Seed
  pairs and placeholders already present in the input never appear in the delta.
- When there are no new pairs, `dictionary_delta` is `{}`.
- If a category has no free ID left up to 999999999, the request fails with `400` and code
  `allocation_exhausted`, with no partial output.

## Response

### Shape

A successful response is `200 OK` with `application/json` and exactly this shape:

```json
{
  "results": [
    {
      "input_id": "text",
      "anonymized_text": "[FULLNAME_7], scrivi a [EMAIL_1]",
      "statistics": {"placeholder_count": 2}
    }
  ],
  "dictionary_delta": {"[EMAIL_1]": "mario@example.com"}
}
```

- `results` contains exactly one element in this slice, and `input_id` is always the constant
  `"text"`.
- `anonymized_text` is the input text with seed matches and new PII replaced by canonical
  placeholders, and everything else unchanged.
- `statistics.placeholder_count` is the number of canonical placeholder tokens in
  `anonymized_text`, counting every occurrence; a placeholder repeated twice counts twice. It
  includes seed placeholders reused in the output and newly allocated placeholders. It is 0 when
  the text contains no placeholder.
- `dictionary_delta` maps new placeholders to the first observed surface form of their original.
- The response never echoes the seed, the full mapping, `source_text`, `segments` or per-entity
  original fields. No other fields are part of the contract.

### Example

Request:

```json
{
  "dictionary": {"[FULLNAME_7]": "Mario Rossi"},
  "text": "Mario Rossi, scrivi a mario@example.com"
}
```

Response:

```json
{
  "results": [
    {
      "input_id": "text",
      "anonymized_text": "[FULLNAME_7], scrivi a [EMAIL_1]",
      "statistics": {"placeholder_count": 2}
    }
  ],
  "dictionary_delta": {"[EMAIL_1]": "mario@example.com"}
}
```

The known pair `[FULLNAME_7] -> Mario Rossi` is reused and kept out of the delta. The new email is
allocated `[EMAIL_1]` because no email ID was occupied, and it appears in the delta. The
`placeholder_count` of 2 counts the reused seed placeholder and the new one.

Equivalent call with authentication (the token value is never printed or documented):

```bash
curl -X POST http://127.0.0.1:5005/api/v1/analyses \
  -H "Authorization: Bearer $PII_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dictionary": {"[FULLNAME_7]": "Mario Rossi"}, "text": "Mario Rossi, scrivi a mario@example.com"}'
```

## Errors

Every error response to `POST /api/v1/analyses` has exactly this body:

```json
{"error": "Invalid request.", "code": "invalid_request"}
```

- `error` is a generic, human-readable message. Clients must branch on `code`, not on the message.
- `code` is a stable identifier.
- Messages must not contain request values, entity names, seed values, the token, stack traces or
  exception text.
- This envelope covers the endpoint's own outcomes only. A request to the same path with an
  unsupported method keeps the framework's HTTP method semantics: a wrong method answers `405` and
  an automatic `OPTIONS` answers `200`, with the framework's body rather than this envelope. Every
  response at `/api/v1/analyses`, including those `405` and `OPTIONS` responses, still sets
  `Cache-Control: no-store`.

Stable codes:

| HTTP | Code | Condition |
|---|---|---|
| 400 | `invalid_request` | Malformed JSON, duplicate keys, non-object envelope, unknown fields, missing, blank or non-string `text`, invalid UTF-8, unpaired surrogate in `text` |
| 400 | `invalid_seed` | Dictionary not an object, `null` dictionary, key not a canonical placeholder, value non-string, blank or with an unpaired surrogate |
| 400 | `seed_conflict` | Two seed entries normalize to the same original |
| 400 | `allocation_exhausted` | No free placeholder ID up to 999999999 in some category |
| 413 | `payload_too_large` | Body, text, dictionary count, single original or aggregate originals over the fixed limits |
| 415 | `unsupported_media_type` | `Content-Type` is not `application/json` encoded as UTF-8 |
| 401 | `unauthorized` | Missing or wrong Bearer credential |
| 429 | `busy` | Another analysis request is already in flight in the process |
| 503 | `unavailable` | `PII_API_TOKEN` unset or blank (endpoint disabled), model not ready, detector unavailable mid-request, or service unavailable |
| 504 | `deadline_exceeded` | The 30-second cooperative processing budget was reached |
| 500 | `internal_error` | Unexpected processing failure |

### Deadline

- The endpoint applies a 30-second wall-clock processing budget per request. The budget starts
  after the bounded body read, authentication, readiness and non-blocking lock checks, before
  validation and anonymization. The body read itself (up to 1048576 bytes) is not counted, so a
  slow upload can take longer than 30 seconds before the guard starts.
- The budget is checked cooperatively at stage boundaries (for example validation, seed location,
  model chunks, allocation and output assembly) and between model chunks. It is not a hard
  cancellation or completion guarantee: it cannot interrupt an in-flight model call, and a request
  that crosses it fails with `504` only at the next check.
- Deployment must therefore impose a hard worker or proxy timeout that bounds the whole HTTP
  request, including slow uploads and in-flight model calls, because the cooperative budget alone
  neither bounds the body read nor stops an in-flight model call.

### Concurrency

- At most one analysis may be in flight per process on this endpoint. A concurrent request is
  rejected immediately with `429` and code `busy`; it is not queued.
- The legacy routes are not affected by this gate.

### Privacy and caching

- The service must not log request bodies, `text`, seed values, placeholder-original pairs,
  authorization headers or the token, and must not echo them in errors.
- The endpoint is stateless: the internal working map and all request state are discarded when the
  response is produced.
- Every response at `/api/v1/analyses`, success or error, sets `Cache-Control: no-store`,
  including framework-level `405` and automatic `OPTIONS` responses. Responses may contain
  personal data and must not be cached by proxies. Legacy routes keep their existing caching
  behaviour.

## Caller ownership and future AAAS integration

- AAAS owns the placeholder registry and the stable IDs for a turn. envai-pii owns none of that:
  this endpoint only applies the seed it receives and returns the new pairs.
- When AAAS merges `dictionary_delta`, it must use a validated merge with conflict detection and
  atomic ID reservation, never a blind `dict.update` that silently overwrites or collides.
  Reservation or serialization must happen before egress so concurrent children, batches and
  callers cannot allocate the same IDs.
- Restore authorization is caller-side: only references produced or authorized for the current
  call may be restored, and placeholder tokens already present in the input are not authorized by
  this endpoint.
- No change to the AAAS repository is part of this slice. The AAAS-side integration (guardrails
  flag, provider adapters, streaming holdback, tool-call restore) is future work outside this
  document.
