# Guardrail PII API contract (ENVAS-23)

> **Status: schema version 0.3.0, both arms implemented.** The 0.3.0 schema adds one optional
> request field, `categories`, to both arms. The JSON request and success-response schema and
> body-validation codes and messages follow schema 0.1.0 except for that field; pre-body error
> precedence is updated. When `categories` is absent or empty the historical default applies (all
> 24 categories), and the success-response shape is unchanged. Bounded server configuration now
> raises JSON-body and dictionary capacities; the text and file limits remain unchanged. The `multipart/form-data` arm is
> implemented in this repository and
> covered by tests: the native-Werkzeug intake in `src/app/guardrail_inputs.py`, the dependency-free
> engine in `src/app/pii_dictionary.py`, the HTTP shell in `src/app/guardrail_api.py`, the adapter
> registered from `src/app/app.py`, and the tests in `tests/test_guardrail_multifiles.py`,
> `tests/test_guardrail_pdf_privacy.py`, `tests/test_pdf_text_limits.py`,
> `tests/test_pii_dictionary.py`, `tests/test_guardrail_api.py`,
> `tests/test_guardrail_timeout.py` and `tests/test_guardrail_categories.py` (category
> selection). Wire types are
> version 0.3.0: the processing budget is server-side configuration and adds no request or
> response field. Pre-body ordering is explicit:
> token configuration, credentials, model readiness and lock checks return 503, 401, 503 or 429
> before the body is read; media type and charset are validated and the body cap is chosen for that
> media type before the bounded read. Combined-invalid requests can therefore have a different
> outcome from historical error precedence, and not every historical invalid-request outcome is
> preserved. The guardrail PDF arm depends on native MuPDF privacy controls: when those controls
> are missing or broken, the PDF arm answers 503 and JSON, `.txt` and `.md` inputs keep working.
> Quality-gate and final security-review verdicts are not declared here. Legacy routes and
> preferences are unchanged. Other ENVAS-23 acceptance criteria beyond this endpoint are out of
> scope and not claimed as complete.

This document and [guardrail-openapi.yaml](guardrail-openapi.yaml) (schema version 0.3.0)
describe the same contract. The OpenAPI 3.1 file is the machine-readable reference for the wire
schema; this document records the semantics, limits and decisions behind it.

## Decisions at a glance

| Area | Decision |
|---|---|
| Endpoint | `POST /api/v1/analyses`, one route for both media types |
| Request | JSON: `text` (required) plus optional `dictionary` and `categories`; the 0.1.0 fields are preserved. Multipart: repeated `files` (max 10) plus optional `text`, `dictionary` and `categories` |
| Response | JSON: exactly one result (`input_id: "text"`). Multipart: 1 to 11 results (`file_1` to `file_10` in part order, then `text`), plus one aggregate `dictionary_delta` |
| Authentication | Bearer secret `PII_API_TOKEN`; 503 when unset, 401 when missing or wrong; evaluated before any body byte is read |
| Readiness | Model readiness checked after credentials and before the per-process lock, still before any body read; 503 even when seed or placeholders cover the text. Guardrail readiness covers the model only; `/health` is unchanged and has no PDF-capability field |
| State | No cross-request mapping or file cache; request-scoped references are released after the response, with no secure-erasure guarantee |
| Placeholders | Canonical `[LABEL_N]`; 24 `TAG_NAMES` labels; N from 1 to 999999999 |
| Categories | Request-only whitelist `categories`: canonical `TAG_NAMES` labels; absent, `null`, `[]` or blank selects all 24; no server preference or environment fallback; only selected labels are anonymized, the others stay in clear |
| Seed | Incoming seed copied, never mutated and validated across all 24 categories; duplicate normalized originals are rejected; configured limits cover the effective seed plus new delta before success |
| New IDs | Reserved across every input of the request and the seed before any allocation |
| Delta | New pairs only, selected categories only, first normalized-original binding wins across categories, value is its first surface form, and the request-local binding is reused in later inputs |
| Limits | JSON defaults: body 8388608 bytes, seed 10000 entries, 4096 chars per original and 1048576 aggregate chars; hard ceilings: 16777216 bytes, 20000 entries, 65536 chars per original and 2097152 aggregate chars. Multipart: body 20 MiB, each file 5 MiB, max 10 files, max 13 parts, dictionary field follows the configured JSON-body cap, other value fields 1 MiB, 100000 aggregate text chars, 200 pages per PDF |
| Deadline | Server-configured cooperative processing budget, default 60 s from `PII_ANALYSIS_TIMEOUT_SECONDS`, after the bounded body read and inside the owned lock; covers multipart parse, extraction, all inputs and allocation |
| Concurrency | One analysis in flight per process; contention rejected with 429, without reading the body and without queueing |
| Errors | Endpoint bodies are exactly `{error, code}`; JSON body-validation statuses, codes and messages are unchanged, but pre-body outcomes take precedence; multipart adds `unsupported_file_type` (415) and `empty_file`, `unreadable_file`, `no_extractable_text` (422) |
| Caching | `Cache-Control: no-store` on every response at the endpoint path, including 405 and OPTIONS |
| Implementation | Both arms implemented; the optional `categories` field is the 0.3.0 addition; with `categories` absent the success shape and category defaults match the 0.1.0 contract; JSON-body and dictionary limits use the bounded server defaults documented below |
| Out of scope | OCR, raster redaction, embedded attachments, PDF binary or ZIP output, JSON batch arrays, UI, training, AAAS changes |

## Scope and non-goals

This contract covers exactly one endpoint: `POST /api/v1/analyses`. The endpoint accepts:

- `application/json`: one UTF-8 JSON object with one text, an optional dictionary seed and an
  optional categories whitelist,
  returning the anonymized text plus the delta of newly allocated placeholder pairs. The request
  and success-response schemas follow schema 0.1.0 except for the optional `categories` field
  added in 0.3.0; pre-body
  error precedence is updated.
- `multipart/form-data`: up to 10 optional files plus an optional text, an optional dictionary
  seed and an optional categories whitelist, with at least one file or one non-blank text,
  returning one anonymized text per input plus a single aggregate delta.

The following are explicitly out of scope and must not be assumed as promised by this document:

- JSON arrays of texts or files: no `files` or `texts` field in a JSON body and no new JSON
  multi-text format;
- PDF redaction, PDF binary or ZIP output: the multifile arm extracts text only, it does not
  return documents;
- OCR, raster anonymization and extraction of embedded file attachments: a page that exists only
  as an image has no extractable text, and nothing promises that text inside images is protected;
- any change to the Envai AaaS monorepo, its placeholder registry, its OpenAPI contract or its
  runtime;
- persistence, TTL, key custody and scope policy for the dictionary, which are caller-side
  decisions;
- the browser UI, training and the model, which are unchanged and outside this endpoint;
- the remaining ENVAS-23 acceptance criteria beyond this endpoint contract, such as cross-repo
  smoke tests, streaming holdback, compaction and tool-call restore, and fail-closed behaviour
  after the provider accepted the turn.

## Compatibility with existing endpoints and preferences

The legacy routes (`/analyze`, `/pdf`, `/pdf/preview`, `/preview`, `/settings`, `/health`,
`/doc/...`, `/config`, `/port-check`) keep their current HTTP semantics, including `mapping` as the
full `placeholder -> value` map. The browser UI has been removed: `GET /`, the former
`/assets/...` paths and the favicon path answer `404` with a generic JSON body, and no service
index or other HTML page is served. The new endpoint is additive and versioned under `/api/v1/`.

The JSON arm of `/api/v1/analyses` keeps the schema 0.1.0 request fields and adds the optional
`categories` field from schema 0.3.0. The success-response shape, 100000-character text cap and
body-validation statuses, codes and messages are preserved once pre-body checks pass. JSON body
and dictionary capacities now have larger bounded defaults and server-configurable ceilings. A
client that omits `categories` still sees the historical all-24-category behavior and the same
success shape. Clients do not need to change their JSON request or success-response handling. Pre-body ordering is updated: configuration, credentials, model readiness and lock
checks run before the body is read, taking precedence in the documented 503, 401, 503 and 429
order. A combined-invalid request can therefore receive a different result from the historical
body-read precedence.

The multifile extension is additive and implemented: same path, same method, same authentication,
same response envelope. It adds no JSON batch mode; its only wire additions are the optional
`categories` value part and, because of that fourth singleton field, the raised part cap.

The `categories` field is the deliberate wire change in this revision and is approved: it can only
narrow the all-category default, and a selected subset leaves other categories in clear by
explicit caller choice. The server-side analysis budget default remains the cooperative 60 seconds
documented in Deadline; it is server configuration, not a wire change, and no request field can
set it.

The new endpoint is stateless: it keeps no dictionary between requests, never reads or writes
`prefs.json`, and never reuses the legacy app's request-local `mapping` (the
`placeholder -> value` map that `/analyze` builds for its own response). Legacy preferences
(`EXCLUDED_TAGS`, `MAPPING_ENABLED` and the CLI, environment or per-request overrides) do not
apply. Without `categories`, every category in `TAG_NAMES` is detected and anonymized; with a
non-empty `categories`, only the selected labels are anonymized. There is no server preference,
environment variable, CLI flag or settings fallback for this endpoint, and the request can only
narrow the default. The internal working map is
built only for the duration of the request. Legacy request fields such as `exclude_tags` or
`include_mapping` are unknown fields and are rejected; `categories` has no `include_tags` or
`exclude_tags` alias.

## Authentication

- The credential is the server-only environment secret `PII_API_TOKEN`. Its value is never
  documented, logged, echoed or returned. The token is configured on the server; clients cannot
  supply or choose it.
- When `PII_API_TOKEN` is unset or blank, the endpoint is disabled and answers `503` with code
  `unavailable`.
- Requests must send `Authorization: Bearer <token>`. A missing or wrong credential answers `401`
  with code `unauthorized`.
- Credential comparison is constant-time and does not short-circuit on the value; the presented
  token is never logged or echoed.
- Configuration state is evaluated before credentials: a disabled endpoint answers `503`
  regardless of the credential presented.
- After credentials, model readiness is checked before the per-process lock; an unavailable model
  answers `503` with code `unavailable` even when the text could be resolved from the seed or
  from placeholders already present.
- No other authentication mode is accepted.

### Request ordering and the body read

- The endpoint evaluates, in order: token configured (`503` `unavailable`), credentials (`401`
  `unauthorized`), model readiness (`503` `unavailable`), per-process lock (`429` `busy`), media
  type and charset validation (`415` `unsupported_media_type` for an unsupported overall media
  type or charset), raw body cap selection by media type, bounded body read, processing clock
  start with the timeout read once per request before the deadline snapshot, parse and
  extraction, anonymization. The media-type and charset check and the cap choice
  happen before the read, so an unsupported type is rejected without reading the body; the body
  cap is applied to the bytes actually read.
- Authentication, readiness and lock acquisition happen before any body byte is read or parsed.
  An unauthenticated request is answered `401` without touching or parsing the payload; a busy
  request is answered `429` without reading the body and without queueing work.
- Typed read and validation errors keep this precedence: an authentication outcome cannot be
  displaced by a body-size, media-type or charset error, and errors produced in or after the read
  keep their documented codes (`413` for configured or fixed caps, `415` for media type and charset, `400`
  for malformed JSON or multipart, `422` for file content).
- The rules above replace the historical body-read order. When several conditions are invalid at
  once, the earlier check wins, so a combined-invalid request can receive a different outcome from
  the historical precedence. Once the pre-body checks pass, the JSON body-validation statuses,
  codes and messages are unchanged from schema 0.1.0.
- The body cap is enforced on the bytes actually read, never on a declared `Content-Length`.
  A read failure after authentication is sanitized to `400` `invalid_request` and never exposes
  framework exception text.
- The per-process lock is held for the whole authenticated request, from before the body read
  through processing and response assembly, and is released on every outcome, including every
  error.

## Deployment

- The service stays internal and authenticated, on loopback or a private network.
- Exposing it beyond loopback or a private network requires an authenticated internal proxy and
  TLS in front of the service. The endpoint must not be reachable directly from untrusted
  networks.
- The analysis budget is server configuration: set the non-secret `PII_ANALYSIS_TIMEOUT_SECONDS`
  in the server environment (for example `PII_ANALYSIS_TIMEOUT_SECONDS=120`), independently of the
  `PII_API_TOKEN` secret. The value is read once per request before the deadline snapshot, and
  clients cannot override it.
- Any worker or proxy in front of the service needs a timeout longer than the configured budget
  plus the upload and native-work margin. Increasing a client or Postman timeout alone does not
  change the server-side budget.

## Media types and request envelopes

### JSON: text, seed and categories (implemented)

#### Envelope

- Media type: `application/json` encoded as UTF-8. A different `Content-Type` answers `415` with
  code `unsupported_media_type`. A `charset` parameter, when present, must be UTF-8; any other
  charset also answers `415`.
- The top-level JSON value must be an object. Arrays, strings, numbers, booleans and `null` answer
  `400` with code `invalid_request`.
- A body that is not valid UTF-8 answers `400` with code `invalid_request`.
- Only the fields in this section are allowed: `text`, `dictionary` and `categories`. Any extra
  or unknown field answers `400` with code `invalid_request`.

#### text (required)

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

#### dictionary (optional)

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

#### categories (optional)

Request-only whitelist of canonical category labels telling the endpoint which labels to
anonymize on the input.

- Absent, `null`, `[]`, an empty string and a whitespace-only string select all 24 categories in
  `TAG_NAMES`. This is the historical default and applies regardless of any legacy server
  exclusion.
- A valid value is an array of canonical category names, exactly as written in `TAG_NAMES`, for
  example `["FULLNAME", "EMAIL"]`. Matching is case-sensitive: lower-case or whitespace-padded
  names are not canonical.
- At most 24 raw items. Duplicates are allowed and deduplicated; more than 24 raw items answers
  `400` with code `invalid_request`. A selection that covers all 24 categories is equivalent to
  no selection.
- A non-blank string, an object, a boolean, a number, an array entry that is not a string, a
  blank entry, an unknown name, a lower-case name or a whitespace-padded name answers `400` with
  code `invalid_request`. Any other value type answers the same way.
- There is no `include_tags` or `exclude_tags` alias, and unknown fields remain rejected.

#### Strict JSON rules

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

### multipart/form-data: files, text, seed and categories (implemented)

The arm is implemented with the native Werkzeug multipart decoder
(`src/app/guardrail_inputs.py`), fed from the bounded raw body already in memory. It never uses
`request.files` or `request.form`, never spools to disk and never writes temporary files; the
whole intake stays in RAM. The rules below are the available behaviour.

#### Envelope and parser rules

- Media type `multipart/form-data` with a `boundary` parameter. A `charset` parameter, when
  present, must be UTF-8; any other charset answers `415` `unsupported_media_type` before the body
  is read.
- The boundary must be a non-empty ASCII token of 1 to 70 bytes, made of visible HTTP token
  characters. A missing, empty, non-ASCII, space-containing, control-containing or overlong
  boundary answers `400` `invalid_request`.
- Every part must carry exactly one `Content-Disposition: form-data; name="..."` header line. A
  missing or empty `name`, a non-`form-data` disposition, and duplicated or ambiguous
  `Content-Disposition` header lines answer `400` `invalid_request`.
- Disposition parameters pass a minimal MIME parser before the decoder's last-value-wins parse:
  duplicate parameter names are rejected case-insensitively, so a second `name`, `NAME`, `filename`
  or `FILENAME` parameter answers `400` `invalid_request`. Quoted strings are scanned with
  backslash escapes, so semicolons and `name=` text inside a quoted filename are data, not
  parameter delimiters; escaped quotes are valid. Unicode filenames and the RFC 2231 `filename*`
  form are accepted, including the `filename` plus `filename*` extended/fallback pair.
- Only four field names are allowed: `files` for file parts, and the singleton value parts `text`,
  `dictionary` and `categories`. Any other field name answers `400` `invalid_request`.
- A value part must not carry a `filename`: a `text`, `dictionary` or `categories` part sent as an
  upload answers `400` `invalid_request`.
- A file part must carry a non-empty `filename`; a missing or empty filename answers `400`
  `invalid_request`.
- A repeated `text`, `dictionary` or `categories` part answers `400` `invalid_request`; a
  `dictionary` split across parts or sent as a file part is rejected the same way, and so is a
  `categories` part sent as a file part.
- A value part whose bytes are not valid UTF-8 answers `400` `invalid_request`. Value fields are
  decoded strictly: invalid UTF-8 is rejected, never replaced.
- More than 13 parts answers `413` `payload_too_large`.

#### files

- Repeated file parts named exactly `files`, up to 10; the field name is `files`, never
  `files[]`. Each part is one input document. The part is optional when a non-blank `text` is
  present (see at least one input).
- Accepted extensions, matched case-insensitively: `.pdf`, `.txt`, `.text`, `.md`, `.markdown`.
  Any other extension answers `415` `unsupported_file_type`.
- The extension whitelist is checked first, before any content handling: a `.jpg` file whose bytes
  start with `%PDF-` is still `415` `unsupported_file_type`. Magic bytes do not widen the
  whitelist; they only route an accepted `.txt`/`.text`/`.md`/`.markdown` file to the PDF extractor
  (see file handling below).
- Filename metadata is not included in results or errors, and filenames must not be logged.
  If a filename also appears in extracted document text, it can appear in `anonymized_text` unless
  the detector identifies and replaces it. Duplicate filenames are allowed and still produce
  distinct inputs.
- Input IDs are positional: the first file part is `file_1`, the second `file_2`, and so on up to
  `file_10`, independent of filenames.
- File parts are never silently skipped, not even when empty: an empty or blank file is an error,
  not a missing input. See file handling below.

#### text

- Optional singleton UTF-8 string. A non-blank value is one input with `input_id: "text"`,
  processed after every file input.
- A present but blank or whitespace-only value is treated as absent: it produces no result and is
  not an error by itself.
- Multipart text alone is a valid request and behaves like the JSON arm.

#### dictionary

- Optional singleton UTF-8 string whose content is a strict JSON object.
- The field missing, or its content exactly `{}`, means an empty seed.
- Blank content, malformed JSON and duplicate JSON object keys answer `400` `invalid_request`.
- Content that parses to `null`, an array, a string, a number or a boolean answers `400`
  `invalid_seed`.
- Once parsed, the seed follows the same validation, normalization, conflict and cap rules as the
  JSON arm, with the same codes: `invalid_seed`, `seed_conflict` and `payload_too_large`.
- The form string content is a strict JSON object literal whose keys are canonical `[LABEL_N]`
  placeholders, for example `[ORG_6]`, never arbitrary key names. A non-canonical key answers `400`
  `invalid_seed`.
- A request with a dictionary but no file and no non-blank text answers `400` `invalid_request`.

#### categories

- Optional singleton UTF-8 form string (value part, no filename) whose content is strict JSON for
  the request-only whitelist. The field name is `categories`, never `categories[]`.
- The field missing or blank means all 24 categories.
- Otherwise the decoded JSON follows the same policy as the JSON arm: `null` and `[]` are accepted
  as empty (all categories), a valid array of canonical names selects those labels, and a decoded
  non-blank string, object, boolean or number is invalid. Decoded blank content is accepted as
  empty.
- Malformed JSON, invalid UTF-8, a duplicate `categories` part and a `categories` part sent as a
  file answer `400` with code `invalid_request`.
- In Postman, add `categories` as a Text field whose value is a JSON array such as
  `["FULLNAME", "EMAIL"]`; do not send it as a File field and do not send CSV, because
  `FULLNAME,EMAIL` is not valid JSON.

#### At least one input

`files`, `text`, `dictionary` and `categories` are each optional on their own. A valid request
needs at least one file part or one non-blank `text`, which mirrors the required JSON `text`.
`categories` only selects labels and is not an input, so a `dictionary` or `categories` alone, an
empty multipart body, and a blank or whitespace-only `text` with no file part all answer `400`
`invalid_request`. A text-only request with no `files` part is valid and behaves like the JSON arm.
A file part that is present but empty or malformed is not treated as a missing input: it still
fails the whole request all-or-nothing (see file handling).

## Limits

JSON body and dictionary capacities are read once per authenticated request from the server
environment. Invalid, blank or non-positive values fall back to their defaults; larger values are
clamped to hard ceilings. The hard ceilings keep request and working-map memory bounded.

| Scope | Default | Hard ceiling | On violation |
|---|---:|---:|---|
| JSON body bytes (`PII_MAX_JSON_BODY_BYTES`) | 8388608 | 16777216 | `413` `payload_too_large` |
| Seed entries (`PII_MAX_SEED_ENTRIES`) | 10000 | 20000 | `413` `payload_too_large` |
| One original in the effective dictionary (`PII_MAX_ORIGINAL_CHARS`) | 4096 | 65536 | `413` `payload_too_large` |
| Aggregate original code points in the effective dictionary (`PII_MAX_AGGREGATE_CHARS`) | 1048576 | 2097152 | `413` `payload_too_large` |
| `text` | 100000 Unicode code points | 100000 | `413` `payload_too_large` |
| `categories` raw items | 24 | 24 | `400` `invalid_request` |
| Placeholder index | 1 to 999999999 per category | 1 to 999999999 | `400` `allocation_exhausted` |

The multipart limits:

| Scope | Limit | On violation |
|---|---|---|
| Multipart body | 20971520 bytes (20 MiB); the Flask framework ceiling remains 50 MiB | `413` `payload_too_large` |
| One file part | 5242880 bytes (5 MiB) | `413` `payload_too_large` |
| File parts | 10 | `413` `payload_too_large` |
| Multipart parts in total | 13 (10 files plus `text`, `dictionary` and `categories`) | `413` `payload_too_large` |
| `dictionary` value form field | Same configured cap as the JSON body, default 8388608 bytes and hard ceiling 16777216 bytes | `413` `payload_too_large` |
| `text` or `categories` value form field | 1048576 raw bytes | `413` `payload_too_large` |
| `categories` raw items | 24 | `400` `invalid_request` |
| Aggregate extracted inputs (all files plus optional `text`) | 100000 Unicode characters | `413` `payload_too_large` |
| One PDF | 200 pages | `413` `payload_too_large` |
| Effective dictionary (`seed` plus `dictionary_delta`) | Same configured entry, per-original and aggregate caps as JSON | `413` `payload_too_large` |
| Placeholder index | same as JSON | `400` `allocation_exhausted` |

The HTTP boundary applies the same configured limits to the incoming seed and to the effective
state after merging the seed with `dictionary_delta`; an overflow rejects the whole request before
any results or delta are returned. The 100000-code-point aggregate input-text budget is unchanged.
Direct callers of `parse_seed()` that omit explicit limits retain the legacy 256-entry,
4096-character-per-original and 65536-character aggregate seed defaults.

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
plus the regex-only `URL` and `IPADDR`. The `categories` request field selects which of these
labels are anonymized; without it, all 24 are used. There is still no server-side opt-out or
server preference for this endpoint: legacy preferences do not apply, and the request can only
narrow the default. Every category remains valid in seed keys and placeholder tokens even when it
is not selected.

## Category selection

`categories` is request-only, has no server fallback, and controls which labels are anonymized in
every input of the request.

### Default

- When `categories` is absent or empty, all 24 categories are detected and anonymized. This
  preserves the historical default regardless of any legacy server exclusion.
- A non-empty valid selection replaces the default with exactly the selected labels. A selection
  that covers all 24 categories is equivalent to no selection. The request
  can only narrow coverage; it cannot widen it beyond `TAG_NAMES`, and it is not an override of a
  server policy.

### Filtering

- The selection is applied to candidates from both the model and the regex network before the
  overlap merge runs. A detection of a non-selected category is discarded the same way for both
  sources, and the overlap-resolution algorithm itself is unchanged.
- On every input (each file and the optional text), only detections of the selected labels are
  replaced by placeholders. Occurrences of every other category remain in the output text as they
  were written.

> **Privacy warning:** a partial selection is an explicit caller choice that leaves every
> non-selected category in clear. It is not a complete PII anonymization guarantee, and the caller
> is responsible for checking that the remaining text is safe for its purpose.

### Seed, placeholders and ID reservation

- The seed is validated, copied and kept immutable against all 24 categories, including inactive
  ones, with the same conflict, entry, original-length and aggregate-length rules.
- A seed pair whose category is not selected is not located literally and never appears in
  `dictionary_delta`, but its ID stays reserved and protected. If a selected detection finds the
  same normalized original, the existing seed placeholder is reused regardless of its category.
  Placeholder tokens of non-selected categories found in any input also stay protected.
- ID reservation, canonical-placeholder protection and the reserved ID scan cover every input and
  all 24 categories, so a later selected allocation cannot collide with an inactive ID.
- `dictionary_delta` contains only new pairs of selected categories.
  `statistics.placeholder_count` still counts every canonical placeholder token in the output,
  including tokens of non-selected categories that were already present, not only the newly
  allocated or selected ones.

### No server policy override

- There is no server-side category policy, preference, environment variable, CLI flag or settings
  value for this endpoint. `categories` is a per-request whitelist; legacy exclusions do not apply
  here, so the field neither enables nor disables them.

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
  never changes a seed value. The server receives the seed, copies it into its own structures and
  never mutates the caller's object or the decoded request.
- Seed identity is the normalized original, independent of the detector's category. The first seed
  binding is reused when a detected entity or a located occurrence matches it; the output keeps
  the seed placeholder and the pair does not appear in the delta. Inactive seed pairs are not
  located literally, but an active detection of the same normalized value reuses that existing
  binding rather than creating a conflicting placeholder.
- The seed is never returned in full and never modified.

### Locating known originals

- Known seed originals are located in each text by literal matching after normalization, even
  when the model and the regex net do not detect them. Matching therefore accepts casefold and
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

- Canonical placeholder tokens already present in an input text are kept untouched in that input's
  `anonymized_text`.
- Their IDs are reserved per category across the whole request: new allocations start above the
  maximum ID observed among seed keys and placeholder tokens found in any input.
- This protection covers all 24 categories, including categories that `categories` did not select.
  Non-selected tokens stay preserved in the output and count toward `statistics.placeholder_count`.
- Such tokens are not added to the delta and carry no value: this endpoint does not return or
  authorize a value for them, and callers must not treat them as authorized for restore.

## Batch allocation across inputs

These rules are implemented for the multipart arm. The JSON arm has one text, so they reduce to
the single-text behaviour.

### ID reservation across all inputs

- Before any allocation, the endpoint scans every input (all files plus the optional text) for
  canonical placeholder tokens and reserves their IDs per category, together with the IDs
  occupied by the incoming seed. The maximum occupied ID per category therefore covers the whole
  batch.
- New IDs start above that maximum. A placeholder that appears only in a later input cannot
  collide with an ID allocated while processing an earlier input.
- Allocation identity is the normalized original across categories. The first placeholder binding
  wins even when a later detector assigns another category; both occurrences use that first token
  and only its first surface form appears in the delta. Seed duplicates remain invalid across
  categories. The deterministic longest-span and lexical-placeholder tie-breaks are unchanged.

### Sequential request-local mapping and cross-input reuse

- All inputs are validated and extracted before any model inference runs.
- Inputs are then processed sequentially in result order: files in part order, then the optional
  text.
- The request keeps one request-local working map and one allocator. A pair allocated for an
  earlier input becomes a known match for later inputs: when the same normalized original
  reappears, its first placeholder is reused even when the detector assigns another category or
  the model does not detect the later occurrence.
- The delta keeps the first observed surface form of the original. Later occurrences do not add
  pairs.
- The working map, seed and intermediate structures are request-scoped; the application releases
  its references when the request ends. No global map, file cache, `prefs.json` keyed state,
  database, session or `seed_version` is involved. Releasing references is not a promise of secure
  memory erasure; Python, Werkzeug or allocator-managed copies may remain in process memory.

### New IDs and delta

- A detected entity that does not match a seed pair or a previous allocation in the same request
  gets the next free ID in its category, starting above the maximum already occupied by seed keys
  and by placeholder tokens in any input.
- The same normalized original maps to its first placeholder within the request, regardless of a
  later detected category.
- The delta contains new pairs of selected categories only. Each new placeholder appears once,
  with the value of the first observed surface form of the original, preserving its casing and
  spacing. Seed pairs, placeholders already present in an input and pairs of non-selected
  categories never appear in the delta.
- When there are no new pairs, `dictionary_delta` is `{}`.
- If a category has no free ID left up to 999999999, the request fails with `400` and code
  `allocation_exhausted`, with no partial output.

## File handling

### Accepted types and all-or-nothing errors

- Unsupported extension: `415` `unsupported_file_type`, message `Unsupported file type.`
- Zero-byte or blank decoded text file: `422` `empty_file`, message `File is empty.` A
  zero-byte `.pdf` is unreadable PDF content (`unreadable_file`), not an empty text file.
- Corrupt, encrypted or otherwise unreadable PDF content: `422` `unreadable_file`, message
  `Unable to read file.`
- Valid PDF with no non-blank extractable text: `422` `no_extractable_text`, message
  `File has no extractable text. OCR is not available.`

File handling is all-or-nothing: if any file is rejected, the whole request fails with that code
and no partial results. The error body is still exactly `{error, code}`; it does not identify the
failing input, and no filename or content appears in it.

### Text formats

`.txt`, `.text`, `.md` and `.markdown` keep the legacy encoding policy:

- UTF-16 only when a byte-order mark is present;
- then UTF-8 with optional BOM;
- then cp1252;
- then Latin-1;
- NUL bytes are stripped after decoding.

The decoded content is treated as plain text: no Markdown or other markup interpretation. A file
that decodes to empty or whitespace-only text answers `422` `empty_file`.

### PDF

A file whose accepted extension is `.pdf`, or whose bytes start with the `%PDF-` magic with an
accepted `.txt`, `.text`, `.md` or `.markdown` filename, is routed to the PDF extractor. The same
strict bounded path runs for every PDF input:

- the native MuPDF privacy controls must be verified first; otherwise the file answers `503`
  `unavailable` before the document is opened (see native PDF privacy controls below);
- PyMuPDF opens the bytes, then a deadline check runs; if that check fails, the document is closed
  and the deadline error is preserved;
- a document that is not a PDF, needs a password or is encrypted answers `422` `unreadable_file`;
- a PDF with more than 200 pages answers `413` `payload_too_large`;
- extraction collects page text, non-redaction annotation content, form widget values and bookmark
  titles through the strict bounded collector in `src/app/pdf_text.py`: every annotation, widget
  and TOC failure becomes `422` `unreadable_file` instead of silently dropping text, the remaining
  100000-character aggregate budget is enforced while collecting (including the join separators),
  and the cooperative deadline is checked at page, annotation, widget and TOC boundaries. Deadline
  and character-budget failures are never degraded into a file error;
- after every attempt that passes the capability check, the native warnings buffer is reset
  (see below); a reset failure disables guardrail PDF extraction until the process restarts;
- extracted text that is blank or whitespace-only answers `422` `no_extractable_text`.

The multifile arm does not OCR, does not rasterize or redact pages, does not extract embedded
attachments, and makes no promise that text inside images is protected. Mixed raster and text
documents contribute only their extractable text. A corrupt, encrypted or unsupported PDF answers
`422` `unreadable_file`; a valid PDF with no non-blank extractable text answers `422`
`no_extractable_text`. No PDF redaction is performed: the response contains anonymized text, not
a PDF binary.

### Native PDF privacy controls

Guardrail PDF extraction depends on native MuPDF diagnostics control, added for the B1 privacy fix.
The service:

- disables MuPDF error and warning display once, process-wide, at startup, before any request, and
  verifies the flags by reading them back; only a boolean `False` or integer `0` readback for both
  flags, with all three native functions present and callable, counts as verified. The native
  warnings buffer is reset once at startup and after every guardrail PDF extraction attempt that
  reaches the native parser, success and failure included, and the reset result is discarded
  because it can contain document text;
- never re-enables the display, never toggles it per request, does not redirect `sys.stderr` and
  does not use a per-request restore hook;
- keeps the versioned PDF path the only user of the reset and readback gate: legacy routes keep
  their existing behavior, and the permanent process-wide quiet also covers native diagnostics
  that legacy PDF code would have printed to stdout. Legacy HTTP responses and the `/health`
  fields are unchanged; guardrail readiness and `/health` still check the model only, with no new
  PDF-capability field.

If any control function is missing, raises, or does not leave both flags off, the capability is
marked broken: only the guardrail PDF arm answers `503` `unavailable`, before opening any
document, and it stays unavailable until the process is restarted with a supported PyMuPDF build.
JSON, `.txt` and `.md` inputs keep working. If a guardrail PDF extraction finished and the cleanup
reset then fails, the request answers `503` `unavailable` with no result, and later guardrail PDF
requests answer `503` until the restart; if the extraction had already failed with `413`, `504` or
`422`, that original status is preserved for the request that saw the failure, and later guardrail
PDF requests answer `503`.

The controls stop native error and warning strings from being printed and keep the buffer from
retaining document text between guardrail PDF calls. This is not a secure-erasure or zeroization
guarantee: Python, Werkzeug, PyMuPDF or allocator-managed copies of document state may persist,
other native caches may survive until the process restarts, and a broken control requires an
operator restart or a fixed PyMuPDF build.

## Response

### Shape

A successful response is `200 OK` with `application/json`, `Cache-Control: no-store`, and exactly
this shape:

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

- `results` contains 1 to 11 elements.
  - JSON: exactly one element, with `input_id` always the constant `"text"`.
  - Multipart: one element per file in part order (`file_1` to `file_10`), then one element for a
    non-blank `text` if present, with `input_id: "text"`.
- `anonymized_text` is the input text with seed matches, known matches from earlier inputs and new
  PII replaced by canonical placeholders, and everything else unchanged. Only detections of the
  selected categories are replaced; occurrences of non-selected categories stay in clear by
  explicit caller choice.
- `statistics.placeholder_count` is the number of canonical placeholder tokens in that input's
  `anonymized_text`, counting every occurrence; a placeholder repeated twice counts twice. It
  includes seed placeholders reused in the output, placeholders reused from earlier inputs,
  newly allocated placeholders and placeholder tokens of categories that were not selected. It is
  0 when the input contains no placeholder.
- `dictionary_delta` is a single aggregate map for the whole request: new placeholders to the
  first observed surface form of their original.
- The response does not return the seed, the full working map, `source_text`, `segments`,
  per-entity original fields, filename metadata, raw file bytes, PDF binaries or ZIP archives. It
  intentionally returns input-derived `anonymized_text`, where text not detected as PII stays
  unchanged, and `dictionary_delta`, whose values are the first observed originals for newly
  allocated pairs. A filename that also occurs in document text may therefore appear in
  `anonymized_text` unless detected and replaced. The contract does not guarantee that arbitrary
  source text or filename strings are absent from success responses. No other fields are part of
  the contract.

### Example (JSON)

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
# PII_API_TOKEN must already be set securely in this shell.
curl -X POST http://127.0.0.1:5005/api/v1/analyses \
  -H "Authorization: Bearer $PII_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dictionary": {"[FULLNAME_7]": "Mario Rossi"}, "text": "Mario Rossi, scrivi a mario@example.com"}'
```

### Example (JSON with a category selection)

Request:

```json
{
  "text": "Mario Rossi, scrivi a mario@example.com o chiama 333 1234567",
  "categories": ["FULLNAME", "EMAIL"]
}
```

Response:

```json
{
  "results": [
    {
      "input_id": "text",
      "anonymized_text": "[FULLNAME_1], scrivi a [EMAIL_1] o chiama 333 1234567",
      "statistics": {"placeholder_count": 2}
    }
  ],
  "dictionary_delta": {
    "[FULLNAME_1]": "Mario Rossi",
    "[EMAIL_1]": "mario@example.com"
  }
}
```

Only the selected labels are replaced. The phone number stays in clear because `TELEPHONENUM`
was not selected: a partial selection is an explicit caller choice and is not a complete PII
anonymization guarantee.

### Example (multipart)

The example below is synthetic. Two files and one text share the same name and email: the seed
pair `[FULLNAME_7]` is reused everywhere, and the email allocated while processing `file_1` is
reused in `file_2` and appears once in the aggregate delta.

Request parts:

- `files` part 1, filename `nota.txt`, content `Mario Rossi scrive a mario.rossi@example.com.`
- `files` part 2, filename `contratto.md`, content `Conferma per Mario Rossi: mario.rossi@example.com.`
- `dictionary` value part: `{"[FULLNAME_7]": "Mario Rossi"}`
- `text` value part: `Referente: Mario Rossi.`

Response:

```json
{
  "results": [
    {
      "input_id": "file_1",
      "anonymized_text": "[FULLNAME_7] scrive a [EMAIL_1].",
      "statistics": {"placeholder_count": 2}
    },
    {
      "input_id": "file_2",
      "anonymized_text": "Conferma per [FULLNAME_7]: [EMAIL_1].",
      "statistics": {"placeholder_count": 2}
    },
    {
      "input_id": "text",
      "anonymized_text": "Referente: [FULLNAME_7].",
      "statistics": {"placeholder_count": 1}
    }
  ],
  "dictionary_delta": {"[EMAIL_1]": "mario.rossi@example.com"}
}
```

These example responses contain no filename metadata. `file_1` and `file_2` come from the order
of the file parts, not from the filenames. A filename string that also occurs in document text can
still appear in `anonymized_text` unless detected and replaced. The email pair is created once and
reused, so it appears in
the delta exactly once.

Equivalent call with authentication (the token value is never printed or documented):

```bash
# PII_API_TOKEN must already be set securely in this shell.
curl -X POST http://127.0.0.1:5005/api/v1/analyses \
  -H "Authorization: Bearer $PII_API_TOKEN" \
  -F 'files=@nota.txt;type=text/plain' \
  -F 'files=@contratto.md;type=text/markdown' \
  -F 'dictionary={"[FULLNAME_7]": "Mario Rossi"}' \
  -F 'text=Referente: Mario Rossi.'
```

Each `-F 'files=@...'` sends a file part. `-F 'dictionary=...'` and `-F 'text=...'` send value
parts; writing `-F 'text=@file'` would send `text` as a file and the request would be answered
`400`.

Text-only multipart call with no file parts:

```bash
# PII_API_TOKEN must already be set securely in this shell.
curl -X POST http://127.0.0.1:5005/api/v1/analyses \
  -H "Authorization: Bearer $PII_API_TOKEN" \
  -F 'text=Referente: Mario Rossi.'
```

Text-only multipart selection: `categories` is a value part, not a file:

```bash
# PII_API_TOKEN must already be set securely in this shell.
curl -X POST http://127.0.0.1:5005/api/v1/analyses \
  -H "Authorization: Bearer $PII_API_TOKEN" \
  -F 'text=Referente: Mario Rossi.' \
  -F 'categories=["FULLNAME", "EMAIL"]'
```

A text-only request omits `files` entirely and behaves like the JSON arm. The field name is
`files` when file parts are present, never `files[]`. In a Postman request, leave the `files` row
unchecked or remove it; do not add a file-type row with an empty placeholder, because that sends
an empty file part and fails the all-or-nothing file checks. Add `categories` as a Text field
whose value is a JSON array such as `["FULLNAME", "EMAIL"]`; do not send it as a File field and do
not send CSV, because `FULLNAME,EMAIL` is not valid JSON.

## Errors

Every error response to `POST /api/v1/analyses` has exactly this body:

```json
{"error": "Invalid request.", "code": "invalid_request"}
```

- `error` is a generic, human-readable message. Clients must branch on `code`, not on the message.
- `code` is a stable identifier.
- Error messages must not contain request values, entity names, seed values, filenames, file
  contents, authorization headers, the token, stack traces or exception text.
- The endpoint keeps the two-field envelope for every outcome, including file errors: there is no
  per-input error object and no `input_id` in the error body.
- This envelope covers the endpoint's own outcomes only. A request to the same path with an
  unsupported method keeps the framework's HTTP method semantics: a wrong method answers `405` with
  the framework's generic JSON error body (not this envelope) and preserves the `Allow` header, and
  an automatic `OPTIONS` answers an empty `200` with the framework's usual headers. Every response
  at `/api/v1/analyses`, including those `405` and `OPTIONS` responses, still sets
  `Cache-Control: no-store`.

Stable codes:

| HTTP | Code | Condition |
|---|---|---|
| 400 | `invalid_request` | Malformed JSON, duplicate keys, non-object envelope, unknown fields, missing, blank or non-string JSON `text`, invalid UTF-8, unpaired surrogate in `text`, invalid `categories` value (non-blank string, object, boolean, number, non-string array entry, blank entry, a name that is unknown, lower-case or whitespace-padded, or more than 24 raw items); multipart: unknown field, wrong file part name, value part with a filename, duplicate `text`, `dictionary` or `categories`, missing or empty part name, missing or empty filename, invalid or ambiguous `Content-Disposition`, bad boundary, invalid UTF-8 in a value field, blank or malformed dictionary JSON, duplicate dictionary JSON keys, malformed `categories` JSON, missing input, dictionary-only or selection-only request |
| 400 | `invalid_seed` | Dictionary not an object, `null` dictionary, multipart dictionary content parsing to a non-object, key not a canonical placeholder, value non-string, blank or with an unpaired surrogate |
| 400 | `seed_conflict` | Two seed entries normalize to the same original |
| 400 | `allocation_exhausted` | No free placeholder ID up to 999999999 in some category |
| 413 | `payload_too_large` | JSON body, JSON `text`, effective dictionary count, single original or aggregate originals over the configured limits; multipart body, one file, file count, part count, value field raw bytes, aggregate extracted inputs or PDF page count over the fixed limits |
| 415 | `unsupported_media_type` | `Content-Type` is neither `application/json` nor `multipart/form-data` encoded as UTF-8, including a non-UTF-8 charset |
| 415 | `unsupported_file_type` | A multipart file has an extension outside `.pdf`, `.txt`, `.text`, `.md`, `.markdown`; message `Unsupported file type.` |
| 422 | `empty_file` | A multipart text file is zero-byte or decodes to blank text; message `File is empty.` |
| 422 | `unreadable_file` | A multipart PDF is corrupt, encrypted or otherwise unreadable; message `Unable to read file.` |
| 422 | `no_extractable_text` | A multipart PDF is valid but has no non-blank extractable text; message `File has no extractable text. OCR is not available.` |
| 401 | `unauthorized` | Missing or wrong Bearer credential |
| 429 | `busy` | Another analysis request is already in flight in the process |
| 503 | `unavailable` | `PII_API_TOKEN` unset or blank (endpoint disabled), model not ready, detector unavailable mid-request, service unavailable, or native MuPDF privacy controls unavailable for guardrail PDF extraction |
| 504 | `deadline_exceeded` | The configured cooperative processing budget was reached |
| 500 | `internal_error` | Unexpected processing failure |

The four file codes are specific to the multipart arm. A JSON request never produces
`unsupported_file_type`, `empty_file`, `unreadable_file` or `no_extractable_text`. The extension
whitelist is evaluated while parsing the part headers, before any file content is extracted, and
file errors are all-or-nothing. When pre-body gates pass, JSON body-validation statuses, codes and
messages remain unchanged from schema 0.1.0; combined-invalid requests can receive a different
result because the pre-body checks now take precedence. The existing codes keep their current
messages; the new file codes use exactly the messages quoted in the table.

### Deadline

- The endpoint applies a server-configured cooperative wall-clock processing budget per request.
  The budget comes from the non-secret server environment variable `PII_ANALYSIS_TIMEOUT_SECONDS`,
  a positive finite float in seconds, and is read once per request before the deadline snapshot.
  It is not a client request field: a client cannot set or override it, and a longer client or
  Postman timeout does not extend it.
- Default and fallback are 60 seconds: an unset or blank variable uses 60, and invalid values
  (non-numeric text, zero, negative, NaN, infinity or an overflow) safely fall back to 60. The new
  default deliberately changes the previous 30-second default with user approval; raising or
  lowering it is a server restart configuration, not a wire change.
- The budget starts after the bounded body read, inside the owned lock, before multipart parsing
  and JSON validation. Authentication, readiness and lock checks happen before the read and are
  not counted; the body read itself is not counted either, so a slow upload can take longer than
  the configured budget before the budget starts. The read is bounded by the configured JSON or fixed multipart cap, and
  the timeout value does not change any fixed wire limit.
- For the multipart arm the budget covers multipart parsing, extraction of every file, processing
  of every input and allocation. For the JSON arm it covers validation and anonymization.
- The budget is global and checked cooperatively at stage boundaries (for example multipart
  parsing, validation, extraction, page loops, seed location, model chunks, allocation and output
  assembly) and between model chunks. It is not a hard cancellation or completion guarantee: it
  cannot interrupt a native PDF operation or an in-flight model call, and a request that crosses
  it fails with `504` only at the next check.
- Deployment must therefore impose a hard worker or proxy timeout that is longer than the
  configured budget plus the expected upload and native-work margin, because the cooperative
  budget alone neither bounds the body read nor stops an in-flight model call.

### Concurrency

- At most one analysis may be in flight per process on this endpoint. A concurrent request is
  rejected immediately with `429` and code `busy`; it is not queued and its body is not read.
- The lock is acquired before the body read and held for the whole authenticated request,
  including parsing, extraction and anonymization, and is released on every outcome, error
  included.
- The legacy routes are not affected by this gate.

### Privacy and caching

- The service must not log request bodies, `text`, seed values, file contents, filenames,
  placeholder-original pairs, authorization headers or the token. Error messages must not contain
  request values, filenames, seed values, authorization headers, the token, stack traces or
  exception text. Successful responses intentionally contain input-derived `anonymized_text` and
  new originals in `dictionary_delta`, as specified above; the response does not contain the seed
  in full, the full working map, `source_text`, `segments`, filename metadata, raw file bytes, PDF
  binaries, ZIP archives or per-entity original lists.
- The endpoint retains no mapping or file cache across requests. Request-scoped state is released
  when the response is produced; this is not a secure-erasure guarantee. Python, Werkzeug or
  allocator-managed memory copies may remain in process memory. No database, session or
  `seed_version` is involved.
- Multipart handling is memory-only: the native Werkzeug decoder is fed from the bounded raw body
  already in memory, field and file bytes accumulate in RAM, `request.files` and `request.form`
  are not used, and no part, extraction or working map is written to disk, to temporary files or
  to file metadata.
- Native MuPDF diagnostics are disabled process-wide once at startup and the native warnings
  buffer is reset after every attempt in the guardrail PDF branch that reaches the native parser;
  this is a privacy measure for that path, not a secure-erasure guarantee, and it leaves legacy
  route behavior on the wire unchanged. See native PDF privacy controls above.
- Every response at `/api/v1/analyses`, success or error, sets `Cache-Control: no-store`,
  including framework-level `405` and automatic `OPTIONS` responses. Responses may contain
  personal data and must not be cached by proxies. Legacy routes keep their existing caching
  behaviour.

## Caller ownership and future AAAS integration

- AAAS owns the placeholder registry and the stable IDs for a turn. envai-pii owns none of that:
  this endpoint only applies the seed it receives and returns the new pairs. With several inputs,
  the delta is the aggregate of the whole request.
- When AAAS merges `dictionary_delta`, it must use a validated merge with conflict detection and
  atomic ID reservation, never a blind `dict.update` that silently overwrites or collides.
  Reservation or serialization must happen before egress so concurrent children, batches and
  callers cannot allocate the same IDs.
- Restore authorization is caller-side: only references produced or authorized for the current
  call may be restored, and placeholder tokens already present in the inputs are not authorized by
  this endpoint.
- No change to the AAAS repository is part of this contract. The AAAS-side integration (guardrails
  flag, provider adapters, streaming holdback, tool-call restore) is future work outside this
  document.
